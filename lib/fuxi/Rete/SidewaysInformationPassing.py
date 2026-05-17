# -*- coding: utf-8 -*-
# flake8: noqa
"""
Implementation of Sideways Information Passing graph (builds it from a given
ruleset)
"""

import itertools
# import os
# import sys
# import unittest


from hashlib import md5
from fuxi.DLP import SKOLEMIZED_CLASS_NS
from fuxi.DLP.Negation import proper_sip_order_with_negation
from fuxi.Horn.PositiveConditions import And
from fuxi.Horn.PositiveConditions import Exists
from fuxi.Horn.PositiveConditions import SetOperator
from fuxi.Horn.PositiveConditions import Uniterm
from fuxi.Rete.RuleStore import N3Builtin

# from fuxi.Rete.Util import selective_memoize
from rdflib.collection import Collection
from rdflib.graph import Graph
from rdflib import BNode, Namespace, Variable, RDF, URIRef
from rdflib.term import Identifier
from rdflib.util import first
from functools import reduce


MAGIC = Namespace("http://doi.acm.org/10.1145/28659.28689#")


def format_doctest_out(obj):
    return obj


def make_md5_digest(value):
    if isinstance(value, str):
        value = value.encode("utf-8")
    return md5(value).hexdigest()


def iter_condition(condition):
    if isinstance(condition, Exists):
        return iter_condition(condition.formula)
    else:
        return isinstance(condition, SetOperator) and condition or iter([condition])


_skolem_labels: dict[Identifier, str] = {}


def normalize_term(uri, sip_graph):
    uri_str = str(uri)
    if str(SKOLEMIZED_CLASS_NS) in uri_str:
        if uri not in _skolem_labels:
            _skolem_labels[uri] = f"_{len(_skolem_labels) + 1}"
        return _skolem_labels[uri]
    try:
        return sip_graph.qname(uri).split(":")[-1]
    except Exception:
        return uri.n3()


def _get_graphviz():
    try:
        import graphviz
    except Exception as exc:
        raise ImportError("graphviz is required for SIP collection rendering") from exc
    return graphviz


def _adorned_label(lit):
    lead = normalize_term(get_op(lit), lit.ns_manager)
    adorn = getattr(lit, "adornment", None)
    if adorn:
        return f"{lead}^{adorn}"
    return lead


def render_sip_collection(sip_graph, format="png", adorned_program=None):
    graphviz = _get_graphviz()
    dot = graphviz.Digraph("SIP Collection", format=format)
    left_nodes_lookup = {}
    nodes = {}

    _skolem_cache: dict[Identifier, str] = {}
    _skolem_idx: list[int] = [0]

    def _label(uri, ns_graph=None):
        uri_str = str(uri)
        if str(SKOLEMIZED_CLASS_NS) in uri_str:
            if uri not in _skolem_cache:
                _skolem_idx[0] += 1
                _skolem_cache[uri] = f"_{_skolem_idx[0]}"
            return _skolem_cache[uri]
        try:
            ns = ns_graph or sip_graph
            return ns.qname(uri).split(":")[-1]
        except Exception:
            return uri.n3()

    for N, prop, q in sip_graph.query(
        "SELECT ?N ?prop ?q {  ?prop a magic:SipArc . ?N ?prop ?q . }",
        initNs={"magic": MAGIC},
    ):
        if MAGIC.BoundHeadPredicate in sip_graph.objects(subject=N, predicate=RDF.type):
            NCol = [N]
        else:
            NCol = Collection(sip_graph, N)

        if q not in nodes:
            q_name = make_md5_digest(q)
            dot.node(
                q_name,
                label=_label(q),
                shape="plaintext",
            )
            nodes[q] = q_name

        bNode = BNode()
        node_label = ", ".join([_label(term) for term in NCol])
        edge_label = ", ".join(
            [
                var.n3()
                for var in Collection(
                    sip_graph,
                    first(sip_graph.objects(prop, MAGIC.bindings)),
                )
            ]
        )
        marked_edge_label = ""
        if node_label in left_nodes_lookup:
            bNode, left_name, marked_edge_label = left_nodes_lookup[node_label]
        else:
            left_name = make_md5_digest(bNode)
            dot.node(left_name, label=node_label, shape="plaintext")
            left_nodes_lookup[node_label] = (bNode, left_name, edge_label)
            nodes[bNode] = left_name

        if edge_label != marked_edge_label:
            dot.edge(left_name, nodes[q], label=edge_label)

    if not nodes and adorned_program:
        _var_labels: dict[str, str] = {}
        _var_idx: list[int] = [0]

        def _adorned_label_from(lit):
            lead = _label(get_op(lit), getattr(lit, "ns_manager", None))
            adorn = getattr(lit, "adornment", None)
            if adorn:
                adorn_str = "".join(adorn) if isinstance(adorn, (list, tuple)) else str(adorn)
                return f"{lead}^{adorn_str}"
            return lead

        def _var_label(v):
            v_str = v.n3()
            if len(v_str) > 10:
                if v_str not in _var_labels:
                    _var_idx[0] += 1
                    _var_labels[v_str] = f"_{_var_idx[0]}"
                return _var_labels[v_str]
            return v_str

        def _shared_vars(left, right):
            left_vars = {
                v for v in get_args(left, second_order=True)
                if isinstance(v, Variable)
            }
            right_vars = {
                v for v in get_args(right, second_order=True)
                if isinstance(v, Variable)
            }
            return left_vars.intersection(right_vars)

        _edges_seen: set[tuple[str, str]] = set()

        for rule in adorned_program:
            head = rule.head if hasattr(rule, "head") else rule.formula.head
            head_label = _adorned_label_from(head)
            head_id = make_md5_digest(head_label)
            dot.node(head_id, label=head_label, shape="box")

            prev_id = head_id
            prev_lit = head
            for lit in iter_condition(rule.formula.body):
                lit_label = _adorned_label_from(lit)
                lit_id = make_md5_digest(lit_label)
                dot.node(lit_id, label=lit_label, shape="plaintext")

                if (prev_id, lit_id) not in _edges_seen:
                    _edges_seen.add((prev_id, lit_id))
                    vars_shared = _shared_vars(prev_lit, lit)
                    if vars_shared:
                        edge_label = " ".join(
                            _var_label(v) for v in sorted(vars_shared, key=str)
                        )
                        dot.edge(prev_id, lit_id, label=edge_label)
                    else:
                        dot.edge(prev_id, lit_id)

                prev_id = lit_id
                prev_lit = lit

    return dot


class SIPGraphArc(object):
    """
    A sip for r is a labeled graph that satisfies the following conditions:
    1. Each node is either a subset or a member of P(r) or {ph}.
    2. Each arc is of the form N -> q, with label X, where N is a subset of
    P (r) or {ph}, q is a member of P(r), and X is a set of variables,
    such that
    (i) Each variable of X appears in N.
    (ii) Each member of N is connected to a variable in X.
    (iii) For some argument of q, all its variables appear in X. Further,
    each variable of X appears in an argument of q that satisfies this
    condition.
    """

    def __init__(self, left, right, variables, graph=None, head_passing=False):
        self.variables = variables
        self.left = left
        self.right = right
        self.graph = graph is None and Graph() or graph
        self.arc = SKOLEMIZED_CLASS_NS[BNode()]
        self.graph.add((self.arc, RDF.type, MAGIC.SipArc))
        vars_col = Collection(self.graph, BNode())
        [vars_col.append(i) for i in self.variables]
        self.graph.add((self.arc, MAGIC.bindings, vars_col.uri))
        if head_passing:
            self.bound_head_predicate = True
            self.graph.add((self.left, self.arc, self.right))
        else:
            self.bound_head_predicate = False
            self.graph.add((self.left, self.arc, self.right))

    def __repr__(self):
        """Visual of graph arc"""
        return "%s - (%s) > %s" % (self.left, self.variables, self.right)


def collect_sip_arc_vars(left, right, ph_bound_vars):
    """docstring for collect_sip_arc_vars"""
    if isinstance(left, list):
        return set(
            reduce(
                lambda x, y: x + y,
                [
                    hasattr(t, "is_head")
                    and ph_bound_vars
                    or get_args(t, second_order=True)
                    for t in left
                ],
            )
        ).intersection(get_args(right, second_order=True))
    else:
        incoming_vars_to_include = (
            ph_bound_vars and ph_bound_vars or get_args(left, second_order=True)
        )
        return set(incoming_vars_to_include).intersection(
            get_args(right, second_order=True)
        )


def set_op(term, value):
    if isinstance(term, N3Builtin):
        term.uri = value
    elif isinstance(term, Uniterm):
        if term.op == RDF.type:
            term.arg[-1] = value
        else:
            term.op = value
    else:
        raise Exception("Unprocessable term: %s" % term)


def get_op(term: Uniterm) -> Identifier:
    """
    Return the predicate of a term, whether it is binary or unary
    :param term:
    :return: Identifier of the predicate
    """
    if isinstance(term, N3Builtin):
        return term.uri
    elif isinstance(term, Uniterm):
        return term.op == RDF.type and term.arg[-1] or term.op
    elif isinstance(term, Exists):
        return get_op(term.formula)
    else:
        raise Exception("Unprocessable term: %s" % term)


def get_variables(term, second_order=False):
    for v in get_args(term, second_order):
        if isinstance(v, Variable):
            yield v


def get_args(term, second_order=False):
    if isinstance(term, N3Builtin):
        return [term.argument, term.result]
    elif isinstance(term, Uniterm):
        args = []
        if term.op == RDF.type:
            if second_order and isinstance(term.arg[-1], (Variable, BNode)):
                args.extend(term.arg)
            else:
                args.append(term.arg[0])
        elif isinstance(term.op, (Variable, BNode)):
            args.append(term.op)
            args.extend(term.arg)
        else:
            args.extend(term.arg)
        return args
    elif isinstance(term, Exists):
        return get_args(term.formula, second_order)
    else:
        raise Exception("Unprocessable term: %s" % term)


def incoming_sip_arcs(sip, pred_occ):
    """docstring for IncomingSIPArcs"""
    for s, p, o in sip.triples((None, None, pred_occ)):
        if (p, RDF.type, MAGIC.SipArc) in sip:
            if (s, RDF.type, MAGIC.BoundHeadPredicate) in sip:
                yield [s], Collection(sip, first(sip.objects(p, MAGIC.bindings)))
            else:
                yield (
                    Collection(sip, s),
                    Collection(sip, first(sip.objects(p, MAGIC.bindings))),
                )


def valid_sip(sip_graph):
    if not len(sip_graph):
        return False
    for arc in sip_graph.query(
        "SELECT ?arc { ?arc m:bindings ?bindings OPTIONAL { ?bindings rdf:first ?val } FILTER(!BOUND(?val)) }",
        initNs={"m": MAGIC},
    ):
        return False
    return True


def get_occurrence_id(uniterm, lookup=None):
    if lookup is None:
        lookup = {}
    pO = URIRef(get_op(uniterm) + "_" + "_".join(get_args(uniterm)))
    lookup[pO] = get_op(uniterm)
    return pO


def find_full_sip(tpl, right):
    (rt, vars) = tpl
    if not vars:
        if len(rt) == 1:
            vars = get_args(rt[0], second_order=True)
        else:
            vars = reduce(
                lambda l, r: [
                    i
                    for i in get_args(l, second_order=True)
                    + get_args(r, second_order=True)
                    if isinstance(i, (Variable, BNode))
                ],
                rt,
            )
    if len(right) == 1:
        if set(get_args(right[0], second_order=True)).intersection(vars):
            # Valid End of recursion, return full SIP order
            yield rt + right
    else:
        # for every possible combination of left and right, trigger recursive
        # call
        for item in right:
            _vars = set(
                [
                    v
                    for v in get_args(item, second_order=True)
                    if isinstance(v, (Variable, BNode))
                ]
            )
            _inVars = set([v for v in vars])
            if _vars.intersection(vars):
                # There is an incoming arc, continue processing inductively on
                # the rest of right
                _inVars.update(_vars.difference(vars))
                for sipOrder in find_full_sip(
                    (rt + [item], _inVars), [i for i in right if i != item]
                ):
                    yield sipOrder


class InvalidSIPException(Exception):
    def __init__(self, msg=None):
        super(InvalidSIPException, self).__init__(msg)


@format_doctest_out
def build_natural_sip(
    clause,
    derived_preds,
    adorned_head,
    hybrid_preds_to_replace=None,
    ignore_unbound_d_preds=False,
):
    """
    Natural SIP:

    Informally, for a rule of a program, a sip represents a
    decision about the order in which the predicates of the rule will be evaluated, and how values
    for variables are passed from predicates to other predicates during evaluation

    >>> from functools import reduce
    >>> from io import StringIO
    >>> from fuxi.Rete.RuleStore import setup_rule_store
    >>> from fuxi.Rete import PROGRAM2
    >>> ruleStore, ruleGraph = setup_rule_store(StringIO(PROGRAM2))
    >>> ruleStore._finalize()
    >>> fg = Graph().parse(data=PROGRAM2, format='n3')
    >>> from fuxi.Horn.HornRules import Ruleset
    >>> rs = Ruleset(n3_rules=ruleGraph.store.rules, ns_mapping=ruleGraph.store.ns_manager)
    >>> for rule in rs: print(rule)
    Forall ?Y ?X ( ex:sg(?X ?Y) :- ex:flat(?X ?Y) )
    Forall ?Y ?Z4 ?X ?Z1 ?Z2 ?Z3 ( ex:sg(?X ?Y) :- And( ex:up(?X ?Z1) ex:sg(?Z1 ?Z2) ex:flat(?Z2 ?Z3) ex:sg(?Z3 ?Z4) ex:down(?Z4 ?Y) ) )
    >>> sip = build_natural_sip(list(rs)[-1], [], None)  #doctest: +SKIP
    >>> for N, x in incoming_sip_arcs(sip, MAGIC.sg): print(N.n3(), x.n3())  #doctest: +SKIP
    ( <http://doi.acm.org/10.1145/28659.28689#up> <http://doi.acm.org/10.1145/28659.28689#sg> <http://doi.acm.org/10.1145/28659.28689#flat> ) ( ?Z3 )
    ( <http://doi.acm.org/10.1145/28659.28689#up> <http://doi.acm.org/10.1145/28659.28689#sg> ) ( ?Z1 )

    >>> sip = build_natural_sip(list(rs)[-1], [MAGIC.sg], None)  #doctest: +SKIP
    >>> list(sip.query('SELECT ?q {  ?prop a magic:SipArc . [] ?prop ?q . }', initNs={%(u)s'magic':MAGIC}))  #doctest: +SKIP
    [rdflib.term.URIRef(%(u)s'http://doi.acm.org/10.1145/28659.28689#sg'), rdflib.term.URIRef(%(u)s'http://doi.acm.org/10.1145/28659.28689#sg')]
    """
    from fuxi.Rete.Magic import AdornedUniTerm

    occur_lookup = {}
    bound_head = (
        isinstance(adorned_head, AdornedUniTerm) and "b" in adorned_head.adornment
    )
    ph_bound_vars = list(adorned_head.get_distinguished_variables(vars_only=True))
    # assert isinstance(clause.head, Uniterm), "Only one literal in the head."

    def collect_sip(left, right):
        if isinstance(left, list):
            vars = collect_sip_arc_vars(left, right, ph_bound_vars)
            if not vars and ignore_unbound_d_preds:
                raise InvalidSIPException("No bound variables for %s" % right)
            left_list = Collection(sip_graph, None)
            left = list(set(left))
            [left_list.append(i) for i in [get_op(ii) for ii in left]]
            left.append(right)
            return left
        else:
            left.is_head = True
            vars = collect_sip_arc_vars(left, right, ph_bound_vars)
            if not vars and ignore_unbound_d_preds:
                raise InvalidSIPException("No bound variables for %s" % right)
            ph = get_op(left)
            if bound_head:
                sip_graph.add((ph, RDF.type, MAGIC.BoundHeadPredicate))
                rt = [left, right]
            else:
                rt = [right]
        return rt

    sip_graph = Graph()
    if isinstance(clause.body, And):
        if ignore_unbound_d_preds:
            found_sip = False
            sips = find_full_sip(([clause.head], None), clause.body)
            while not found_sip:
                sip = next(sips)
                try:
                    reduce(collect_sip, iter_condition(And(sip)))
                    found_sip = True
                    body_order = sip
                except InvalidSIPException:
                    found_sip = False
        else:
            if first(
                filter(lambda i: isinstance(i, Uniterm) and i.naf or False, clause.body)
            ):
                # There are negative literals in body, ensure
                # the given sip order puts negated literals at the end
                body_order = first(
                    filter(
                        proper_sip_order_with_negation,
                        find_full_sip(([clause.head], None), clause.body),
                    )
                )
            else:
                body_order = first(find_full_sip(([clause.head], None), clause.body))
            assert body_order, "Couldn't find a valid SIP for %s" % clause
            reduce(collect_sip, iter_condition(And(body_order)))
        sip_graph.sipOrder = And(body_order[1:])
        # assert validSip(sip_graph), sip_graph.serialize(format='n3')
    else:
        if bound_head:
            reduce(
                collect_sip,
                itertools.chain(
                    iter_condition(clause.head), iter_condition(clause.body)
                ),
            )
        sip_graph.sipOrder = clause.body
    if derived_preds:
        # We therefore generalize our notation to allow
        # more succint representation of sips, in which only arcs entering
        # derived predicates are represented.
        arcs_to_remove = []
        collections_to_clear = []
        for N, prop, q in sip_graph.query(
            "SELECT ?N ?prop ?q {  ?prop a magic:SipArc . ?N ?prop ?q . }",
            initNs={"magic": MAGIC},
        ):
            if occur_lookup[q] not in derived_preds and (
                occur_lookup[q] not in hybrid_preds_to_replace
                if hybrid_preds_to_replace
                else False
            ):
                arcs_to_remove.extend([(N, prop, q), (prop, None, None)])
                collections_to_clear.append(Collection(sip_graph, N))
                # clear bindings collection as well
                bindings_col_b_node = first(sip_graph.objects(prop, MAGIC.bindings))
                collections_to_clear.append(Collection(sip_graph, bindings_col_b_node))
        for remove_sts in arcs_to_remove:
            sip_graph.remove(remove_sts)
        for col in collections_to_clear:
            col.clear()
    return sip_graph


def sip_representation(sip_graph):
    rt = []
    for N, prop, q in sip_graph.query(
        "SELECT ?N ?prop ?q {  ?prop a magic:SipArc . ?N ?prop ?q . }",
        initNs={"magic": MAGIC},
    ):
        if MAGIC.BoundHeadPredicate in sip_graph.objects(subject=N, predicate=RDF.type):
            n_col = [N]
        else:
            n_col = Collection(sip_graph, N)
        rt.append(
            "{ %s } -> %s %s"
            % (
                ", ".join([normalize_term(term, sip_graph) for term in n_col]),
                ", ".join(
                    [
                        var.n3()
                        for var in Collection(
                            sip_graph, first(sip_graph.objects(prop, MAGIC.bindings))
                        )
                    ]
                ),
                normalize_term(q, sip_graph),
            )
        )
    return rt


def test():
    import doctest

    doctest.testmod()


if __name__ == "__main__":
    test()
