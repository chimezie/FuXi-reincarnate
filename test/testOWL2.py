import io
from io import StringIO

import pytest
from rdflib.graph import Graph
from rdflib.namespace import NamespaceManager

from fuxi.Horn.HornRules import horn_from_n3
from fuxi.Horn.PositiveConditions import build_uniterm_from_tuple
from fuxi.LP.BackwardFixpointProcedure import BFP_NS, BFP_RULE
from fuxi.SPARQL import EDBQuery
from fuxi.SPARQL.utilities import owl_entailment_regime_graph
from fuxi.Syntax.InfixOWL import nsBinds
from rdflib import RDF, RDFS, XSD, BNode, Namespace, Variable

from .conftest import (
    OwlTestOptions,
    _network_for_goal,
    _render_proof_diagrams,
    _safe_test_id,
)

pytestmark = pytest.mark.integration


OWL_NS = Namespace("http://www.w3.org/2002/07/owl#")
OWL_TEST = Namespace("http://www.w3.org/2007/OWL/testOntology#")

ns_map = {
    "rdfs": RDFS,
    "rdf": RDF,
    "owl": OWL_NS,
    "test": OWL_TEST,
    "xsd": XSD,
    "eval": BFP_NS,
    "rule": BFP_RULE,
}

MANIFEST_QUERY = """\
SELECT ?test ?id ?profile ?comment ?description ?premiseOntology ?conclusionOntology
WHERE {
  ?test
    a                               test:PositiveEntailmentTest;
    test:semantics                  test:RDF-BASED;
    test:status                     test:Approved;
    test:identifier                 ?id;
    test:profile                    ?profile;
    rdfs:comment                    ?comment;
    test:description                ?description;
    test:rdfXmlPremiseOntology      ?premiseOntology;
    test:rdfXmlConclusionOntology   ?conclusionOntology
}
"""

thing_rule = """\
@prefix owl: <http://www.w3.org/2002/07/owl#>.

{ ?thing a ?class } => { ?thing a owl:Thing }.
"""


IMPORTS_QUERY = "SELECT ?ontology { [] a owl:Ontology; owl:imports ?ontology }"


def collect_owl_test_cases(manifest_url: str):
    manifest_graph = Graph()
    manifest_graph.parse(manifest_url, format="xml")
    rt = manifest_graph.query(MANIFEST_QUERY, initNs=ns_map)
    namespace_manager = NamespaceManager(Graph())
    for prefix, uri in nsBinds.items():
        namespace_manager.bind(prefix, uri, override=False)
    for test, test_id, profile, comment, description, premise_ont, conclusion_ont in rt:
        yield pytest.param(
            test_id,
            test,
            profile,
            comment,
            description,
            premise_ont,
            conclusion_ont,
            namespace_manager,
            id=str(test_id),
        )


def pytest_generate_tests(metafunc):
    if "test_id" in metafunc.fixturenames:
        manifest_url = metafunc.config.getoption("--owl2-test-manifest")
        metafunc.parametrize(
            "test_id, test, profile, comment, description, premise_ont, "
            "conclusion_ont, namespace_manager",
            collect_owl_test_cases(manifest_url),
        )


def test_owl_2(
    test_id,
    test,
    profile,
    comment,
    description,
    premise_ont,
    conclusion_ont,
    namespace_manager,
    owl_test_options: OwlTestOptions,
):
    debug = owl_test_options.debug
    if owl_test_options.single_test and str(test_id) != owl_test_options.single_test:
        pytest.skip(f"Skipping {test_id} (--single-test filter active)")
    premise_graph = Graph().parse(io.StringIO(premise_ont), format="xml")
    for (imported_ontology_url,) in premise_graph.query(IMPORTS_QUERY, initNs=ns_map):
        print("Importing", imported_ontology_url)
        premise_graph.parse(imported_ontology_url, format="xml")
    conclusion_graph = Graph().parse(io.StringIO(conclusion_ont), format="xml")
    goals = []
    for triple in conclusion_graph:
        s, p, o = triple
        if isinstance(s, BNode):
            if len(list(conclusion_graph.triples((s, None, None)))) > 1:
                # If the subject is a BNode, and part of a connected BGP then
                # this is a valid goal and we use the BNode label as a
                # variable to match consistently across BGPs
                triple = tuple(
                    [
                        Variable(t) if isinstance(t, BNode) else t
                        for idx, t in enumerate(triple)
                    ]
                )
                goals.append(triple)
        elif isinstance(o, BNode):
            if len(list(conclusion_graph.triples((o, None, None)))) > 1:
                # If the object is a BNode, and part of a connected BGP then
                # this is a valid goal and we use the BNode label as a
                # variable to match consistently across BGPs
                triple = tuple(
                    [
                        Variable(t) if isinstance(t, BNode) else t
                        for idx, t in enumerate(triple)
                    ]
                )
                goals.append(triple)
        elif triple not in premise_graph:
            goals.append(triple)
    for _graph in [premise_graph, conclusion_graph]:
        for prefix, uri in _graph.namespace_manager.namespaces():
            ns_map[prefix] = uri
    entailing_graph, closure_delta_graph = owl_entailment_regime_graph(
        premise_graph,
        ns_map,
        identify_hybrid_predicates=True,
        derived_predicates=None,
        hybrid_predicates=None,
        goals=goals,
        namespace_manager=namespace_manager,
        extra_rulesets=horn_from_n3(StringIO(thing_rule)),
        verbose=debug,
    )
    proof_id = _safe_test_id(str(test_id)) if owl_test_options.capture_proofs else None
    top_down_store = entailing_graph.store

    for goal_index, goal in enumerate(goals, start=1):
        query_literal = EDBQuery(
            [build_uniterm_from_tuple(goal, ns_map)], premise_graph, None
        )
        query = query_literal.as_sparql()
        rt = entailing_graph.query(query, initNs=ns_map)
        if debug or not rt.askAnswer:
            print(test_id, "\n", comment, "\n", description, "\n", profile)
            print("## Premise\n", premise_graph.serialize(format="turtle"))
            print("## Conclusion\n", conclusion_graph.serialize(format="turtle"))
            print("## Closure graph\n", closure_delta_graph.serialize(format="turtle"))
            print("## Goal\n", query_literal, query)
        assert rt.askAnswer, "Failed top-down problem"

        if proof_id and owl_test_options.capture_proofs:
            network_for_goal = _network_for_goal(top_down_store.query_networks, goal)
            if network_for_goal is None and top_down_store.query_networks:
                network_for_goal = top_down_store.query_networks[-1][0]
            if network_for_goal is not None:
                _render_proof_diagrams(
                    network_for_goal,
                    goal,
                    proof_id,
                    goal_index,
                    top_down_store,
                    extra_nsmap=ns_map,
                )
