from rdflib import Graph

from FuXi.Rete.RuleStore import SetupRuleStore

# fix for bug in reset method which didn't initialise
# network.inferredFacts properly if the provided graph
# was empty
# http://code.google.com/p/fuxi/issues/detail?id=17
##


def test_reset_initializes_inferred_facts():
    rule_store, rule_graph, network = SetupRuleStore(makeNetwork=True)
    new_inferred_facts = Graph()
    network.reset(new_inferred_facts)
    assert new_inferred_facts is network.inferredFacts
