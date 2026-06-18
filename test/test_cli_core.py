"""Unit and integration tests for the fuxi.core sub-command."""

from pathlib import Path
import subprocess

import pytest

from rdflib import Graph, Namespace

TEST_DIR = Path(__file__).parent
RULES_FILE = TEST_DIR / "command_line_test_rules.n3"
FACTS_FILE = TEST_DIR / "command_line_facts.n3"
FAM_NS = "http://dev.w3.org/2000/10/swap/test/cwm/fam.n3#"
FAM = Namespace(FAM_NS)
FUXI_CORE_CMD = ["uv", "run", "--active", "--extra", "dev", "fuxi.core"]


@pytest.mark.integration
def test_core_naive_forward_chaining():
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
    assert (FAM.david, FAM.ancestor, FAM.christine) in inferred


@pytest.mark.integration
def test_core_rete_network_svg():
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
    assert result.stdout.startswith(b"<?xml") or result.stdout.startswith(b"<svg")


@pytest.mark.integration
def test_core_rete_network_png():
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
            "rete-network-png",
            str(FACTS_FILE),
        ],
        capture_output=True,
        timeout=60,
    )
    assert result.returncode == 0, f"CLI failed:\nstderr: {result.stderr.decode()}"
    png_magic = b"\x89PNG\r\n\x1a\n"
    assert result.stdout.startswith(png_magic)


@pytest.mark.integration
def test_core_rejects_why():
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
    assert result.returncode != 0
    assert "fuxi.proof" in result.stderr


@pytest.mark.integration
def test_core_rejects_proof_graph():
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
            "proof-graph-svg",
            str(FACTS_FILE),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode != 0
    assert "fuxi.proof" in result.stderr


@pytest.mark.integration
def test_core_rejects_man_owl():
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
            "man-owl",
            str(FACTS_FILE),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode != 0
    assert "fuxi.owl" in result.stderr


@pytest.mark.integration
def test_core_conflict_output():
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
            "conflict",
            str(FACTS_FILE),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"CLI failed:\nstderr: {result.stderr}"


@pytest.mark.integration
def test_core_rif_output():
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
            "rif",
            str(FACTS_FILE),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"CLI failed:\nstderr: {result.stderr}"
