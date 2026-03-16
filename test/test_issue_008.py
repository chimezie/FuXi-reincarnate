# -*- coding: utf-8 -*-
"""
https://github.com/RDFLib/FuXi/issues/8
"""

from io import StringIO

from rdflib import Graph, Namespace

from fuxi.Horn.HornRules import HornFromN3
from fuxi.SPARQL.BackwardChainingStore import TopDownSPARQLEntailingStore

rules = """\
@prefix : <fam.n3#>.
@keywords is, of, a.
{ ?x begat ?y } => { ?y ancestor ?x }.
{ ?x ancestor ?y. ?y ancestor ?z } => { ?x ancestor ?z }."""

facts = """\
@prefix : <fam.n3#>.
@keywords is, of, a.

albert begat bill, bevan.
bill begat carol, charlie.
bertha begat carol, charlie.
bevan begat chaude, christine.
christine begat david, diana, douglas."""


def _make_store_and_graph():
    fam_ns = Namespace("http://dev.w3.org/2000/10/swap/test/cwm/fam.n3#")
    ns_mapping = {"fam": fam_ns}
    parsed_rules = HornFromN3(StringIO(rules))
    fact_graph = Graph().parse(StringIO(facts), format="n3")
    fact_graph.bind("fam", fam_ns)
    fact_graph.bind("", fam_ns)
    derived_predicates = [fam_ns.ancestor]
    top_down_store = TopDownSPARQLEntailingStore(
        fact_graph.store,
        fact_graph,
        idb=parsed_rules,
        derivedPredicates=derived_predicates,
        nsBindings=ns_mapping,
    )
    return fam_ns, ns_mapping, top_down_store


def test_issue_008():
    """Test that rule variables don't leak between rules (GitHub issue #8)."""
    fam_ns, ns_mapping, top_down_store = _make_store_and_graph()
    target_graph = Graph(store=top_down_store)
    target_graph.bind("ex", fam_ns)
    target_graph.bind("fam", fam_ns)
    res = target_graph.query(
        """PREFIX fam: <http://dev.w3.org/2000/10/swap/test/cwm/fam.n3#>
SELECT ?a { fam:david fam:ancestor ?a }""",
        initNs=ns_mapping,
    )
    assert len(list(res)) == 0, "Variables should not leak between rules"
