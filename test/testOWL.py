import os
import time
from io import StringIO
from pprint import pformat

import pytest
from rdflib.graph import Graph
from rdflib.term import Identifier

from fuxi.DLP import NON_DHL_OWL_SEMANTICS
from fuxi.DLP.ConditionalAxioms import additional_rules
from fuxi.Horn.HornRules import horn_from_n3
from fuxi.Horn.PositiveConditions import build_uniterm_from_tuple
from fuxi.Rete.Network import ReteNetwork
from fuxi.Rete.ReteVocabulary import RETE_NS
from fuxi.Rete.SidewaysInformationPassing import get_op
from fuxi.Rete.Util import generate_token_set
from fuxi.SPARQL import EDBQuery
from fuxi.SPARQL.BackwardChainingStore import TopDownSPARQLEntailingStore
from fuxi.Syntax.InfixOWL import Individual, Variable, all_classes
from fuxi.types import Triple
from rdflib import RDF, RDFS, BNode, Literal, Namespace, URIRef

from .conftest import (
    OwlTestOptions,
    _network_for_goal,
    _owl_test_uri_id,
    _proof_goal_for_query,
    _render_proof_diagrams,
    _safe_test_id,
)

pytestmark = pytest.mark.integration

RDFLIB_CONNECTION = ""
RDFLIB_STORE = "IOMemory"

CWM_NS = Namespace("http://cwmTest/")
DC_NS = Namespace("http://purl.org/dc/elements/1.1/")
STRING_NS = Namespace("http://www.w3.org/2000/10/swap/string#")
MATH_NS = Namespace("http://www.w3.org/2000/10/swap/math#")
FOAF_NS = Namespace("http://xmlns.com/foaf/0.1/")
OWL_NS = Namespace("http://www.w3.org/2002/07/owl#")
TEST_NS = Namespace("http://metacognition.info/FuXi/DL-SHIOF-test.n3#")
LOG = Namespace("http://www.w3.org/2000/10/swap/log#")
RDF_TEST = Namespace(
    "http://www.w3.org/2000/10/rdf-tests/rdfcore/testSchema#")
OWL_TEST = Namespace("http://www.w3.org/2002/03owlt/testOntology#")
LIST = Namespace("http://www.w3.org/2000/10/swap/list#")

query_ns_mapping = {
    "test": "http://metacognition.info/FuXi/test#",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "foaf": "http://xmlns.com/foaf/0.1/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "rss": "http://purl.org/rss/1.0/",
    "owl": str(OWL_NS),
    "rdfs": str(RDFS),
}

ns_map = {
    "rdfs": RDFS,
    "rdf": RDF,
    "rete": RETE_NS,
    "owl": OWL_NS,
    "": TEST_NS,
    "otest": OWL_TEST,
    "rtest": RDF_TEST,
    "foaf": URIRef("http://xmlns.com/foaf/0.1/"),
    "math": URIRef("http://www.w3.org/2000/10/swap/math#"),
}

MANIFEST_QUERY = """\
SELECT ?test ?status ?premise ?conclusion ?feature ?descr
WHERE {
  ?test
    a otest:PositiveEntailmentTest;
    otest:feature ?feature;
    rtest:description ?descr;
    rtest:status ?status;
    rtest:premiseDocument ?premise;
    rtest:conclusionDocument ?conclusion
}
"""
# PARSED_MANIFEST_QUERY = parse(MANIFEST_QUERY)

FEATURES_TO_SKIP = [
    URIRef("http://www.w3.org/2002/07/owl#sameClassAs"),
]

NON_NAIVE_SKIP = [
    "OWL/oneOf/Manifest002.rdf",  # see Issue 25
    "OWL/unionOf/Manifest002.rdf",  # support for disjunctive horn logic
]

MAGIC_TESTS_TO_SKIP = [
    # requires second order predicate derivation
    "OWL/oneOf/Manifest002.rdf",
    # requires second order predicate derivation
    "OWL/oneOf/Manifest003.rdf",
    # requires second order predicate derivation
    "OWL/disjointWith/Manifest001.rdf",
]


BFP_TESTS_TO_SKIP = [
    # Haven't reconciled *all* 2nd order predicate queries
    "OWL/FunctionalProperty/Manifest002.rdf",
    # "         "        "    "
    "OWL/InverseFunctionalProperty/Manifest002.rdf",
    # 'OWL/oneOf/Manifest002.rdf',                    #  "         "        "    "
    "OWL/oneOf/Manifest003.rdf",  # "         "        "    "
]

TOP_DOWN_TESTS_TO_SKIP = [
    # requires second order predicate derivation
    "OWL/FunctionalProperty/Manifest002.rdf",
    "OWL/FunctionalProperty/Manifest004.rdf",
    "OWL/InverseFunctionalProperty/Manifest002.rdf",
    "OWL/InverseFunctionalProperty/Manifest004.rdf",
    # Requires quantification over predicate symbol (2nd order)
    "OWL/oneOf/Manifest003.rdf",
    # 'OWL/AllDifferent/Manifest001.rdf', #Not sure why
    "OWL/distinctMembers/Manifest001.rdf",  # Not sure why
]

TESTS_TO_SKIP = [
    # owl:sameIndividualAs deprecated
    "OWL/InverseFunctionalProperty/Manifest001.rdf",
    # owl:sameIndividualAs deprecated
    "OWL/FunctionalProperty/Manifest001.rdf",
    "OWL/Nothing/Manifest002.rdf",  # owl:sameClassAs deprecated
]

PATTERNS_TO_SKIP = ["OWL/cardinality", "OWL/samePropertyAs"]

def triple_to_triple_pattern(graph, triple):
    return " ".join([render_term(graph, term) for term in triple])


def render_term(graph, term):
    if term == RDF.type:
        return " a "
    else:
        try:
            return isinstance(term, BNode) and term.n3() or graph.qname(term)
        except Exception:
            return term.n3()

def calculate_entailments(network, fact_graph):
    start = time.time()
    network.feed_facts_to_add(generate_token_set(fact_graph))
    s_time = time.time() - start
    if s_time > 1:
        s_time_str = f"{s_time} seconds"
    else:
        s_time = s_time * 1000
        s_time_str = f"{s_time} milli seconds"
    print(f"Time to calculate closure on working memory: {s_time_str}")
    print(network)

    terminal_node_order = [
        t_node for t_node in network.terminal_nodes
        if network.instantiations.get(t_node, 0)
    ]
    terminal_node_order.sort(key=lambda x: network.instantiations[x],
                             reverse=True)
    for term_node in terminal_node_order:
        print(term_node)
        print("\t", term_node.rules)
        print(f"\t\t{network.instantiations[term_node]} instantiations")
    print("==============")
    network.inferred_facts.namespace_manager = fact_graph.namespace_manager
    return s_time_str

def _owl_test_id(params):
    if not isinstance(params, tuple):
        return str(params)
    (manifest,
     premise_file,
     _conclusion_file,
     _feature,
     _description,
     test_uri) = params
    short_id = test_uri
    if "http://www.w3.org/2002/03owlt/" in test_uri:
        short_id = test_uri.split("http://www.w3.org/2002/03owlt/")[-1]
    manifest_token = manifest.replace("/", "_")
    return "::".join([manifest, manifest_token, short_id, premise_file])


def collect_owl_test_cases():
    """
    Collect all OWL test cases from manifest files.

    Returns a list of test case tuples:
    (manifest, premise_file, conclusion_file, feature, description)
    """
    from pathlib import Path

    test_dir = Path(__file__).parent
    test_cases = []

    for manifest in (test_dir / "OWL").glob("*//Manifest*.rdf"):
        manifest_str = str(manifest.relative_to(test_dir))

        # Skip explicitly excluded manifests
        if manifest_str in TESTS_TO_SKIP:
            continue

        # Skip based on patterns
        skip = False
        for pattern_to_skip in PATTERNS_TO_SKIP:
            if manifest_str.find(pattern_to_skip) > -1:
                skip = True
                break
        if skip:
            continue

        # Parse manifest
        manifest_graph = Graph()
        manifest_graph.parse(open(manifest), format="xml")
        rt = manifest_graph.query(MANIFEST_QUERY, initNs=ns_map, DEBUG=False)

        for test_uri, status, premise, conclusion, feature, description in rt:
            # Only process APPROVED tests
            if status != Literal("APPROVED"):
                continue

            # Skip features that are explicitly excluded
            if feature in FEATURES_TO_SKIP:
                continue

            # Extract file names
            premise = manifest_graph.namespace_manager.compute_qname(
                premise)[-1]
            conclusion = manifest_graph.namespace_manager.compute_qname(
                conclusion
            )[-1]

            manifest_parent = manifest.parent
            premise_file = str((manifest_parent / premise).relative_to(test_dir))
            conclusion_file = str((manifest_parent / conclusion).relative_to(
                test_dir))

            # Check that files exist
            if not (test_dir / f"{premise_file}.rdf").exists():
                continue
            if not (test_dir / f"{conclusion_file}.rdf").exists():
                continue

            # Add test case
            test_params = (
                manifest_str,
                premise_file,
                conclusion_file,
                str(feature),
                str(description),
                str(test_uri),
            )
            test_cases.append(
                pytest.param(*test_params, id=_owl_test_id(test_params))
            )
    return test_cases


def magic_owl_proof(
        network,
        goals,
        rules,
        fact_graph,
        options,
        proof_id=None):
    goal_dict = None
    for rule in additional_rules(fact_graph):
        rules.append(rule)
    if not options.ground_query:
        goal_dict: dict[Triple, Identifier] = dict(
            [
                ((Variable("SUBJECT"),
                  goalP,
                  goalO),
                 goalS)
                for goalS, goalP, goalO in goals
            ]
        )
        goals: list[Triple] = list(goal_dict.keys())
    assert goals

    if options.strategy == "bfp":
        top_down_store = TopDownSPARQLEntailingStore(
            fact_graph.store,
            fact_graph,
            idb=rules,
            debug=options.debug,
            ns_bindings=ns_map,
            identify_hybrid_predicates=True
        )
        target_graph = Graph(top_down_store)
        for pref, ns_uri in list(ns_map.items()):
            target_graph.bind(pref, ns_uri)
        start = time.time()

        for goal_index, goal in enumerate(goals, start=1):
            query_literal = EDBQuery(
                [build_uniterm_from_tuple(goal)],
                fact_graph,
                None if options.ground_query else [goal[0]]
            )
            query = query_literal.as_sparql()
            print("Goal to solve ", query)
            rt = target_graph.query(query, initNs=ns_map)
            if options.ground_query:
                assert bool(rt), "Failed top-down problem"
            else:
                if not any(row[0] == goal_dict[goal]
                           for row in rt) or options.debug:
                    for network, _goal in top_down_store.query_networks:
                        print(network, _goal)
                        network.report_conflict_set(True)
                    for query in top_down_store.edb_queries:
                        print(query)
                assert any(row[0] == goal_dict[goal] for row in rt), (
                    "Failed top-down problem"
                )
            if proof_id and options.capture_proofs:
                network_for_goal = _network_for_goal(
                    top_down_store.query_networks,
                    goal
                )
                if network_for_goal is None and top_down_store.query_networks:
                    network_for_goal = top_down_store.query_networks[-1][0]
                if network_for_goal is None:
                    network_for_goal = network
                proof_goal = _proof_goal_for_query(goal, goal_dict)

                if top_down_store.hybrid_predicates:
                    lit = build_uniterm_from_tuple(proof_goal)
                    op = get_op(lit)
                    if op in top_down_store.hybrid_predicates:
                        lit.set_operator(URIRef(op + "_derived"))
                        proof_goal = lit.to_rdf_tuple()
                _render_proof_diagrams(
                    network_for_goal,
                    proof_goal,
                    proof_id,
                    goal_index,
                    top_down_store
                )
        s_time = time.perf_counter() - start
        if s_time > 1:
            s_time_str = f"{s_time} seconds"
        else:
            s_time = s_time * 1000
            s_time_str = f"{s_time} milli seconds"
        return s_time_str
    else:
        raise NotImplementedError(
            f"Unsupported reasoning strategy: {options.strategy}")

@pytest.mark.parametrize(
    "manifest,premise_file,conclusion_file,feature,description,test_uri",
    collect_owl_test_cases(),
)
def test_owl(
    rete_network: ReteNetwork,
    owl_test_options: OwlTestOptions,
    manifest,
    premise_file,
    conclusion_file,
    feature,
    description,
    test_uri,
):
    """
    Individual OWL test case.

    Each approved test from the OWL manifest files runs as a separate pytest
    test.
    """
    # Apply single test filter
    if (owl_test_options.single_test and
        premise_file != owl_test_options.single_test):
        pytest.skip(f"Skipping {premise_file} (--singleTest filter active)")

    # Apply strategy-specific skips
    if manifest in NON_NAIVE_SKIP or (owl_test_options.strategy == "bfp" and
                                      manifest in BFP_TESTS_TO_SKIP):
        pytest.skip(
            f"Incompatible with reasoning strategy: "
            f"{owl_test_options.strategy}")

    if feature in TOP_DOWN_TESTS_TO_SKIP:
        pytest.skip(f"Feature {feature} requires skipping for top-down tests")

    from pathlib import Path
    base_dir = Path(os.path.relpath(__file__, os.getcwd())).parent

    # Verify files exist
    premise_rdf = base_dir / Path(premise_file + ".rdf")
    conclusion_rdf = base_dir / Path(conclusion_file + ".rdf")
    assert premise_rdf.exists(), f"Premise file not found: {premise_rdf}"
    assert conclusion_rdf.exists(), (f"Conclusion file not found: "
                                     f"{conclusion_rdf}")

    print(f"\n{'=' * 60}")
    print(f"Test: {premise_file}")
    print(f"Feature: {feature}")
    print(f"Description: {description}")
    print(f"{'=' * 60}")
    print(f"{conclusion_rdf} :- {premise_rdf}")

    # Parse premise graph
    fact_graph = Graph()
    with premise_rdf.open() as f:
        fact_graph.parse(f, format="xml")
    ns_map.update(dict([(k, v) for k, v in fact_graph.namespaces()]))

    if owl_test_options.debug:
        print("\n## Source Graph ##")
        print(fact_graph.serialize(format="n3"))

    Individual.factoryGraph = fact_graph

    if owl_test_options.debug:
        for c in all_classes(fact_graph):
            if not isinstance(c.identifier, BNode):
                print(c.__repr__(True))

    # Build program
    program = list(horn_from_n3(StringIO(NON_DHL_OWL_SEMANTICS)))
    program.extend(
        rete_network.setup_description_logic_programming(
            fact_graph,
            add_pd_semantics=False,
            construct_network=False)
    )

    if owl_test_options.debug:
        print("\n## Original Program ##")
        print(pformat(program))

    # Run test based on reasoning strategy
    if owl_test_options.strategy is None:
        # Naive forward chaining
        s_time_str = calculate_entailments(rete_network, fact_graph)

        # Verify expected facts
        expected_facts = Graph()
        with conclusion_rdf.open() as f:
            for triple in expected_facts.parse(f, format="xml"):
                if (triple not in rete_network.inferred_facts and
                    triple not in fact_graph):
                    print(f"\nMissing triple: {pformat(triple)}")
                    print(f"Manifest: {manifest}")
                    print(f"Feature: {feature}")
                    print(f"Description: {description}")
                    if owl_test_options.debug:
                        print("\n## Inferred Facts ##")
                        print(pformat(list(rete_network.inferred_facts)))
                    pytest.fail(f"Failed test: {feature} - "
                                f"Missing expected triple")

        print(f"\n=== PASSED === (Time: {s_time_str})")
    else:
        # Top-down or magic set reasoning
        goals = []
        conclusion_graph = Graph()
        with conclusion_rdf.open() as f:
            for triple in conclusion_graph.parse(f, format="xml"):
                if triple not in fact_graph:
                    goals.append(triple)

        test_id = _safe_test_id(_owl_test_uri_id(test_uri))
        timing = magic_owl_proof(
            rete_network,
            goals,
            program,
            fact_graph,
            owl_test_options,
            proof_id=test_id,
        )
        print(f"\n=== PASSED === (Time: {timing})")

