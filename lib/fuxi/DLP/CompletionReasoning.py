# -*- coding: utf-8 -*-
# flake8: noqa
"""
Solution:
Unadorned:

Query: rdfs:subClassOf_bf(KneeJoint,?Class)
Query fact: rdfs:subClassOf_derived_query_bf(KneeJoint)

7. Forall ?C3 ?C2 ?C1 (
    rdfs:subClassOf_derived_bf(?C1 ?C3)
        :- And( rdfs:subClassOf_derived_bf(?C1 ?C2)
                rdfs:subClassOf_derived_bf(?C2 ?C3) ) )

        { subClassOf }             -> ?C1 subClassOf_C1_C2
        { subClassOf, subClassOf } -> ?C2 subClassOf_C2_C3

"""

__author__ = "chimezieogbuji"

import sys

# from pprint import pprint
from fuxi.DLP import NON_DHL_OWL_SEMANTICS as SUBSUMPTION_SEMANTICS
from fuxi.DLP import SKOLEMIZED_CLASS_NS
from fuxi.DLP import skolemize_existential_classes
from fuxi.Horn.HornRules import horn_from_n3
from fuxi.Rete.RuleStore import setup_rule_store
from fuxi.SPARQL.BackwardChainingStore import TopDownSPARQLEntailingStore
from fuxi.Syntax.InfixOWL import all_classes
from fuxi.Syntax.InfixOWL import BooleanClass
from fuxi.Syntax.InfixOWL import cast_class
from fuxi.Syntax.InfixOWL import Class
from fuxi.Syntax.InfixOWL import ClassNamespaceFactory
from fuxi.Syntax.InfixOWL import Individual
from fuxi.Syntax.InfixOWL import OWL_NS
from fuxi.Syntax.InfixOWL import Property
from fuxi.Syntax.InfixOWL import Restriction
from fuxi.Syntax.InfixOWL import some
from rdflib import (
    Graph,
    BNode,
    Namespace,
    OWL,
    RDF,
    RDFS,
    URIRef,
    Variable,
)

# try:
#     from functools import reduce
# except ImportError:
#     pass
from io import StringIO

import logging

log = logging.getLogger(__name__)

LIST_NS = Namespace("http://www.w3.org/2000/10/swap/list#")
KOR_NS = Namespace("http://korrekt.org/")
EX_NS = Namespace("http://example.com/")
EX_CL = ClassNamespaceFactory(EX_NS)

derived_predicates = [
    LIST_NS["in"],
    KOR_NS.subPropertyOf,
    RDFS.subClassOf,
    OWL.onProperty,
    OWL.someValuesFrom,
]

hybridPredicates = [RDFS.subClassOf, OWL.onProperty, OWL.someValuesFrom]

CONDITIONAL_THING_RULE = """
@prefix kor:    <http://korrekt.org/>.
@prefix owl:    <http://www.w3.org/2002/07/owl#>.
@prefix rdfs:   <http://www.w3.org/2000/01/rdf-schema#>.
@prefix rdf:    <http://www.w3.org/1999/02/22-rdf-syntax-ns#>.
@prefix list:   <http://www.w3.org/2000/10/swap/list#>.

#Rule 4 (needs to be added conditionally - only if owl:Thing appears in the ontology)
{ ?C rdfs:subClassOf ?C } => { ?C rdfs:subClassOf owl:Thing }."""

RULES = """
@prefix kor:    <http://korrekt.org/>.
@prefix owl:    <http://www.w3.org/2002/07/owl#>.
@prefix rdfs:   <http://www.w3.org/2000/01/rdf-schema#>.
@prefix rdf:    <http://www.w3.org/1999/02/22-rdf-syntax-ns#>.
@prefix list:   <http://www.w3.org/2000/10/swap/list#>.
#ELH completion rules in N3 / RIF / Datalog

{?L rdf:first ?I}               => {?I list:in ?L} .
{?L rdf:rest ?R. ?I list:in ?R} => {?I list:in ?L} .

#CTO: Sufficient to assert ?R kor:subPropertyOf ?R for all properties ?R in ontology?
{ ?P1 rdfs:subPropertyOf ?P2 } => { ?P1 kor:subPropertyOf ?P2 } .

#kor:subPropertyOf a owl:TransitiveProperty .
{ ?P1 kor:subPropertyOf ?P2 . ?P2 kor:subPropertyOf ?P3 } => { ?P1 kor:subPropertyOf ?P3 } .

#Rule 1
#rdfs:subClassOf a owl:TransitiveProperty
{ ?C1 rdfs:subClassOf ?C2 . ?C2 rdfs:subClassOf ?C3 } => { ?C1 rdfs:subClassOf ?C3 } .

#Rule 2 (CTO: Different from LL's formulation?)
{ ?C  rdfs:subClassOf ?CLASS .
  ?CLASS owl:intersectionOf ?L  .
  ?D list:in ?L  } => { ?C rdfs:subClassOf ?D } .

#Rule 3
{ ?C rdfs:subClassOf ?RESTRICTION .
  ?RESTRICTION owl:onProperty ?R ;
               owl:someValuesFrom ?D } => { ?D rdfs:subClassOf ?D } .

#Rule 5
{ ?C rdfs:subClassOf ?D1, ?D2 .
  ?D1 list:in ?L .
  ?D2 list:in ?L .
  ?E owl:intersectionOf ?L } => { ?C rdfs:subClassOf ?E } .

#Rule 6
{ ?C rdfs:subClassOf ?D .
  ?E owl:onProperty ?S ;
     owl:someValuesFrom ?D
 } => { [ a owl:Restriction;
          owl:onProperty ?S ;
          owl:someValuesFrom ?C ] rdfs:subClassOf ?E } .

#Rule 7
{ ?D rdfs:subClassOf ?RESTRICTION1 .
  ?RESTRICTION1 owl:onProperty ?R ;
               owl:someValuesFrom ?C  .
  ?RESTRICTION2 owl:onProperty ?S ;
                owl:someValuesFrom ?C .
  ?RESTRICTION2 rdfs:subClassOf ?E .
  ?R kor:subPropertyOf ?S } => { ?D rdfs:subClassOf ?E } .

#Rule 8
{ ?D rdfs:subClassOf ?RESTRICTION1 .
  ?RESTRICTION1 owl:onProperty ?R ;
               owl:someValuesFrom ?C  .
  ?RESTRICTION2 owl:onProperty ?S ;
                owl:someValuesFrom ?C .
  ?RESTRICTION2 rdfs:subClassOf ?E .
  ?R kor:subPropertyOf ?T .
  ?T kor:subPropertyOf ?S .
  ?T a owl:TransitiveProperty } => {
  [ a owl:Restriction;
    owl:onProperty ?T ;
    owl:someValuesFrom ?D ] rdfs:subClassOf ?E } .
"""

LEFT_SUBSUMPTION_OPERAND = 0
RIGHT_SUBSUMPTION_OPERAND = 1
BOTH_SUBSUMPTION_OPERAND = 2
NEITHER_SUBSUMPTION_OPERAND = 3

SUBSUMPTION_SEMANTICS = """
@prefix log: <http://www.w3.org/2000/10/swap/log#>.
@prefix str: <http://www.w3.org/2000/10/swap/string#>.
@prefix owl: <http://www.w3.org/2002/07/owl#>.
@prefix xsd: <http://www.w3.org/2001/XMLSchema#>.
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#>.
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>.
@prefix e: <http://eulersharp.sourceforge.net/2003/03swap/log-rules#>.
@prefix : <http://eulersharp.sourceforge.net/2003/03swap/rdfs-rules#>.


### Resource Description Framework RDF(S)

rdf:Alt rdfs:subClassOf rdfs:Container.
rdf:Bag rdfs:subClassOf rdfs:Container.
rdfs:ContainerMembershipProperty rdfs:subClassOf rdf:Property.
rdfs:Datatype rdfs:subClassOf rdfs:Class.
rdf:Seq rdfs:subClassOf rdfs:Container.
rdf:XMLLiteral rdfs:subClassOf rdfs:Literal; a rdfs:Datatype.

rdfs:comment rdfs:domain rdfs:Resource; rdfs:range rdfs:Literal.
rdfs:domain rdfs:domain rdf:Property; rdfs:range rdfs:Class.
rdf:first rdfs:domain rdf:List; rdfs:range rdfs:Resource; a owl:FunctionalProperty.
rdfs:isDefinedBy rdfs:domain rdfs:Resource; rdfs:range rdfs:Resource; rdfs:subPropertyOf rdfs:seeAlso.
rdfs:label rdfs:domain rdfs:Resource; rdfs:range rdfs:Literal.
rdfs:member rdfs:domain rdfs:Container; rdfs:range rdfs:Resource.
rdf:object rdfs:domain rdf:Statement; rdfs:range rdfs:Resource.
rdf:predicate rdfs:domain rdf:Statement; rdfs:range rdf:Property.
rdfs:range rdfs:domain rdf:Property; rdfs:range rdfs:Class.
rdf:rest rdfs:domain rdf:List; rdfs:range rdf:List; a owl:FunctionalProperty.
rdfs:seeAlso rdfs:domain rdfs:Resource; rdfs:range rdfs:Resource.
rdfs:subClassOf rdfs:domain rdfs:Class; rdfs:range rdfs:Class.
rdfs:subPropertyOf rdfs:domain rdf:Property; rdfs:range rdf:Property.
rdf:subject rdfs:domain rdf:Statement; rdfs:range rdfs:Resource.
rdf:type rdfs:domain rdfs:Resource; rdfs:range rdfs:Class.
rdf:value rdfs:domain rdfs:Resource; rdfs:range rdfs:Resource.

rdf:nil a rdf:List.


### inference rules for RDF(S)

{?S ?P ?O} => {?P a rdf:Property}.

{?P @has rdfs:domain ?C. ?S ?P ?O} => {?S a ?C}.

{?P @has rdfs:range ?C. ?S ?P ?O} => {?O a ?C}.

{?S ?P ?O} => {?S a rdfs:Resource}.
{?S ?P ?O} => {?O a rdfs:Resource}.

{?Q rdfs:subPropertyOf ?R. ?P rdfs:subPropertyOf ?Q} => {?P rdfs:subPropertyOf ?R}.

{?P @has rdfs:subPropertyOf ?R. ?S ?P ?O} => {?S ?R ?O}.

{?C a rdfs:Class} => {?C rdfs:subClassOf rdfs:Resource}.

{?A rdfs:subClassOf ?B. ?S a ?A} => {?S a ?B}.

{?B rdfs:subClassOf ?C. ?A rdfs:subClassOf ?B} => {?A rdfs:subClassOf ?C}.

{?X a rdfs:ContainerMembershipProperty} => {?X rdfs:subPropertyOf rdfs:member}.

{?X a rdfs:Datatype} => {?X rdfs:subClassOf rdfs:Literal}.


### inconsistency detections @@

{?S a rdf:XMLLiteral; e:clashesWith rdf:XMLLiteral} => false.
"""


def which_subsumption_operand(term, owl_graph):
    top_down_store = TopDownSPARQLEntailingStore(owl_graph.store, owl_graph,
                                                 idb=horn_from_n3(StringIO(SUBSUMPTION_SEMANTICS)), debug=False)
    target_graph = Graph(top_down_store)
    appears_left = target_graph.query(
        "ASK { <%s> rdfs:subClassOf [] } ", initNs={"rdfs": RDFS}
    )
    appears_right = target_graph.query(
        "ASK { [] rdfs:subClassOf <%s> } ", initNs={"rdfs": RDFS}
    )
    if appears_left and appears_right:
        return BOTH_SUBSUMPTION_OPERAND
    elif appears_left:
        return LEFT_SUBSUMPTION_OPERAND
    else:
        return RIGHT_SUBSUMPTION_OPERAND


def structural_transformation(owl_graph, new_owl_graph):
    """
    Entry point for the transformation of the given ontology

    >>> EX = Namespace('http://example.com/')
    >>> EX_CL = ClassNamespaceFactory(EX)
    >>> graph = Graph()
    >>> graph.bind('ex', EX, True)
    >>> Individual.factoryGraph = graph
    >>> kneeJoint = EX_CL.KneeJoint
    >>> joint = EX_CL.Joint
    >>> knee  = EX_CL.Knee
    >>> isPartOf = Property(EX.isPartOf)
    >>> structure = EX_CL.Structure
    >>> leg = EX_CL.Leg
    >>> hasLocation = Property(EX.hasLocation)

    >>> kneeJoint.equivalent_class = [joint & (isPartOf | some | knee)]
    >>> legStructure = EX_CL.LegStructure
    >>> legStructure.equivalent_class = [structure & (isPartOf | some | leg)]
    >>> structure += leg
    >>> locatedInLeg = hasLocation | some | leg
    >>> locatedInLeg += knee

    >>> newGraph, conceptMap = structural_transformation(graph, Graph())
    >>> revDict = dict([(v, k) for k, v in conceptMap.items()])
    >>> newGraph.bind('ex', EX, True)
    >>> Individual.factoryGraph = newGraph

    Generated concepts can be listed ...

    .. code-block:: python

        for c in AllClasses(newGraph):
            if c.identifier in revDict:
                print("## New concept for %s ##" % revDict[c.identifier])
            print(c.__repr__(True))
            print("################################")

    """
    FreshConcept = {}
    new_owl_graph.bind("skolem", SKOLEMIZED_CLASS_NS, True)

    for cls in all_classes(owl_graph):
        process_concept(cls, owl_graph, FreshConcept, new_owl_graph)
    return new_owl_graph, FreshConcept


def process_concept(klass, owl_graph, fresh_concept, new_owl_graph):
    """
    This method implements the pre-processing portion of the completion-based procedure
    and recursively transforms the input ontology one concept at a time
    """
    iD = klass.identifier
    # maps the identifier to skolem:bnodeLabel if
    # the identifier is a BNode or to skolem:newBNodeLabel
    # if its a URI
    fresh_concept[iD] = skolemize_existential_classes(
        BNode() if isinstance(iD, URIRef) else iD
    )
    # A fresh atomic concept (A_c)
    new_cls = Class(fresh_concept[iD], graph=new_owl_graph)

    cls = cast_class(klass, owl_graph)

    # determine if the concept is the left, right (or both)
    # operand of a subsumption axiom in the ontology
    location = which_subsumption_operand(iD, owl_graph)
    # log.debug(repr(cls))
    if isinstance(iD, URIRef):
        # An atomic concept?
        if location in [LEFT_SUBSUMPTION_OPERAND, BOTH_SUBSUMPTION_OPERAND]:
            log.debug(
                "Original (atomic) concept appears in the left HS of a subsumption axiom"
            )
            # If class is left operand of subsumption operator,
            # assert (in new OWL graph) that A_c subsumes the concept
            _cls = Class(cls.identifier, graph=new_owl_graph)
            new_cls += _cls
            log.debug("%s subsumes %s" % (new_cls, _cls))
        if location in [RIGHT_SUBSUMPTION_OPERAND, BOTH_SUBSUMPTION_OPERAND]:
            log.debug(
                "Original (atomic) concept appears in the right HS of a subsumption axiom"
            )
            # If class is right operand of subsumption operator,
            # assert that it subsumes A_c
            _cls = Class(cls.identifier, graph=new_owl_graph)
            _cls += new_cls
            log.debug("%s subsumes %s" % (_cls, new_cls))
    elif isinstance(cls, Restriction):
        if location != NEITHER_SUBSUMPTION_OPERAND:
            # appears in at least one subsumption operator

            # An existential role restriction
            log.debug("Original (role restriction) appears in a subsumption axiom")
            role = Property(cls.on_property, graph=new_owl_graph)

            filler_cls = process_concept(
                Class(cls.restrictionRange), owl_graph, fresh_concept, new_owl_graph
            )
            # left_cls is (role SOME filler_cls)
            left_cls = role | some | filler_cls
            log.debug("let left_cls be %s" % left_cls)
            if location in [LEFT_SUBSUMPTION_OPERAND, BOTH_SUBSUMPTION_OPERAND]:
                # if appears as the left operand, we say A_c subsumes
                # left_cls
                new_cls += left_cls
                log.debug("%s subsumes left_cls" % new_cls)
            if location in [RIGHT_SUBSUMPTION_OPERAND, BOTH_SUBSUMPTION_OPERAND]:
                # if appears as right operand, we say left Cls subsumes A_c
                left_cls += new_cls
                log.debug("left_cls subsumes %s" % new_cls)
    else:
        assert isinstance(cls, BooleanClass), "Not ELH ontology: %r" % cls
        assert cls._operator == OWL_NS.intersectionOf, "Not ELH ontology"
        log.debug(
            "Original conjunction (or boolean operator wlog ) appears in a subsumption axiom"
        )
        # A boolean conjunction
        if location != NEITHER_SUBSUMPTION_OPERAND:
            members = [
                process_concept(Class(c), owl_graph, fresh_concept, new_owl_graph)
                for c in cls
            ]
            new_boolean = BooleanClass(BNode(), members=members, graph=new_owl_graph)
            # create a boolean conjunction of the fresh concepts corresponding
            # to processing each member of the existing conjunction
            if location in [LEFT_SUBSUMPTION_OPERAND, BOTH_SUBSUMPTION_OPERAND]:
                # if appears as the left operand, we say the new conjunction
                # is subsumed by A_c
                new_cls += new_boolean
                log.debug("%s subsumes %s" % (new_cls, new_boolean))
            if location in [RIGHT_SUBSUMPTION_OPERAND, BOTH_SUBSUMPTION_OPERAND]:
                # if appears as the right operand, we say A_c is subsumed by
                # the new conjunction
                new_boolean += new_cls
                log.debug("%s subsumes %s" % (new_boolean, new_cls))
    return new_cls


def create_test_ont_graph():
    graph = Graph()
    graph.bind("ex", EX_NS, True)
    Individual.factoryGraph = graph
    knee_joint = EX_CL.KneeJoint
    joint = EX_CL.Joint

    knee = EX_CL.Knee
    is_part_of = Property(EX_NS.isPartOf)
    graph.add((is_part_of.identifier, RDF.type, OWL_NS.TransitiveProperty))
    structure = EX_CL.Structure
    leg = EX_CL.Leg
    has_location = Property(EX_NS.hasLocation, sub_property_of=[is_part_of])
    # graph.add((has_location.identifier,RDFS.subPropertyOf,is_part_of.identifier))

    knee_joint.equivalent_class = [joint & (is_part_of | some | knee)]
    leg_structure = EX_CL.LegStructure
    leg_structure.equivalent_class = [structure & (is_part_of | some | leg)]
    structure += leg
    structure += joint
    located_in_leg = has_location | some | leg
    located_in_leg += knee
    return graph


def setup_meta_interpreter(t_box_graph, goal, use_thing_rule=True):
    from fuxi.LP.BackwardFixpointProcedure import BackwardFixpointProcedure
    from fuxi.Rete.Magic import setup_ddl_and_adorn_program
    from fuxi.Horn.PositiveConditions import build_uniterm_from_tuple
    from fuxi.Rete.TopDown import prepare_sip_collection
    from fuxi.DLP import lloyd_topor_transformation, make_rule
    from fuxi.Rete.SidewaysInformationPassing import get_op

    owl_thing_appears = False
    if use_thing_rule and OWL.Thing in t_box_graph.all_nodes():
        owl_thing_appears = True
    completion_rules = horn_from_n3(StringIO(RULES))
    if owl_thing_appears:
        completion_rules.formulae.extend(horn_from_n3(StringIO(CONDITIONAL_THING_RULE)))
    reduced_completion_rules = set()
    for rule in completion_rules:
        for clause in lloyd_topor_transformation(rule.formula):
            rule = make_rule(clause, {})
            # log.debug(rule)
            # PrettyPrintRule(rule)
            reduced_completion_rules.add(rule)

    network = setup_rule_store(make_network=True)[-1]
    setup_ddl_and_adorn_program(t_box_graph, reduced_completion_rules, [goal], derived_preds=derived_predicates,
                                ignore_unbound_d_preds=True, hybrid_preds_to_replace=hybridPredicates)

    lit = build_uniterm_from_tuple(goal)
    op = get_op(lit)
    lit.set_operator(URIRef(op + "_derived"))
    goal = lit.to_rdf_tuple()

    sip_collection = prepare_sip_collection(reduced_completion_rules)
    t_box_graph.templateMap = {}
    bfp = BackwardFixpointProcedure(t_box_graph, network, derived_predicates, goal, sip_collection,
                                    hybrid_predicates=hybridPredicates, debug=True)
    bfp.create_top_down_rete_network(True)
    log.debug(reduced_completion_rules)
    rt = bfp.answers(debug=True)
    log.debug(rt)
    log.debug(bfp.meta_interp_network)
    bfp.meta_interp_network.report_conflict_set(True, sys.stderr)
    for query in bfp.edb_queries:
        log.debug("Dispatched query against dataset: ", query.as_sparql())
    log.debug(list(bfp.goal_solutions))


def normalize_subsumption(owl_graph):
    operands = [
        (clsLHS, clsRHS)
        for clsLHS, p, clsRHS in owl_graph.triples((None, OWL_NS.equivalentClass, None))
    ]
    for clsLHS, clsRHS in operands:
        if isinstance(clsLHS, URIRef) and isinstance(clsRHS, URIRef):
            owl_graph.add((clsLHS, RDFS.subClassOf, clsRHS))
            owl_graph.add((clsRHS, RDFS.subClassOf, clsLHS))
            owl_graph.remove((clsLHS, OWL_NS.equivalentClass, clsRHS))
        elif isinstance(clsLHS, URIRef) and isinstance(clsRHS, BNode):
            owl_graph.add((clsLHS, RDFS.subClassOf, clsRHS))
            owl_graph.remove((clsLHS, OWL_NS.equivalentClass, clsRHS))
        elif isinstance(clsLHS, BNode) and isinstance(clsRHS, URIRef):
            owl_graph.add((clsRHS, RDFS.subClassOf, clsLHS))
            owl_graph.remove((clsLHS, OWL_NS.equivalentClass, clsRHS))


if __name__ == "__main__":
    goal = (EX_NS.KneeJoint, RDFS.subClassOf, Variable("Class"))
    ontGraph = create_test_ont_graph()
    # ontGraph.add((EX_NS.KneeJoint,
    #               RDFS.subClassOf,
    #               EX_NS.KneeJoint))
    normalize_subsumption(ontGraph)
    for c in all_classes(ontGraph):
        log.debug(c.__repr__(True))
    setup_meta_interpreter(ontGraph, goal)
