import pytest
from rdflib import Graph, Namespace
from fuxi.Horn.HornRules import HornFromN3
from fuxi.Rete.RuleStore import SetupRuleStore
from dataclasses import dataclass


@dataclass(frozen=True)
class OwlTestOptions:
    profile: bool
    manifest: str
    single_test: str
    ground_query: bool
    strategy: str | None
    debug: bool
    capture_proofs: bool

def pytest_addoption(parser):
    """Add custom command-line options for OWL tests."""
    group = parser.getgroup("owl tests", "Options for OWL tests")
    group.addoption(
        "--profile",
        action="store_true",
        default=False,
        help="Whether or not to run a profile",
    )
    group.addoption(
        "--owl2-test-manifest",
        default="https://www.w3.org/2009/11/owl-test/approved/all.rdf",
        help="The location of the manifest to use for OWL2 testing",
    )
    group.addoption(
        "--single-test",
        default="",
        help="The identifier for the test to run",
    )
    group.addoption(
        "--ground-query",
        action="store_true",
        default=False,
        help="For top-down strategies, whether to solve ground triple patterns or not",
    )
    group.addoption(
        "--strategy",
        default="bfp",
        choices=["naive", "bfp"],
        help="Which reasoning strategy to use in solving the OWL test cases",
    )
    group.addoption(
        "--owl-debug",
        action="store_true",
        default=False,
        help="Enable verbose OWL entailment debugging",
    )
    group.addoption(
        "--capture-proofs",
        action="store_true",
        default=False,
        help="Capture PML for tests",
    )

@pytest.fixture(scope="session")
def owl_test_options(pytestconfig):
    """Session-scoped access to custom OWL test options."""
    return OwlTestOptions(
        profile=pytestconfig.getoption("profile"),
        manifest=pytestconfig.getoption("owl2_test_manifest"),
        single_test=pytestconfig.getoption("single_test"),
        ground_query=pytestconfig.getoption("ground_query"),
        strategy=pytestconfig.getoption("strategy"),
        debug=pytestconfig.getoption("owl_debug"),
        capture_proofs=pytestconfig.getoption("capture_proofs"),
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
