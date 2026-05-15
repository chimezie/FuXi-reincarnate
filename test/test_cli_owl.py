"""Unit and integration tests for the fuxi.owl sub-command."""

import subprocess
from pathlib import Path

import pytest

TEST_DIR = Path(__file__).parent
RULES_FILE = TEST_DIR / "command_line_test_rules.n3"
FACTS_FILE = TEST_DIR / "command_line_facts.n3"
FAM_NS = "http://dev.w3.org/2000/10/swap/test/cwm/fam.n3#"
FUXI_OWL_CMD = ["uv", "run", "--active", "--extra", "dev", "fuxi.owl"]


@pytest.mark.integration
def test_owl_naive_forward_chaining():
    result = subprocess.run(
        [
            *FUXI_OWL_CMD,
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


@pytest.mark.integration
def test_owl_rejects_proof_graph_without_bfp():
    result = subprocess.run(
        [
            *FUXI_OWL_CMD,
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
    assert "requires --why --method=bfp" in result.stderr


@pytest.mark.integration
def test_owl_bfp_with_why():
    query = f"PREFIX fam: <{FAM_NS}> SELECT ?a {{ fam:david fam:ancestor ?a }}"
    result = subprocess.run(
        [
            *FUXI_OWL_CMD,
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
            "n3",
            str(FACTS_FILE),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"CLI failed:\nstderr: {result.stderr}"


@pytest.mark.integration
def test_owl_rejects_unsupported_method():
    query = f"PREFIX fam: <{FAM_NS}> SELECT ?a {{ fam:david fam:ancestor ?a }}"
    result = subprocess.run(
        [
            *FUXI_OWL_CMD,
            "--rules",
            str(RULES_FILE),
            "--input-format",
            "n3",
            "--ns",
            f"fam={FAM_NS}",
            "--method",
            "naive",
            "--why",
            query,
            str(FACTS_FILE),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode != 0
