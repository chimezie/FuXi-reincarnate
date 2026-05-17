"""Unit and integration tests for the fuxi.proof sub-command."""

import subprocess
from pathlib import Path

import pytest

TEST_DIR = Path(__file__).parent
RULES_FILE = TEST_DIR / "command_line_test_rules.n3"
FACTS_FILE = TEST_DIR / "command_line_facts.n3"
FAM_NS = "http://dev.w3.org/2000/10/swap/test/cwm/fam.n3#"
FUXI_PROOF_CMD = ["uv", "run", "--active", "--extra", "dev", "fuxi.proof"]


@pytest.mark.integration
def test_proof_requires_why():
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
    assert result.returncode != 0
    assert "--why" in result.stderr


@pytest.mark.integration
def test_proof_rete_network_svg():
    """rete-network-svg must not crash with BFP query networks."""
    inverse_of_premises = TEST_DIR / "OWL" / "inverseOf" / "premises001.rdf"
    query = "ASK { eg:bob your:isBrotherOf eg:joe }"
    result = subprocess.run(
        [
            *FUXI_PROOF_CMD,
            "--dlp",
            "--hybrid",
            "--ns",
            "eg=http://example.net/vocab#",
            "--ns",
            "your=http://example.net/vocab#",
            "--why",
            query,
            "--output",
            "rete-network-svg",
            str(inverse_of_premises),
        ],
        capture_output=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"CLI failed:\nstdout: {result.stdout[:500]}\nstderr: {result.stderr[:500]}"
    )
    output = result.stdout
    assert output.startswith(b"<?xml") or output.startswith(b"<svg"), (
        f"SVG rete network should start with XML/SVG header, got: {output[:200]!r}"
    )


@pytest.mark.integration
def test_proof_graph_svg():
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
def test_proof_graph_png():
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
            "proof-graph-png",
            str(FACTS_FILE),
        ],
        capture_output=True,
        timeout=60,
    )
    assert result.returncode == 0, f"CLI failed:\nstderr: {result.stderr.decode()}"
    png_magic = b"\x89PNG\r\n\x1a\n"
    assert result.stdout.startswith(png_magic)


@pytest.mark.integration
def test_proof_sip_collection_svg():
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
            "sip-collection-svg",
            str(FACTS_FILE),
        ],
        capture_output=True,
        timeout=60,
    )
    assert result.returncode == 0, f"CLI failed:\nstderr: {result.stderr.decode()}"


@pytest.mark.integration
def test_proof_accepts_method_for_compat():
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
            "--method",
            "bfp",
            "--output",
            "n3",
            str(FACTS_FILE),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"CLI failed:\nstderr: {result.stderr}"


@pytest.mark.integration
def test_proof_conflict_output():
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
            "conflict",
            str(FACTS_FILE),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"CLI failed:\nstderr: {result.stderr}"


@pytest.mark.integration
def test_render_network_rejects_store():
    """render_network() must reject store= (dead parameter removed)."""
    from fuxi.Rete.Util import render_network

    with pytest.raises(TypeError, match="unexpected keyword argument 'store'"):
        render_network(object(), store=object())


@pytest.mark.integration
def test_multiple_query_networks_no_crash():
    """Multiple query networks must produce valid SVG, not crash."""
    query = (
        f"PREFIX fam: <{FAM_NS}> "
        "SELECT ?a ?b ?c { ?a fam:ancestor ?b . ?b fam:ancestor ?c }"
    )
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
            "rete-network-svg",
            str(FACTS_FILE),
        ],
        capture_output=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"CLI failed:\nstdout: {result.stdout[:500]}\nstderr: {result.stderr[:500]}"
    )
    output = result.stdout
    assert output.startswith(b"<?xml") or output.startswith(b"<svg"), (
        f"SVG rete network should start with XML/SVG header, got: {output[:200]!r}"
    )
