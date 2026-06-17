"""
Regression test: :meth:`TopDownSPARQLEntailingStore.batch_unify` does not route
``(?x, rdf:type, EX.Parent)`` through backchaining when ``rdf:type`` is in
``derived_predicates``.

Bug
---
:file:`lib/fuxi/SPARQL/BackwardChainingStore.py`, lines 786–790::

    d_pred = o if p == RDF.type else p            # line 786
    if d_pred in self.hybrid_predicates:
        d_preds.add(URIRef(d_pred + "_derived"))
    else:
        d_preds.add(p == RDF.type and o or p)     # line 790

For a triple ``(?x, rdf:type, EX.Parent)``:

1. Line 786 assigns ``d_pred = EX.Parent`` (the **object**).
2. Line 790 adds ``EX.Parent`` to ``d_preds``.
3. Line 791 checks ``d_preds & self.derived_predicates``.

But ``self.derived_predicates`` contains ``rdf:type`` (the predicate that
appears in rule heads such as ``{ ?x a ex:Parent }``), **not** ``EX.Parent``
(the class name).  The intersection is empty, so the query falls through to
the EDB-only path (line 797) instead of the backchaining path (line 794).

Fix suggestion
--------------
Replace the inline logic at lines 786–790 with a call to
:meth:`derived_predicate_from_triple`, which already correctly handles this
case::

    for s, p, o, g in patterns:
        goals.append((s, p, o))
        d_pred = self.derived_predicate_from_triple((s, p, o))
        if d_pred is not None:
            if p == RDF.type and o in self.hybrid_predicates:
                d_preds.add(URIRef(o + "_derived"))
            elif p in self.hybrid_predicates:
                d_preds.add(URIRef(p + "_derived"))
            else:
                d_preds.add(d_pred)
"""

from unittest.mock import Mock

import pytest

from fuxi.SPARQL.BackwardChainingStore import TopDownSPARQLEntailingStore
from fuxi.SPARQL.service import _SelectResult
from rdflib import RDF, RDFS, Graph, Namespace, URIRef, Variable

EX = Namespace("http://example.org/")


def _make_edb_mock() -> Mock:
    """Build an EDB mock whose ``.query()`` returns empty (no base facts)."""
    edb = Mock(spec=Graph)
    edb.query.return_value = _SelectResult([], [])
    edb.qname = Mock(side_effect=lambda uri: uri.split("/")[-1].lower())
    edb.namespaces.return_value = []
    edb.template_map = {}
    return edb


def _make_store(
    derived_preds: list | None = None,
    hybrid_preds: list | None = None,
    edb: Graph | None = None,
) -> TopDownSPARQLEntailingStore:
    """Build a TopDownSPARQLEntailingStore with mocked dependencies."""
    ns_bindings = {"ex": EX, "rdf": RDF, "rdfs": RDFS}
    return TopDownSPARQLEntailingStore(
        store=Mock(),
        edb=edb or _make_edb_mock(),
        derived_predicates=derived_preds or [],
        hybrid_predicates=hybrid_preds or [],
        ns_bindings=ns_bindings,
    )


# ── tests ─────────────────────────────────────────────────────────────────────


def test_rdf_type_object_pattern_routes_through_backchaining():
    """
    ``batch_unify`` should route ``(?x, rdf:type, EX.Parent)`` through
    backchaining when ``rdf:type`` is a derived predicate.

    Bug: ``d_pred`` is set to ``EX.Parent`` (the class), so the
    ``derived_predicates`` intersection check fails — ``rdf:type`` is in
    ``derived_predicates``, but ``EX.Parent`` is not.
    """
    store = _make_store(derived_preds=[RDF.type])

    # Spy on conjunctive_sip_strategy to detect whether backchaining fires
    sip = Mock(return_value=iter([]))
    store.conjunctive_sip_strategy = sip

    list(
        store.batch_unify(
            [
                (Variable("x"), RDF.type, EX.Parent, None),
            ]
        )
    )

    # BUG: sip.assert_called() FAILS because batch_unify falls to EDB-only path.
    #
    # The intersection check at line 791 is:
    #   d_preds = {EX.Parent}, derived_predicates = {RDF.type}
    #   {EX.Parent} & {RDF.type} => empty => EDB-only path
    #
    # Correct behavior: should call conjunctive_sip_strategy because RDF.type
    # IS in derived_predicates.
    sip.assert_called_once()


def test_non_rdf_type_pattern_routes_through_backchaining():
    """
    For non-``rdf:type`` patterns the routing works correctly — when the
    predicate itself is in ``derived_predicates``, backchaining fires.
    """
    store = _make_store(derived_preds=[EX.parentOf])

    sip = Mock(return_value=iter([]))
    store.conjunctive_sip_strategy = sip

    list(
        store.batch_unify(
            [
                (Variable("x"), EX.parentOf, Variable("y"), None),
            ]
        )
    )

    sip.assert_called_once()


def test_rdf_type_pattern_with_hybrid_class_uses_derived_suffix():
    """
    When the class in an ``rdf:type`` pattern is a hybrid predicate, the
    store should look for the ``_derived`` variant in ``derived_predicates``.
    """
    store = _make_store(
        derived_preds=[URIRef(str(EX.Parent) + "_derived")],
        hybrid_preds=[EX.Parent],
    )

    sip = Mock(return_value=iter([]))
    store.conjunctive_sip_strategy = sip

    list(
        store.batch_unify(
            [
                (Variable("x"), RDF.type, EX.Parent, None),
            ]
        )
    )

    sip.assert_called_once()


def test_purely_edb_pattern_does_not_route_through_backchaining():
    """
    Patterns with no derived predicates should stay in the EDB-only path.
    """
    store = _make_store(derived_preds=[RDF.type])

    sip = Mock(return_value=iter([]))
    store.conjunctive_sip_strategy = sip

    list(
        store.batch_unify(
            [
                (Variable("x"), EX.name, Variable("y"), None),
            ]
        )
    )

    sip.assert_not_called()
