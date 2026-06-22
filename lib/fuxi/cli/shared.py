from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from enum import StrEnum
import importlib.util
import logging
import sys
import time
from typing import TYPE_CHECKING

from rdflib.graph import Graph
from rdflib.namespace import NamespaceManager
from rdflib.plugins.sparql.parser import parseQuery
from rdflib.term import Identifier, Variable

from fuxi.DLP.DLNormalization import normal_form_reduction
from fuxi.Horn import safety_name_map
from fuxi.Horn.HornRules import Ruleset, horn_from_n3
from fuxi.Rete.RuleStore import setup_rule_store
from fuxi.Rete.Util import collapse_dictionary, generate_token_set
from fuxi.SPARQL.service import SPARQLServiceGraph
from fuxi.SPARQL.utilities import (
    extract_triples_from_query,
    owl_entailment_regime_graph,
)
from fuxi.Syntax.InfixOWL import (
    OWL_NS,
)
from rdflib import RDF, Namespace, URIRef

if TYPE_CHECKING:
    from fuxi.Rete.Network import ReteNetwork
    from fuxi.SPARQL.BackwardChainingStore import TopDownSPARQLEntailingStore

logger = logging.getLogger(__name__)

TEMPLATES = Namespace("http://code.google.com/p/fuxi/wiki/BuiltinSPARQLTemplates#")


class OutputFormat(StrEnum):
    XML = "xml"
    TRI_X = "TriX"
    N3 = "n3"
    NT = "nt"
    TTL = "ttl"
    PML = "pml"
    RIF = "rif"
    RIF_XML = "rif-xml"
    CONFLICT = "conflict"
    MAN_OWL = "man-owl"
    ADORNMENT = "adornment"
    PROOF_GRAPH_SVG = "proof-graph-svg"
    PROOF_GRAPH_PNG = "proof-graph-png"
    RETE_NETWORK_SVG = "rete-network-svg"
    RETE_NETWORK_PNG = "rete-network-png"
    SIP_COLLECTION_SVG = "sip-collection-svg"
    SIP_COLLECTION_PNG = "sip-collection-png"

    @classmethod
    def proof_graph_formats(cls) -> set[OutputFormat]:
        return {cls.PROOF_GRAPH_SVG, cls.PROOF_GRAPH_PNG, cls.PML}

    @classmethod
    def rete_network_formats(cls) -> set[OutputFormat]:
        return {cls.RETE_NETWORK_SVG, cls.RETE_NETWORK_PNG}

    @classmethod
    def sip_collection_formats(cls) -> set[OutputFormat]:
        return {cls.SIP_COLLECTION_SVG, cls.SIP_COLLECTION_PNG}

    @classmethod
    def rdf_formats(cls) -> set[OutputFormat]:
        return {cls.XML, cls.TRI_X, cls.N3, cls.NT, cls.TTL}

    @classmethod
    def choices(cls) -> list[str]:
        return [f.value for f in cls]


@dataclass
class BFPResult:
    top_down_store: TopDownSPARQLEntailingStore
    answers: list = field(default_factory=list)
    has_answers: bool = False
    elapsed: float = 0.0


def _format_timing(seconds: float) -> str:
    if seconds > 1:
        return f"{seconds} seconds"
    return f"{seconds * 1000} milli seconds"


def _load_builtin_module(path: str):
    spec = importlib.util.spec_from_file_location("builtins", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load builtin module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _resolve_qname(qname: str, namespace_manager: NamespaceManager) -> URIRef:
    pref, uri = qname.split(":")
    mapping = dict(namespace_manager.namespaces())
    return URIRef(mapping[pref] + uri)


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "facts",
        nargs="*",
        default=[],
        metavar="FACT_FILE",
        help="RDF files to load as initial facts",
    )
    parser.add_argument(
        "--input-format",
        default="xml",
        dest="input_format",
        metavar="FORMAT",
        choices=["xml", "trix", "n3", "nt", "rdfa"],
        help="Format of input RDF fact files (default: xml)",
    )
    parser.add_argument(
        "--ns",
        action="append",
        default=[],
        metavar="PREFIX=URI",
        help="Register a namespace binding (repeatable)",
    )
    parser.add_argument(
        "--rules",
        action="append",
        default=[],
        metavar="PATH_OR_URI",
        help="N3 documents to use as rulesets (repeatable)",
    )
    parser.add_argument(
        "-d",
        "--debug",
        action="store_true",
        default=False,
        help="Include debugging output",
    )
    parser.add_argument(
        "--rule-facts",
        action="store_true",
        default=False,
        help="Parse initial facts from rule graphs",
    )
    parser.add_argument(
        "--builtins",
        default=None,
        metavar="PATH",
        help="Python module with ADDITIONAL_FILTERS for builtin implementations",
    )
    parser.add_argument(
        "--safety",
        default="none",
        choices=["loose", "strict", "none"],
        help="RIF Core safety handling (default: none)",
    )
    parser.add_argument(
        "--imports",
        action="store_true",
        default=False,
        help="Follow owl:imports in the fact graph",
    )
    parser.add_argument(
        "--stdin",
        action="store_true",
        default=False,
        help="Parse STDIN as an RDF graph for initial facts",
    )
    parser.add_argument(
        "--closure",
        action="store_true",
        default=False,
        help="Serialize inferred triples along with original triples",
    )
    parser.add_argument(
        "--normal-form",
        action="store_true",
        default=False,
        help="Reduce DL axioms and LP rules to normal form",
    )
    parser.add_argument(
        "--negation",
        action="store_true",
        default=False,
        help="Extract negative rules",
    )
    parser.add_argument(
        "--filter",
        action="append",
        default=[],
        metavar="PATH_OR_URI",
        help="N3 documents to use as filters (repeatable)",
    )
    parser.add_argument(
        "--edb",
        action="append",
        default=[],
        metavar="QNAME",
        help="Designate a clashing predicate as base (repeatable)",
    )
    parser.add_argument(
        "--idb",
        action="append",
        default=[],
        metavar="QNAME",
        help="Designate a clashing predicate as derived (repeatable)",
    )
    parser.add_argument(
        "--hybrid-predicate",
        action="append",
        default=[],
        metavar="QNAME",
        help="Explicitly specify a hybrid predicate (repeatable)",
    )
    parser.add_argument(
        "--hybrid",
        action="store_true",
        default=False,
        help="Identify predicates that are both derived and base",
    )
    parser.add_argument(
        "--sparql-endpoint",
        action="store_true",
        default=False,
        help="Interpret the sole argument as a SPARQL endpoint URI",
    )


def add_owl_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--dlp",
        action="store_true",
        default=False,
        help="Use DLP to extract rules from OWL/RDF",
    )
    parser.add_argument(
        "--ontology",
        action="append",
        default=[],
        metavar="PATH_OR_URI",
        help="OWL RDF/XML graph for DLP rule extraction (repeatable)",
    )
    parser.add_argument(
        "--ontology-format",
        default="xml",
        dest="ontology_format",
        metavar="FORMAT",
        choices=["xml", "trix", "n3", "nt", "rdfa"],
        help="Format of --ontology graphs (default: xml)",
    )
    parser.add_argument(
        "--builtin-templates",
        default=None,
        metavar="PATH_OR_URI",
        help="N3 document for SPARQL FILTER template associations",
    )
    parser.add_argument(
        "--pd-semantics",
        action="store_true",
        default=False,
        help="Add pD semantics ruleset with --dlp",
    )


def add_man_owl_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--class",
        dest="classes",
        action="append",
        default=[],
        metavar="QNAME",
        help="Classes to target for --output=man-owl (repeatable)",
    )
    parser.add_argument(
        "--property",
        dest="properties",
        action="append",
        default=[],
        metavar="QNAME",
        help="Properties to serialize/extract (repeatable)",
    )
    parser.add_argument(
        "--normalize",
        action="store_true",
        default=False,
        help="Check if ontology is 'normalized' [Rector, A. 2003]",
    )


def build_fact_graph(
    options: argparse.Namespace,
) -> tuple[Graph, dict[str, Identifier], NamespaceManager]:
    ns_binds: dict[str, Identifier] = {
        "iw": URIRef("http://inferenceweb.stanford.edu/2004/07/iw.owl#")
    }
    for ns_bind in options.ns:
        pref, ns_uri = ns_bind.split("=")
        ns_binds[pref] = URIRef(ns_uri)

    namespace_manager = NamespaceManager(Graph())

    if options.sparql_endpoint:
        if len(options.facts) != 1:
            raise SystemExit(
                "--sparql-endpoint expects exactly one endpoint URI argument"
            )
        fact_graph: Graph = SPARQLServiceGraph(options.facts[0])
        options.hybrid = False
    else:
        fact_graph = Graph()

    for prefix, uri in list(ns_binds.items()):
        namespace_manager.bind(prefix, uri, override=False)
        if options.sparql_endpoint:
            fact_graph.store.bind(prefix, uri)

    if not options.sparql_endpoint:
        for file_n in options.facts:
            fact_graph.parse(file_n, format=options.input_format)
            if options.imports:
                for owl_import in fact_graph.objects(predicate=OWL_NS.imports):
                    fact_graph.parse(owl_import)
                    logger.info("Parsed Semantic Web Graph: %s", owl_import)

    if not options.sparql_endpoint and options.facts:
        for pref, uri in fact_graph.namespaces():
            ns_binds[pref] = uri

    if options.stdin:
        if options.sparql_endpoint:
            raise SystemExit("Cannot use --stdin with --sparql-endpoint")
        fact_graph.parse(sys.stdin, format=options.input_format)

    new_ns_mgr = NamespaceManager(fact_graph)
    for k, v in list(
        collapse_dictionary(dict([(k, v) for k, v in fact_graph.namespaces()])).items()
    ):
        new_ns_mgr.bind(k, v)
    fact_graph.namespace_manager = new_ns_mgr

    if options.normal_form:
        normal_form_reduction(fact_graph)

    return fact_graph, ns_binds, new_ns_mgr


def build_program(
    options: argparse.Namespace,
    fact_graph: Graph,
    ns_binds: dict[str, Identifier],
    namespace_manager: NamespaceManager,
) -> tuple[Ruleset, Graph, ReteNetwork]:
    rule_set = Ruleset()

    for file_n in options.rules:
        if options.rule_facts and not options.sparql_endpoint:
            fact_graph.parse(file_n, format="n3")
            logger.info("Parsing RDF facts from %s", file_n)
        if options.builtins:
            user_funcs = _load_builtin_module(options.builtins)
            rs = horn_from_n3(file_n, additional_builtins=user_funcs.ADDITIONAL_FILTERS)
        else:
            rs = horn_from_n3(file_n)
        ns_binds.update(rs.ns_mapping)
        rule_set.formulae.extend(rs)

    rule_set.ns_mapping = ns_binds

    for prefix, uri in list(ns_binds.items()):
        namespace_manager.bind(prefix, uri, override=False)
        if options.sparql_endpoint:
            fact_graph.store.bind(prefix, uri)

    closure_delta_graph = Graph()
    closure_delta_graph.namespace_manager = namespace_manager
    fact_graph.namespace_manager = namespace_manager

    if options.builtins:
        user_funcs = _load_builtin_module(options.builtins)
        rule_store, rule_graph, network = setup_rule_store(
            additional_builtins=user_funcs.ADDITIONAL_FILTERS,
            make_network=True,
        )
    else:
        rule_store, rule_graph, network = setup_rule_store(make_network=True)

    network.inferred_facts = closure_delta_graph
    network.ns_map = ns_binds

    if getattr(options, "dlp", False):
        if getattr(options, "ontology", None):
            ont_graph = Graph()
            for file_n in options.ontology:
                ont_graph.parse(file_n, format=options.ontology_format)
                for prefix, uri in ont_graph.namespaces():
                    ns_binds[prefix] = uri
                    namespace_manager.bind(prefix, uri, override=False)
                    if options.sparql_endpoint:
                        fact_graph.store.bind(prefix, uri)
        else:
            ont_graph = fact_graph
        normal_form_reduction(ont_graph)
        dlp = network.setup_description_logic_programming(
            ont_graph,
            add_pd_semantics=getattr(options, "pd_semantics", False),
            construct_network=False,
            ignore_negative_stratus=options.negation,
            safety=safety_name_map[options.safety],
        )
        rule_set.formulae.extend(dlp)

    return rule_set, closure_delta_graph, network


def _extract_goals(query_str: str, ns_binds: dict[str, Identifier]) -> list[tuple]:
    parsed_query = parseQuery(query_str)
    _, parsed_body = parsed_query
    _, triples = extract_triples_from_query(parsed_body, ns_binds)
    return triples


def _compute_derived_predicates(
    goals: list[tuple],
    options: argparse.Namespace,
    namespace_manager: NamespaceManager,
    rule_set: Ruleset,
) -> tuple[list[Identifier], list[URIRef]]:
    derived_preds: set[Identifier] = set()
    hybrid_preds: list[URIRef] = []

    for idb in options.idb:
        derived_preds.add(_resolve_qname(idb, namespace_manager))

    derived_preds.update(
        {obj if pred == RDF.type else pred for _subj, pred, obj in goals}
    )

    for hybrid in options.hybrid_predicate:
        hybrid_preds.append(_resolve_qname(hybrid, namespace_manager))

    return list(derived_preds), hybrid_preds


def run_naive(
    options: argparse.Namespace,
    rule_set: Ruleset,
    network: ReteNetwork,
    fact_graph: Graph,
) -> None:
    for rule in rule_set:
        network.build_network_from_clause(rule)

    working_memory = generate_token_set(fact_graph)

    start = time.time()
    network.feed_facts_to_add(working_memory)
    s_time = time.time() - start

    if options.debug:
        logger.info(
            "Time to calculate closure on working memory: %s",
            _format_timing(s_time),
        )
        logger.info("%s", network)


def run_bfp(
    options: argparse.Namespace,
    rule_set: Ruleset,
    network: ReteNetwork,
    fact_graph: Graph,
    ns_binds: dict[str, Identifier],
    namespace_manager: NamespaceManager,
    closure_delta_graph: Graph,
) -> BFPResult:
    if not options.why:
        raise ValueError("--method=bfp requires --why")

    goals = _extract_goals(options.why, ns_binds)
    derived_preds, hybrid_preds = _compute_derived_predicates(
        goals, options, namespace_manager, rule_set
    )

    entailing_graph, _closure_delta = owl_entailment_regime_graph(
        fact_graph,
        ns_binds,
        identify_hybrid_predicates=options.hybrid,
        hybrid_predicates=hybrid_preds if hybrid_preds else None,
        derived_predicates=derived_preds if derived_preds else None,
        goals=goals,
        namespace_manager=namespace_manager,
        extra_rulesets=rule_set if rule_set.formulae else None,
        verbose=options.debug,
        add_pd_semantics=getattr(options, "pd_semantics", False),
    )

    top_down_store = entailing_graph.store

    start = time.time()
    answers: list = []
    for answer in entailing_graph.query(options.why):
        answers.append(answer)
        s_time = time.time() - start
        logger.debug(
            "Answer via top-down SPARQL SIP strategy: %s (%s)",
            answer,
            _format_timing(s_time),
        )
        if options.first_answer:
            break

    elapsed = time.time() - start
    if not answers:
        logger.warning("No answers found for query (%s)", _format_timing(elapsed))

    return BFPResult(
        top_down_store=top_down_store,
        answers=answers,
        has_answers=bool(answers),
        elapsed=elapsed,
    )


def _ground_goal(
    goal_pattern: tuple,
    answers: list[dict],
    network: ReteNetwork,
) -> list[tuple]:
    grounded = []
    for answer in answers:
        triple = tuple(
            answer.get(t, t) if isinstance(t, Variable) else t for t in goal_pattern
        )
        if triple in network.inferred_facts:
            grounded.append(triple)
    return grounded
