from __future__ import annotations

import logging
import sys


def _route_to_subcommand(argv: list[str] | None = None) -> None:
    raw = argv if argv is not None else sys.argv[1:]

    has_why = "--why" in raw or any(a.startswith("--why=") for a in raw)
    has_dlp = "--dlp" in raw
    has_man_owl = "--output=man-owl" in raw or (
        "--output" in raw
        and raw.index("--output") + 1 < len(raw)
        and raw[raw.index("--output") + 1] == "man-owl"
    )
    has_class = "--class" in raw or any(a.startswith("--class=") for a in raw)
    has_property = "--property" in raw or any(a.startswith("--property=") for a in raw)

    is_owl_cmd = has_man_owl or has_class or has_property or (has_dlp and has_why)
    is_proof_cmd = has_why and not is_owl_cmd

    if is_proof_cmd:
        from fuxi.cli.proof import main as proof_main

        proof_main(argv)
        return

    if is_owl_cmd:
        from fuxi.cli.owl import main as owl_main

        owl_main(argv)
        return

    from fuxi.cli.core import main as core_main

    core_main(argv)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(
        level=logging.DEBUG if "--debug" in (argv or sys.argv[1:]) else logging.INFO,
        format="%(name)s: %(message)s",
    )
    _route_to_subcommand(argv)


if __name__ == "__main__":
    main()
