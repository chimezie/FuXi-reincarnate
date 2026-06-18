"""
This module implements a Description Horn Logic implementation as defined
by Grosof, B. et.al. ("Description Logic Programs: Combining Logic Programs with
Description Logic" [1]) in section 4.4.  As such, it implements recursive mapping
functions "T", "Th" and "Tb" which result in "custom" (dynamic) rulesets, RIF Basic
Logic Dialect: Horn rulesets [2], [3].  The rulesets are evaluated against an
efficient RETE-UL network.

It is a Description Logic Programming [1] Implementation on top of RETE-UL:

"A DLP is directly defined as the LP-correspondent of a def-Horn
ruleset that results from applying the mapping T ."

The mapping is as follows:

== Core (Description Horn Logic) ==

== Class Equivalence ==

T(owl:equivalentClass(C, D)) -> { T(rdfs:subClassOf(C, D)
                                 T(rdfs:subClassOf(D, C) }

== Domain and Range Axioms (Base Description Logic: "ALC") ==

T(rdfs:range(P, D))  -> D(y) := P(x, y)
T(rdfs:domain(P, D)) -> D(x) := P(x, y)

== Property Axioms (Role constructors: "I") ==

T(rdfs:subPropertyOf(P, Q))     -> Q(x, y) :- P(x, y)
T(owl:equivalentProperty(P, Q)) -> { Q(x, y) :- P(x, y)
                                    P(x, y) :- Q(x, y) }
T(owl:inverseOf(P, Q))          -> { Q(x, y) :- P(y, x)
                                    P(y, x) :- Q(x, y) }
T(owl:TransitiveProperty(P))   -> P(x, z) :- P(x, y) ^ P(y, z)

[1] http://www.cs.man.ac.uk/~horrocks/Publications/download/2003/p117-grosof.pdf
[2] http://www.w3.org/2005/rules/wg/wiki/Core/Positive_Conditions
[3] http://www.w3.org/2005/rules/wg/wiki/asn06

"""

from __future__ import annotations

import collections.abc
import copy
import logging
import warnings
from collections.abc import Generator, Iterable
from functools import reduce

from rdflib.collection import Collection
from rdflib.namespace import RDF, RDFS, Namespace
from rdflib.util import first

from fuxi.Horn import DATALOG_SAFETY_LOOSE, DATALOG_SAFETY_NONE, DATALOG_SAFETY_STRICT
from fuxi.Horn.HornRules import Clause as original_clause
from fuxi.Horn.HornRules import Rule
from fuxi.Horn.PositiveConditions import (
    And,
    Atomic,
    Condition,
    Exists,
    Or,
    SetOperator,
    Uniterm,
)
from rdflib import BNode, URIRef, Variable

from .LPNormalForms import normalize_disjunctions

logger = logging.getLogger(__name__)

SKOLEMIZED_CLASS_NS = Namespace("http://code.google.com/p/python-dlp/wiki/SkolemTerm#")

NON_DHL_OWL_SEMANTICS = """
@prefix log: <http://www.w3.org/2000/10/swap/log#>.
@prefix math: <http://www.w3.org/2000/10/swap/math#>.
@prefix owl: <http://www.w3.org/2002/07/owl#>.
@prefix xsd: <http://www.w3.org/2001/XMLSchema#>.
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#>.
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>.
@prefix : <http://eulersharp.sourceforge.net/2003/03swap/owl-rules#>.
@prefix list: <http://www.w3.org/2000/10/swap/list#>.
#Additional OWL-compliant semantics, mappable to Production Rules

#Subsumption (purely for TBOX classification)
{?C rdfs:subClassOf ?SC. ?A rdfs:subClassOf ?C} => {?A rdfs:subClassOf ?SC}.
{?C owl:equivalentClass ?A} => {?C rdfs:subClassOf ?A. ?A rdfs:subClassOf ?C}.
{?C rdfs:subClassOf ?SC. ?SC rdfs:subClassOf ?C} => {?C owl:equivalentClass ?SC}.

{?C owl:disjointWith ?B. ?M a ?C. ?Y a ?B } => {?M owl:differentFrom ?Y}.

{?P owl:inverseOf ?Q.
 ?P a owl:InverseFunctionalProperty} => {?Q a owl:FunctionalProperty}.
{?P owl:inverseOf ?Q.
 ?P a owl:FunctionalProperty} => {?Q a owl:InverseFunctionalProperty}.

#For OWL/InverseFunctionalProperty/premises004
{?C owl:oneOf ?L.
 ?L rdf:first ?X;
    rdf:rest rdf:nil.
 ?P rdfs:domain ?C} => {?P a owl:InverseFunctionalProperty}.

#For OWL/InverseFunctionalProperty/premises004
{?C owl:oneOf ?L.
 ?L rdf:first ?X;
    rdf:rest rdf:nil.
 ?P rdfs:range ?C} => {?P a owl:FunctionalProperty}.

{?S owl:differentFrom ?O} => {?O owl:differentFrom ?S}.
{?S owl:complementOf ?O} => {?O owl:complementOf ?S}.
{?S owl:disjointWith ?O} => {?O owl:disjointWith ?S}.

"""

OWL_NS = Namespace("http://www.w3.org/2002/07/owl#")

LOG = Namespace("http://www.w3.org/2000/10/swap/log#")
Any = None

LHS = 0
RHS = 1


def reduce_and(left, right):
    if isinstance(left, And):
        left = reduce(reduce_and, left)
    elif isinstance(right, And):
        right = reduce(reduce_and, right)
    if isinstance(left, list) and not isinstance(right, list):
        return left + [right]
    elif isinstance(left, list) and isinstance(right, list):
        return left + right
    elif isinstance(left, list) and not isinstance(right, list):
        return left + [right]
    elif not isinstance(left, list) and isinstance(right, list):
        return [left] + right
    else:
        return [left, right]


def normalize_clause(clause):
    def fetch_first(gen):
        rt = first(gen)
        assert rt is not None
        return rt

    if isinstance(clause.head, collections.abc.Iterator):
        clause.head = fetch_first(clause.head)
    if isinstance(clause.body, collections.abc.Iterator):
        clause.body = fetch_first(clause.body)
    if isinstance(clause.head, And):
        clause.head.formulae = reduce(reduce_and, clause.head, [])
    if isinstance(clause.body, And):
        clause.body.formulae = reduce(reduce_and, clause.body)
    return clause


class UnsupportedNegationError(Exception):
    def __init__(self, msg):
        super().__init__(msg)


class Clause(original_clause):
    """
    The RETE-UL algorithm supports conjunctions of facts in the head of a rule
    i.e.:   H1 ^ H2 ^ ... ^ H3 :- B1 ^  ^ Bm
    The Clause definition is overridden to permit this syntax (not allowed
    in definite LP or Horn rules)

    In addition, since we allow (in definite Horn) entailments beyond simple facts
    we ease restrictions on the form of the head to include Clauses
    """

    def __init__(self, body, head):
        self.body = body
        self.head = head
        if isinstance(head, Uniterm):
            from fuxi.Rete.Network import HashablePatternList

            try:
                ant_hash = HashablePatternList(
                    [term.to_rdf_tuple() for term in body], skip_b_nodes=True
                )
                cons_hash = HashablePatternList(
                    [term.to_rdf_tuple() for term in head], skip_b_nodes=True
                )
                self._bodyHash = hash(ant_hash)
                self._headHash = hash(cons_hash)
                self._hash = hash((self._headHash, self._bodyHash))
            except Exception:
                self._hash = None
        else:
            self._hash = None

    def __hash__(self):
        if self._hash is None:
            from fuxi.Rete.Network import HashablePatternList

            ant_hash = HashablePatternList(
                [term.to_rdf_tuple() for term in self.body], skip_b_nodes=True
            )
            cons_hash = HashablePatternList(
                [term.to_rdf_tuple() for term in self.head], skip_b_nodes=True
            )
            self._bodyHash = hash(ant_hash)
            self._headHash = hash(cons_hash)
            self._hash = hash((self._headHash, self._bodyHash))
        return self._hash

    def __repr__(self):
        return f"{self.head} :- {self.body}"

    def n3(self):
        return f"{ {self.body.n3()} } => { {self.head.n3()} }"


def make_rule(clause, ns_map):
    vars = set()
    for child in clause.head:
        if isinstance(child, Or):
            return None
        assert isinstance(child, Uniterm), repr(child)
        vars.update(
            [term for term in child.to_rdf_tuple() if isinstance(term, Variable)]
        )
    negative_stratus = False
    for child in clause.body:
        if hasattr(child, "naf") and child.naf:
            negative_stratus = True
        elif not hasattr(child, "naf"):
            child.naf = False
        vars.update(
            [term for term in child.to_rdf_tuple() if isinstance(term, Variable)]
        )
    return Rule(
        clause, declare=vars, ns_mapping=ns_map, negative_stratus=negative_stratus
    )


def disjunctive_normal_form(
    program: Iterable[Rule], safety: int = DATALOG_SAFETY_NONE, network=None
) -> Generator[Rule] | None:
    for rule in program:
        tx_horn_clause = normalize_clause(rule.formula)
        for tx_horn_clause in lloyd_topor_transformation(tx_horn_clause, True):
            if safety in [DATALOG_SAFETY_LOOSE, DATALOG_SAFETY_STRICT]:
                rule = Rule(
                    tx_horn_clause, ns_mapping={} if network is None else network.ns_map
                )
                if not rule.is_safe():
                    if safety == DATALOG_SAFETY_LOOSE:
                        warnings.warn(
                            f"Ignoring unsafe rule ({rule})", SyntaxWarning, 3
                        )
                        continue
                    elif safety == DATALOG_SAFETY_STRICT:
                        raise SyntaxError(f"Unsafe RIF Core rule: {rule}")
            disj = [i for i in breadth_first(tx_horn_clause.body) if isinstance(i, Or)]
            if len(disj) > 0:
                normalize_disjunctions(disj, tx_horn_clause, program, network)
            elif isinstance(tx_horn_clause.head, (And, Uniterm)):
                for hc in extend_n3_rules(network, normalize_clause(tx_horn_clause)):
                    yield make_rule(hc, network and network.ns_map or {})


def map_dlp_to_network(
    network,
    fact_graph,
    complement_expansions=None,
    construct_network=False,
    derived_preds=None,
    ignore_negative_stratus=False,
    safety=DATALOG_SAFETY_NONE,
):
    if complement_expansions is None:
        complement_expansions = []
    if derived_preds is None:
        derived_preds = []
    ruleset = set()
    negative_stratus = []
    for horn_clause in T(
        fact_graph,
        complement_expansions=complement_expansions,
        derived_preds=derived_preds,
    ):
        full_reduce = True
        for tx_horn_clause in lloyd_topor_transformation(horn_clause, full_reduce):
            tx_horn_clause = normalize_clause(tx_horn_clause)
            disj = [i for i in breadth_first(tx_horn_clause.body) if isinstance(i, Or)]
            if len(disj) > 0:
                normalize_disjunctions(
                    disj,
                    tx_horn_clause,
                    ruleset,
                    network,
                    construct_network,
                    negative_stratus,
                    ignore_negative_stratus,
                )
            elif isinstance(tx_horn_clause.head, (And, Uniterm)):
                for hc in extend_n3_rules(
                    network, normalize_clause(tx_horn_clause), construct_network
                ):
                    if safety in [DATALOG_SAFETY_LOOSE, DATALOG_SAFETY_STRICT]:
                        rule = Rule(hc, ns_mapping=network.ns_map)
                        if not rule.is_safe():
                            if safety == DATALOG_SAFETY_LOOSE:
                                warnings.warn(
                                    f"Ignoring unsafe rule ({rule})", SyntaxWarning, 3
                                )
                                continue
                            elif safety == DATALOG_SAFETY_STRICT:
                                raise SyntaxError(f"Unsafe RIF Core rule: {rule}")
                    _rule = make_rule(hc, network.ns_map)
                    if _rule.negative_stratus:
                        negative_stratus.append(_rule)
                    if _rule is not None and (
                        not _rule.negative_stratus or not ignore_negative_stratus
                    ):
                        ruleset.add(_rule)
    if ignore_negative_stratus:
        return ruleset, negative_stratus
    else:
        return iter(ruleset)


def isa_fact_forming_conclusion(head):
    if isinstance(head, And):
        for i in head:
            if not isa_fact_forming_conclusion(i):
                return False
        return True
    elif isinstance(head, Or):
        return False
    elif isinstance(head, Atomic):
        return True
    elif isinstance(head, original_clause):
        return False
    else:
        logger.error("Unexpected head type: %s", head)
        raise TypeError(f"Unexpected head type: {type(head)}")


def traverse_clause(condition):
    if isinstance(condition, SetOperator):
        yield from condition


def breadth_first(condition, children=traverse_clause):
    yield condition
    last = condition
    for node in breadth_first(condition, children):
        for child in children(node):
            yield child
            last = child
        if last == node:
            return


def breadth_first_replace(
    condition, children=traverse_clause, candidate=None, replacement=None
):
    yield condition
    last = condition
    for node in breadth_first_replace(condition, children, candidate, replacement):
        for child in children(node):
            yield child
            if candidate and child is candidate:
                i = node.formulae.index(child)
                node.formulae[i] = replacement
                return
            last = child
        if last == node:
            return


def extend_n3_rules(network, horn_clause, construct_network=False):
    from fuxi.Rete.AlphaNode import AlphaNode
    from fuxi.Rete.RuleStore import Formula

    rt = []
    if construct_network:
        rule_store = network.rule_store
        lhs = BNode()
        rhs = BNode()
    assert isinstance(horn_clause.body, (And, Uniterm)), list(horn_clause.body)
    assert len(list(horn_clause.body))
    if construct_network:
        for term in horn_clause.body:
            rule_store.formulae.setdefault(lhs, Formula(lhs)).append(
                term.to_rdf_tuple()
            )
    assert isinstance(horn_clause.head, (And, Uniterm)), repr(horn_clause.head)

    if isa_fact_forming_conclusion(horn_clause.head):
        prepare_horn_clause_for_rete(horn_clause)
        if construct_network:
            for term in horn_clause.head:
                assert not isinstance(term, collections.abc.Iterator)
                if isinstance(term, Or):
                    rule_store.formulae.setdefault(rhs, Formula(rhs)).append(term)
                else:
                    rule_store.formulae.setdefault(rhs, Formula(rhs)).append(
                        term.to_rdf_tuple()
                    )
            rule_store.rules.append(
                (rule_store.formulae[lhs], rule_store.formulae[rhs])
            )
            network.build_network(
                iter(rule_store.formulae[lhs]),
                iter(rule_store.formulae[rhs]),
                Rule(horn_clause),
            )
            network.alpha_nodes = [
                node
                for node in list(network.nodes.values())
                if isinstance(node, AlphaNode)
            ]
        rt.append(horn_clause)
    else:
        for hc in lloyd_topor_transformation(horn_clause, full_reduction=True):
            rt.append(hc)
            for i in extend_n3_rules(network, hc, construct_network):
                rt.append(hc)
    return rt


def prepare_head_existential(clause):
    from fuxi.Rete.SidewaysInformationPassing import get_args

    skolems_in_head = [
        list(filter(lambda term: isinstance(term, BNode), get_args(lit)))
        for lit in iter_condition(clause.head)
    ]
    skolems_in_head = reduce(lambda x, y: x + y, skolems_in_head, [])
    if skolems_in_head:
        new_head = copy.deepcopy(clause.head)
        _e = Exists(formula=new_head, declare=set(skolems_in_head))
        clause.head = _e
    return clause


def prepare_horn_clause_for_rete(horn_clause):
    if isinstance(horn_clause, Rule):
        horn_clause = horn_clause.formula

    def extract_variables(term, existential=True):
        if isinstance(term, existential and BNode or Variable):
            yield term
        elif isinstance(term, Uniterm):
            for t in term.to_rdf_tuple():
                if isinstance(t, existential and BNode or Variable):
                    yield t

    from fuxi.Rete.SidewaysInformationPassing import get_args, iter_condition

    body_vars = set(
        reduce(
            lambda x, y: x + y,
            [
                list(extract_variables(i, existential=False))
                for i in iter_condition(horn_clause.body)
            ],
        )
    )

    head_vars = set(
        reduce(
            lambda x, y: x + y,
            [
                list(extract_variables(i, existential=False))
                for i in iter_condition(horn_clause.head)
            ],
        )
    )

    update_dict = dict([(var, BNode()) for var in head_vars if var not in body_vars])

    if set(update_dict.keys()).intersection(get_args(horn_clause.head)):
        new_head = copy.deepcopy(horn_clause.head)
        for uni_term in iter_condition(new_head):
            new_arg = [update_dict.get(i, i) for i in uni_term.arg]
            uni_term.arg = new_arg
        horn_clause.head = new_head

    skolems_in_body = [
        list(filter(lambda term: isinstance(term, BNode), get_args(lit)))
        for lit in iter_condition(horn_clause.body)
    ]
    skolems_in_body = reduce(lambda x, y: x + y, skolems_in_body, [])
    if skolems_in_body:
        new_body = copy.deepcopy(horn_clause.body)
        _e = Exists(formula=new_body, declare=set(skolems_in_body))
        horn_clause.body = _e

    prepare_head_existential(horn_clause)


def generator_flattener(gen):
    assert isinstance(gen, collections.abc.Iterator)
    i = list(gen)
    i = (
        len(i) > 1
        and [
            isinstance(i2, collections.abc.Iterator) and generator_flattener(i2) or i2
            for i2 in i
        ]
        or i[0]
    )
    if isinstance(i, collections.abc.Iterator):
        raise RuntimeError
        # i = listOrThingGenerator(i)
        # return i
    elif isinstance(i, SetOperator):
        i.formulae = [
            isinstance(i2, collections.abc.Iterator) and generator_flattener(i2) or i2
            for i2 in i.formulae
        ]
        return i
    else:
        return i


def skolemize_existential_classes(term, check=True):
    if check:
        return isinstance(term, BNode) and SKOLEMIZED_CLASS_NS[term] or term
    return SKOLEMIZED_CLASS_NS[term]


def normalize_boolean_class_operand(term, owl_graph):
    return (
        (
            (isinstance(term, BNode) and isa_boolean_class_description(term, owl_graph))
            or isa_restriction(term, owl_graph)
        )
        and skolemize_existential_classes(term)
        or term
    )


def isa_boolean_class_description(term, owl_graph):
    for _ in owl_graph.triples_choices(
        (term, [OWL_NS.unionOf, OWL_NS.intersectionOf], None)
    ):
        return True


def isa_restriction(term, owl_graph):
    return (term, RDF.type, OWL_NS.Restriction) in owl_graph


def iter_condition(condition):
    return isinstance(condition, SetOperator) and condition or iter([condition])


def Tc(owl_graph, negated_formula):
    if (negated_formula, OWL_NS.hasValue, None) in owl_graph:
        body_uni_term = Uniterm(
            RDF.type,
            [
                Variable("X"),
                normalize_boolean_class_operand(negated_formula, owl_graph),
            ],
            new_nss=owl_graph.namespaces(),
        )

        condition = normalize_clause(
            Clause(Tb(owl_graph, negated_formula), body_uni_term)
        ).body
        assert isinstance(condition, Uniterm)
        condition.naf = True
        return condition
    elif (negated_formula, OWL_NS.someValuesFrom, None) in owl_graph:
        binary_rel, unary_rel = Tb(owl_graph, negated_formula)
        negated_binary_rel = copy.deepcopy(binary_rel)
        negated_binary_rel.naf = True
        negated_unary_rel = copy.deepcopy(unary_rel)
        negated_unary_rel.naf = True
        return Or([negated_binary_rel, And([binary_rel, negated_unary_rel])])
    elif isinstance(negated_formula, URIRef):
        return Uniterm(
            RDF.type,
            [
                Variable("X"),
                normalize_boolean_class_operand(negated_formula, owl_graph),
            ],
            new_nss=owl_graph.namespaces(),
            naf=True,
        )
    else:
        raise UnsupportedNegationError(
            f"Unsupported negated concept: {negated_formula}"
        )


class MalformedDLPFormulaError(NotImplementedError):
    def __init__(self, message):
        self.message = message


def handle_conjunct(conjunction, owl_graph, o, conjunct_var=Variable("X")):
    for body_term in Collection(owl_graph, o):
        negated_formula = False
        add_to_conjunct = None
        for negated_formula in owl_graph.objects(
            subject=body_term, predicate=OWL_NS.complementOf
        ):
            add_to_conjunct = Tc(owl_graph, negated_formula)
        if negated_formula:
            conjunction.append(add_to_conjunct)
        else:
            normalized_body_term = normalize_boolean_class_operand(body_term, owl_graph)
            body_uni_term = Uniterm(
                RDF.type,
                [conjunct_var, normalized_body_term],
                new_nss=owl_graph.namespaces(),
            )
            processed_body_term = Tb(owl_graph, body_term, conjunct_var)
            classifying_clause = normalize_clause(
                Clause(processed_body_term, body_uni_term)
            )
            if (
                isinstance(normalized_body_term, URIRef)
                and normalized_body_term.find(SKOLEMIZED_CLASS_NS) == -1
            ):
                conjunction.append(body_uni_term)
            elif (body_term, OWL_NS.someValuesFrom, None) in owl_graph or (
                body_term,
                OWL_NS.hasValue,
                None,
            ) in owl_graph:
                conjunction.extend(classifying_clause.body)
            elif (body_term, OWL_NS.allValuesFrom, None) in owl_graph:
                raise MalformedDLPFormulaError(
                    "Universal restrictions can only be used as "
                    "the second argument to rdfs:subClassOf (GCIs)"
                )
            elif (body_term, OWL_NS.unionOf, None) in owl_graph:
                conjunction.append(classifying_clause.body)
            elif (body_term, OWL_NS.intersectionOf, None) in owl_graph:
                conjunction.append(body_uni_term)


def T(owl_graph, complement_expansions=None, derived_preds=None):
    if complement_expansions is None:
        complement_expansions = []
    if derived_preds is None:
        derived_preds = []
    for s, p, o in owl_graph.triples((None, OWL_NS.complementOf, None)):
        if isinstance(o, URIRef) and isinstance(s, URIRef):
            head_literal = Uniterm(
                RDF.type,
                [Variable("X"), skolemize_existential_classes(s)],
                new_nss=owl_graph.namespaces(),
            )
            yield normalize_clause(Clause(Tc(owl_graph, o), head_literal))
    for c, p, d in owl_graph.triples((None, RDFS.subClassOf, None)):
        try:
            yield normalize_clause(Clause(Tb(owl_graph, c), Th(owl_graph, d)))
        except UnsupportedNegationError:
            warnings.warn(
                f"Unable to handle negation in DL axiom ({c}), skipping",
                SyntaxWarning,
                3,
            )
    for c, p, d in owl_graph.triples((None, OWL_NS.equivalentClass, None)):
        if c not in derived_preds:
            yield normalize_clause(Clause(Tb(owl_graph, c), Th(owl_graph, d)))
        yield normalize_clause(Clause(Tb(owl_graph, d), Th(owl_graph, c)))
    for s, p, o in owl_graph.triples((None, OWL_NS.intersectionOf, None)):
        try:
            if s not in complement_expansions:
                if s in derived_preds:
                    warnings.warn(
                        f"Derived predicate ({owl_graph.qname(s)}) "
                        f"is defined via a conjunction "
                        f"(consider using a complex GCI) ",
                        SyntaxWarning,
                        3,
                    )
                elif isinstance(s, BNode):
                    continue
                conjunction = []
                handle_conjunct(conjunction, owl_graph, o)
                body = And(conjunction)
                head = Uniterm(
                    RDF.type,
                    [Variable("X"), skolemize_existential_classes(s)],
                    new_nss=owl_graph.namespaces(),
                )
                yield Clause(body, head)
                if isinstance(s, URIRef):
                    if s not in derived_preds:
                        yield Clause(head, body)
        except UnsupportedNegationError:
            warnings.warn(
                f"Unable to handle negation in DL axiom ({s}), skipping",
                SyntaxWarning,
                3,
            )

    for s, p, o in owl_graph.triples((None, OWL_NS.unionOf, None)):
        if isinstance(s, URIRef):
            body = Or(
                [
                    Uniterm(
                        RDF.type,
                        [Variable("X"), normalize_boolean_class_operand(i, owl_graph)],
                        new_nss=owl_graph.namespaces(),
                    )
                    for i in Collection(owl_graph, o)
                ]
            )
            head = Uniterm(RDF.type, [Variable("X"), s], new_nss=owl_graph.namespaces())
            yield Clause(body, head)
    for s, p, o in owl_graph.triples((None, OWL_NS.inverseOf, None)):
        new_var = Variable(BNode())

        s = skolemize_existential_classes(s) if isinstance(s, BNode) else s
        o = skolemize_existential_classes(o) if isinstance(o, BNode) else o

        body1 = Uniterm(s, [new_var, Variable("X")], new_nss=owl_graph.namespaces())
        head1 = Uniterm(o, [Variable("X"), new_var], new_nss=owl_graph.namespaces())
        yield Clause(body1, head1)
        new_var = Variable(BNode())
        body2 = Uniterm(o, [Variable("X"), new_var], new_nss=owl_graph.namespaces())
        head2 = Uniterm(s, [new_var, Variable("X")], new_nss=owl_graph.namespaces())
        yield Clause(body2, head2)
    for s, p, o in owl_graph.triples((None, RDF.type, OWL_NS.TransitiveProperty)):
        y = Variable(BNode())
        z = Variable(BNode())
        x = Variable("X")

        s = skolemize_existential_classes(s) if isinstance(s, BNode) else s

        body = And(
            [
                Uniterm(s, [x, y], new_nss=owl_graph.namespaces()),
                Uniterm(s, [y, z], new_nss=owl_graph.namespaces()),
            ]
        )
        head = Uniterm(s, [x, z], new_nss=owl_graph.namespaces())
        yield Clause(body, head)
    for s, p, o in owl_graph.triples((None, RDFS.subPropertyOf, None)):
        x = Variable("X")
        y = Variable("Y")

        s = skolemize_existential_classes(s) if isinstance(s, BNode) else s
        o = skolemize_existential_classes(o) if isinstance(o, BNode) else o

        body = Uniterm(s, [x, y], new_nss=owl_graph.namespaces())
        head = Uniterm(o, [x, y], new_nss=owl_graph.namespaces())

        yield Clause(body, head)
    for s, p, o in owl_graph.triples((None, OWL_NS.equivalentProperty, None)):
        x = Variable("X")
        y = Variable("Y")

        s = skolemize_existential_classes(s) if isinstance(s, BNode) else s
        o = skolemize_existential_classes(o) if isinstance(o, BNode) else o

        body = Uniterm(s, [x, y], new_nss=owl_graph.namespaces())
        head = Uniterm(o, [x, y], new_nss=owl_graph.namespaces())
        yield Clause(body, head)
        yield Clause(head, body)

    for s, p, o in owl_graph.triples((None, RDF.type, OWL_NS.SymmetricProperty)):
        y = Variable("Y")
        x = Variable("X")

        s = skolemize_existential_classes(s) if isinstance(s, BNode) else s

        body = Uniterm(s, [x, y], new_nss=owl_graph.namespaces())
        head = Uniterm(s, [y, x], new_nss=owl_graph.namespaces())
        yield Clause(body, head)

    for s, p, o in owl_graph.triples_choices((None, [RDFS.range, RDFS.domain], None)):
        s = skolemize_existential_classes(s) if isinstance(s, BNode) else s

        if p == RDFS.range:
            x = Variable("X")
            y = Variable(BNode())
            body = Uniterm(s, [x, y], new_nss=owl_graph.namespaces())
            head = Uniterm(RDF.type, [y, o], new_nss=owl_graph.namespaces())
            yield Clause(body, head)
        else:
            x = Variable("X")
            y = Variable(BNode())
            body = Uniterm(s, [x, y], new_nss=owl_graph.namespaces())
            head = Uniterm(RDF.type, [x, o], new_nss=owl_graph.namespaces())
            yield Clause(body, head)


def lloyd_topor_transformation(clause, full_reduction=True):
    assert isinstance(clause, original_clause), repr(clause)
    assert isinstance(clause.body, Condition), repr(clause.body)
    if isinstance(clause.body, Or):
        for atom in clause.body.formulae:
            if isinstance(atom, collections.abc.Iterator):
                atom = first(atom)
            yield from lloyd_topor_transformation(
                normalize_clause(Clause(atom, clause.head)),
                full_reduction=full_reduction,
            )
    elif isinstance(clause.head, original_clause):
        yield normalize_clause(
            Clause(And([clause.body, clause.head.body]), clause.head.head)
        )
    elif full_reduction and (
        (isinstance(clause.head, Exists) and isinstance(clause.head.formula, And))
        or isinstance(clause.head, And)
    ):
        if isinstance(clause.head, Exists):
            head = clause.head.formula
        elif isinstance(clause.head, And):
            head = clause.head
        for i in head:
            for j in lloyd_topor_transformation(
                Clause(clause.body, i), full_reduction=full_reduction
            ):
                if [i for i in breadth_first(j.head) if isinstance(i, And)]:
                    yield prepare_head_existential(normalize_clause(j))
                else:
                    yield prepare_head_existential(j)
    else:
        yield clause


def Th(owl_graph, _class, variable=Variable("X"), position=LHS):
    props = list(set(owl_graph.predicates(subject=_class)))
    if OWL_NS.allValuesFrom in props:
        for s, p, o in owl_graph.triples((_class, OWL_NS.allValuesFrom, None)):
            prop = list(owl_graph.objects(subject=_class, predicate=OWL_NS.onProperty))[
                0
            ]
            new_var = Variable(BNode())
            body = Uniterm(prop, [variable, new_var], new_nss=owl_graph.namespaces())
            for head in Th(owl_graph, o, variable=new_var):
                yield Clause(body, head)
    elif OWL_NS.hasValue in props:
        prop = list(owl_graph.objects(subject=_class, predicate=OWL_NS.onProperty))[0]
        o = first(owl_graph.objects(subject=_class, predicate=OWL_NS.hasValue))
        yield Uniterm(prop, [variable, o], new_nss=owl_graph.namespaces())
    elif OWL_NS.someValuesFrom in props:
        for s, p, o in owl_graph.triples((_class, OWL_NS.someValuesFrom, None)):
            prop = list(owl_graph.objects(subject=_class, predicate=OWL_NS.onProperty))[
                0
            ]
            new_var = BNode()
            yield And(
                [
                    Uniterm(prop, [variable, new_var], new_nss=owl_graph.namespaces()),
                    generator_flattener(Th(owl_graph, o, variable=new_var)),
                ]
            )
    elif OWL_NS.intersectionOf in props:
        from fuxi.Syntax.InfixOWL import BooleanClass

        yield And([first(Th(owl_graph, h, variable)) for h in BooleanClass(_class)])
    else:
        yield Uniterm(
            RDF.type,
            [
                variable,
                isinstance(_class, BNode)
                and skolemize_existential_classes(_class)
                or _class,
            ],
            new_nss=owl_graph.namespaces(),
        )


def Tb(owl_graph, _class, variable=Variable("X")):
    props = list(set(owl_graph.predicates(subject=_class)))
    if OWL_NS.intersectionOf in props and not isinstance(_class, URIRef):
        for s, p, o in owl_graph.triples((_class, OWL_NS.intersectionOf, None)):
            conj = []
            handle_conjunct(conj, owl_graph, o, variable)
            return And(conj)
    elif OWL_NS.unionOf in props and not isinstance(_class, URIRef):
        for s, p, o in owl_graph.triples((_class, OWL_NS.unionOf, None)):
            return Or(
                [Tb(owl_graph, c, variable=variable) for c in Collection(owl_graph, o)]
            )
    elif OWL_NS.someValuesFrom in props:
        prop = list(owl_graph.objects(subject=_class, predicate=OWL_NS.onProperty))[0]
        o = list(owl_graph.objects(subject=_class, predicate=OWL_NS.someValuesFrom))[0]
        new_var = Variable(BNode())
        return And(
            [
                Uniterm(prop, [variable, new_var], new_nss=owl_graph.namespaces()),
                Tb(owl_graph, o, variable=new_var),
            ]
        )
    elif OWL_NS.hasValue in props:
        prop = list(owl_graph.objects(subject=_class, predicate=OWL_NS.onProperty))[0]
        o = first(owl_graph.objects(subject=_class, predicate=OWL_NS.hasValue))
        return Uniterm(prop, [variable, o], new_nss=owl_graph.namespaces())
    elif OWL_NS.complementOf in props:
        return Tc(owl_graph, first(owl_graph.objects(_class, OWL_NS.complementOf)))
    else:
        _class_term = skolemize_existential_classes(_class)
        return Uniterm(
            RDF.type, [variable, _class_term], new_nss=owl_graph.namespaces()
        )
