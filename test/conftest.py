import pytest
from rdflib import Graph, Namespace

from fuxi.Horn.HornRules import HornFromN3
from fuxi.Rete.RuleStore import SetupRuleStore


def pytest_addoption(parser):
    """Add custom command-line options for OWL tests."""
    parser.addoption(
        "--profile",
        action="store_true",
        default=False,
        help="Whether or not to run a profile",
    )
    parser.addoption(
        "--singleTest",
        default="",
        help="The identifier for the test to run",
    )
    parser.addoption(
        "--groundQuery",
        action="store_true",
        default=False,
        help="For top-down strategies, whether to solve ground triple patterns or not",
    )
    parser.addoption(
        "--strategy",
        default="bfp",
        choices=["gms", "sld", "bfp"],
        help="Which reasoning strategy to use in solving the OWL test cases",
    )


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
