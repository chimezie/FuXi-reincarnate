from io import StringIO
from glob import glob
import os
import time
import pytest
from pprint import pprint, pformat
from rdflib import BNode, Namespace, RDF, RDFS, URIRef, plugin, Literal
from rdflib.graph import Graph
from rdflib.store import Store
from fuxi.DLP import non_DHL_OWL_Semantics
from fuxi.DLP.ConditionalAxioms import AdditionalRules
from fuxi.Horn.HornRules import HornFromN3
from fuxi.Horn.PositiveConditions import BuildUnitermFromTuple
from fuxi.Rete.Magic import AdornLiteral, MagicSetTransformation
from fuxi.Syntax.InfixOWL import nsBinds, AllClasses, Individual, Variable
from fuxi.Rete.ReteVocabulary import RETE_NS
from fuxi.Rete.RuleStore import SetupRuleStore
from fuxi.Rete.Util import generateTokenSet
from fuxi.SPARQL.BackwardChainingStore import (
    BFP_METHOD,
    TOP_DOWN_METHOD,
    TopDownSPARQLEntailingStore,
)
from fuxi.SPARQL import EDBQuery

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

queryNsMapping = {
    "test": "http://metacognition.info/FuXi/test#",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "foaf": "http://xmlns.com/foaf/0.1/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "rss": "http://purl.org/rss/1.0/",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
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

Features2Skip = [
    URIRef("http://www.w3.org/2002/07/owl#sameClassAs"),
]

NonNaiveSkip = [
    "OWL/oneOf/Manifest002.rdf",  # see Issue 25
    "OWL/unionOf/Manifest002.rdf",  # support for disjunctive horn logic
]

MagicTest2Skip = [
    # requires second order predicate derivation
    "OWL/oneOf/Manifest002.rdf",
    # requires second order predicate derivation
    "OWL/oneOf/Manifest003.rdf",
    # requires second order predicate derivation
    "OWL/disjointWith/Manifest001.rdf",
]


BFPTests2SKip = [
    # Haven't reconciled *all* 2nd order predicate queries
    "OWL/FunctionalProperty/Manifest002.rdf",
    # "         "        "    "
    "OWL/InverseFunctionalProperty/Manifest002.rdf",
    # 'OWL/oneOf/Manifest002.rdf',                    #  "         "        "    "
    "OWL/oneOf/Manifest003.rdf",  # "         "        "    "
]

TopDownTests2Skip = [
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

Tests2Skip = [
    # owl:sameIndividualAs deprecated
    "OWL/InverseFunctionalProperty/Manifest001.rdf",
    # owl:sameIndividualAs deprecated
    "OWL/FunctionalProperty/Manifest001.rdf",
    "OWL/Nothing/Manifest002.rdf",  # owl:sameClassAs deprecated
]

patterns2Skip = ["OWL/cardinality", "OWL/samePropertyAs"]


@pytest.fixture(scope="session")
def test_options(request):
    """Session-scoped fixture to access test configuration options."""

    class Options:
        def __init__(self):
            self.profile = request.config.getoption("profile")
            self.singleTest = request.config.getoption("singleTest")
            self.debug = request.config.getoption("verbose") > 0
            self.groundQuery = request.config.getoption("groundQuery")
            self.strategy = request.config.getoption("strategy")

    return Options()


@pytest.fixture(scope="session")
def reasoning_strategy(test_options):
    """Get the reasoning strategy from test options."""
    return test_options.strategy


@pytest.fixture(scope="session")
def ground_query(test_options):
    """Get the ground query setting from test options."""
    return test_options.groundQuery


@pytest.fixture(scope="session")
def debug_mode(test_options):
    """Get the debug mode from test options."""
    return test_options.debug


@pytest.fixture(scope="session")
def single_test(test_options):
    """Get the single test filter from test options."""
    return test_options.singleTest


def tripleToTriplePattern(graph, triple):
    return "%s %s %s" % tuple([renderTerm(graph, term) for term in triple])


def renderTerm(graph, term):
    if term == RDF.type:
        return " a "
    else:
        try:
            return isinstance(term, BNode) and term.n3() or graph.qname(term)
        except:
            return term.n3()


@pytest.fixture(scope="function")
def network_fixture():
    """Function-scoped pytest fixture to set up a fresh network for each test."""
    rule_store, rule_graph, network = SetupRuleStore(makeNetwork=True)
    network.nsMap = nsBinds
    return network


def calculateEntailments(network, factGraph):
    start = time.time()
    network.feedFactsToAdd(generateTokenSet(factGraph))
    sTime = time.time() - start
    if sTime > 1:
        sTimeStr = "%s seconds" % sTime
    else:
        sTime = sTime * 1000
        sTimeStr = "%s milli seconds" % sTime
    print("Time to calculate closure on working memory: %s" % sTimeStr)
    print(network)

    tNodeOrder = [
        tNode for tNode in network.terminalNodes if network.instantiations.get(tNode, 0)
    ]
    tNodeOrder.sort(key=lambda x: network.instantiations[x], reverse=True)
    for termNode in tNodeOrder:
        print(termNode)
        print("\t", termNode.rules)
        print("\t\t%s instantiations" % network.instantiations[termNode])
        # for c in AllClasses(factGraph):
        #     print(CastClass(c,factGraph))
    print("==============")
    network.inferredFacts.namespace_manager = factGraph.namespace_manager
    return sTimeStr


def _owl_test_id(params):
    if not isinstance(params, tuple):
        return str(params)
    manifest, premise_file, _conclusion_file, _feature, _description, test_uri = params
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
    test_cases = []
    here = os.getcwd()
    original_dir = here

    # Change to test directory if needed
    if not here.endswith("/test") and not here.endswith("entailment"):
        test_dir = here + "/test"
        if os.path.exists(test_dir):
            os.chdir(test_dir)
        else:
            # Try to find test directory
            return test_cases

    try:
        for manifest in glob("OWL/*/Manifest*.rdf"):
            # Skip explicitly excluded manifests
            if manifest in Tests2Skip:
                continue

            # Skip based on patterns
            skip = False
            for pattern2Skip in patterns2Skip:
                if manifest.find(pattern2Skip) > -1:
                    skip = True
                    break
            if skip:
                continue

            # Parse manifest
            try:
                manifestGraph = Graph()
                manifestGraph.parse(open(manifest), format="xml")
                rt = manifestGraph.query(MANIFEST_QUERY, initNs=nsMap, DEBUG=False)

                for test_uri, status, premise, conclusion, feature, description in rt:
                    # Only process APPROVED tests
                    if status != Literal("APPROVED"):
                        continue

                    # Skip features that are explicitly excluded
                    if feature in Features2Skip:
                        continue

                    # Extract file names
                    premise = manifestGraph.namespace_manager.compute_qname(premise)[-1]
                    conclusion = manifestGraph.namespace_manager.compute_qname(
                        conclusion
                    )[-1]

                    premiseFile = "/".join(manifest.split("/")[:2] + [premise])
                    conclusionFile = "/".join(manifest.split("/")[:2] + [conclusion])

                    # Check that files exist
                    if not os.path.exists(".".join([premiseFile, "rdf"])):
                        continue
                    if not os.path.exists(".".join([conclusionFile, "rdf"])):
                        continue

                    # Add test case
                    test_params = (
                        manifest,
                        premiseFile,
                        conclusionFile,
                        str(feature),
                        str(description),
                        str(test_uri),
                    )
                    test_cases.append(
                        pytest.param(*test_params, id=_owl_test_id(test_params))
                    )
            except Exception as e:
                print(f"Error parsing manifest {manifest}: {e}")
                continue
    finally:
        # Restore original directory
        os.chdir(original_dir)

    return test_cases


def MagicOWLProof(network, goals, rules, factGraph, conclusionFile):
    progLen = len(rules)
    magicRuleNo = 0
    dPreds = []
    for rule in AdditionalRules(factGraph):
        rules.append(rule)
    if not GROUND_QUERY and REASONING_STRATEGY != "gms":
        goalDict = dict(
            [
                ((Variable("SUBJECT"), goalP, goalO), goalS)
                for goalS, goalP, goalO in goals
            ]
        )
        goals = list(goalDict.keys())
    assert goals

    if REASONING_STRATEGY == "gms":
        for rule in MagicSetTransformation(factGraph, rules, goals, dPreds):
            magicRuleNo += 1
            network.buildNetworkFromClause(rule)
            network.rules.add(rule)
            if DEBUG:
                print("\t%s" % rule)
        print(
            "rate of reduction in the size of the program: %s "
            % (100 - (float(magicRuleNo) / float(progLen)) * 100)
        )

    if REASONING_STRATEGY in ["bfp", "sld"]:  # and not GROUND_QUERY:
        reasoningAlg = TOP_DOWN_METHOD if REASONING_STRATEGY == "sld" else BFP_METHOD
        topDownStore = TopDownSPARQLEntailingStore(
            factGraph.store,
            factGraph,
            idb=rules,
            DEBUG=DEBUG,
            nsBindings=nsMap,
            decisionProcedure=reasoningAlg,
            identifyHybridPredicates=REASONING_STRATEGY == "bfp",
        )
        targetGraph = Graph(topDownStore)
        for pref, nsUri in list(nsMap.items()):
            targetGraph.bind(pref, nsUri)
        start = time.time()

        for goal in goals:
            queryLiteral = EDBQuery(
                [BuildUnitermFromTuple(goal)],
                factGraph,
                None if GROUND_QUERY else [goal[0]],
            )
            query = queryLiteral.asSPARQL()
            print("Goal to solve ", query)
            rt = targetGraph.query(query, initNs=nsMap)
            if GROUND_QUERY:
                assert bool(rt), "Failed top-down problem"
            else:
                if not any(row[0] == goalDict[goal] for row in rt) or DEBUG:
                    for network, _goal in topDownStore.queryNetworks:
                        print(network, _goal)
                        network.reportConflictSet(True)
                    for query in topDownStore.edbQueries:
                        print(query.asSPARQL())
                assert any(row[0] == goalDict[goal] for row in rt), (
                    "Failed top-down problem"
                )
        sTime = time.time() - start
        if sTime > 1:
            sTimeStr = "%s seconds" % sTime
        else:
            sTime = sTime * 1000
            sTimeStr = "%s milli seconds" % sTime
        return sTimeStr
    elif REASONING_STRATEGY == "gms":
        for goal in goals:
            adornedGoalSeed = AdornLiteral(goal).makeMagicPred()
            goal = adornedGoalSeed.toRDFTuple()
            if DEBUG:
                print("Magic seed fact %s" % adornedGoalSeed)
            factGraph.add(goal)
        timing = calculateEntailments(network, factGraph)
        for goal in goals:
            # assert goal in network.inferredFacts or goal in factGraph, "Failed GMS query"
            if goal not in network.inferredFacts and goal not in factGraph:
                print("missing triple %s" % (pformat(goal)))
                pprint(list(factGraph.adornedProgram))
                # from fuxi.Rete.Util import renderNetwork
                # dot=renderNetwork(network,network.nsMap).write_jpeg('test-fail.jpeg')
                network.reportConflictSet(True)
                raise  # Exception ("Failed test: "+feature)
            else:
                print("=== Passed! ===")
        return timing


@pytest.mark.parametrize(
    "manifest,premise_file,conclusion_file,feature,description,test_uri",
    collect_owl_test_cases(),
)
def test_owl(
    network_fixture,
    reasoning_strategy,
    ground_query,
    debug_mode,
    single_test,
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
    # Set global variables for compatibility with existing code
    global REASONING_STRATEGY, GROUND_QUERY, DEBUG
    REASONING_STRATEGY = reasoning_strategy
    GROUND_QUERY = ground_query
    DEBUG = debug_mode

    network = network_fixture

    # Apply single test filter
    if single_test and premise_file != single_test:
        pytest.skip(f"Skipping {premise_file} (--singleTest filter active)")

    # Apply strategy-specific skips
    if (
        (reasoning_strategy is not None and manifest in NonNaiveSkip)
        or (reasoning_strategy == "sld" and manifest in TopDownTests2Skip)
        or (reasoning_strategy == "bfp" and manifest in BFPTests2SKip)
        or (reasoning_strategy == "gms" and manifest in MagicTest2Skip)
    ):
        pytest.skip(f"Incompatible with reasoning strategy: {reasoning_strategy}")

    if feature in TopDownTests2Skip:
        pytest.skip(f"Feature {feature} requires skipping for top-down tests")

    # Change to test directory
    here = os.getcwd()
    if not here.endswith("/test") and not here.endswith("entailment"):
        test_dir = here + "/test"
        if os.path.exists(test_dir):
            os.chdir(test_dir)

    try:
        # Verify files exist
        premise_rdf = ".".join([premise_file, "rdf"])
        conclusion_rdf = ".".join([conclusion_file, "rdf"])

        assert os.path.exists(premise_rdf), f"Premise file not found: {premise_rdf}"
        assert os.path.exists(conclusion_rdf), (
            f"Conclusion file not found: {conclusion_rdf}"
        )

        print(f"\n{'=' * 60}")
        print(f"Test: {premise_file}")
        print(f"Feature: {feature}")
        print(f"Description: {description}")
        print(f"{'=' * 60}")
        print(f"<{conclusion_rdf}> :- <{premise_rdf}>")

        # Parse premise graph
        factGraph = Graph()
        factGraph.parse(open(premise_rdf), format="xml")
        nsMap.update(dict([(k, v) for k, v in factGraph.namespaces()]))

        if DEBUG:
            print("\n## Source Graph ##")
            print(factGraph.serialize(format="n3"))

        Individual.factoryGraph = factGraph

        if DEBUG:
            for c in AllClasses(factGraph):
                if not isinstance(c.identifier, BNode):
                    print(c.__repr__(True))

        # Build program
        program = list(HornFromN3(StringIO(non_DHL_OWL_Semantics)))
        program.extend(
            network.setupDescriptionLogicProgramming(
                factGraph, addPDSemantics=False, constructNetwork=False
            )
        )

        if DEBUG:
            print("\n## Original Program ##")
            print(pformat(program))

        # Run test based on reasoning strategy
        if reasoning_strategy is None:
            # Naive forward chaining
            sTimeStr = calculateEntailments(network, factGraph)

            # Verify expected facts
            expectedFacts = Graph()
            for triple in expectedFacts.parse(conclusion_rdf, format="xml"):
                if triple not in network.inferredFacts and triple not in factGraph:
                    print(f"\nMissing triple: {pformat(triple)}")
                    print(f"Manifest: {manifest}")
                    print(f"Feature: {feature}")
                    print(f"Description: {description}")
                    if DEBUG:
                        print("\n## Inferred Facts ##")
                        print(pformat(list(network.inferredFacts)))
                    pytest.fail(f"Failed test: {feature} - Missing expected triple")

            print(f"\n=== PASSED === (Time: {sTimeStr})")
        else:
            # Top-down or magic set reasoning
            goals = []
            conclusionGraph = Graph()
            for triple in conclusionGraph.parse(conclusion_rdf, format="xml"):
                if triple not in factGraph:
                    goals.append(triple)

            timing = MagicOWLProof(network, goals, program, factGraph, conclusion_file)
            print(f"\n=== PASSED === (Time: {timing})")

    finally:
        # Restore original directory
        os.chdir(here)
