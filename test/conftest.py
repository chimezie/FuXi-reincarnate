import re
from dataclasses import dataclass

import pytest
from rdflib.term import Identifier

from fuxi.Horn.HornRules import horn_from_n3
from fuxi.Rete.Proof import generate_proof
from fuxi.Rete.RuleStore import setup_rule_store
from fuxi.types import Triple
from rdflib import Graph, Namespace


@dataclass(frozen=True)
class OwlTestOptions:
    profile: bool
    manifest: str
    single_test: str
    ground_query: bool
    strategy: str | None
    debug: bool
    capture_proofs: bool


def _owl_test_uri_id(test_uri):
    if not test_uri:
        return "owl_test"
    if "http://www.w3.org/2002/03owlt/" in test_uri:
        return test_uri.split("http://www.w3.org/2002/03owlt/")[-1]
    return test_uri


def _safe_test_id(test_id):
    safe_id = re.sub(r"[^A-Za-z0-9._-]+", "_", test_id)
    safe_id = safe_id.strip("_")
    return safe_id or "owl_test"


def _network_for_goal(query_networks, goal):
    for network, tp in query_networks:
        if tp == goal:
            return network
    if isinstance(goal, tuple) and len(goal) == 3:
        for network, tp in query_networks:
            if isinstance(tp, tuple) and len(tp) == 3:
                if tp[1] == goal[1] and tp[2] == goal[2]:
                    return network
    return None


def _proof_goal_for_query(goal: Triple, goal_dict: dict[Triple, Identifier] | None):
    if goal_dict and goal in goal_dict:
        return goal_dict[goal], goal[1], goal[2]
    return goal


def _render_proof_diagrams(
    network, goal, proof_id, goal_index, top_down_store, extra_nsmap=None
):
    builder, proof = generate_proof(network, goal, top_down_store)
    ns_map = {**network.ns_map, **(extra_nsmap or {})}
    if not ns_map:
        ns_map = top_down_store.ns_bindings or (extra_nsmap or {})
    dot = builder.render_proof(proof, ns_map=ns_map, format="svg")
    suffix = f"-goal-{goal_index}" if goal_index is not None else ""
    base = f"/tmp/{proof_id}{suffix}"
    dot.render(filename=base, cleanup=True, format="svg")
    dot.render(filename=base, cleanup=True, format="png")


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
    return horn_from_n3(simple_rules_n3)


@pytest.fixture()
def rete_network():
    rule_store, rule_graph, network = setup_rule_store(make_network=True)
    return network
