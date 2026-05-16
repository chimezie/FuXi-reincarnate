from io import StringIO

import pytest
from rdflib.graph import Graph

from fuxi.Horn.HornRules import horn_from_n3
from fuxi.Rete.RuleStore import setup_rule_store
from fuxi.SPARQL.BackwardChainingStore import TopDownSPARQLEntailingStore
from fuxi.Syntax.InfixOWL import OWL_NS
from rdflib import Namespace, Variable

EX = Namespace("http://example.org/")

FACTS = """\
@prefix ex: <http://example.org/> .
@prefix owl: <http://www.w3.org/2002/07/owl#>.

ex:foo ex:x "xxxx";
       owl:sameAs ex:bar .
ex:bar ex:y "yyyy";
       owl:sameAs ex:baz .
"""

RULES = """\
@prefix owl: <http://www.w3.org/2002/07/owl#>.

{ ?x owl:sameAs ?y } => { ?y owl:sameAs ?x } .
# { ?x owl:sameAs ?y . ?x ?p ?o } => { ?y ?p ?o } .
{ ?X owl:sameAs ?A . ?A owl:sameAs ?B } => { ?X owl:sameAs ?B } .
"""

GOALS = [(EX.foo, EX.y, Variable("o")), (EX.foo, OWL_NS.sameAs, Variable("o"))]

QUERIES = {
    "SELECT ?o { ex:baz owl:sameAs ?o }": set([EX.bar, EX.foo]),
    "SELECT ?o { ex:foo owl:sameAs ?o }": set([EX.bar, EX.baz]),
}


def _make_network_and_graph():
    rule_store, rule_graph, network = setup_rule_store(make_network=True)
    graph = Graph().parse(StringIO(FACTS), format="n3")
    return rule_store, rule_graph, network, graph


@pytest.mark.skip(
    reason="Known failure: transitivity of owl:sameAs not working correctly"
)
def test_transitivity():
    """Test transitivity of owl:sameAs property."""
    _rule_store, _rule_graph, _network, graph = _make_network_and_graph()
    ns_bindings = {"owl": OWL_NS, "ex": EX}
    top_down_store = TopDownSPARQLEntailingStore(graph.store,
                                                 graph,
                                                 idb=horn_from_n3(StringIO(RULES)),
                                                 debug=True)
    target_graph = Graph(top_down_store)
    for query, solns in QUERIES.items():
        result = set(target_graph.query(query, initNs=ns_bindings))
        assert not solns.difference(result)
