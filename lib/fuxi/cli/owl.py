from __future__ import annotations

import argparse
import logging
import sys

from fuxi.cli.renderers import render_output
from fuxi.cli.shared import (
    BFPResult,
    OutputFormat,
    add_common_arguments,
    add_man_owl_arguments,
    add_owl_arguments,
    build_fact_graph,
    build_program,
    run_bfp,
    run_naive,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="fuxi.owl",
        description=(
            "FuXi OWL - DLP rule extraction, "
            "ontology reasoning, Manchester OWL rendering"
        ),
        usage="%(prog)s [options] factFile1 factFile2 ... factFileN",
    )
    add_common_arguments(parser)
    add_owl_arguments(parser)
    add_man_owl_arguments(parser)
    parser.add_argument(
        "--output",
        default="n3",
        metavar="FORMAT",
        choices=OutputFormat.choices(),
        help="Output format (default: n3)",
    )
    parser.add_argument(
        "--why",
        default=None,
        metavar="SPARQL_QUERY",
        help="SPARQL query to solve using BFP (optional)",
    )
    parser.add_argument(
        "--method",
        default="naive",
        choices=["bfp", "naive"],
        help="Reasoning method with --why: bfp or naive (default: naive)",
    )
    parser.add_argument(
        "--first-answer",
        action="store_true",
        default=False,
        help="Return only the first answer with --why",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(
        level=logging.DEBUG if "--debug" in (argv or sys.argv[1:]) else logging.INFO,
        format="%(name)s: %(message)s",
    )

    options = parse_args(argv)
    fmt = OutputFormat(options.output)

    if (
        fmt in OutputFormat.proof_graph_formats()
        or fmt in OutputFormat.sip_collection_formats()
    ):
        if not options.why or options.method != "bfp":
            raise SystemExit(f"--output={options.output} requires --why --method=bfp")

    fact_graph, ns_binds, namespace_manager = build_fact_graph(options)
    rule_set, closure_delta_graph, network = build_program(
        options, fact_graph, ns_binds, namespace_manager
    )

    bfp_result: BFPResult | None = None
    if options.why:
        if options.method == "bfp":
            bfp_result = run_bfp(
                options,
                rule_set,
                network,
                fact_graph,
                ns_binds,
                namespace_manager,
                closure_delta_graph,
            )
        else:
            raise SystemExit(
                f"Unsupported reasoning method with --why: {options.method}. "
                f"Use --method=bfp"
            )
    else:
        run_naive(options, rule_set, network, fact_graph)

    render_output(
        options,
        bfp_result,
        rule_set,
        network,
        fact_graph,
        ns_binds,
        namespace_manager,
    )


if __name__ == "__main__":
    main()
