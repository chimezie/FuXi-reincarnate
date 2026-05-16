"""
Test that ``_extract_goals`` correctly extracts BGP triples from a SPARQL
query using the modern ``extract_triples_from_query`` utility (which
replaced the removed ``_normalize_sparql_parse`` helper).
"""

from fuxi.Rete.CommandLine import _extract_goals
from rdflib import Namespace

EX = Namespace("http://example.org/")


def test_extract_goals_from_select():
    ns_binds = {"ex": EX}
    query = f"PREFIX ex: <{EX}> SELECT ?s ?o {{ ex:x ex:p ?o }}"
    triples = _extract_goals(query, ns_binds)
    assert len(triples) >= 1
    predicates = {t[1] for t in triples}
    assert EX.p in predicates


def test_extract_goals_from_ask():
    ns_binds = {"ex": EX}
    query = f"PREFIX ex: <{EX}> ASK {{ ex:i a ex:A }}"
    triples = _extract_goals(query, ns_binds)
    assert len(triples) >= 1
