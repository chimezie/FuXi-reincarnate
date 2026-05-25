"""
Regression test: :meth:`TopDownSPARQLEntailingStore.batch_unify` returns
incorrectly structured bindings when the EDB ``.query()`` returns
dict-shaped results (as :class:`SPARQLServiceGraph` does) instead of
tuple-shaped results (as a local :class:`~rdflib.Graph` does).

Bug location
------------
:file:`lib/fuxi/SPARQL/BackwardChainingStore.py`, lines 811–815::

    rt = (
        len(vars) > 1
        and (dict([(vars[idx], i) for idx, i in enumerate(v)]) for v in rt)
        or (dict([(vars[0], v)]) for v in rt)
    )

The variable ``rt`` comes from ``self.edb.query(...)``.

**Local ``rdflib.Graph``** — ``Result.__iter__`` yields tuples of terms.
    * single var: ``(URIRef('Alice'),)``  →
      ``{Variable('x'): URIRef('Alice')}``  ✅
    * multi  var: ``(URIRef('Alice'), Literal(30))``  →
      ``{Variable('x'): URIRef('Alice'), Variable('z'): Literal(30)}``  ✅

**``SPARQLServiceGraph``** — ``_SelectResult.__iter__`` yields dicts.
    * single var: ``{'x': URIRef('Alice')}``  →
      ``{Variable('x'): {'x': URIRef('Alice')}}``  ❌  *dict wrapped as value*
    * multi  var: ``{'x': URIRef('Alice'), 'z': Literal(30)}``  →
      ``enumerate(v)`` walks dict *keys*  →
      ``{Variable('x'): 'x', Variable('z'): 'z'}``  ❌

Both bugs produce bindings that do not contain usable RDF terms, so the
caller in :func:`~fuxi.SPARQL.utilities.sparql_interlocution` cannot
extract query results.
"""

from __future__ import annotations

from typing import Any

import pytest

from fuxi.SPARQL.BackwardChainingStore import TopDownSPARQLEntailingStore
from fuxi.SPARQL.service import _SelectResult
from rdflib import RDF, RDFS, Graph, Literal, Namespace, Variable

pytestmark = pytest.mark.integration

EX = Namespace("http://example.org/")


# ── helpers ──────────────────────────────────────────────────────────────────


def _make_edb_mock(*select_results: _SelectResult):
    """Build a Graph mock whose ``.query()`` returns ``select_results[0]``."""
    from unittest.mock import Mock

    edb = Mock(spec=Graph)
    edb.query.return_value = select_results[0]
    edb.qname = Mock(side_effect=lambda uri: uri.split("/")[-1].lower())
    edb.namespaces.return_value = []
    edb.template_map = {}
    return edb


def _make_store(edb, derived_preds: list | None = None) -> TopDownSPARQLEntailingStore:
    """Build a ``TopDownSPARQLEntailingStore`` with a given EDB mock.

    We pass a dummy ``store`` argument (an empty Graph) — the constructor
    uses it only via ``self.dataset = store`` and never calls methods on it.
    """
    from unittest.mock import Mock

    ns_bindings: dict[str, Any] = {
        "ex": EX,
        "rdf": RDF,
        "rdfs": RDFS,
    }
    return TopDownSPARQLEntailingStore(
        store=Mock(),  # not used by batch_unify
        edb=edb,
        derived_predicates=derived_preds or [],
        ns_bindings=ns_bindings,
    )


# ── single-variable patterns ─────────────────────────────────────────────────


def _single_var_bindings() -> list[dict]:
    """Rows that ``_json_to_result`` would produce for ``SELECT ?x``."""
    return [
        {"x": EX.Adam},
        {"x": EX.Eve},
    ]


def _single_var_store() -> TopDownSPARQLEntailingStore:
    return _make_store(_make_edb_mock(_SelectResult(["x"], _single_var_bindings())))


def test_batch_unify_single_var_returns_rdf_term():
    """Single var with SPARQLServiceGraph-style results should yield URIRef values.

    Current (buggy):  {Variable('x'): {'x': URIRef('Adam')}}
    Correct:          {Variable('x'): URIRef('Adam')}
    """
    store = _single_var_store()
    results = list(
        store.batch_unify(
            [
                (Variable("x"), RDF.type, EX.Person, None),
            ]
        )
    )

    assert len(results) == 2
    terms = {results[0][Variable("x")], results[1][Variable("x")]}
    assert terms == {EX.Adam, EX.Eve}, f"Got {terms!r}"


# ── multi-variable patterns ──────────────────────────────────────────────────


def _multi_var_bindings() -> list[dict]:
    return [
        {"x": EX.Alice, "z": Literal(30)},
    ]


def _multi_var_store() -> TopDownSPARQLEntailingStore:
    return _make_store(_make_edb_mock(_SelectResult(["x", "z"], _multi_var_bindings())))


def test_batch_unify_multi_var_returns_rdf_terms():
    """Multi var with SPARQLServiceGraph-style results should yield RDF term values.

    Current (buggy):  {Variable('x'): 'x', Variable('z'): 'z'}
    Correct:          {Variable('x'): URIRef('Alice'), Variable('z'): Literal(30)}
    """
    store = _multi_var_store()
    patterns = [
        (Variable("x"), RDF.type, EX.Person, None),
        (Variable("x"), EX.hasAge, Variable("z"), None),
    ]
    results = list(store.batch_unify(patterns))

    assert len(results) == 1
    r = results[0]
    assert r[Variable("x")] == EX.Alice, (
        f"Got {r[Variable('x')]!r} (bug: dict key instead of term)"
    )
    assert r[Variable("z")] == Literal(30), (
        f"Got {r[Variable('z')]!r} (bug: dict key instead of term)"
    )
