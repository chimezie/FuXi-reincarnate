from __future__ import annotations

import sys
import time
import warnings

from rdflib.graph import Graph
from rdflib.namespace import NamespaceManager
from rdflib.term import Identifier, Variable
from rdflib.util import first

from fuxi.cli.shared import (
    BFPResult,
    OutputFormat,
    _format_timing,
    _ground_goal,
)
from fuxi.Horn.HornRules import Ruleset, horn_from_n3
from fuxi.Syntax.InfixOWL import (
    Class,
    Individual,
    Property,
    all_classes,
    all_properties,
)
from rdflib import URIRef


def _render_proof_graph(
    fmt: OutputFormat,
    result: BFPResult,
    ns_binds: dict[str, Identifier],
) -> None:
    if not result.has_answers:
        import logging

        logging.getLogger(__name__).warning(
            "No answers found; cannot render proof graph"
        )
        return

    from fuxi.Rete.Proof import generate_proof
    if fmt in [OutputFormat.PROOF_GRAPH_SVG, OutputFormat.PROOF_GRAPH_PNG]:
        img_format = "svg" if fmt == OutputFormat.PROOF_GRAPH_SVG else "png"
        store = result.top_down_store

        for network_for_goal, goal_pattern in store.query_networks:
            has_variable = any(isinstance(t, Variable) for t in goal_pattern)
            if has_variable:
                goals_to_prove = _ground_goal(
                    goal_pattern, result.answers, network_for_goal
                )
            else:
                goals_to_prove = (
                    [goal_pattern]
                    if goal_pattern in network_for_goal.inferred_facts
                    else []
                )

            for ground_goal in goals_to_prove:
                builder, proof = generate_proof(network_for_goal, ground_goal, store)
                ns_map = {**network_for_goal.ns_map, **ns_binds}
                if not ns_map:
                    ns_map = store.ns_bindings or ns_binds
                dot = builder.render_proof(proof, ns_map=ns_map, format=img_format)
                try:
                    data = dot.pipe(format=img_format)
                except Exception as exc:
                    raise SystemExit(
                        f"Failed to render proof graph: {exc}. "
                        f"Is Graphviz ('dot' binary) installed?"
                    ) from exc
                sys.stdout.buffer.write(data)
    elif fmt == OutputFormat.PML:
        pml = result.top_down_store.to_pml(fmt="xml")
        sys.stdout.buffer.write(pml.encode("utf-8"))
        return


def _render_rete_network(
    fmt: OutputFormat,
    result: BFPResult | None,
    ns_binds: dict[str, Identifier],
    network=None,
) -> None:
    from fuxi.Rete.Util import render_network

    img_format = "svg" if fmt == OutputFormat.RETE_NETWORK_SVG else "png"

    if result is not None:
        store = result.top_down_store
        for idx, (network_for_goal, goal_pattern) in enumerate(
            store.query_networks, 1
        ):
            ns_map = {**network_for_goal.ns_map, **ns_binds}
            dot = render_network(
                network_for_goal, ns_map=ns_map, format=img_format
            )
            try:
                data = dot.pipe(format=img_format)
            except Exception as exc:
                raise SystemExit(
                    f"Failed to render RETE network: {exc}. "
                    f"Is Graphviz ('dot' binary) installed?"
                ) from exc
            sys.stdout.buffer.write(data)
            if idx >= 2:
                import logging
                logging.getLogger(__name__).warning(
                    "Found %d query networks; only the first was rendered", idx,
                )
    elif network is not None:
        dot = render_network(network, ns_map=ns_binds, format=img_format)
        try:
            data = dot.pipe(format=img_format)
        except Exception as exc:
            raise SystemExit(
                f"Failed to render RETE network: {exc}. "
                f"Is Graphviz ('dot' binary) installed?"
            ) from exc
        sys.stdout.buffer.write(data)


def _render_sip_collection(
    fmt: OutputFormat,
    result: BFPResult | None,
) -> None:
    if result is None:
        raise SystemExit("--output=sip-collection-* requires --why --method=bfp")
    from fuxi.Rete.SidewaysInformationPassing import MAGIC, render_sip_collection
    from rdflib import RDF

    img_format = "svg" if fmt == OutputFormat.SIP_COLLECTION_SVG else "png"
    store = result.top_down_store
    for _network, _goal in store.query_networks:
        goal_info = store.goal_rule_sip_info.get(_goal)
        if goal_info is None:
            continue
        _, adorned_program, sip_collection, _, _ = goal_info
        if sip_collection is None:
            continue
        has_arcs = list(
            sip_collection.triples((None, RDF.type, MAGIC.SipArc))
        )
        dot = render_sip_collection(
            sip_collection,
            format=img_format,
            adorned_program=adorned_program if not has_arcs else None,
        )
        try:
            data = dot.pipe(format=img_format)
        except Exception as exc:
            raise SystemExit(
                f"Failed to render SIP collection: {exc}. "
                f"Is Graphviz ('dot' binary) installed?"
            ) from exc
        sys.stdout.buffer.write(data)


def _render_rif(
    rule_set: Ruleset,
    network,
    negation: bool,
    result: BFPResult | None = None,
) -> None:
    rules = (rule_set if rule_set
             else network.rules if network.rules
             else network.justifications if network.justifications
             else [])
    for rule in rules:
        print(rule)
    if negation:
        for n_rule in network.neg_rules:
            print(n_rule)

    if result is not None:
        for _network, _goal in result.top_down_store.query_networks:
            goal_info = result.top_down_store.goal_rule_sip_info.get(_goal)
            if goal_info is None:
                continue
            _, adorned_program, _, _, _ = goal_info
            if adorned_program:
                print("# Adorned rules:")
                for adorned_rule in adorned_program:
                    print(adorned_rule)


def _render_conflict(
    options,
    result: BFPResult | None,
    network,
) -> None:
    if result is not None:
        for _network, _goal in result.top_down_store.query_networks:
            print(_network, _goal)
            _network.report_conflict_set(options.debug)
        for query in result.top_down_store.edb_queries:
            print(query.as_sparql())
    else:
        network.report_conflict_set()


def _render_adornment(result: BFPResult) -> None:
    if result is None:
        raise SystemExit("--output=adornment requires --why --method=bfp")
    for _network, _goal in result.top_down_store.query_networks:
        goal_info = result.top_down_store.goal_rule_sip_info.get(_goal)
        if goal_info is None:
            continue
        _, adorned_program, _, _, _ = goal_info
        if adorned_program:
            for adorned_rule in adorned_program:
                print(adorned_rule)


def _render_rdf(
    options,
    network,
    fact_graph: Graph,
    namespace_manager: NamespaceManager,
    result: BFPResult | None = None,
    rule_set: Ruleset | None = None,
) -> None:
    for file_n in options.filter:
        for rule in horn_from_n3(file_n):
            network.build_filter_network_from_clause(rule)

    if options.negation and network.neg_rules and options.method in ["naive"]:
        _start = time.time()
        rt = network.calculate_stratified_model(fact_graph)
        if options.debug:
            import logging

            logging.getLogger(__name__).info(
                "Time to calculate stratified, stable model "
                "(inferred %s facts): %s",
                rt,
                _format_timing(time.time() - _start),
            )

    if options.filter:
        import logging

        logging.getLogger(__name__).info("Applying filter to entailed facts")
        network.inferred_facts = network.filtered_facts

    fmt = options.output
    if fmt == OutputFormat.N3:
        rules = (rule_set if rule_set
                 else network.rules if network.rules
                 else [])
        for rule in rules:
            print(rule)

    if options.closure and fmt in OutputFormat.rdf_formats():
        closure_graph = network.closure_graph(fact_graph)
        closure_graph.namespace_manager = namespace_manager
        print(closure_graph.serialize(destination=None, format=fmt, base=None))
    elif fmt in OutputFormat.rdf_formats():
        print(network.inferred_facts.serialize(destination=None, format=fmt, base=None))


def _render_man_owl(
    options,
    network,
    fact_graph: Graph,
) -> None:
    closure_graph = network.closure_graph(fact_graph, read_only=False)
    closure_graph.namespace_manager = fact_graph.namespace_manager
    Individual.factoryGraph = closure_graph

    if getattr(options, "classes", None):
        mapping = dict(closure_graph.namespace_manager.namespaces())
        for c in options.classes:
            pref, uri = c.split(":")
            print(Class(URIRef(mapping[pref] + uri)).__repr__(True))
    elif getattr(options, "properties", None):
        mapping = dict(closure_graph.namespace_manager.namespaces())
        for p in options.properties:
            pref, uri = p.split(":")
            print(Property(URIRef(mapping[pref] + uri)))
    else:
        for p in all_properties(closure_graph):
            print(p.identifier, first(p.label))
            print(repr(p))
        for c in all_classes(closure_graph):
            if getattr(options, "normalize", False):
                if c.is_primitive():
                    prim_anc = [sc for sc in c.sub_class_of if sc.is_primitive()]
                    if len(prim_anc) > 1:
                        warnings.warn(
                            f"Branches of primitive skeleton taxonomy "
                            f"should form trees: {c.qname} has "
                            f"{len(prim_anc)} primitive parents: {prim_anc}",
                            stacklevel=1,
                        )
                    children = [desc for desc in c.sub_sumptee_ids()]
                    for child in children:
                        for other_child in [o for o in children if o is not child]:
                            if other_child not in [
                                c.identifier for c in Class(child).disjoint_with
                            ]:
                                warnings.warn(
                                    f"Primitive children (of {c.qname}) "
                                    f"must be mutually disjoint: "
                                    f"{Class(child).qname} and "
                                    f"{Class(other_child).qname}",
                                    stacklevel=1,
                                )
            print(c.__repr__(True))


def render_output(
    options,
    result: BFPResult | None,
    rule_set: Ruleset,
    network,
    fact_graph: Graph,
    ns_binds: dict[str, Identifier],
    namespace_manager: NamespaceManager,
) -> None:
    fmt = OutputFormat(options.output)

    if fmt in OutputFormat.proof_graph_formats():
        _render_proof_graph(fmt, result, ns_binds)
        return

    if fmt in OutputFormat.rete_network_formats():
        _render_rete_network(fmt, result, ns_binds, network=network)
        return

    if fmt in OutputFormat.sip_collection_formats():
        _render_sip_collection(fmt, result)
        return

    if fmt == OutputFormat.CONFLICT:
        _render_conflict(options, result, network)
    elif fmt == OutputFormat.RIF:
        _render_rif(rule_set, network, options.negation, result=result)
    elif fmt == OutputFormat.ADORNMENT:
        _render_adornment(result)
        return
    elif fmt == OutputFormat.MAN_OWL:
        _render_man_owl(options, network, fact_graph)

    if result is not None:
        for answer in result.answers:
            print(answer)

    if fmt in OutputFormat.rdf_formats():
        _render_rdf(options, network, fact_graph, namespace_manager,
                     result=result, rule_set=rule_set)
