# -*- coding: utf-8 -*-
# flake8: noqa
"""

[[[
    One method, called magic sets, is a general algorithm for rewriting logical rules
so that they may be implemented bottom-UP (= forward chaining) in a way that
is that by working bottom-up, we can take advantage of efficient methods for doing
massive joins.
]]] -- Magic Sets and Other Strange Ways to Implement Logic Programs, F. Bancilhon,
D. Maier, Y. Sagiv and J. Ullman, Proc. 5th ACM SIGMOD-SIGACT Symposium on
Principles of Database Systems, 1986.

" [..] proposed transformation is to define additional predicates that compute the values that
are passed from one predicate to another in the original rules, according to the sip strategy chosen for each
rule. Each of the original rules is then modified so that it fires only when values for these
additional predicates are available. These auxiliary predicates are called "magic predicates" and
the sets of values that they compute are called "magic sets". The intention is that the bottom-up
evaluation of the modified set of rules simulate the sip we have chosen for each adorned rule,
thus restricting the search space."

" we are interested in binding propagation and how it can be used to improve the
 efficiency of evaluation in the presence of recursion

"""

import copy
import itertools
from functools import reduce


NON_LINEAR_MS_QUERY = """\
PREFIX ex: <http://doi.acm.org/10.1145/28659.28689#>

SELECT * WHERE { ex:john ex:sg ?X }

"""

from fuxi.DLP.ConditionalAxioms import additional_rules as additional_rules_fn
from fuxi.Horn.HornRules import Clause
from fuxi.Horn.HornRules import Rule
from fuxi.Horn.PositiveConditions import And
from fuxi.Horn.PositiveConditions import build_uniTerm
from fuxi.Horn.PositiveConditions import build_uniterm_from_tuple
from fuxi.Horn.PositiveConditions import Exists
from fuxi.Horn.PositiveConditions import get_uterm
from fuxi.Horn.PositiveConditions import Uniterm
from fuxi.Rete.RuleStore import LOG
from fuxi.Rete.RuleStore import N3Builtin
from fuxi.Rete.SidewaysInformationPassing import build_natural_sip
from fuxi.Rete.SidewaysInformationPassing import get_args
from fuxi.Rete.SidewaysInformationPassing import get_occurrence_id
from fuxi.Rete.SidewaysInformationPassing import get_op
from fuxi.Rete.SidewaysInformationPassing import incoming_sip_arcs
from fuxi.Rete.SidewaysInformationPassing import iter_condition
from fuxi.Rete.SidewaysInformationPassing import set_op
from fuxi.Rete.SidewaysInformationPassing import sip_representation
from fuxi.Syntax.InfixOWL import OWL_NS

from rdflib import Graph, Namespace, RDF, URIRef, Variable
from rdflib.util import first
from rdflib.collection import Collection

# from rdflib.plugins.sparql.algebra import RenderSPARQLAlgebra
from rdflib.plugins.sparql.algebra import translateQuery as RenderSPARQLAlgebra
from rdflib.plugins.sparql.parser import parseQuery
from rdflib.plugins.sparql.sparql import Query as sparqlQuery


EX_ULMAN = Namespace("http://doi.acm.org/10.1145/6012.15399#")
LOG_NS = Namespace("http://www.w3.org/2000/10/swap/log#")
MAGIC = Namespace("http://doi.acm.org/10.1145/28659.28689#")

DDL_STRICTNESS_LOOSE = 0
DDL_STRICTNESS_HARSH = 1
DDL_STRICTNESS_FALLBACK_DERIVED = 2
DDL_STRICTNESS_FALLBACK_BASE = 3
DDL_MUST_CHECK = [
    DDL_STRICTNESS_HARSH,
    DDL_STRICTNESS_FALLBACK_DERIVED,
    DDL_STRICTNESS_FALLBACK_BASE,
]
DDL_FALLBACK = [DDL_STRICTNESS_FALLBACK_DERIVED, DDL_STRICTNESS_FALLBACK_BASE]

nameMap = {
    "loose": DDL_STRICTNESS_LOOSE,
    "defaultDerived": DDL_STRICTNESS_FALLBACK_DERIVED,
    "defaultBase": DDL_STRICTNESS_FALLBACK_BASE,
    "harsh": DDL_STRICTNESS_HARSH,
}


def setup_ddl_and_adorn_program(
        fact_graph,
        rules,
        goals,
        derived_preds=None,
        strict_check=DDL_STRICTNESS_FALLBACK_DERIVED,
        default_predicates=None,
        ignore_unbound_d_preds=False,
        hybrid_preds_to_replace=None):
    if not default_predicates:
        default_predicates = [], []
    if not derived_preds:
        _derived_preds = derived_predicate_iterator(fact_graph, rules, strict=strict_check,
                                                    default_predicates=default_predicates)
        if not isinstance(derived_preds, (set, list)):
            derived_preds = list(_derived_preds)
        else:
            derived_preds.extend(_derived_preds)
    hybrid_preds_to_replace = hybrid_preds_to_replace or []
    adorned_program = adorn_program(fact_graph, rules, goals, derived_preds, ignore_unbound_d_preds,
                                    hybrid_preds_to_replace=hybrid_preds_to_replace)
    if adorned_program != set([]):
        rt = reduce(
            lambda l, r: l + r,
            [list(iter_condition(clause.formula.body)) for clause in adorned_program],
        )
    else:
        rt = set()
    for hybrid_pred, adornment in [
        (t, a)
        for t, a in set(
            [
                (
                    URIRef(get_op(term).split("_derived")[0])
                    if get_op(term).find("_derived") + 1
                    else get_op(term),
                    "".join(term.adornment),
                )
                for term in rt
                if isinstance(term, AdornedUniTerm)
            ]
        )
        if t in hybrid_preds_to_replace
    ]:
        # If there are hybrid predicates, add rules that derived their IDB counterpart
        # using information from the adorned queries to determine appropriate arity
        # and adornment
        hybrid_pred = URIRef(hybrid_pred)
        h_pred = URIRef(hybrid_pred + "_derived")
        if len(adornment) == 1:
            # p_derived^{a}(X) :- p(X)
            body = build_uniterm_from_tuple((Variable("X"), RDF.type, hybrid_pred))
            head = build_uniterm_from_tuple((Variable("X"), RDF.type, h_pred))
        else:
            # p_derived^{a}(X, Y) :- p(X, Y)
            body = build_uniterm_from_tuple((Variable("X"), hybrid_pred, Variable("Y")))
            head = build_uniterm_from_tuple((Variable("X"), h_pred, Variable("Y")))
        _head = AdornedUniTerm(head, list(adornment))
        rule = AdornedRule(Clause(And([body]), _head.clone()))
        rule.sip = Graph()
        adorned_program.add(rule)

    if fact_graph is not None:
        fact_graph.adorned_program = adorned_program
    return adorned_program

def magic_set_transformation(
        fact_graph,
        rules,
        goals,
        derived_preds=None,
        strict_check=DDL_STRICTNESS_FALLBACK_DERIVED,
        no_magic=None,
        default_predicates=None):
    """
    Apply the magic set transformation to a ruleset.

    This rewrites rules so that bottom-up evaluation simulates a
    goal-directed (top-down) query, reducing the search space.

    :param fact_graph: RDF graph providing base (EDB) predicates.
    :param rules: Iterable of Horn rules (Ruleset).
    :param goals: List of goal triple patterns used to seed adornment.
    :param derived_preds: Optional derived predicates (IDB) to guide SIP.
    :param strict_check: DDL strictness level for predicate classification.
    :param no_magic: Predicates that should not be magic-transformed.
    :param default_predicates: Optional default predicate partitions.
    :return: Iterable of rewritten rules (adorned and magic rules).
    """
    no_magic = no_magic and no_magic or []
    magic_predicates = set()
    adorned_program = setup_ddl_and_adorn_program(fact_graph,
                                                  rules,
                                                  goals,
                                                  derived_preds=derived_preds,
                                                  strict_check=strict_check,
                                                  default_predicates=default_predicates)
    new_rules = []
    for rule in adorned_program:
        if rule.is_second_order():
            import warnings

            warnings.warn(
                "Second order rule no supported by GMS: %s" % rule, RuntimeWarning
            )

        magic_positions = {}
        # Generate magic rules
        for idx, pred in enumerate(iter_condition(rule.formula.body)):
            if isinstance(pred, AdornedUniTerm):
                # For each rule r in Pad, and for each occurrence of an adorned
                # predicate p a in its body, we generate a magic rule defining
                # magic_p a
                prev_preds = [
                    item for _idx, item in enumerate(rule.formula.body) if _idx < idx
                ]
                if "b" not in pred.adornment:
                    import warnings

                    warnings.warn(
                        "adorned predicate w/out any bound arguments (%s in %s)"
                        % (pred, rule.formula),
                        RuntimeWarning,
                    )
                if get_op(pred) not in no_magic:
                    magic_pred = pred.make_magic_pred()
                    magic_positions[idx] = (magic_pred, pred)
                    in_arcs = [
                        (N, x)
                        for (N, x) in incoming_sip_arcs(rule.sip, get_occurrence_id(pred))
                        if not set(x).difference(get_args(pred))
                    ]
                    if len(in_arcs) > 1:
                        # If there are several arcs entering qi, we define the
                        # magic rule defining magic_qi in two steps. First,
                        # for each arc Nj --> qi with label cj , we define a
                        # rule with head label_qi_j(cj ). The body of the rule
                        # is the same as the body of the magic rule in the
                        # case where there is a single arc entering qi
                        # (described above). Then the magic rule is defined as
                        # follows. The head is magic_q(0). The body contains
                        # label_qi_j(cj) for all j (that is, for all arcs
                        # entering qi ).
                        #
                        # We combine all incoming arcs into a single list of
                        # (body) conditions for the magic set
                        pretty_print_rule(rule)
                        sip_representation(rule.sip)
                        print(pred, magic_pred)
                        _body = []
                        additional_rules = []
                        for idxSip, (N, x) in enumerate(in_arcs):
                            new_pred = pred.clone()
                            set_op(new_pred, URIRef("%s_label_%s" % (new_pred.op, idxSip)))
                            rule_body = And(
                                build_magic_body(N, prev_preds, rule.formula.head, derived_preds)
                            )
                            additional_rules.append(Rule(Clause(rule_body, new_pred)))
                            _body.extend(new_pred)
                        additional_rules.append(Rule(Clause(And(_body), magic_pred)))
                        new_rules.extend(additional_rules)
                        for i in additional_rules:
                            print(i)
                        raise NotImplementedError()
                    else:
                        for idxSip, (N, x) in enumerate(in_arcs):
                            rule_body = And(
                                build_magic_body(N, prev_preds, rule.formula.head, derived_preds, no_magic)
                            )
                            new_rule = Rule(Clause(rule_body, magic_pred))
                            new_rules.append(new_rule)
                    magic_predicates.add(magic_pred)
        # Modify rules
        # we modify the original rule by inserting
        # occurrences of the magic predicates corresponding
        # to the derived predicates of the body and to the head
        # If there are no bound arguments in the head, we don't modify the rule
        idx_increment = 0
        new_rule = copy.deepcopy(rule)
        for idx, (magic_pred, origPred) in list(magic_positions.items()):
            new_rule.formula.body.formulae.insert(idx + idx_increment, magic_pred)
            idx_increment += 1
        if (
            "b" in rule.formula.head.adornment
            and get_op(rule.formula.head) not in no_magic
        ):
            head_magic_pred = rule.formula.head.make_magic_pred()
            if isinstance(new_rule.formula.body, Uniterm):
                new_rule.formula.body = And([head_magic_pred, new_rule.formula.body])
            else:
                new_rule.formula.body.formulae.insert(0, head_magic_pred)
        new_rules.append(new_rule)

    if not new_rules:
        new_rules.extend(additional_rules_fn(fact_graph))
    for rule in new_rules:
        if rule.formula.body:
            yield rule


def normalize_goals(goals):
    if isinstance(goals, (list, set)):
        for goal in goals:
            yield goal, {}
    elif isinstance(goals, tuple):
        yield sparqlQuery, {}
    else:
        query = RenderSPARQLAlgebra(parseQuery(goals))
        for pattern in query.patterns:
            yield pattern[:3], query.prologue.prefixBindings


class AdornedRule(Rule):
    """Rule with 'bf' adornment and is comparable"""

    def __init__(self, clause, declare=None, ns_mapping=None):
        decl = set()
        self.rule_str = ""
        for pred in itertools.chain(
            iter_condition(clause.head), iter_condition(clause.body)
        ):
            decl.update([term for term in get_args(pred) if isinstance(term, Variable)])
            if isinstance(pred, AdornedUniTerm):
                self.rule_str += "".join(pred.adornment)
            self.rule_str += "".join(pred.to_rdf_tuple())
        super(AdornedRule, self).__init__(clause, decl, ns_mapping)

    def is_recursive(self):
        def term_hash(term):
            return get_op(term), reduce(lambda x, y: x + y, term.adornment)

        head_hash = term_hash(self.formula.head)

        def recursive_literal(term):
            return isinstance(term, AdornedUniTerm) and term_hash(term) == head_hash

        if first(filter(recursive_literal, iter_condition(self.formula.body))):
            return True
        else:
            return False

    def __hash__(self):
        return hash(self.rule_str)

    def __eq__(self, other):
        return hash(self) == hash(other)


def normalize_uniterm(term):
    if isinstance(term, Uniterm):
        return term
    elif isinstance(term, N3Builtin):
        return Uniterm(term.uri, term.argument, term.naf)


def adorn_rule(derived_preds, clause, new_head, ignore_unbound_d_preds=False, hybrid_preds_to_replace=None):
    """
    Adorns a horn clause using the given new head and list of
    derived predicates
    """
    assert len(list(iter_condition(clause.head))) == 1
    hybrid_preds_to_replace = hybrid_preds_to_replace or []
    adorned_head = AdornedUniTerm(clause.head, new_head.adornment)
    sip = build_natural_sip(
        clause,
        derived_preds,
        adorned_head,
        hybrid_preds_to_replace=hybrid_preds_to_replace,
        ignore_unbound_d_preds=ignore_unbound_d_preds,
    )
    body_pred_replace = {}

    def adornment(arg, head_arc, x):
        if head_arc:
            # Sip arc from head
            # don't mark bound if query has no bound/distinguished terms
            return (
                (arg in x and arg in adorned_head.get_distinguished_variables(True))
                and "b"
                or "f"
            )
        else:
            return arg in x and "b" or "f"

    for literal in iter_condition(sip.sipOrder):
        op = get_op(literal)
        args = get_args(literal)
        if op in derived_preds or (
                op in hybrid_preds_to_replace if hybrid_preds_to_replace else False
        ):
            for N, x in incoming_sip_arcs(sip, get_occurrence_id(literal)):
                head_arc = len(N) == 1 and N[0] == get_op(new_head)
                if not set(x).difference(args):
                    # A binding
                    # for q is useful, however, only if it is a binding for an
                    # argument of q.
                    body_pred_replace[literal] = AdornedUniTerm(
                        normalize_uniterm(literal),
                        [adornment(arg, head_arc, x) for arg in args],
                        literal.naf,
                    )
                # For a predicate occurrence with no incoming
                # arc, the adornment contains only f. For our purposes here,
                # we do not distinguish between a predicate with such an
                # adornment and an unadorned predicate (we do in order to
                # support open queries)
            if literal not in body_pred_replace and ignore_unbound_d_preds:
                body_pred_replace[literal] = AdornedUniTerm(
                    normalize_uniterm(literal),
                    ["f" for arg in get_args(literal)],
                    literal.naf,
                )
    if hybrid_preds_to_replace:
        atom_pred = get_op(adorned_head)
        if atom_pred in hybrid_preds_to_replace:
            adorned_head.set_operator(URIRef(atom_pred + "_derived"))
        for body_atom in [body_pred_replace.get(p, p) for p in iter_condition(sip.sipOrder)]:
            body_pred = get_op(body_atom)
            if body_pred in hybrid_preds_to_replace:
                body_atom.set_operator(URIRef(body_pred + "_derived"))
    rule = AdornedRule(
        Clause(
            And([body_pred_replace.get(p, p) for p in iter_condition(sip.sipOrder)]),
            adorned_head,
        )
    )
    rule.sip = sip
    return rule


def base_predicate_from_hybrid(pred):
    return URIRef(pred[:-8])


def is_hybrid_predicate(pred, hybrid_preds_to_replace):
    op = get_op(pred)
    return op[-7:] == "derived" and op[:-8] in hybrid_preds_to_replace


def compare_adorned_pred_to_rule_head(adorned_pred, head, hybrid_preds_to_replace):
    """
    If p_a is an unmarked adorned predicate, then for each rule that has p in its head, ..
    """
    head_predicate_term = get_op(head)
    adorned_pred_term = get_op(adorned_pred)
    assert isinstance(head, Uniterm)
    if head.get_arity() == adorned_pred.get_arity():
        return (
            head_predicate_term == adorned_pred_term
            or isinstance(head_predicate_term, Variable)
            or (
                    is_hybrid_predicate(adorned_pred, hybrid_preds_to_replace)
                    and adorned_pred_term[:-8] == head_predicate_term
            )
        )
    return False


def adorn_program(fact_graph,
                  rs,
                  goals,
                  derived_preds=None,
                  ignore_unbound_d_preds=False,
                  hybrid_preds_to_replace=None):
    """
    The process starts from the given query. The query determines bindings for q, and we replace
    q by an adorned version, in which precisely the positions bound in the query are designated as
    bound, say q e . In general, we have a collection of adorned predicates, and as each one is processed,
    we will mark it, so that it will not be processed again. If p a is an unmarked adorned
    predicate, then for each rule that has p in its head, we generate an adorned version for the rule
    and add it to Pad; then p is marked as processed.

    The adorned version of a rule contains additional
    adorned predicates, and these are added to the collection, unless they already appear
    there. The process terminates when no unmarked adorned predicates are left.

    """
    from fuxi.DLP import lloyd_topor_transformation
    from collections import deque

    goal_dict = {}
    hybrid_preds_to_replace = hybrid_preds_to_replace or []
    adorned_predicate_collection = set()
    for goal, nsBindings in normalize_goals(goals):
        adorned_predicate_collection.add(adorn_literal(goal, nsBindings))
    if not derived_preds:
        derived_preds = list(derived_predicate_iterator(fact_graph, rs))

    def unprocessed_preds(adorned_pred_col):
        rt = []
        for p in adorned_pred_col:
            if not p.marked:
                rt.append(p)
            if p not in goal_dict:
                goal_dict.setdefault(get_op(p), set()).add(p)
        return rt

    to_do = deque(unprocessed_preds(adorned_predicate_collection))
    adorned_program = set()
    while len(to_do):
        term = to_do.popleft()
        # check if there is a rule with term as its head
        for rule in rs:
            for clause in lloyd_topor_transformation(rule.formula):
                head = (
                    isinstance(clause.head, Exists)
                    and clause.head.formula
                    or clause.head
                )
                if compare_adorned_pred_to_rule_head(term, head, hybrid_preds_to_replace):
                    # for each rule that has p in its head, we generate an
                    # adorned version for the rule
                    adorned_rule = adorn_rule(derived_preds, clause, term, ignore_unbound_d_preds=ignore_unbound_d_preds,
                                             hybrid_preds_to_replace=hybrid_preds_to_replace)
                    adorned_program.add(adorned_rule)
                    # The adorned version of a rule contains additional adorned
                    # predicates, and these are added
                    for pred in iter_condition(adorned_rule.formula.body):
                        if isinstance(pred, N3Builtin):
                            adorned_pred = pred
                        else:
                            adorned_pred = (
                                    not isinstance(pred, AdornedUniTerm)
                                    and adorn_literal(pred.to_rdf_tuple(), nsBindings, pred.naf)
                                    or pred
                            )
                        op = get_op(pred)
                        if (
                                op in derived_preds
                                or (
                                        op in hybrid_preds_to_replace
                                if hybrid_preds_to_replace
                                else False
                            )
                        ) and adorned_pred not in adorned_predicate_collection:
                            adorned_predicate_collection.add(adorned_pred)
        term.marked = True
        to_do.extendleft(unprocessed_preds(adorned_predicate_collection))

    fact_graph.query_atoms = goal_dict
    return adorned_program


class AdornedUniTerm(Uniterm):
    def __init__(self, uterm, adornment=None, naf=False):
        self.marked = False
        self.adornment = adornment
        self.ns_manager = get_uterm(uterm).ns_manager
        new_args = copy.deepcopy(get_uterm(uterm).arg)
        super(AdornedUniTerm, self).__init__(get_uterm(uterm).op, new_args, naf=naf)
        self.is_magic = False

    def clone(self):
        return AdornedUniTerm(self, self.adornment, self.naf)

    def make_magic_pred(self):
        """
        Make a (cloned) magic predicate

        The arity of the new predicate is the number of occurrences of b in the
        adornment a, and its arguments correspond to the bound arguments of p a
        """
        new_adorned_pred = AdornedUniTerm(self, self.adornment, self.naf)
        if self.op == RDF.type:
            new_adorned_pred.arg[-1] = URIRef(self.arg[-1] + "_magic")
        elif len([i for i in self.adornment if i == " b"]) == 1:
            # adorned predicate occurrence with one out of two arguments bound
            # converted into a magic predicate: It becomes a unary predicate
            # (an rdf:type assertion)
            new_adorned_pred.arg[-1] = URIRef(self.op + "_magic")
            new_adorned_pred.arg[0] = [
                self.arg[idx] for idx, i in enumerate(self.adornment) if i == "b"
            ][0]
            new_adorned_pred.op = RDF.type
        else:
            new_adorned_pred.op = URIRef(self.op + "_magic")
        new_adorned_pred.is_magic = True
        return new_adorned_pred

    def __hash__(self):
        return self._hash ^ hash(reduce(lambda x, y: x + y, self.adornment))

    def has_bindings(self, vars_only=False):
        for idx, term in enumerate(get_args(self)):
            if self.adornment[idx] == "b":
                if not vars_only or isinstance(term, Variable):
                    return True
        return False

    def get_distinguished_variables(self, vars_only=False):
        if self.op == RDF.type:
            for idx, term in enumerate(get_args(self)):
                if self.adornment[idx] == "b":
                    if not vars_only or isinstance(term, Variable):
                        yield term
        else:
            for idx, term in enumerate(self.arg):
                try:
                    if self.adornment[idx] == "b":
                        if not vars_only or isinstance(term, Variable):
                            yield term
                except IndexError:
                    pass

    def get_bindings(self, uniterm):
        rt = {}
        for idx, term in enumerate(self.arg):
            goal_arg = self.arg[idx]
            candidate_arg = uniterm.arg[idx]
            if self.adornment[idx] == "b" and isinstance(candidate_arg, Variable):
                # binding
                rt[candidate_arg] = goal_arg
        return rt

    def to_rdf_tuple(self):
        if hasattr(self, "is_magic") and self.is_magic:
            return self.arg[0], self.op, self.arg[-1]
        else:
            subject, _object = self.arg
            return subject, self.op, _object

    def __repr__(self):
        pred = self.normalize_term(self.op)
        neg_prefix = self.naf and "not " or ""
        if self.op == RDF.type:
            adorn_suffix = "_" + self.adornment[0]
        else:
            adorn_suffix = "_" + "".join(self.adornment)
        if self.is_magic:
            if self.op == RDF.type:
                return "%s%s(%s)" % (
                    neg_prefix,
                    self.normalize_term(self.arg[-1]),
                    self.normalize_term(self.arg[0]),
                )
            else:
                return "%s%s(%s)" % (
                    neg_prefix,
                    pred,
                    " ".join(
                        [
                            self.normalize_term(i)
                            for idx, i in enumerate(self.arg)
                            if self.adornment[idx] == "b"
                        ]
                    ),
                )
        elif self.op == RDF.type:
            return "%s%s%s(%s)" % (
                neg_prefix,
                self.normalize_term(self.arg[-1]),
                adorn_suffix,
                self.normalize_term(self.arg[0]),
            )
        else:
            return "%s%s%s(%s)" % (
                neg_prefix,
                pred,
                adorn_suffix,
                " ".join([self.normalize_term(i) for i in self.arg]),
            )


def adorn_literal(rdf_tuple, new_nss=None, naf=False):
    """
    An adornment for an n-ary predicate p is a string a of length n on the
    alphabet {b, f}, where b stands for bound and f stands for free. We
    assume a fixed order of the arguments of the predicate.

    Intuitively, an adorned occurrence of the predicate, p a, corresponds to a
    computation of the predicate with some arguments bound to constants, and
    the other arguments free, where the bound arguments are those that are
    so indicated by the adornment.

    >>> EX = Namespace('http://doi.acm.org/10.1145/6012.15399#')
    >>> query = RenderSPARQLAlgebra(parse(NON_LINEAR_MS_QUERY))  #doctest: +SKIP
    >>> literal = query.patterns[0][:3]  #doctest: +SKIP
    >>> literal  #doctest: +SKIP
    (rdflib.URIRef('http://doi.acm.org/10.1145/6012.15399#john'), rdflib.URIRef('http://doi.acm.org/10.1145/6012.15399#sg'), ?X)
    >>> aLit = adorn_literal(literal,query.prologue.prefixBindings)  #doctest: +SKIP
    >>> aLit  #doctest: +SKIP
    mst:sg_bf(mst:john ?X)
    >>> aLit.adornment  #doctest: +SKIP
    ['b', 'f']
    >>> aLit.get_bindings(Uniterm(EX.sg, [Variable('X'), EX.jill]))  #doctest: +SKIP
    {?X: rdflib.URIRef('http://doi.acm.org/10.1145/6012.15399#john')}
    """
    args = [rdf_tuple[0], rdf_tuple[-1]]
    new_nss = new_nss is None and {} or new_nss
    uniterm = build_uniterm_from_tuple(rdf_tuple, new_nss)
    op_args = rdf_tuple[1] == RDF.type and [args[0]] or args

    def is_free_term(term):
        return isinstance(term, Variable)

    adornment = [is_free_term(term) and "f" or "b" for idx, term in enumerate(op_args)]
    return AdornedUniTerm(uniterm, adornment, naf)


def derived_predicate_iterator(facts_or_base_preds,
                               ruleset,
                               strict=DDL_STRICTNESS_FALLBACK_DERIVED,
                               default_predicates=None):
    if not default_predicates:
        default_predicates = [], []
    default_base_preds, default_derived_preds = default_predicates
    base_preds = [
        get_op(build_uniTerm(fact)) for fact in facts_or_base_preds if fact[1] != LOG.implies
    ]
    processed = {True: set(), False: set()}
    derived_preds = set()
    uncertain_preds = set()
    rule_body_preds = set()
    rule_heads = set()
    for rule in ruleset:
        if rule.formula.body:
            for idx, term in enumerate(
                itertools.chain(
                    iter_condition(rule.formula.head), iter_condition(rule.formula.body)
                )
            ):
                # iterate over terms from head to end of body
                op = get_op(term)
                if op not in processed[idx > 0]:
                    # not processed before
                    if idx > 0:
                        # body literal
                        rule_body_preds.add(op)
                    else:
                        # head literal
                        rule_heads.add(op)
                    if strict in DDL_MUST_CHECK and not (
                        op not in base_preds or idx > 0
                    ):
                        # checking DDL well formedness and
                        # op is a base predicate *and* a head literal (derived)
                        if strict in DDL_FALLBACK:
                            mark = (
                                strict == DDL_STRICTNESS_FALLBACK_DERIVED
                                and "derived"
                                or "base"
                            )
                            if (
                                strict == DDL_STRICTNESS_FALLBACK_DERIVED
                                and op not in default_base_preds
                            ):
                                # a clashing predicate is marked as derived due
                                # to level of strictness
                                derived_preds.add(op)
                            elif (
                                strict == DDL_STRICTNESS_FALLBACK_BASE
                                and op not in default_derived_preds
                            ):
                                # a clashing predicate is marked as base dur
                                # to level of strictness
                                default_base_preds.append(op)
                            import warnings

                            warnings.warn(
                                "predicate symbol of %s is in both IDB and EDB. Marking as %s"
                                % (term, mark)
                            )
                        else:
                            raise SyntaxError(
                                "%s is a member of a derived predicate and a base predicate."
                                % term
                            )
                    if op in base_preds:
                        # base predicates are marked for later validation
                        uncertain_preds.add(op)
                    else:
                        if idx == 0 and not isinstance(op, Variable):
                            # head literal with proper predicate symbol
                            # identify as a derived predicate
                            derived_preds.add(op)
                        elif not isinstance(op, Variable):
                            # body literal with proper predicate symbol
                            # mark for later validation
                            uncertain_preds.add(op)
                    processed[idx > 0].add(op)
    for pred in uncertain_preds:
        # for each predicate marked as 'uncertain'
        # do further checking
        if (
            pred not in rule_body_preds and not isinstance(pred, Variable)
        ) or pred in rule_heads:
            # pred is not in a body literal and is a proper predicate symbol
            # or it is a rule head -> mark as a derived predicate
            derived_preds.add(pred)
    for pred in derived_preds:
        if pred not in default_base_preds:
            yield pred


def iter_non_base_non_derived_preds(ruleset, intensional_db):
    rt = set()
    intensional_preds = set(
        [p for p in intensional_db.predicates() if p != LOG_NS.implies]
    )
    for rule in ruleset:
        for uterm in rule.formula.head:
            if uterm.op in intensional_preds and uterm.op not in rt:
                rt.add(uterm.op)
                yield (
                    uterm.op,
                    (fact for fact in intensional_db.triples((None, uterm.op, None))),
                )


def build_magic_body(N, prev_predicates, adorned_head, derived_preds, no_magic=[]):
    unbound_head = "b" in adorned_head.adornment
    if unbound_head:
        body = [adorned_head.make_magic_pred()]
    else:
        # If there are no bound argument positions to pass magic values with,
        # we propagate values in the full relation
        body = []
    for prev_a_pred in prev_predicates:
        op = get_op(prev_a_pred)
        if op in N or isinstance(op, Variable):
            # If qj, j<i, is in N, we add qj to the body of the magic rule
            # Note, if the atom has a variable for the predicate, treat it as a base
            # predicate occurrence
            body.append(prev_a_pred)
        if (
            op in derived_preds
            and isinstance(prev_a_pred, AdornedUniTerm)
            and prev_a_pred.adornment.count("b") > 0
        ):
            # If qj is a derived predicate and its adornment contains at least
            # one b, we also add the corresponding magic predicate to the body
            if op in no_magic:
                body.append(prev_a_pred)
            else:
                body.append(prev_a_pred.make_magic_pred())
    return body


def pretty_print_rule(rule):
    if isinstance(rule.formula.body, And):
        print(rule.formula.head)
        print("    :- %s" % rule.formula.body.formulae[0])
        for idx, literal in enumerate(rule.formula.body.formulae[1:]):
            print(
                "       %s%s"
                % (literal, literal == rule.formula.body.formulae[-1] and "" or ", ")
            )
    else:
        print(rule.formula)


OWL_PROPERTIES_QUERY = """
SELECT ?prop
WHERE {
    ?prop a ?propType
      FILTER(
        ?propType = owl:ObjectProperty ||
        ?propType = owl:TransitiveProperty ||
        ?propType = owl:SymmetricProperty ||
        ?propType = owl:InverseFunctionalProperty ||
        ?propType = owl:DatatypeProperty )
}"""

EXCLUDED_DERIVED_PREDS = []


def identify_derived_predicates(ddl_meta_graph, tbox, ruleset=None):
    """
    See: tag:info@metacognition.info,2026:FuXiVocabulary#
    """
    d_preds = set()
    base_preds = set()
    ddl = Namespace("tag:info@metacognition.info,2026:FuXiVocabulary#")

    if ruleset:
        for rule in ruleset:
            d_preds.add(get_op(rule.formula.head))

    for derivedClassList in ddl_meta_graph.subjects(
        predicate=RDF.type, object=ddl.DerivedClassList
    ):
        d_preds.update(Collection(ddl_meta_graph, derivedClassList))
    for derivedClassList in ddl_meta_graph.subjects(
        predicate=RDF.type, object=ddl.DerivedPropertyList
    ):
        d_preds.update(Collection(ddl_meta_graph, derivedClassList))
    derived_prop_prefixes = []
    base_prop_prefixes = []
    for derived_prop_prefix_list in ddl_meta_graph.subjects(
        predicate=RDF.type, object=ddl.DerivedPropertyPrefix
    ):
        derived_prop_prefixes.extend(Collection(ddl_meta_graph, derived_prop_prefix_list))
    for basePropPrefixList in ddl_meta_graph.subjects(
        predicate=RDF.type, object=ddl.BasePropertyPrefix
    ):
        base_prop_prefixes.extend(Collection(ddl_meta_graph, basePropPrefixList))

    for prop in tbox.query(OWL_PROPERTIES_QUERY):
        if (
            first(filter(lambda prefix: prop.startswith(prefix), derived_prop_prefixes))
            and (prop, RDF.type, OWL_NS.AnnotationProperty) not in tbox
        ):
            d_preds.add(prop)
        if (
            first(filter(lambda prefix: prop.startswith(prefix), base_prop_prefixes))
            and (prop, RDF.type, OWL_NS.AnnotationProperty) not in tbox
            and prop not in d_preds
        ):
            base_preds.add(prop)

    derived_class_prefixes = []
    for derived_cls_prefix_list in ddl_meta_graph.subjects(
        predicate=RDF.type, object=ddl.DerivedClassPrefix
    ):
        derived_class_prefixes.extend(Collection(ddl_meta_graph, derived_cls_prefix_list))
    base_class_prefixes = []
    for base_cls_prefix_list in ddl_meta_graph.subjects(
        predicate=RDF.type, object=ddl.BaseClassPrefix
    ):
        base_class_prefixes.extend(Collection(ddl_meta_graph, base_cls_prefix_list))
    for cls in tbox.subjects(predicate=RDF.type, object=OWL_NS.Class):
        if first(filter(lambda prefix: cls.startswith(prefix), base_class_prefixes)):
            if cls not in d_preds:
                base_preds.add(cls)
        if first(filter(lambda prefix: cls.startswith(prefix), derived_class_prefixes)):
            if cls not in base_preds:
                d_preds.add(cls)

    ns_bindings = dict(
        [
            (prefix, nsUri)
            for prefix, nsUri in itertools.chain(
                tbox.namespaces(), ddl_meta_graph.namespaces()
            )
            if prefix
        ]
    )
    for query_node in ddl_meta_graph.subjects(
        predicate=RDF.type, object=ddl.DerivedClassQuery
    ):
        query = first(ddl_meta_graph.objects(query_node, RDF.value))
        for cls in tbox.query(query, initNs=ns_bindings):
            d_preds.add(cls)

    for base_cls_list in ddl_meta_graph.subjects(
        predicate=RDF.type, object=ddl.BaseClassList
    ):
        base_preds.update(Collection(ddl_meta_graph, base_cls_list))

    d_preds.difference_update(base_preds)
    return d_preds


