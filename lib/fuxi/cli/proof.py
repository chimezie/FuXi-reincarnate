from __future__ import annotations

import argparse
import logging
import sys

from fuxi.cli.renderers import render_output
from fuxi.cli.shared import (
    OutputFormat,
    add_common_arguments,
    add_owl_arguments,
    build_fact_graph,
    build_program,
    run_bfp,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="fuxi.proof",
        description="FuXi proof - BFP query answering, proof and SIP graph rendering",
        usage="%(prog)s [options] factFile1 factFile2 ... factFileN",
    )
    add_common_arguments(parser)
    add_owl_arguments(parser)
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
        help="SPARQL query to solve using BFP (required)",
    )
    parser.add_argument(
        "--method",
        default="bfp",
        choices=["bfp", "naive"],
        help=(
            "Reasoning method (fuxi.proof always uses bfp; accepted for compatibility)"
        ),
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

    if not options.why:
        raise SystemExit("fuxi.proof requires --why (a SPARQL query)")

    if options.output == "man-owl":
        raise SystemExit("--output=man-owl requires fuxi.owl command")

    if (
        fmt in OutputFormat.proof_graph_formats()
        or fmt in OutputFormat.sip_collection_formats()
    ):
        pass

    fact_graph, ns_binds, namespace_manager = build_fact_graph(options)
    rule_set, closure_delta_graph, network = build_program(
        options, fact_graph, ns_binds, namespace_manager
    )

    options.method = "bfp"
    bfp_result = run_bfp(
        options,
        rule_set,
        network,
        fact_graph,
        ns_binds,
        namespace_manager,
        closure_delta_graph,
    )

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
