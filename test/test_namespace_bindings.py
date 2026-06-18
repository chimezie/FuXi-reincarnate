"""
Test: namespace bindings propagate through to adorned programs in
``goal_rule_sip_info``.

The ``ns_map`` passed to
:meth:`SPARQLPredicatePartitioner.create_entailing_store` should flow into:

1. The **goal literal** (``Uniterm``) stored for each goal key.
2. The **adorned program rules** (``AdornedRule``) stored for each goal key.

When the bindings are missing, rdflib auto-generates placeholder prefixes
(``ns1``, ``ns2``, …) or falls back to full URIs in ``repr()`` output.

See ``lib/fuxi/Rete/Magic.py`` — :func:`normalize_goals` and
:class:`AdornedUniTerm` — and ``lib/fuxi/Horn/PositiveConditions.py`` —
:class:`QNameManager` — for the root causes.
"""

from __future__ import annotations

from io import StringIO

from fuxi.Horn.HornRules import horn_from_n3
from fuxi.predicates import SPARQLPredicatePartitioner
from fuxi.Rete.Magic import AdornedUniTerm
from rdflib import RDF, Graph, Namespace, Variable

# ---------------------------------------------------------------------------
# Namespace & data constants
# ---------------------------------------------------------------------------

EX = Namespace("http://example.org/")

NS_BINDINGS: dict[str, Namespace] = {
    "ex": EX,
    "rdf": RDF,
}

RULES_N3 = """\
@prefix ex: <http://example.org/>.
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>.
{ ?x ex:parentOf ?y } => { ?x ex:ancestorOf ?y }.
"""

FACTS_N3 = """\
@prefix ex: <http://example.org/>.
ex:alice ex:parentOf ex:bob .
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entailing_store():
    """Build a configured entailing graph ready for queries."""
    fact_graph = Graph().parse(StringIO(FACTS_N3), format="n3")
    rules = list(horn_from_n3(StringIO(RULES_N3)))

    partitioner = SPARQLPredicatePartitioner(
        fact_graph=fact_graph,
        rules=rules,
        edb_predicates=[EX.parentOf],
        derived_predicates=[EX.ancestorOf],
    )
    return partitioner.create_entailing_store(ns_map=NS_BINDINGS)


def _trigger_adornment(entailing_graph):
    """
    Issue a query against a derived predicate so that
    :meth:`TopDownSPARQLEntailingStore.batch_unify` runs the
    adornment pipeline and populates ``goal_rule_sip_info``.

    ``batch_unify`` expects 4-tuple patterns ``(s, p, o, graph)``.
    """
    store = entailing_graph.store
    x, y = Variable("x"), Variable("y")
    list(store.batch_unify([(x, EX.ancestorOf, y, None)]))


def _all_terminal_ns_managers(adorned_program):
    """
    Yield every :class:`~rdflib.namespace.NamespaceManager` reachable inside
    the adorned-program rules.
    """
    for rule in adorned_program:
        yield rule.formula.head.ns_manager
        if rule.formula.body:
            for lit in rule.formula.body:
                if hasattr(lit, "ns_manager"):
                    yield lit.ns_manager


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGoalLiteralNamespaceBindings:
    """The goal literal stored in ``goal_rule_sip_info`` should use ``ex:``."""

    def test_all_goals_in_goal_rule_sip_info(self):
        """Every goal entry should have proper namespace prefixes."""
        entailing_graph = _make_entailing_store()
        _trigger_adornment(entailing_graph)

        store = entailing_graph.store
        assert store.goal_rule_sip_info, (
            "Expected at least one entry in goal_rule_sip_info after query"
        )

        for goal_triple, (goal_lit, *_) in store.goal_rule_sip_info.items():
            goal_repr = repr(goal_lit)
            assert "ex:" in goal_repr, (
                f"Goal literal repr {goal_repr!r} should include 'ex:' prefix; "
                f"goal_triple={goal_triple}"
            )
            assert "ns1" not in goal_repr, (
                f"Goal literal repr {goal_repr!r} should not contain "
                f"auto-generated 'ns1' prefix; goal_triple={goal_triple}"
            )
            assert "http://example.org/" not in goal_repr, (
                f"Goal literal repr {goal_repr!r} should not contain full URIs; "
                f"goal_triple={goal_triple}"
            )

    def test_goal_lit_has_ex_prefix_in_repr(self):
        """repr(goal_lit) should contain 'ex:' for the custom namespace."""
        entailing_graph = _make_entailing_store()
        _trigger_adornment(entailing_graph)

        store = entailing_graph.store
        for goal_triple, (goal_lit, *_) in store.goal_rule_sip_info.items():
            goal_repr = repr(goal_lit)
            assert "ex:" in goal_repr, (
                f"Expected 'ex:' in goal literal repr {goal_repr!r}; "
                f"goal_triple={goal_triple}"
            )

    def test_goal_lit_no_ns1_prefix_in_repr(self):
        """repr(goal_lit) should NOT contain auto-generated 'ns1'."""
        entailing_graph = _make_entailing_store()
        _trigger_adornment(entailing_graph)

        store = entailing_graph.store
        for goal_triple, (goal_lit, *_) in store.goal_rule_sip_info.items():
            goal_repr = repr(goal_lit)
            assert "ns1" not in goal_repr, (
                f"Unexpected 'ns1' in goal literal repr {goal_repr!r}; "
                f"goal_triple={goal_triple}"
            )

    def test_goal_lit_no_full_uri_in_repr(self):
        """repr(goal_lit) should NOT contain the full example.org URI."""
        entailing_graph = _make_entailing_store()
        _trigger_adornment(entailing_graph)

        store = entailing_graph.store
        for goal_triple, (goal_lit, *_) in store.goal_rule_sip_info.items():
            goal_repr = repr(goal_lit)
            assert "http://example.org/" not in goal_repr, (
                f"Unexpected full URI in goal literal repr {goal_repr!r}; "
                f"goal_triple={goal_triple}"
            )


class TestAdornedProgramNamespaceBindings:
    """The adorned-program rules in ``goal_rule_sip_info`` should use ``ex:``."""

    def test_all_adorned_rules_have_ex_prefix(self):
        """Every AdornedRule repr should use 'ex:' not raw URIs or 'ns1'."""
        entailing_graph = _make_entailing_store()
        _trigger_adornment(entailing_graph)

        store = entailing_graph.store
        for goal_triple, (_, adorned_program, *_) in store.goal_rule_sip_info.items():
            for program in adorned_program:
                rule_repr = repr(program)
                assert "ex:" in rule_repr, (
                    f"Adorned rule repr {rule_repr!r} should include "
                    f"'ex:' prefix; goal_triple={goal_triple}"
                )
                assert "ns1" not in rule_repr, (
                    f"Adorned rule repr {rule_repr!r} should not contain "
                    f"auto-generated 'ns1' prefix; goal_triple={goal_triple}"
                )
                assert "http://example.org/" not in rule_repr, (
                    f"Adorned rule repr {rule_repr!r} should not contain "
                    f"full URIs; goal_triple={goal_triple}"
                )

    def test_adorned_head_has_ex_prefix(self):
        """The head of each adorned rule should show 'ex:..._bf'."""
        entailing_graph = _make_entailing_store()
        _trigger_adornment(entailing_graph)

        store = entailing_graph.store
        for _, (_, adorned_program, *_) in store.goal_rule_sip_info.items():
            for program in adorned_program:
                head_repr = repr(program.formula.head)
                assert "ex:ancestorOf_bf" in head_repr or "ex:" in head_repr, (
                    f"Expected 'ex:' in head repr {head_repr!r}"
                )

    def test_adorned_body_has_ex_prefix(self):
        """The body atoms of each adorned rule should show 'ex:..._ff'."""
        entailing_graph = _make_entailing_store()
        _trigger_adornment(entailing_graph)

        store = entailing_graph.store
        for _, (_, adorned_program, *_) in store.goal_rule_sip_info.items():
            for program in adorned_program:
                body = program.formula.body
                if body:
                    body_repr = repr(body)
                    assert "ex:" in body_repr, (
                        f"Expected 'ex:' in body repr {body_repr!r}"
                    )


class TestQNameManagerBindsProvidedNamespaces:
    """The QNameManager/ns_manager behind the scenes should hold the bindings."""

    def test_goal_lit_ns_manager_has_ex_binding(self):
        """The goal literal's ns_manager should have 'ex' -> http://example.org/."""
        entailing_graph = _make_entailing_store()
        _trigger_adornment(entailing_graph)

        store = entailing_graph.store
        for _, (goal_lit, *_) in store.goal_rule_sip_info.items():
            ns_manager = goal_lit.ns_manager
            prefixes = dict(ns_manager.namespaces())
            assert "ex" in prefixes, (
                f"ns_manager should have prefix 'ex'; "
                f"found prefixes: {list(prefixes.keys())}"
            )
            assert str(prefixes["ex"]) == str(EX), (
                f"ns_manager['ex'] should map to {EX}; "
                f"got {prefixes['ex']}"
            )

    def test_adorned_term_ns_manager_has_ex_binding(self):
        """Each AdornedUniTerm's ns_manager should have 'ex' bound."""
        entailing_graph = _make_entailing_store()
        _trigger_adornment(entailing_graph)

        store = entailing_graph.store
        for _, (_, adorned_program, *_) in store.goal_rule_sip_info.items():
            for ns_mgr in _all_terminal_ns_managers(adorned_program):
                prefixes = dict(ns_mgr.namespaces())
                assert "ex" in prefixes, (
                    f"AdornedUniTerm ns_manager should have prefix 'ex'; "
                    f"found prefixes: {list(prefixes.keys())}"
                )
                assert str(prefixes["ex"]) == str(EX), (
                    f"ns_manager['ex'] should map to {EX}; "
                    f"got {prefixes['ex']}"
                )

    def test_goal_lit_belongs_to_uniterm_class(self):
        """Goal literal should be a Uniterm (or AdornedUniTerm) with ns_manager."""
        entailing_graph = _make_entailing_store()
        _trigger_adornment(entailing_graph)

        store = entailing_graph.store
        for _, (goal_lit, *_) in store.goal_rule_sip_info.items():
            assert hasattr(goal_lit, "ns_manager"), (
                "Goal literal should have an ns_manager attribute"
            )

    def test_adorned_head_is_adorned_uniterm(self):
        """The head of each adorned rule should be an AdornedUniTerm."""
        entailing_graph = _make_entailing_store()
        _trigger_adornment(entailing_graph)

        store = entailing_graph.store
        for _, (_, adorned_program, *_) in store.goal_rule_sip_info.items():
            for rule in adorned_program:
                assert isinstance(rule.formula.head, AdornedUniTerm), (
                    "Adorned rule head should be an AdornedUniTerm"
                )


class TestMultiplePredicateTypes:
    """Verify namespace prefixes work for both rdf:type and non-rdf:type."""

    RDF_TYPE_RULES_N3 = """\
@prefix ex: <http://example.org/>.
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>.
@prefix owl: <http://www.w3.org/2002/07/owl#>.
{ ?x a ex:Parent } => { ?x a ex:Ancestor }.
"""

    RDF_TYPE_FACTS_N3 = """\
@prefix ex: <http://example.org/>.
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>.
ex:alice a ex:Parent .
"""

    def test_rdf_type_derived_predicate(self):
        """
        Derived predicate via rdf:type (class-based) should also use
        proper namespace prefixes after adornment.
        """
        fact_graph = Graph().parse(
            StringIO(self.RDF_TYPE_FACTS_N3), format="n3"
        )
        rules = list(
            horn_from_n3(StringIO(self.RDF_TYPE_RULES_N3))
        )

        partitioner = SPARQLPredicatePartitioner(
            fact_graph=fact_graph,
            rules=rules,
            edb_predicates=[EX.Parent],
            derived_predicates=[EX.Ancestor],
        )
        entailing_graph = partitioner.create_entailing_store(ns_map=NS_BINDINGS)
        store = entailing_graph.store

        # Trigger adornment via batch_unify for the rdf:type derived predicate.
        x = Variable("x")
        list(store.batch_unify([(x, RDF.type, EX.Ancestor, None)]))

        assert store.goal_rule_sip_info, (
            "Expected goal_rule_sip_info entries after rdf:type batch_unify"
        )
        for _, (goal_lit, adorned_program, *_) in store.goal_rule_sip_info.items():
            goal_repr = repr(goal_lit)
            assert "ex:" in goal_repr, (
                f"Goal repr {goal_repr!r} should contain 'ex:' for "
                f"rdf:type derived predicate; "
                f"ns_manager prefixes={dict(goal_lit.ns_manager.namespaces())}"
            )

            for program in adorned_program:
                rule_repr = repr(program)
                assert "ex:" in rule_repr, (
                    f"Rule repr {rule_repr!r} should contain 'ex:' for "
                    f"rdf:type adorned rule"
                )


class TestStoreDoesNotContainNsPrefixes:
    """
    Negative test: without ns_bindings the repr should contain auto-generated
    prefixes or full URIs (confirming the test infrastructure is sensitive).
    """

    def test_no_ns_bindings_goal_has_no_ex_prefix(self):
        """When ns_map is omitted, goal repr should NOT contain 'ex:'."""
        fact_graph = Graph().parse(StringIO(FACTS_N3), format="n3")
        rules = list(horn_from_n3(StringIO(RULES_N3)))

        partitioner = SPARQLPredicatePartitioner(
            fact_graph=fact_graph,
            rules=rules,
            edb_predicates=[EX.parentOf],
            derived_predicates=[EX.ancestorOf],
        )
        # NOTE: no ns_map passed here
        entailing_graph = partitioner.create_entailing_store(ns_map=None)
        _trigger_adornment(entailing_graph)

        store = entailing_graph.store
        for _, (goal_lit, *_) in store.goal_rule_sip_info.items():
            goal_repr = repr(goal_lit)
            assert "ex:" not in goal_repr, (
                f"Without ns_map, goal repr should not contain 'ex:'; "
                f"got {goal_repr!r}"
            )

    def test_no_ns_bindings_head_no_full_uri(self):
        """
        When ns_map is omitted, the adorned rule HEAD should still
        resolve to a prefix (original rule's binding or auto-generated),
        never a full raw URI.
        """
        fact_graph = Graph().parse(StringIO(FACTS_N3), format="n3")
        rules = list(horn_from_n3(StringIO(RULES_N3)))

        partitioner = SPARQLPredicatePartitioner(
            fact_graph=fact_graph,
            rules=rules,
            edb_predicates=[EX.parentOf],
            derived_predicates=[EX.ancestorOf],
        )
        entailing_graph = partitioner.create_entailing_store(ns_map=None)
        _trigger_adornment(entailing_graph)

        store = entailing_graph.store
        for _, (_, adorned_program, *_) in store.goal_rule_sip_info.items():
            for program in adorned_program:
                head_repr = repr(program.formula.head)
                assert "http://example.org/" not in head_repr, (
                    f"Without ns_map, head repr should not contain full URIs; "
                    f"got {head_repr!r}"
                )


# ---------------------------------------------------------------------------
# Smoke / integration tests
# ---------------------------------------------------------------------------


class TestRoundtripQuery:
    """The entailing store should still return correct query results."""

    def test_derived_predicate_is_inferred(self):
        """
        Querying for ex:ancestorOf via batch_unify should infer
        from ex:parentOf facts and return correct variable bindings.
        """
        entailing_graph = _make_entailing_store()
        store = entailing_graph.store

        x, y = Variable("x"), Variable("y")
        results = list(
            store.batch_unify([(x, EX.ancestorOf, y, None)])
        )

        assert len(results) > 0, "Should have inferred at least one binding"
        found = {(str(r[x]), str(r[y])) for r in results if x in r and y in r}
        expected_pair = (str(EX.alice), str(EX.bob))
        assert expected_pair in found, (
            f"Expected binding {expected_pair!r} to be inferred; "
            f"found bindings: {found}"
        )

    def test_base_predicate_is_available(self):
        """Base (EDB) predicates should still be queryable through the store."""
        entailing_graph = _make_entailing_store()
        store = entailing_graph.store

        # Use batch_unify for an EDB-only predicate.
        x, y = Variable("x"), Variable("y")
        results = list(
            store.batch_unify([(x, EX.parentOf, y, None)])
        )

        assert len(results) > 0, "Should have base facts"
