"""
Integration tests for the FuXi command-line interface.

These tests exercise the ``fuxi`` CLI (registered as the ``fuxi`` console
script in *pyproject.toml*) against the family/ancestor ruleset originally
from ``test_issue_008.py`` (GitHub issue #8 – variable leakage in BFP).

Data files
----------
- *command_line_test_rules.n3* – N3 rules for ``begat → ancestor`` and
  transitive ``ancestor``.
- *command_line_facts.n3* – N3 facts describing a small family tree.

Manual usage
------------

Naive forward chaining (produces inferred triples as N3)::

    uv run --active --extra dev fuxi \\
        --rules test/command_line_test_rules.n3 \\
        --input-format n3 \\
        --ns fam=http://dev.w3.org/2000/10/swap/test/cwm/fam.n3# \\
        --output n3 \\
        test/command_line_facts.n3

BFP top-down query (answers printed as ``{Variable: URIRef}`` dicts)::

    uv run --active --extra dev fuxi \\
        --rules test/command_line_test_rules.n3 \\
        --input-format n3 \\
        --ns fam=http://dev.w3.org/2000/10/swap/test/cwm/fam.n3# \\
        --method bfp \\
        --why "PREFIX fam: <http://dev.w3.org/2000/10/swap/test/cwm/fam.n3#> \\
               SELECT ?a { fam:david fam:ancestor ?a }" \\
        test/command_line_facts.n3

Using sub-commands directly::

    uv run --active --extra dev fuxi.core \\
        --rules test/command_line_test_rules.n3 \\
        --input-format n3 \\
        --ns fam=http://dev.w3.org/2000/10/swap/test/cwm/fam.n3# \\
        --output n3 \\
        test/command_line_facts.n3

    uv run --active --extra dev fuxi.proof \\
        --rules test/command_line_test_rules.n3 \\
        --input-format n3 \\
        --ns fam=http://dev.w3.org/2000/10/swap/test/cwm/fam.n3# \\
        --why "PREFIX fam: <http://dev.w3.org/2000/10/swap/test/cwm/fam.n3#> \\
               SELECT ?a { fam:david fam:ancestor ?a }" \\
        --output proof-graph-svg \\
        test/command_line_facts.n3 > proof.svg
"""

from pathlib import Path
import subprocess

import pytest

from rdflib import Graph, Namespace

TEST_DIR = Path(__file__).parent
RULES_FILE = TEST_DIR / "command_line_test_rules.n3"
FACTS_FILE = TEST_DIR / "command_line_facts.n3"
FAM_NS = "http://dev.w3.org/2000/10/swap/test/cwm/fam.n3#"
FAM = Namespace(FAM_NS)
FUXI_CMD = ["uv", "run", "--active", "--extra", "dev", "fuxi"]
FUXI_CORE_CMD = ["uv", "run", "--active", "--extra", "dev", "fuxi.core"]
FUXI_PROOF_CMD = ["uv", "run", "--active", "--extra", "dev", "fuxi.proof"]


def _parse_answer_dicts(stdout: str) -> list[str]:
    """Extract sparql_interlocution answer-dict lines from CLI stdout."""
    answers = []
    for line in stdout.strip().splitlines():
        stripped = line.strip()
        if stripped.startswith("{") and "Variable" in stripped:
            answers.append(stripped)
    return answers


@pytest.mark.integration
def test_cli_naive_forward_chaining():
    """Naive forward chaining should produce ancestor triples.

    Runs::

        fuxi --rules ... --input-format n3 --ns fam=... --output n3 facts.n3
    """
    result = subprocess.run(
        [
            *FUXI_CMD,
            "--rules",
            str(RULES_FILE),
            "--input-format",
            "n3",
            "--ns",
            f"fam={FAM_NS}",
            "--output",
            "n3",
            str(FACTS_FILE),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"CLI failed:\nstderr: {result.stderr}"
    inferred = Graph().parse(data=result.stdout, format="n3")
    assert (FAM.david, FAM.ancestor, FAM.christine) in inferred, (
        "Forward chaining should infer david ancestor christine"
    )


@pytest.mark.integration
def test_cli_core_naive_forward_chaining():
    """fuxi.core should produce same results as fuxi for naive forward chaining."""
    result = subprocess.run(
        [
            *FUXI_CORE_CMD,
            "--rules",
            str(RULES_FILE),
            "--input-format",
            "n3",
            "--ns",
            f"fam={FAM_NS}",
            "--output",
            "n3",
            str(FACTS_FILE),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"CLI failed:\nstderr: {result.stderr}"
    inferred = Graph().parse(data=result.stdout, format="n3")
    assert (FAM.david, FAM.ancestor, FAM.christine) in inferred, (
        "Forward chaining should infer david ancestor christine"
    )


@pytest.mark.integration
@pytest.mark.xfail(reason="Known variable leakage in BFP (issue #8)")
def test_cli_bfp_issue_008():
    """BFP should not leak variables between rules (GitHub issue #8).

    Runs::

        fuxi --rules ... --input-format n3 --ns fam=... \\
             --method bfp --why "SELECT ?a { fam:david fam:ancestor ?a }" \\
             facts.n3
    """
    query = f"PREFIX fam: <{FAM_NS}> SELECT ?a {{ fam:david fam:ancestor ?a }}"
    result = subprocess.run(
        [
            *FUXI_CMD,
            "--rules",
            str(RULES_FILE),
            "--input-format",
            "n3",
            "--ns",
            f"fam={FAM_NS}",
            "--method",
            "bfp",
            "--why",
            query,
            str(FACTS_FILE),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"CLI failed:\nstderr: {result.stderr}"
    answer_lines = _parse_answer_dicts(result.stdout)
    assert len(answer_lines) == 0, (
        f"Variables should not leak between rules, "
        f"got {len(answer_lines)} answers: {answer_lines}"
    )


@pytest.mark.integration
def test_cli_proof_graph_requires_bfp():
    """--output=proof-graph-svg without --why --method=bfp should fail."""
    result = subprocess.run(
        [
            *FUXI_CMD,
            "--rules",
            str(RULES_FILE),
            "--input-format",
            "n3",
            "--ns",
            f"fam={FAM_NS}",
            "--output",
            "proof-graph-svg",
            str(FACTS_FILE),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode != 0, (
        "Should fail when proof-graph output used without --why --method=bfp"
    )
    stderr = result.stderr
    assert (
        "requires --why --method=bfp" in stderr
        or "requires fuxi.proof" in stderr
        or "fuxi.proof command" in stderr
    ), f"Expected validation error, got: {stderr}"


@pytest.mark.integration
def test_cli_proof_graph_svg():
    """BFP proof graph SVG output should contain valid SVG markup.

    Runs::

        fuxi --rules ... --input-format n3 --ns fam=... \\
             --method bfp --why "SELECT ?a { ... }" \\
             --output proof-graph-svg facts.n3
    """
    query = f"PREFIX fam: <{FAM_NS}> SELECT ?a {{ fam:david fam:ancestor ?a }}"
    result = subprocess.run(
        [
            *FUXI_CMD,
            "--rules",
            str(RULES_FILE),
            "--input-format",
            "n3",
            "--ns",
            f"fam={FAM_NS}",
            "--method",
            "bfp",
            "--why",
            query,
            "--output",
            "proof-graph-svg",
            str(FACTS_FILE),
        ],
        capture_output=True,
        timeout=60,
    )
    assert result.returncode == 0, f"CLI failed:\nstderr: {result.stderr.decode()}"
    output = result.stdout
    assert output.startswith(b"<?xml") or output.startswith(b"<svg"), (
        f"SVG proof graph should start with XML/SVG header, got: {output[:200]!r}"
    )
    assert b"Variable" not in output, (
        "No answer dicts should leak into proof-graph stdout"
    )


@pytest.mark.integration
def test_cli_proof_graph_png():
    """BFP proof graph PNG output should contain valid PNG binary data.

    Runs::

        fuxi --rules ... --input-format n3 --ns fam=... \\
             --method bfp --why "SELECT ?a { ... }" \\
             --output proof-graph-png facts.n3
    """
    query = f"PREFIX fam: <{FAM_NS}> SELECT ?a {{ fam:david fam:ancestor ?a }}"
    result = subprocess.run(
        [
            *FUXI_CMD,
            "--rules",
            str(RULES_FILE),
            "--input-format",
            "n3",
            "--ns",
            f"fam={FAM_NS}",
            "--method",
            "bfp",
            "--why",
            query,
            "--output",
            "proof-graph-png",
            str(FACTS_FILE),
        ],
        capture_output=True,
        timeout=60,
    )
    assert result.returncode == 0, f"CLI failed:\nstderr: {result.stderr.decode()}"
    output = result.stdout
    png_magic = b"\x89PNG\r\n\x1a\n"
    assert output.startswith(png_magic), (
        "PNG proof graph should start with PNG magic bytes"
    )


@pytest.mark.integration
def test_cli_rete_network_svg():
    """Naive forward chaining with --output=rete-network-svg should produce SVG."""
    result = subprocess.run(
        [
            *FUXI_CMD,
            "--rules",
            str(RULES_FILE),
            "--input-format",
            "n3",
            "--ns",
            f"fam={FAM_NS}",
            "--output",
            "rete-network-svg",
            str(FACTS_FILE),
        ],
        capture_output=True,
        timeout=60,
    )
    assert result.returncode == 0, f"CLI failed:\nstderr: {result.stderr.decode()}"
    output = result.stdout
    assert output.startswith(b"<?xml") or output.startswith(b"<svg"), (
        "SVG RETE network should start with XML/SVG header"
    )


@pytest.mark.integration
def test_cli_rete_network_png():
    """Naive forward chaining with --output=rete-network-png should produce PNG."""
    result = subprocess.run(
        [
            *FUXI_CMD,
            "--rules",
            str(RULES_FILE),
            "--input-format",
            "n3",
            "--ns",
            f"fam={FAM_NS}",
            "--output",
            "rete-network-png",
            str(FACTS_FILE),
        ],
        capture_output=True,
        timeout=60,
    )
    assert result.returncode == 0, f"CLI failed:\nstderr: {result.stderr.decode()}"
    output = result.stdout
    png_magic = b"\x89PNG\r\n\x1a\n"
    assert output.startswith(png_magic), (
        "PNG RETE network should start with PNG magic bytes"
    )


@pytest.mark.integration
def test_cli_sip_collection_requires_bfp():
    """--output=sip-collection-svg without --why --method=bfp should fail."""
    result = subprocess.run(
        [
            *FUXI_CMD,
            "--rules",
            str(RULES_FILE),
            "--input-format",
            "n3",
            "--ns",
            f"fam={FAM_NS}",
            "--output",
            "sip-collection-svg",
            str(FACTS_FILE),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode != 0, (
        "Should fail when sip-collection output used without --why --method=bfp"
    )
    stderr = result.stderr
    assert (
        "requires --why --method=bfp" in stderr
        or "requires fuxi.proof" in stderr
        or "fuxi.proof command" in stderr
    ), f"Expected validation error, got: {stderr}"


@pytest.mark.integration
def test_cli_core_rejects_why():
    """fuxi.core should reject --why flag."""
    query = f"PREFIX fam: <{FAM_NS}> SELECT ?a {{ fam:david fam:ancestor ?a }}"
    result = subprocess.run(
        [
            *FUXI_CORE_CMD,
            "--rules",
            str(RULES_FILE),
            "--input-format",
            "n3",
            "--ns",
            f"fam={FAM_NS}",
            "--why",
            query,
            str(FACTS_FILE),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode != 0, "fuxi.core should reject --why"
    assert "fuxi.proof" in result.stderr, (
        f"Should suggest fuxi.proof, got: {result.stderr}"
    )


@pytest.mark.integration
def test_cli_proof_requires_why():
    """fuxi.proof should require --why flag."""
    result = subprocess.run(
        [
            *FUXI_PROOF_CMD,
            "--rules",
            str(RULES_FILE),
            "--input-format",
            "n3",
            "--ns",
            f"fam={FAM_NS}",
            str(FACTS_FILE),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode != 0, "fuxi.proof should require --why"
    assert "--why" in result.stderr, (
        f"Should mention --why requirement, got: {result.stderr}"
    )


@pytest.mark.integration
def test_cli_proof_graph_svg_via_proof_command():
    """fuxi.proof --output proof-graph-svg should produce SVG."""
    query = f"PREFIX fam: <{FAM_NS}> SELECT ?a {{ fam:david fam:ancestor ?a }}"
    result = subprocess.run(
        [
            *FUXI_PROOF_CMD,
            "--rules",
            str(RULES_FILE),
            "--input-format",
            "n3",
            "--ns",
            f"fam={FAM_NS}",
            "--why",
            query,
            "--output",
            "proof-graph-svg",
            str(FACTS_FILE),
        ],
        capture_output=True,
        timeout=60,
    )
    assert result.returncode == 0, f"CLI failed:\nstderr: {result.stderr.decode()}"
    output = result.stdout
    assert output.startswith(b"<?xml") or output.startswith(b"<svg"), (
        f"SVG proof graph should start with XML/SVG header, got: {output[:200]!r}"
    )


@pytest.mark.integration
def test_cli_core_rete_network_svg():
    """fuxi.core --output rete-network-svg should produce SVG."""
    result = subprocess.run(
        [
            *FUXI_CORE_CMD,
            "--rules",
            str(RULES_FILE),
            "--input-format",
            "n3",
            "--ns",
            f"fam={FAM_NS}",
            "--output",
            "rete-network-svg",
            str(FACTS_FILE),
        ],
        capture_output=True,
        timeout=60,
    )
    assert result.returncode == 0, f"CLI failed:\nstderr: {result.stderr.decode()}"
    output = result.stdout
    assert output.startswith(b"<?xml") or output.startswith(b"<svg"), (
        "SVG RETE network should start with XML/SVG header"
    )
