"""
Tests for the sparql_interlocution function.

sparql_interlocution is the query-evaluation bridge between the CLI
and the TopDownSPARQLEntailingStore.  It must correctly handle
ground ASK queries that the BFP solver proves.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fuxi.cli.shared import _compute_derived_predicates, _extract_goals
from fuxi.DLP.DLNormalization import normal_form_reduction
from fuxi.Horn.HornRules import Ruleset
from fuxi.Rete.RuleStore import setup_rule_store
from fuxi.SPARQL.utilities import (
    owl_entailment_regime_graph,
    sparql_interlocution,
)
from rdflib import Graph, Namespace

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
        add_non_dhl_owl_rules=True,
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
    top_down_store = entailing_graph.store

    answers = list(sparql_interlocution(ASK_QUERY, top_down_store))

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
    top_down_store = entailing_graph.store

    # Antwerp path Ghent is NOT a fact and cannot be derived (no
    # chain from any known fact to this combination).
    query = "ASK { first:Antwerp first:path first:Ghent }"
    answers = list(sparql_interlocution(query, top_down_store))

    assert len(answers) == 0, "Expected no answers for an unprovable ground goal"


def test_sparql_interlocution_select_open():
    """
    A SELECT query with a variable in the object position must still
    return binding dicts (not bools).
    """
    entailing_graph = _make_entailing_graph()
    top_down_store = entailing_graph.store

    query = "SELECT ?city WHERE { first:Ghent first:path ?city }"
    answers = list(sparql_interlocution(query, top_down_store))

    assert len(answers) > 0, "Expected at least one answer for Ghent path ?city"
    for answer in answers:
        assert isinstance(answer, dict), f"Expected dict, got {type(answer).__name__}"
