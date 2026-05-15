"""
FuXi harness for W3C SPARQL 1.1 entailment evaluation tests.
"""

from __future__ import annotations

from collections import Counter
from io import BytesIO, StringIO
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import urlopen

import pytest
from rdflib.collection import Collection
from rdflib.namespace import RDF, RDFS
from rdflib.plugins.sparql.results.xmlresults import XMLResult
from rdflib.term import BNode, Identifier, URIRef

from fuxi.Horn.HornRules import horn_from_n3
from fuxi.SPARQL.utilities import owl_entailment_regime_graph
from rdflib import Graph, Namespace
from test.conftest import OwlTestOptions

pytestmark = pytest.mark.integration

MANIFEST_URL = (
    "https://www.w3.org/2009/sparql/docs/tests/data-sparql11/entailment/manifest.ttl"
)

MF = Namespace("http://www.w3.org/2001/sw/DataAccess/tests/test-manifest#")
QT = Namespace("http://www.w3.org/2001/sw/DataAccess/tests/test-query#")
SD = Namespace("http://www.w3.org/ns/sparql-service-description#")
DAWGT = Namespace("http://www.w3.org/2001/sw/DataAccess/tests/test-dawg#")
ENT = Namespace("http://www.w3.org/ns/entailment/")

SUPPORTED_ENTAILMENT = (ENT.RDFS, ENT.RDF)

SKIP: dict[str, str] = {
    "rdf01": "Quantification over predicates",
    "rdfs01": "Quantification over predicates",
    "rdf02": "Reification",
    "rdf03": "Parse of query fails",
    "rdf10": "Malformed test",
    "rdfs05": "Quantification over predicates (unary)",
    "rdfs11": "Reflexivity of rdfs:subClassOf (?x -> rdfs:Container)",
    "sparqldl-06": "Cycle pattern requires OWL entailment, not available under RDFS",
}

W3C_DIR = Path(__file__).parent / "W3C"
RDFS_RULES_PATH = W3C_DIR / "rdf-rdfs.n3"
RDFS_AXIOMS_PATH = W3C_DIR / "rdfs-axiomatic-triples.n3"

RDF_RULES_N3 = """\
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>.

{ ?s ?p ?o } => { ?p a rdf:Property }.
"""

MANIFEST_QUERY = """\
SELECT ?test ?name ?approval ?queryFile ?rdfDoc ?regime ?result
WHERE {
  ?test
    a mf:QueryEvaluationTest;
    mf:name ?name;
    dawgt:approval ?approval;
    mf:action [
      qt:query ?queryFile;
      qt:data ?rdfDoc;
      sd:entailmentRegime ?regime
    ];
    mf:result ?result .
}
ORDER BY ?test
"""


def _fetch_text(url: str) -> str:
    with urlopen(url) as response:
        return response.read().decode("utf-8")


def _fetch_bytes(url: str) -> bytes:
    with urlopen(url) as response:
        return response.read()


def _short_test_id(test_uri: Identifier) -> str:
    uri = str(test_uri)
    if "#" in uri:
        return uri.rsplit("#", 1)[-1]
    return uri.rstrip("/").rsplit("/", 1)[-1]


def _resolve_manifest_ref(base_url: str, ref: Identifier) -> str:
    return urljoin(base_url, str(ref))


def _collect_regimes(
    manifest_graph: Graph, regime_node: Identifier
) -> list[Identifier]:
    if isinstance(regime_node, BNode):
        return list(Collection(manifest_graph, regime_node))
    return [regime_node]


def _select_supported_regime(regimes: list[Identifier]) -> URIRef | None:
    for candidate in SUPPORTED_ENTAILMENT:
        if candidate in regimes:
            return candidate
    return None


def _normalize_term(term: Identifier, bnode_map: dict[BNode, str]) -> str:
    if isinstance(term, BNode):
        if term not in bnode_map:
            bnode_map[term] = f"_:b{len(bnode_map)}"
        return bnode_map[term]
    return term.n3()


def _normalize_binding_row(binding: dict) -> tuple[tuple[str, str], ...]:
    bnode_map: dict[BNode, str] = {}
    normalized: list[tuple[str, str]] = []
    for key, value in binding.items():
        var_name = str(key)
        if var_name.startswith("?"):
            var_name = var_name[1:]
        normalized.append((var_name, _normalize_term(value, bnode_map)))
    normalized.sort()
    return tuple(normalized)


def _binding_counter(bindings: list[dict]) -> Counter:
    return Counter(_normalize_binding_row(row) for row in bindings)


def _extra_rules_for_regime(regime: URIRef):
    if regime == ENT.RDFS:
        return list(horn_from_n3(str(RDFS_RULES_PATH)))
    if regime == ENT.RDF:
        return list(horn_from_n3(StringIO(RDF_RULES_N3)))
    return None


def collect_sparql_entailment_test_cases(manifest_url: str = MANIFEST_URL):
    manifest_graph = Graph()
    manifest_graph.parse(manifest_url, format="turtle")
    test_cases = []

    rows = manifest_graph.query(
        MANIFEST_QUERY,
        initNs={"mf": MF, "qt": QT, "sd": SD, "dawgt": DAWGT},
    )
    for test, name, approval, query_file, rdf_doc, regime, result in rows:
        if approval != DAWGT.Approved:
            continue

        short_test_name = _short_test_id(test)
        regimes = _collect_regimes(manifest_graph, regime)
        selected_regime = _select_supported_regime(regimes)
        if selected_regime is None:
            continue

        query_url = _resolve_manifest_ref(manifest_url, query_file)
        data_url = _resolve_manifest_ref(manifest_url, rdf_doc)
        result_url = _resolve_manifest_ref(manifest_url, result)

        marks = []
        if short_test_name in SKIP:
            marks.append(pytest.mark.skip(reason=SKIP[short_test_name]))

        test_cases.append(
            pytest.param(
                str(test),
                short_test_name,
                str(name),
                query_url,
                data_url,
                selected_regime,
                result_url,
                id=short_test_name,
                marks=marks,
            )
        )
    return test_cases


@pytest.mark.parametrize(
    "test_uri,short_test_name,name,query_url,data_url,regime,result_url",
    collect_sparql_entailment_test_cases(),
)
def test_sparql_entailment(
    owl_test_options: OwlTestOptions,
    test_uri: str,
    short_test_name: str,
    name: str,
    query_url: str,
    data_url: str,
    regime: URIRef,
    result_url: str,
):
    if owl_test_options.single_test:
        single = owl_test_options.single_test
        if single not in {short_test_name, test_uri}:
            pytest.skip(f"Skipping {short_test_name} (--single-test filter active)")

    fact_graph = Graph()
    fact_graph.parse(data_url)
    if regime == ENT.RDFS:
        fact_graph.parse(RDFS_AXIOMS_PATH, format="n3")

    query = _fetch_text(query_url)
    expected_result = XMLResult(BytesIO(_fetch_bytes(result_url)))

    ns_map: dict[str, Identifier] = {
        "rdf": RDF,
        "rdfs": RDFS,
    }
    ns_map.update(dict(fact_graph.namespace_manager.namespaces()))

    extra_rules = _extra_rules_for_regime(regime)

    entailing_graph, _closure_delta_graph = owl_entailment_regime_graph(
        fact_graph,
        ns_map,
        identify_hybrid_predicates=True,
        extra_rulesets=extra_rules,
        verbose=owl_test_options.debug,
        add_non_dhl_owl_rules=False,
    )

    result = entailing_graph.query(query, initNs=ns_map)

    result_type = getattr(result, "type", None)
    ask_answer = getattr(result, "askAnswer", None)
    if ask_answer is None:
        ask_answer = getattr(result, "ask_answer", None)

    if result_type == "ASK":
        assert bool(ask_answer) is True, (
            f"{short_test_name} ({name}) regime={regime}\n"
            f"Expected ASK=True but got False\n"
            f"Query: {query_url}\n"
            f"Data: {data_url}\n"
            f"Result: {result_url}"
        )
        return

    expected_counter = _binding_counter(expected_result.bindings)
    actual_counter = _binding_counter(result.bindings)
    missing = expected_counter - actual_counter
    if missing:
        pytest.fail(
            f"{short_test_name} ({name}) regime={regime}\n"
            f"Missing bindings: {list(missing.elements())}\n"
            f"Query: {query_url}\n"
            f"Data: {data_url}\n"
            f"Result: {result_url}"
        )
