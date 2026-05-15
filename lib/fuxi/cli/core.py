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
    run_naive,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="fuxi.core",
        description="FuXi core - forward chaining inference and RETE diagnostics",
        usage="%(prog)s [options] factFile1 factFile2 ... factFileN",
    )
    add_common_arguments(parser)
    add_owl_arguments(parser)
    parser.add_argument(
        "--why",
        default=None,
        metavar="SPARQL_QUERY",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--method",
        default="naive",
        choices=["bfp", "naive"],
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--first-answer",
        action="store_true",
        default=False,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--output",
        default="n3",
        metavar="FORMAT",
        choices=OutputFormat.choices(),
        help="Output format (default: n3)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(
        level=logging.DEBUG if "--debug" in (argv or sys.argv[1:]) else logging.INFO,
        format="%(name)s: %(message)s",
    )

    options = parse_args(argv)
    fmt = OutputFormat(options.output)

    proof_or_sip = (
        fmt in OutputFormat.proof_graph_formats()
        or fmt in OutputFormat.sip_collection_formats()
    )
    if proof_or_sip:
        raise SystemExit(
            f"--output={options.output} requires fuxi.proof command"
        )

    if options.output == "man-owl":
        raise SystemExit(
            "--output=man-owl requires fuxi.owl command"
        )

    if getattr(options, "why", None):
        raise SystemExit(
            "fuxi.core does not support --why; use fuxi.proof for BFP queries"
        )

    fact_graph, ns_binds, namespace_manager = build_fact_graph(options)
    rule_set, closure_delta_graph, network = build_program(
        options, fact_graph, ns_binds, namespace_manager
    )

    run_naive(options, rule_set, network, fact_graph)

    render_output(
        options,
        None,
        rule_set,
        network,
        fact_graph,
        ns_binds,
        namespace_manager,
    )


if __name__ == "__main__":
    main()
