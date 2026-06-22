"""
Tests for the sparql_interlocution function.

sparql_interlocution is the query-evaluation bridge between the CLI
and the TopDownSPARQLEntailingStore.  It must correctly handle
ground ASK queries that the BFP solver proves.

This module also covers ``sparql_interlocution_basic_graph_pattern``, the
SELECT-only bridge that drives ``TopDownSPARQLEntailingStore.batch_unify`` (the
conjunctive SIP join path).  Unlike ``store.query()``/``solve_triple_pattern``
-- which partitions EDB and IDB patterns and evaluates them independently --
this API threads bindings across patterns so that basic graph patterns mixing
base (EDB) and derived (IDB) predicates join correctly.  Its contract:

* SELECT queries return an rdflib ``SPARQLResult`` (drop-in with ``query()``).
* ASK (and other non-SELECT forms) raise ``NotImplementedError``.
* ``generate_proofs=True`` returns a ``(SPARQLResult, proofs)`` tuple, where
  ``proofs`` maps each proved ground goal triple to its ``(builder, proof)``
  pair drawn from the store's ``goal_rule_sip_info`` BFP state.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from rdflib.plugins.sparql.processor import SPARQLResult

from fuxi.cli.shared import _compute_derived_predicates, _extract_goals
from fuxi.DLP.DLNormalization import normal_form_reduction
from fuxi.Horn.HornRules import Ruleset
from fuxi.Rete.RuleStore import setup_rule_store
from fuxi.SPARQL.utilities import (
    owl_entailment_regime_graph,
    sparql_interlocution_basic_graph_pattern,
)
from rdflib import Graph, Namespace, Variable

pytestmark = pytest.mark.integration

TEST_DIR = Path(__file__).parent.parent
FIRST = Namespace("http://www.w3.org/2002/03owlt/TransitiveProperty/premises001#")
PREMISE_RDF = TEST_DIR / "OWL" / "TransitiveProperty" / "premises001.rdf"

ASK_QUERY = "ASK { first:Ghent first:path first:Amsterdam }"
NS_BINDS = {"first": FIRST}


def _make_entailing_graph():
    """Build the entailing graph just like the CLI does in run_bfp."""
    fact_graph = Graph()
    fact_graph.parse(PREMISE_RDF, format="xml")
    ns_binds = dict(fact_graph.namespaces())

    normal_form_reduction(fact_graph)
    _, _, network = setup_rule_store(make_network=True)
    dlp = list(
        network.setup_description_logic_programming(
            fact_graph,
            add_pd_semantics=False,
            construct_network=False,
        )
    )

    goals = _extract_goals(ASK_QUERY, ns_binds)
    derived_preds, _hybrid_preds = _compute_derived_predicates(
        goals,
        type("Options", (), {"idb": [], "hybrid_predicate": []})(),
        fact_graph.namespace_manager,
        type("RS", (), {"formulae": dlp})(),
    )

    rule_set = Ruleset()
    rule_set.formulae.extend(dlp)

    entailing_graph, _delta = owl_entailment_regime_graph(
        fact_graph,
        ns_binds,
        identify_hybrid_predicates=True,
        derived_predicates=derived_preds if derived_preds else None,
        goals=goals,
        namespace_manager=fact_graph.namespace_manager,
        extra_rulesets=rule_set if rule_set.formulae else None,
        verbose=False,
        add_pd_semantics=False,
    )
    return entailing_graph


def test_sparql_interlocution_ground_ask_proved():
    """
    A ground ASK query for a provable derived triple must yield True.

    Regression test: ``sparql_interlocution`` crashed with
    ``TypeError: 'bool' object is not iterable`` when ``batch_unify``
    yielded ``True`` (a boolean) for a successfully proved ground goal.
    """
    entailing_graph = _make_entailing_graph()
    answers = list(entailing_graph.query(ASK_QUERY))

    assert len(answers) > 0, "Expected at least one answer for a provable ground goal"
    assert answers[0] is True


def test_sparql_interlocution_ground_ask_not_proved():
    """
    A ground ASK query for a *non*-provable derived triple yields nothing.

    This ensures the fix doesn't accidentally produce a boolean for
    ground goals that the BFP cannot prove (where ``answers()`` returns
    ``False``).
    """
    entailing_graph = _make_entailing_graph()

    # Antwerp path Ghent is NOT a fact and cannot be derived (no
    # chain from any known fact to this combination).
    assert not bool(
        entailing_graph.query("ASK { first:Antwerp first:path first:Ghent }")
    )


def test_sparql_interlocution_select_open():
    """
    A SELECT query with a variable in the object position must still
    return binding dicts (not bools).
    """
    entailing_graph = _make_entailing_graph()
    answers = list(
        entailing_graph.query("SELECT ?city WHERE { first:Ghent first:path ?city }")
    )
    assert len(answers) > 0, "Expected at least one answer for Ghent path ?city"


# ---------------------------------------------------------------------------
# sparql_interlocution_basic_graph_pattern (SELECT BGP + proof) API
#
# These tests pin the planned contract for the augmenting BGP bridge.  They
# exercise the conjunctive-join path (batch_unify) and the proof-capture hook,
# neither of which the standard query() path provides.
# ---------------------------------------------------------------------------

# Self-join over the transitive ``path`` predicate.  With EDB facts
# (Ghent->Antwerp, Antwerp->Amsterdam) and transitivity, the only consistent
# join solution is (mid=Antwerp, dest=Amsterdam): Ghent path Antwerp (base)
# joined with Antwerp path Amsterdam (base).  This requires threading the
# ?mid binding from the first pattern into the second -- the behavior that
# distinguishes batch_unify from solve_triple_pattern's flat accumulation.
MIXED_JOIN_QUERY = (
    "SELECT ?mid ?dest WHERE { first:Ghent first:path ?mid . ?mid first:path ?dest . }"
)

SELECT_DERIVED_QUERY = "SELECT ?city WHERE { first:Ghent first:path ?city }"


def test_bgp_select_returns_sparql_result():
    """A SELECT query returns an rdflib ``SPARQLResult`` (drop-in with query())."""
    store = _make_entailing_graph().store

    result = sparql_interlocution_basic_graph_pattern(SELECT_DERIVED_QUERY, store)

    assert isinstance(result, SPARQLResult)
    assert result.type == "SELECT"
    assert Variable("city") in result.vars


def test_bgp_select_projects_only_requested_variables():
    """SELECT bindings are projected onto the query's projection variables."""
    store = _make_entailing_graph().store

    result = sparql_interlocution_basic_graph_pattern(SELECT_DERIVED_QUERY, store)

    assert set(result.vars) == {Variable("city")}
    assert len(result.bindings) > 0
    for binding in result.bindings:
        assert set(binding).issubset({Variable("city")})


def test_bgp_select_returns_derived_solution():
    """The transitively-derived city (Amsterdam) appears among the answers."""
    store = _make_entailing_graph().store

    result = sparql_interlocution_basic_graph_pattern(SELECT_DERIVED_QUERY, store)
    cities = {row["city"] for row in result}

    assert FIRST.Amsterdam in cities, (
        "Expected the transitively-derived 'Amsterdam' binding for Ghent path ?city"
    )


def test_bgp_mixed_idb_edb_join():
    """A self-join over a hybrid predicate threads bindings across patterns."""
    store = _make_entailing_graph().store

    result = sparql_interlocution_basic_graph_pattern(MIXED_JOIN_QUERY, store)
    pairs = {(row["mid"], row["dest"]) for row in result}

    assert (FIRST.Antwerp, FIRST.Amsterdam) in pairs, (
        "Expected the joined solution (mid=Antwerp, dest=Amsterdam)"
    )
    # Every returned row must bind both projected variables (no partial rows).
    for binding in result.bindings:
        assert Variable("mid") in binding
        assert Variable("dest") in binding


def test_bgp_ask_raises_not_implemented():
    """ASK queries are out of scope and must raise ``NotImplementedError``."""
    store = _make_entailing_graph().store

    with pytest.raises(NotImplementedError):
        sparql_interlocution_basic_graph_pattern(ASK_QUERY, store)


def test_bgp_generate_proofs_returns_result_and_proofs():
    """``generate_proofs=True`` returns a (SPARQLResult, proofs-dict) tuple."""
    store = _make_entailing_graph().store

    returned = sparql_interlocution_basic_graph_pattern(
        SELECT_DERIVED_QUERY, store, generate_proofs=True
    )

    assert isinstance(returned, tuple)
    assert len(returned) == 2
    result, proofs = returned
    assert isinstance(result, SPARQLResult)
    assert isinstance(proofs, dict)


def test_bgp_generate_proofs_captures_derived_goal():
    """Proofs include an entry for the transitively-derived ground goal."""
    from fuxi.Horn.PositiveConditions import build_uniterm_from_tuple
    from fuxi.Rete.SidewaysInformationPassing import get_op

    store = _make_entailing_graph().store

    _result, proof_info = sparql_interlocution_basic_graph_pattern(
        SELECT_DERIVED_QUERY, store, generate_proofs=True
    )

    derived_goal = (FIRST.Ghent, FIRST.path_derived, FIRST.Amsterdam)
    assert derived_goal[1] in store.derived_predicates
    assert derived_goal in proof_info, (
        "Expected a captured proof for the derived goal (Ghent path Amsterdam)"
    )

    assert len(proof_info) > 1
    truth_maintainance_graph, adorned_program, meta_interp_network, inferred_facts = proof_info[derived_goal]