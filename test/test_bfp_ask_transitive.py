from typing import Tuple, Dict, Union
from pathlib import Path

from fuxi.SPARQL.utilities import extract_triples_from_query

from rdflib import Graph, URIRef
from fuxi.DLP.DLNormalization import NormalFormReduction
from rdflib.plugins.sparql import prepareQuery
from rdflib.plugins.sparql.sparql import Prologue
from rdflib.plugins.sparql.parser import parseQuery as ParseSPARQL
from rdflib.namespace import NamespaceManager
from rdflib.plugins.sparql.parserutils import CompValue
from fuxi.Rete.Proof import PML, GMP_NS
from fuxi.Syntax.InfixOWL import OWL_NS
from rdflib import RDF
from rdflib.plugins.sparql.processor import SPARQLResult
from fuxi.Horn import safetyNameMap
from fuxi.Horn.HornRules import Ruleset
from fuxi.Rete.RuleStore import SetupRuleStore
from fuxi.SPARQL.BackwardChainingStore import TopDownSPARQLEntailingStore
from pyparsing.results import ParseResults

QUERY_STRING = "ASK { test:Ghent test:path test:Amsterdam }"

def _normalize_sparql_parse(parsed_query: Union[Tuple, ParseResults], ns_binds: Dict[str, str]):
    if isinstance(parsed_query, tuple) and len(parsed_query) == 2:
        raise NotImplementedError(f"Not sure how to handle this yet: {parsed_query}")
        prologue, query = parsed_query
    elif isinstance(parsed_query, ParseResults):
        prologue, query = parsed_query
    else:
        raise NotImplementedError(f"Not sure how to handle this yet: {parsed_query}")
        prologue = getattr(parsed_query, "prologue", None)
        query = getattr(parsed_query, "query", parsed_query)
    if not prologue:
        prologue = Prologue()
    for prefix, ns_inst in list(ns_binds.items()):
        prologue.namespace_manager.bind(prefix, ns_inst)
    return prologue, query


def test_bfp_ask_transitive_property_returns_true():
    facts_path = (
        Path(__file__).resolve().parent.parent / "n3" / "w3c" / "premises001.rdf"
    )
    fact_graph = Graph().parse(facts_path.as_posix(), format="xml")

    _rule_store, _rule_graph, network = SetupRuleStore(makeNetwork=True)

    nsBinds = {"iw": "http://inferenceweb.stanford.edu/2004/07/iw.owl#"}
    for pref, nsUri in {'test': 'http://www.w3.org/2002/03owlt/TransitiveProperty/premises001#'}.items():
        nsBinds[pref] = nsUri

    namespace_manager = NamespaceManager(Graph())

    for prefix, uri in list(nsBinds.items()):
        namespace_manager.bind(prefix, uri, override=False)
    closureDeltaGraph = Graph()
    closureDeltaGraph.namespace_manager = namespace_manager
    network.inferredFacts = closureDeltaGraph
    fact_graph.namespace_manager = namespace_manager

    network.nsMap["pml"] = PML
    network.nsMap["gmp"] = GMP_NS
    network.nsMap["owl"] = OWL_NS
    nsBinds.update(network.nsMap)
    network.nsMap = nsBinds

    rule_set = Ruleset()
    rule_set.nsMapping = nsBinds

    #Setup DLP
    NormalFormReduction(fact_graph)
    dlp = network.setupDescriptionLogicProgramming(
        fact_graph,
        addPDSemantics=True,
        constructNetwork=False,
        ignoreNegativeStratus=False,
        safety=safetyNameMap["none"],
    )
    rule_set.formulae.extend(dlp)

    goals = []
    parsed_query = ParseSPARQL(QUERY_STRING)
    prologue, query = _normalize_sparql_parse(parsed_query, nsBinds)
    extract_triples_from_query(query, nsBinds, goals)

    defaultDerivedPreds = set()
    defaultDerivedPreds.update(
        set([p == RDF.type and o or p for s, p, o in goals])
    )

    base_ns = "http://www.w3.org/2002/03owlt/TransitiveProperty/premises001#"
    path_predicate = URIRef(f"{base_ns}path")

    print("Rules:")
    for rule in rule_set.formulae:
        print(rule)

    top_down_store = TopDownSPARQLEntailingStore(
        fact_graph.store,
        fact_graph,
        idb=rule_set,
        DEBUG=True,
        derivedPredicates=defaultDerivedPreds,
        nsBindings=network.nsMap,
        identifyHybridPredicates=True
    )
    target_graph = Graph(top_down_store)
    for pref, nsUri in list(network.nsMap.items()):
        target_graph.bind(pref, nsUri)

    result = target_graph.query(QUERY_STRING, initNs=network.nsMap)

    print("RETE-UL conflict info")
    for _network, _goal in top_down_store.queryNetworks:
        print(network, _goal)
        _network.reportConflictSet(True)
    for query in top_down_store.edbQueries:
        print(query.asSPARQL())

    assert result.askAnswer is True

if __name__ == "__main__":
    test_bfp_ask_transitive_property_returns_true()