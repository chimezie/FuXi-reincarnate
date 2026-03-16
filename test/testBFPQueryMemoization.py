# -*- coding: utf-8 -*-
from io import StringIO

import pytest
from rdflib import RDF, Namespace, URIRef, Variable
from rdflib.graph import Graph

from fuxi.DLP.ConditionalAxioms import AdditionalRules
from fuxi.Horn.PositiveConditions import BuildUnitermFromTuple
from fuxi.Rete.RuleStore import SetupRuleStore
from fuxi.SPARQL import EDBQuery
from fuxi.SPARQL.BackwardChainingStore import BFP_METHOD, TopDownSPARQLEntailingStore
from fuxi.Syntax.InfixOWL import OWL_NS


EX_ONT = """\
@prefix first: <http://www.w3.org/2002/03owlt/intersectionOf/premises001#>.
@prefix owl: <http://www.w3.org/2002/07/owl#>.
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>.

 first:C owl:intersectionOf ( first:Employee first:Student ).

 first:John a first:B.

 first:B owl:intersectionOf ( first:Student first:Employee ).

"""

EX = Namespace("http://www.w3.org/2002/03owlt/intersectionOf/premises001#")

NS_MAP = {
    "owl": OWL_NS,
    "first": URIRef("http://www.w3.org/2002/03owlt/intersectionOf/premises001#"),
}


class QueryCountingGraph(Graph):
    def __init__(self, store="default", identifier=None, namespace_manager=None):
        self.queries_dispatched = []
        super().__init__(store, identifier, namespace_manager)

    def query(self, *args, **kwargs):
        if args:
            self.queries_dispatched.append(args[0])
        else:
            self.queries_dispatched.append(kwargs.get("query_object"))
        kwargs.setdefault("use_store_provided", False)
        kwargs.setdefault("DEBUG", True)
        return super().query(*args, **kwargs)


@pytest.mark.xfail(reason="Known failure: duplicate query dispatch in BFP memoization")
def test_query_memoization():
    """Ensure EDB queries are memoized (issue from historical Google tracker)."""
    owl_graph = QueryCountingGraph()
    owl_graph.parse(StringIO(EX_ONT), format="n3")
    _rule_store, _rule_graph, network = SetupRuleStore(makeNetwork=True)
    program = network.setupDescriptionLogicProgramming(
        owl_graph, addPDSemantics=False, constructNetwork=False
    )
    program.update(AdditionalRules(owl_graph))

    top_down_store = TopDownSPARQLEntailingStore(
        owl_graph.store,
        owl_graph,
        idb=program,
        DEBUG=False,
        nsBindings=NS_MAP,
        decisionProcedure=BFP_METHOD,
        identifyHybridPredicates=True,
    )
    target_graph = Graph(top_down_store)
    for pref, ns_uri in NS_MAP.items():
        target_graph.bind(pref, ns_uri)

    goal = (Variable("SUBJECT"), RDF.type, EX.C)
    query_literal = EDBQuery(
        [BuildUnitermFromTuple(goal)], owl_graph, [Variable("SUBJECT")]
    )
    query = query_literal.asSPARQL()
    target_graph.query(query, initNs=NS_MAP)

    assert len(owl_graph.queries_dispatched) == 4, "Duplicate query"


"""
======================================================================
FAIL: testQueryMemoization (test.testBFPQueryMemoization.QueryMemoizationTest)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/gjh/.virtualenvs/rdfdev/src/fuxi/test/testBFPQueryMemoization.py", line 100, in testQueryMemoization
    len(self.owlGraph.queriesDispatched), 4, "Duplicate query")
AssertionError: Duplicate query
-------------------- >> begin captured stdout << ---------------------
createSPARQLPConstraint reducedFilter=<ConditionalExpressionList: [(KIND = owl:InverseFunctionalProperty), (KIND = owl:FunctionalProperty)]>, type=<class 'rdflib.plugins.sparql.ParsedConditionalAndExpressionList'>
createSPARQLPConst: reducedFilterType = <class 'rdflib.plugins.sparql.ParsedConditionalAndExpressionList'>, constraint = False
mapToOperator:
    expr=(KIND = owl:InverseFunctionalProperty),
    type=<class 'rdflib.plugins.sparql.EqualityOperator'>,
    constr=False.

mapToOperator:
    expr=<AdditiveExpressionList: [<MultiplicativeExpressionList: [?KIND]>]>,
    type=<class 'rdflib.plugins.sparql.ParsedAdditiveExpressionList'>,
    constr=False.

mapToOperator:
    expr=<AdditiveExpressionList: [<MultiplicativeExpressionList: [u'owl:InverseFunctionalProperty']>]>,
    type=<class 'rdflib.plugins.sparql.ParsedAdditiveExpressionList'>,
    constr=False.

mapToOperator:
    expr=(KIND = owl:FunctionalProperty),
    type=<class 'rdflib.plugins.sparql.EqualityOperator'>,
    constr=False.

mapToOperator:
    expr=<AdditiveExpressionList: [<MultiplicativeExpressionList: [?KIND]>]>,
    type=<class 'rdflib.plugins.sparql.ParsedAdditiveExpressionList'>,
    constr=False.

mapToOperator:
    expr=<AdditiveExpressionList: [<MultiplicativeExpressionList: [u'owl:FunctionalProperty']>]>,
    type=<class 'rdflib.plugins.sparql.ParsedAdditiveExpressionList'>,
    constr=False.

a. sparql-p operator(s): lambda i: operators.eq("?KIND",'http://www.w3.org/2002/07/owl#InverseFunctionalProperty')(i) or operators.eq("?KIND",'http://www.w3.org/2002/07/owl#FunctionalProperty')(i)
createSPARQLPConstraint reducedFilter=<ConditionalExpressionList: [(KIND = owl:InverseFunctionalProperty), (KIND = owl:FunctionalProperty)]>, type=<class 'rdflib.plugins.sparql.ParsedConditionalAndExpressionList'>
createSPARQLPConst: reducedFilterType = <class 'rdflib.plugins.sparql.ParsedConditionalAndExpressionList'>, constraint = False
mapToOperator:
    expr=(KIND = owl:InverseFunctionalProperty),
    type=<class 'rdflib.plugins.sparql.EqualityOperator'>,
    constr=False.

mapToOperator:
    expr=<AdditiveExpressionList: [<MultiplicativeExpressionList: [?KIND]>]>,
    type=<class 'rdflib.plugins.sparql.ParsedAdditiveExpressionList'>,
    constr=False.

mapToOperator:
    expr=<AdditiveExpressionList: [<MultiplicativeExpressionList: [u'owl:InverseFunctionalProperty']>]>,
    type=<class 'rdflib.plugins.sparql.ParsedAdditiveExpressionList'>,
    constr=False.

mapToOperator:
    expr=(KIND = owl:FunctionalProperty),
    type=<class 'rdflib.plugins.sparql.EqualityOperator'>,
    constr=False.

mapToOperator:
    expr=<AdditiveExpressionList: [<MultiplicativeExpressionList: [?KIND]>]>,
    type=<class 'rdflib.plugins.sparql.ParsedAdditiveExpressionList'>,
    constr=False.

mapToOperator:
    expr=<AdditiveExpressionList: [<MultiplicativeExpressionList: [u'owl:FunctionalProperty']>]>,
    type=<class 'rdflib.plugins.sparql.ParsedAdditiveExpressionList'>,
    constr=False.

a. sparql-p operator(s): lambda i: operators.eq("?KIND",'http://www.w3.org/2002/07/owl#InverseFunctionalProperty')(i) or operators.eq("?KIND",'http://www.w3.org/2002/07/owl#FunctionalProperty')(i)
Queries dispatched against EDB

ASK {
  [] a ?KIND
  FILTER(
      ?KIND = owl:InverseFunctionalProperty ||
      ?KIND = owl:FunctionalProperty
  )
}

ASK {
  [] a ?KIND
  FILTER(
      ?KIND = owl:InverseFunctionalProperty ||
      ?KIND = owl:FunctionalProperty
  )
}

--------------------- >> end captured stdout << ----------------------
-------------------- >> begin captured logging << --------------------
rdflib.plugins.sparql.algebra: DEBUG: ## Full SPARQL Algebra expression ##
rdflib.plugins.sparql.algebra: DEBUG: Filter(.. a filter ..,BGP(_:Neb4be2109f58434fb9b776fe285f4a4d,rdf:type,?KIND))
rdflib.plugins.sparql.algebra: DEBUG: ###################################
rdflib.plugins.sparql.algebra: DEBUG: ## Full SPARQL Algebra expression ##
rdflib.plugins.sparql.algebra: DEBUG: Filter(.. a filter ..,BGP(_:Nc1882a8aed2941c6abad2c1bc9a51bdb,rdf:type,?KIND))
rdflib.plugins.sparql.algebra: DEBUG: ###################################
--------------------- >> end captured logging << ---------------------

"""
