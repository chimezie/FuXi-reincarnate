from io import StringIO
from glob import glob
import os
import re
import time
import pytest
from pprint import pformat

from fuxi.Rete.Network import ReteNetwork
from rdflib import BNode, Namespace, RDF, RDFS, URIRef, Literal
from rdflib.graph import Graph
from fuxi.DLP import non_DHL_OWL_Semantics
from fuxi.DLP.ConditionalAxioms import AdditionalRules
from fuxi.Horn.HornRules import HornFromN3
from fuxi.Horn.PositiveConditions import BuildUnitermFromTuple
from fuxi.Syntax.InfixOWL import all_classes, Individual, Variable
from fuxi.Rete.ReteVocabulary import RETE_NS
from fuxi.Rete.Util import generateTokenSet
from fuxi.Rete.Proof import GenerateProof
from fuxi.Rete.SidewaysInformationPassing import GetOp
from fuxi.SPARQL.BackwardChainingStore import BFP_METHOD, TopDownSPARQLEntailingStore
from fuxi.SPARQL import EDBQuery
from rdflib.term import Identifier
from .conftest import OwlTestOptions

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
RDF_TEST = Namespace("http://www.w3.org/2000/10/rdf-tests/rdfcore/testSchema#")
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

nsMap = {
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
    return "%s %s %s" % tuple([render_term(graph, term) for term in triple])


def render_term(graph, term):
    if term == RDF.type:
        return " a "
    else:
        try:
            return isinstance(term, BNode) and term.n3() or graph.qname(term)
        except:
            return term.n3()

def calculate_entailments(network, factGraph):
    start = time.time()
    network.feedFactsToAdd(generateTokenSet(factGraph))
    s_time = time.time() - start
    if s_time > 1:
        s_time_str = "%s seconds" % s_time
    else:
        s_time = s_time * 1000
        s_time_str = "%s milli seconds" % s_time
    print("Time to calculate closure on working memory: %s" % s_time_str)
    print(network)

    terminal_node_order = [
        t_node for t_node in network.terminalNodes if network.instantiations.get(t_node, 0)
    ]
    terminal_node_order.sort(key=lambda x: network.instantiations[x], reverse=True)
    for term_node in terminal_node_order:
        print(term_node)
        print("\t", term_node.rules)
        print("\t\t%s instantiations" % network.instantiations[term_node])
    print("==============")
    network.inferredFacts.namespace_manager = factGraph.namespace_manager
    return s_time_str

def _owl_test_id(params):
    if not isinstance(params, tuple):
        return str(params)
    manifest, premise_file, _conclusion_file, _feature, _description, test_uri = params
    short_id = test_uri
    if "http://www.w3.org/2002/03owlt/" in test_uri:
        short_id = test_uri.split("http://www.w3.org/2002/03owlt/")[-1]
    manifest_token = manifest.replace("/", "_")
    return "::".join([manifest, manifest_token, short_id, premise_file])


def _owl_test_uri_id(test_uri):
    """Return the most specific portion of the OWL test URI."""
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


def _proof_goal_for_query(goal: tuple[Variable, Identifier, Identifier],
                          goal_dict: dict[tuple[Variable, Identifier, Identifier], Identifier] | None):
    if goal_dict and goal in goal_dict:
        return (goal_dict[goal], goal[1], goal[2])
    return goal


def _render_proof_diagrams(network, goal, proof_id, goal_index, top_down_store):
    builder, proof = GenerateProof(network, goal, top_down_store)
    dot = builder.renderProof(proof, nsMap=network.nsMap)
    suffix = f"-goal-{goal_index}" if goal_index is not None else ""
    base = f"/tmp/{proof_id}{suffix}"
    dot.render(filename=base, cleanup=True, format="svg")
    dot.render(filename=base, cleanup=True, format="png")

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
        for pattern2Skip in PATTERNS_TO_SKIP:
            if manifest_str.find(pattern2Skip) > -1:
                skip = True
                break
        if skip:
            continue

        # Parse manifest
        manifest_graph = Graph()
        manifest_graph.parse(open(manifest), format="xml")
        rt = manifest_graph.query(MANIFEST_QUERY, initNs=nsMap, DEBUG=False)

        for test_uri, status, premise, conclusion, feature, description in rt:
            # Only process APPROVED tests
            if status != Literal("APPROVED"):
                continue

            # Skip features that are explicitly excluded
            if feature in FEATURES_TO_SKIP:
                continue

            # Extract file names
            premise = manifest_graph.namespace_manager.compute_qname(premise)[-1]
            conclusion = manifest_graph.namespace_manager.compute_qname(
                conclusion
            )[-1]

            manifest_parent = manifest.parent
            premise_file = str((manifest_parent / premise).relative_to(test_dir))
            conclusion_file = str((manifest_parent / conclusion).relative_to(test_dir))

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


def magic_owl_proof(network, goals, rules, fact_graph, options, proof_id=None):
    goal_dict = None
    for rule in AdditionalRules(fact_graph):
        rules.append(rule)
    if not options.ground_query:
        goal_dict: dict[tuple[Variable, Identifier, Identifier], Identifier] = dict(
            [
                ((Variable("SUBJECT"),
                  goalP,
                  goalO),
                 goalS)
                for goalS, goalP, goalO in goals
            ]
        )
        goals: list[tuple[Variable, Identifier, Identifier]] = list(goal_dict.keys())
    assert goals

    if options.strategy == "bfp":
        reasoning_alg = BFP_METHOD
        top_down_store = TopDownSPARQLEntailingStore(
            fact_graph.store,
            fact_graph,
            idb=rules,
            DEBUG=options.debug,
            nsBindings=nsMap,
            decisionProcedure=reasoning_alg,
            identifyHybridPredicates=True,
        )
        target_graph = Graph(top_down_store)
        for pref, nsUri in list(nsMap.items()):
            target_graph.bind(pref, nsUri)
        start = time.time()

        for goal_index, goal in enumerate(goals, start=1):
            query_literal = EDBQuery(
                [BuildUnitermFromTuple(goal)],
                fact_graph,
                None if options.ground_query else [goal[0]],
            )
            query = query_literal.asSPARQL()
            print("Goal to solve ", query)
            rt = target_graph.query(query, initNs=nsMap)
            if options.ground_query:
                assert bool(rt), "Failed top-down problem"
            else:
                if not any(row[0] == goal_dict[goal] for row in rt) or options.debug:
                    for network, _goal in top_down_store.queryNetworks:
                        print(network, _goal)
                        network.reportConflictSet(True)
                    for query in top_down_store.edbQueries:
                        print(query)
                assert any(row[0] == goal_dict[goal] for row in rt), (
                    "Failed top-down problem"
                )
            if proof_id and options.capture_proofs:
                network_for_goal = _network_for_goal(top_down_store.queryNetworks, goal)
                if network_for_goal is None and top_down_store.queryNetworks:
                    network_for_goal = top_down_store.queryNetworks[-1][0]
                if network_for_goal is None:
                    network_for_goal = network
                proof_goal = _proof_goal_for_query(goal, goal_dict)

                if top_down_store.hybrid_predicates:
                    lit = BuildUnitermFromTuple(proof_goal)
                    op = GetOp(lit)
                    if op in top_down_store.hybrid_predicates:
                        lit.setOperator(URIRef(op + "_derived"))
                        proof_goal = lit.toRDFTuple()
                _render_proof_diagrams(
                    network_for_goal,
                    proof_goal,
                    proof_id,
                    goal_index,
                    top_down_store
                )
        s_time = time.perf_counter() - start
        if s_time > 1:
            s_time_str = "%s seconds" % s_time
        else:
            s_time = s_time * 1000
            s_time_str = "%s milli seconds" % s_time
        return s_time_str
    else:
        raise NotImplementedError(f"Unsupported reasoning strategy: {options.strategy}")

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

    Each approved test from the OWL manifest files runs as a separate pytest test.
    """
    # Apply single test filter
    if owl_test_options.single_test and premise_file != owl_test_options.single_test:
        pytest.skip(f"Skipping {premise_file} (--singleTest filter active)")

    # Apply strategy-specific skips
    if manifest in NON_NAIVE_SKIP or (owl_test_options.strategy == "bfp" and manifest in BFP_TESTS_TO_SKIP):
        pytest.skip(f"Incompatible with reasoning strategy: {owl_test_options.strategy}")

    if feature in TOP_DOWN_TESTS_TO_SKIP:
        pytest.skip(f"Feature {feature} requires skipping for top-down tests")

    from pathlib import Path
    base_dir = Path(os.path.relpath(__file__, os.getcwd())).parent

    # Verify files exist
    premise_rdf = base_dir / Path(premise_file + ".rdf")
    conclusion_rdf = base_dir / Path(conclusion_file + ".rdf")
    assert premise_rdf.exists(), f"Premise file not found: {premise_rdf}"
    assert conclusion_rdf.exists(), f"Conclusion file not found: {conclusion_rdf}"

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
    nsMap.update(dict([(k, v) for k, v in fact_graph.namespaces()]))

    if owl_test_options.debug:
        print("\n## Source Graph ##")
        print(fact_graph.serialize(format="n3"))

    Individual.factoryGraph = fact_graph

    if owl_test_options.debug:
        for c in all_classes(fact_graph):
            if not isinstance(c.identifier, BNode):
                print(c.__repr__(True))

    # Build program
    program = list(HornFromN3(StringIO(non_DHL_OWL_Semantics)))
    program.extend(
        rete_network.setupDescriptionLogicProgramming(
            fact_graph, addPDSemantics=False, constructNetwork=False
        )
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
                if triple not in rete_network.inferredFacts and triple not in fact_graph:
                    print(f"\nMissing triple: {pformat(triple)}")
                    print(f"Manifest: {manifest}")
                    print(f"Feature: {feature}")
                    print(f"Description: {description}")
                    if owl_test_options.debug:
                        print("\n## Inferred Facts ##")
                        print(pformat(list(rete_network.inferredFacts)))
                    pytest.fail(f"Failed test: {feature} - Missing expected triple")

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

