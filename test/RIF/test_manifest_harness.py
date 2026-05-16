from __future__ import annotations

import xml.etree.ElementTree as ET
from urllib.request import Request, urlopen

import pytest

from fuxi.Horn.rif_presentation_serializer import RIFPresentationSerializer
from fuxi.Horn.rif_xml_serializer import serialize_xml
from fuxi.Horn.RIFCore import RIFParser

pytestmark = pytest.mark.integration

CORE_MANIFEST_URL = "http://www.w3.org/2005/rules/test/repository/CoreTests.xml"

RIF_TEST_NS = "http://www.w3.org/2009/10/rif-test#"

SKIP: dict[str, str] = {
    "Negation_as_failure_funct_win": "Depends on PRD-specific features",
    "Negation_as_failure_win_win": "Depends on PRD-specific features",
    "Core_NonSaffold": "Non-existent test resource",
    "Core_NonSafeness_2": "Or in body not supported by Clause.__init__",
}

IGNORED_TEST_TYPES = frozenset(
    {
        "NegativeEntailmentTest",
        "NegativeEntailmentTestMultipleConclusions",
        "PositiveEntailmentTestMultipleConclusions",
    }
)


def _fetch_manifest(url: str) -> ET.Element:
    with urlopen(Request(url), timeout=15) as f:
        return ET.fromstring(f.read())


def _collect_tests(
    root: ET.Element,
) -> list[tuple[str, str, str]]:
    tests: list[tuple[str, str, str]] = []
    for child in root:
        tag = child.tag
        if tag == f"{{{RIF_TEST_NS}}}PositiveEntailmentTest":
            id_ = child.get("id", "")
            premise = child.find(f"{{{RIF_TEST_NS}}}PremiseDocument")
            if premise is None:
                continue
            remote = premise.find(f"{{{RIF_TEST_NS}}}Normative/{{{RIF_TEST_NS}}}remote")
            if remote is not None and remote.text:
                tests.append((id_, remote.text, "parse-rt"))
        elif tag == f"{{{RIF_TEST_NS}}}PositiveSyntaxTest":
            id_ = child.get("id", "")
            inp = child.find(f"{{{RIF_TEST_NS}}}InputDocument")
            if inp is None:
                continue
            remote = inp.find(f"{{{RIF_TEST_NS}}}Normative/{{{RIF_TEST_NS}}}remote")
            if remote is not None and remote.text:
                tests.append((id_, remote.text, "parse-rt"))
        elif tag == f"{{{RIF_TEST_NS}}}NegativeSyntaxTest":
            id_ = child.get("id", "")
            inp = child.find(f"{{{RIF_TEST_NS}}}InputDocument")
            if inp is None:
                continue
            remote = inp.find(f"{{{RIF_TEST_NS}}}Normative/{{{RIF_TEST_NS}}}remote")
            if remote is not None and remote.text:
                tests.append((id_, remote.text, "parse-only"))
    return tests


def _fetch_rif(url: str) -> bytes:
    with urlopen(Request(url), timeout=15) as f:
        return f.read()


@pytest.fixture(scope="session")
def manifest_tests() -> list[tuple[str, str, str]]:
    root = _fetch_manifest(CORE_MANIFEST_URL)
    return _collect_tests(root)


def test_parse_roundtrip(
    manifest_tests: list[tuple[str, str, str]],
) -> None:
    passed = 0
    failed: list[tuple[str, str]] = []
    for id_, url, test_type in manifest_tests:
        if id_ in SKIP:
            continue
        content = _fetch_rif(url)
        try:
            result = RIFParser.parse_xml(content)
            n_rules = len(result.formulae)
            if test_type == "parse-rt" and n_rules > 0:
                xml_out = serialize_xml(result)
                result2 = RIFParser.parse_xml(xml_out)
                assert len(result2.formulae) == n_rules, (
                    f"{id_}: XML round-trip rule count mismatch "
                    f"({len(result2.formulae)} vs {n_rules})"
                )
                ps = RIFPresentationSerializer().serialize(result)
                assert "Document(" in ps, f"{id_}: PS output missing Document"
            passed += 1
        except Exception as e:
            failed.append((id_, f"{type(e).__name__}: {e}"))
    total = passed + len(failed)
    msg = f"{passed}/{total} passed"
    if failed:
        lines = "\n  ".join(f"{k}: {v}" for k, v in failed)
        msg += f"\n  Failures:\n  {lines}"
    assert not failed, msg
    print(msg)
