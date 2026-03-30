# -*- coding: utf-8 -*-
# flake8: noqa
import copy
from itertools import takewhile

from rdflib import (
    BNode,
    # Graph,
    Literal,
    RDF,
    URIRef,
    Variable,
    Graph,
)
from rdflib.util import first
from rdflib.namespace import split_uri

from fuxi.Horn.PositiveConditions import (
    And,
    # BuildUnitermFromTuple,
    Condition,
    Or,
    QNameManager,
    SetOperator,
    Uniterm,
)
from fuxi.Rete.BetaNode import project
from fuxi.Rete.Magic import AdornedUniTerm
from fuxi.Rete.Proof import ImmutableDict
from fuxi.Rete.RuleStore import N3Builtin
from fuxi.Rete.SidewaysInformationPassing import (
    GetOp,
    GetVariables,
    iterCondition,
)
from fuxi.Rete.Util import selective_memoize
from functools import reduce


def normalize_bindings_and_query(vars, bindings, conjunct):
    """
    Takes a query in the form of a list of variables to bind to
    an a priori set of bindings and a conjunct of literals and applies the bindings
    returning:
     - The remaining variables that were not substituted
     - The (possibly grounded) conjunct of literals
     - The bindings minus mappings involving substituted variables

    """
    _vars = set(vars)
    binding_domain = set(bindings.keys())
    applied_bindings = False
    if bindings:
        # Apply a priori substitutions
        for lit in conjunct:
            substituted_vars = binding_domain.intersection(lit.toRDFTuple())
            lit.ground(bindings)
            if substituted_vars:
                applied_bindings = True
                _vars.difference_update(substituted_vars)
    return (
        list(_vars),
        conjunct,
        project(bindings, _vars, inverse=True) if applied_bindings else bindings,
    )


def triple_to_triple_pattern(graph, term):
    if isinstance(term, N3Builtin):
        template = graph.template_map[term.uri]
        return "FILTER(%s)" % (template % (term.argument.n3(), term.result.n3()))
    else:
        return "%s %s %s" % tuple(
            [
                render_term(graph, trm, pred_term=idx == 1)
                for idx, trm in enumerate(term.toRDFTuple())
            ]
        )


@selective_memoize([0])
def normalize_uri(rdf_term, rev_ns_map):
    """
    Takes an RDF Term and 'normalizes' it into a QName (using the registered prefix)
    or (unlike compute_qname) the Notation 3 form for URIs: <...URI...>
    """
    try:
        namespace, name = split_uri(rdf_term)
        namespace = URIRef(namespace)
    except (ValueError, AttributeError, TypeError):
        if isinstance(rdf_term, Variable):
            return "?%s" % rdf_term
        else:
            return "<%s>" % rdf_term
    prefix = rev_ns_map.get(namespace)
    if prefix is None and isinstance(rdf_term, Variable):
        return "?%s" % rdf_term
    elif prefix is None:
        return "<%s>" % rdf_term
    else:
        q_name_parts = compute_qname(rdf_term, rev_ns_map)
        return ":".join([q_name_parts[0], q_name_parts[-1]])


@selective_memoize([0])
def compute_qname(uri, rev_ns_map):
    namespace, name = split_uri(uri)
    namespace = URIRef(namespace)
    prefix = rev_ns_map.get(namespace)
    if prefix is None:
        prefix = "_%s" % len(rev_ns_map)
        rev_ns_map[namespace] = prefix
    return (prefix, namespace, name)


def render_term(graph, term, pred_term=False):
    if term == RDF.type and pred_term:
        return " a "
    elif isinstance(term, URIRef):
        qname = normalize_uri(
            term,
            hasattr(graph, "rev_ns_map")
            and graph.rev_ns_map
            or dict([(u, p) for p, u in graph.namespaces()]),
        )
        return qname[0] == "_" and "<%s>" % term or qname
    elif isinstance(term, Literal):
        return term.n3()
    else:
        try:
            return isinstance(term, BNode) and term.n3() or graph.qname(term)
        except (ValueError, AttributeError, KeyError):
            return term.n3()


def rdf_tuples_to_sparql(
        conjunct,
        edb,
        is_ground=False,
        vars=None,
        symm_atomic_inclusion=False,
        service_url=None
):
    """
    Takes a conjunction of Horn literals and returns the
    corresponding SPARQL query

    if service_url is specified, the query is wrapped in a service definition like so

    SELECT ?s { SERVICE <service_url> { ?body } }

    """
    if vars is None:
        vars = []
    query_type = is_ground and "ASK" or "SELECT %s" % (" ".join([v.n3() for v in vars]))

    if service_url:
        service_expr = f"SERVICE <{service_url}> "
        query_shell = "%s {\n " + service_expr + "{ %s\n}}" if len(conjunct) > 1 else "%s { " + service_expr + "{ %s }}"
    else:
        query_shell = len(conjunct) > 1 and "%s {\n%s\n}" or "%s { %s }"

    if symm_atomic_inclusion:
        if vars:
            var = vars.pop()
            prefix = "%s a ?KIND" % var.n3()
        else:
            prefix = "%s a ?KIND" % first(
                [first(iterCondition(lit)).arg[0].n3() for lit in conjunct]
            )
        conjunct = (i.formulae[0] if isinstance(i, And) else i for i in conjunct)

        subquery = query_shell % (
            query_type,
            "%s\nFILTER(%s)"
            % (
                prefix,
                " ||\n".join(
                    ["?KIND = %s" % edb.qname(GetOp(lit)) for lit in conjunct]
                ),
            ),
        )
    else:
        subquery = query_shell % (
            query_type,
            " .\n".join(["\t" + triple_to_triple_pattern(edb, lit) for lit in conjunct]),
        )
    return subquery


# @selective_memoize([0, 1], ['vars', 'symm_atomic_inclusion'])
def run_query(
    sub_query_join: list[Uniterm],
    bindings: dict,
    fact_graph: Graph,
    vars: list[Variable] | None = None,
    debug: bool = False,
    symm_atomic_inclusion: bool = False,
):
    initial_ns = (
        hasattr(fact_graph, "ns_map")
        and fact_graph.ns_map
        or dict([(k, v) for k, v in fact_graph.namespaces()])
    )
    if not sub_query_join:
        return False
    if not vars:
        vars = []
    if bool(bindings):
        # Apply a priori substitutions
        open_vars, conj_ground_literals, bindings = normalize_bindings_and_query(
            set(vars), bindings, sub_query_join
        )
        vars = list(open_vars)
    else:
        conj_ground_literals = sub_query_join
    is_ground = not vars
    subquery = rdf_tuples_to_sparql(
        conj_ground_literals, fact_graph, is_ground, [v for v in vars], symm_atomic_inclusion
    )
    rt = fact_graph.query(subquery, initNs=initial_ns)  # DEBUG=debug)
    projected_bindings = vars and project(bindings, vars) or bindings
    if is_ground:
        if debug:
            print(
                "%s%s-> %s"
                % (
                    subquery,
                    projected_bindings
                    and " %s apriori binding(s)" % len(projected_bindings)
                    or "",
                    bool(rt),
                )
            )
        return subquery, bool(rt)
    else:
        rt = (
            len(vars) > 1
            and (dict([(vars[idx], i) for idx, i in enumerate(v)]) for v in rt)
            or (dict([(vars[0], v[0] if hasattr(v, "__getitem__") else v)]) for v in rt)
        )
        if debug:
            print(
                "%s%s-> %s"
                % (
                    subquery,
                    projected_bindings
                    and " %s apriori binding(s)" % len(projected_bindings)
                    or "",
                    rt and "[]",
                )
            )  # .. %s answers .. ]'%len(rt) or '[]')
        return subquery, rt


def edb_query_from_body_iterator(
    fact_graph, remaining_body_list, derived_preds, hybrid_predicates=None
):
    hybrid_predicates = hybrid_predicates if hybrid_predicates is not None else []

    def sparql_resolvable(literal):
        pred_term = GetOp(literal)
        if not isinstance(literal, AdornedUniTerm) and isinstance(literal, Uniterm):
            return not literal.naf and (
                pred_term not in derived_preds
                or (pred_term in hybrid_predicates and not pred_term.find("_derived") + 1)
            )
        else:
            return (
                isinstance(literal, N3Builtin) and literal.uri in fact_graph.template_map
            )

    def sparql_resolvable_no_templates(literal):
        pred_term = GetOp(literal)
        if isinstance(literal, Uniterm):
            return not literal.naf and (
                pred_term not in derived_preds
                or (pred_term in hybrid_predicates and not pred_term.find("_derived") + 1)
            )
        else:
            return False

    return list(
        takewhile(
            hasattr(fact_graph, "template_map")
            and sparql_resolvable
            or sparql_resolvable_no_templates,
            remaining_body_list,
        )
    )


class ConjunctiveQueryMemoize(object):
    """
    Ideas from MemoizeMutable class of Recipe 52201 by Paul Moore and
    from memoized decorator of http://wiki.python.org/moin/PythonDecoratorLibrary

    A memoization decorator of a function which take (as argument): a
    graph and a conjunctive query and returns a generator over results of evaluating
    the conjunctive query against the graph
    """

    def __init__(self, cache=None):
        self._cache = cache if cache is not None else {}

    def produce_answers_and_cache(self, answers, key, cache=None):
        cache = cache if cache is not None else []
        for item in answers:
            self._cache.setdefault(key, cache).append(item)
            yield item

    def __call__(self, func):
        def inner_handler(query_exec_action, conj_query):
            key = (conj_query.fact_graph, conj_query)
            try:
                rt = self._cache.get(key)
                if rt is not None:
                    for item in rt:
                        yield item
                else:
                    for item in self.produce_answers_and_cache(
                        func(query_exec_action, conj_query), key
                    ):
                        yield item
            except TypeError:
                import pickle

                try:
                    dump = pickle.dumps(key)
                except pickle.PicklingError:
                    # FIXME: flake8 reports args and kwds as undefined
                    for item in func(*args, **kwds):
                        yield item
                else:
                    if dump in self._cache:
                        for item in self._cache[dump]:
                            yield item
                    else:
                        for item in self.produce_answers_and_cache(
                            func(query_exec_action, conj_query), dump
                        ):
                            yield item

        return inner_handler


class EDBQuery(QNameManager, SetOperator, Condition):
    """
    A list of frames (comprised of EDB predicates) meant for evaluation over a large EDB

    lst is a conjunct of terms
    factGraph is the RDF graph to evaluate queries over
    returnVars is the return variables (None, the default, will cause the list
     to be built via instrospection on lst)
    bindings is a solution mapping to apply to the terms in lst


    """

    def __init__(
        self,
        lst,
        fact_graph,
        return_vars=None,
        bindings=None,
        var_map=None,
        sym_inc_ax_map=None,
        symm_atomic_inclusion=False,
    ):
        if sym_inc_ax_map is None:
            sym_inc_ax_map = {}
        if var_map is None:
            var_map = {}
        if bindings is None:
            bindings = {}
        self.fact_graph = fact_graph
        self.var_map = var_map
        self.symm_atomic_inclusion = symm_atomic_inclusion
        self.formulae = lst
        self.naf = False

        # apply an apriori solutions
        if bool(bindings):
            # Apply a priori substitutions
            open_vars, term_list, bindings = normalize_bindings_and_query(
                set(return_vars) if return_vars else [v for v in self.get_open_vars()],
                bindings,
                lst,
            )
            self.return_vars = list(open_vars)
        else:
            if return_vars is None:
                # return vars not specified, but meant to be determined by
                # constructor
                self.return_vars = self.get_open_vars()
            else:
                # Note if return_vars is an empty list, this
                self.return_vars = (
                    (return_vars if isinstance(return_vars, list) else list(return_vars))
                    if return_vars
                    else []
                )
            term_list = lst

        super(EDBQuery, self).__init__(fact_graph.namespace_manager.namespaces())
        self.bindings = (
            bindings.normalize() if isinstance(bindings, ImmutableDict) else bindings
        )

    def copy(self):
        """
        A shallow copy of an EDB query
        """
        return EDBQuery(
            [copy.deepcopy(t) for t in self.formulae],
            self.fact_graph,
            self.return_vars,
            self.bindings.copy(),
            self.var_map.copy(),
            symm_atomic_inclusion=self.symm_atomic_inclusion,
        )

    def rename_variables(self, var_map):
        for item in self.formulae:
            item.renameVariables(var_map)

    def ground(self, mapping):
        applied_vars = set()
        for item in self.formulae:
            if isinstance(item, Or):
                for _item in item.formulae:
                    applied_vars.update(item.ground(mapping))
            else:
                applied_vars.update(item.ground(mapping))
        self.bindings = project(self.bindings, applied_vars, True)
        self.return_vars = self.get_open_vars()
        return applied_vars

    def accumulate_bindings(self, bindings):
        """ """
        self.bindings.update(project(bindings, self.get_open_vars(), inverse=True))

    def get_open_vars(self):
        return list(
            set(
                reduce(
                    lambda x, y: x + y,
                    [
                        list(GetVariables(arg, secondOrder=True))
                        for arg in self.formulae
                    ],
                )
            )
        )

    def apply_mgu(self, substitutions):
        for term in self.formulae:
            term.renameVariables(substitutions)
        self.bindings = dict(
            [(substitutions.get(k, k), v) for k, v in list(self.bindings.items())]
        )

    def evaluate(self, debug=False, symm_atomic_inclusion=False):
        return run_query(
            self.formulae,
            self.bindings,
            self.fact_graph,
            vars=self.return_vars,
            debug=debug,
            symm_atomic_inclusion=symm_atomic_inclusion,
        )

    def as_owl_dsl_phase(self):
        pass

    def as_sparql(self, service_url: str = None):
        return rdf_tuples_to_sparql(
            self.formulae,
            self.fact_graph,
            not self.return_vars,
            self.return_vars,
            self.symm_atomic_inclusion,
            service_url=service_url
        )

    def __len__(self):
        return len(self.formulae)

    def __eq__(self, other):
        return hash(self) == hash(other)

    def __hash__(self):
        """
        >>> g = Graph()
        >>> lit1 = (Variable('X'), RDF.type, Variable('Y'))
        >>> q1 = EDBQuery([BuildUnitermFromTuple(lit1)], g)
        >>> q2 = EDBQuery([BuildUnitermFromTuple(lit1)], g)
        >>> q1 == q2
        True
        >>> d = {q1:True}
        >>> q2 in d
        True

        """
        from fuxi.Rete.Network import HashablePatternList

        conj = HashablePatternList(
            [term.toRDFTuple() for term in self.formulae], skipBNodes=True
        )
        return hash(conj)

    def extend(self, query, new_var_map=None):
        assert not query.symm_atomic_inclusion
        assert not self.symm_atomic_inclusion
        if new_var_map:
            query.rename_variables(new_var_map)
            self.var_map.update(new_var_map)
        self.formulae.extend(
            [term for term in query.formulae if term not in self.formulae]
        )
        self.bindings.update(query.bindings)

    def __repr__(self):
        return "EDBQuery(%s%s)" % (
            self.repr(self.symm_atomic_inclusion and "Or" or "And"),
            self.bindings and ", %s" % self.bindings or "",
        )


def test():
    import doctest

    doctest.testmod()


if __name__ == "__main__":
    test()

