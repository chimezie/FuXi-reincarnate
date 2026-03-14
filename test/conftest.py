import pytest
from rdflib import Graph, Namespace

from fuxi.Horn.HornRules import HornFromN3
from fuxi.Rete.RuleStore import SetupRuleStore


@pytest.fixture()
def ns_test():
    return Namespace("http://example.org/test#")


@pytest.fixture()
def graph_empty(ns_test):
    graph = Graph()
    graph.bind("test", ns_test)
    return graph


@pytest.fixture()
def simple_rules_n3():
    return """\
@prefix test: <http://example.org/test#> .

{ ?s test:parent ?o } => { ?o test:child ?s } .
"""


@pytest.fixture()
def simple_facts_n3():
    return """\
@prefix test: <http://example.org/test#> .

test:alice test:parent test:bob .
"""


@pytest.fixture()
def horn_ruleset(simple_rules_n3):
    return HornFromN3(simple_rules_n3)


@pytest.fixture()
def rete_network():
    rule_store, rule_graph, network = SetupRuleStore(makeNetwork=True)
    return network
