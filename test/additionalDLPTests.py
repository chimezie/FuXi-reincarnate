"""
Tests for additional Description Logic Programming (DLP) functionality.

These tests verify:
- GCI (General Concept Inclusion) with disjunctions
- Base predicate equivalence
- Existential restrictions in GCI
- Value restrictions in GCI
- Nested conjunctions
- Complex OWL class expressions
"""

import pytest
from rdflib.util import first

from fuxi.DLP import SKOLEMIZED_CLASS_NS
from fuxi.Rete.RuleStore import setup_rule_store
from fuxi.Syntax.InfixOWL import (
    OWL_NS,
    Class,
    ClassNamespaceFactory,
    EnumeratedClass,
    Individual,
    Property,
    some,
    value,
)
from rdflib import Graph, Namespace


@pytest.fixture
def ex_ns():
    """Provide example namespace."""
    return Namespace("http://example.com/")


@pytest.fixture
def ex_factory(ex_ns):
    """Provide ClassNamespaceFactory for example namespace."""
    return ClassNamespaceFactory(ex_ns)


@pytest.fixture
def ontology_graph(ex_ns):
    """Provide empty ontology graph with bound prefixes."""
    graph = Graph()
    graph.bind("ex", ex_ns)
    graph.bind("owl", OWL_NS)
    Individual.factoryGraph = graph
    return graph


class TestGCIWithDisjunction:
    """Tests for General Concept Inclusion (GCI) with disjunctions."""

    def test_gci_con_disjunction(self, ontology_graph, ex_ns, ex_factory):
        """Test GCI with conjunction and disjunction produces correct rules."""
        conjunct = ex_factory.Foo & (ex_factory.Omega | ex_factory.Alpha)
        ex_factory.Bar += conjunct

        _rule_store, _rule_graph, network = setup_rule_store(make_network=True)
        rules = network.setup_description_logic_programming(
            ontology_graph,
            add_pd_semantics=False,
            construct_network=False,
            derived_preds=[ex_ns.Bar]
        )

        assert len(rules) == 2, f"Expected 2 rules, got {len(rules)}"
        rules_repr = repr(rules)
        assert "ex:Bar(?X)" in rules_repr
        assert "ex:Foo(?X)" in rules_repr
        assert "ex:Alpha(?X)" in rules_repr
        assert "ex:Omega(?X)" in rules_repr


class TestBasePredicateEquivalence:
    """Tests for base predicate equivalence."""

    def test_base_predicate_equivalence(self, ontology_graph, ex_ns, ex_factory):
        """Test that equivalent classes produce bidirectional rules."""
        ex_factory.Foo.equivalent_class = [ex_factory.Bar]

        class_repr = repr(Class(ex_ns.Foo))
        assert "Class: ex:Foo" in class_repr
        assert "EquivalentTo: ex:Bar" in class_repr

        _rule_store, _rule_graph, network = setup_rule_store(make_network=True)
        rules = network.setup_description_logic_programming(
            ontology_graph,
            add_pd_semantics=False,
            construct_network=False
        )

        assert len(rules) == 2, f"Expected 2 rules, got {len(rules)}"
        rules_repr = repr(rules)
        assert "ex:Foo(?X)" in rules_repr
        assert "ex:Bar(?X)" in rules_repr


class TestExistentialRestrictions:
    """Tests for existential restrictions in GCI."""

    def test_existential_in_right_of_gci(self, ontology_graph, ex_ns, ex_factory):
        """Test existential restriction on right side of GCI."""
        some_prop = Property(ex_ns.someProp)
        existential = some_prop | some | ex_factory.Omega
        existential += ex_factory.Foo

        class_repr = repr(Class(ex_ns.Foo))
        assert "Class: ex:Foo" in class_repr
        assert "SubClassOf" in class_repr
        assert "ex:someProp" in class_repr
        assert "SOME" in class_repr
        assert "ex:Omega" in class_repr

    def test_value_restriction_in_left_of_gci(self, ontology_graph, ex_ns, ex_factory):
        """Test value restriction on left side of GCI."""
        some_prop = Property(ex_ns.someProp)
        left_gci = (some_prop | value | ex_ns.fish) & ex_factory.Bar
        foo = ex_factory.Foo
        foo += left_gci

        left_gci_repr = repr(left_gci)
        assert "ex:Bar" in left_gci_repr
        assert "ex:someProp" in left_gci_repr
        assert "VALUE" in left_gci_repr
        assert "ex:fish" in left_gci_repr

        _rule_store, _rule_graph, network = setup_rule_store(make_network=True)
        rules = network.setup_description_logic_programming(
            ontology_graph,
            add_pd_semantics=False,
            construct_network=False
        )

        assert len(rules) == 1, f"Expected 1 rule, got {len(rules)}"
        rules_repr = repr(rules)
        assert "ex:Foo(?X)" in rules_repr
        assert "ex:someProp" in rules_repr
        assert "ex:Bar(?X)" in rules_repr


class TestNestedConjunctions:
    """Tests for nested conjunction handling."""

    def test_nested_conjunct(self, ontology_graph, ex_ns, ex_factory):
        """Test nested conjunctions produce correct skolemized rules."""
        nested_conj = (ex_factory.Foo & ex_factory.Bar) & ex_factory.Baz
        ex_factory.Omega += nested_conj

        _rule_store, _rule_graph, network = setup_rule_store(
            make_network=True
        )
        rules = network.setup_description_logic_programming(
            ontology_graph,
            add_pd_semantics=False,
            construct_network=False
        )

        omega_rules = [r for r in rules
                       if r.formula.head.arg[-1] == ex_ns.Omega]
        assert len(omega_rules) == 1, (f"Expected 1 rule for Omega, "
                                       f"got {len(omega_rules)}")

        omega_rule = omega_rules[0]
        assert len(
            omega_rule.formula.body) == 2, "Body should have 2 elements"

        skolem_predicates = [
            term.arg[-1]
            for term in omega_rule.formula.body
            if term.arg[-1].find(SKOLEMIZED_CLASS_NS) != -1
        ]
        assert len(skolem_predicates) == 1, "Couldn't find skolem unary predicate"


class TestComplexClassExpressions:
    """Tests for complex OWL class expressions."""

    def test_other_form_complex_expression(self,
                                           ontology_graph,
                                           ex_ns,
                                           ex_factory):
        """Test complex class expression with multiple existentials."""
        contains = Property(ex_ns.contains)
        located_in = Property(ex_ns.locatedIn)

        top_conjunct = (
            ex_factory.Cath
            & (contains | some | (ex_factory.MajorStenosis &
                                  (located_in | value | ex_ns.LAD)))
            & (contains | some | (ex_factory.MajorStenosis &
                                  (located_in | value | ex_ns.RCA)))
        )
        ex_factory.NumDisV2D += top_conjunct

        from fuxi.DLP.DLNormalization import normal_form_reduction
        normal_form_reduction(ontology_graph)

        _rule_store, _rule_graph, network = setup_rule_store(
            make_network=True
        )
        rules = network.setup_description_logic_programming(
            ontology_graph,
            add_pd_semantics=False,
            construct_network=False,
            derived_preds=[ex_ns.NumDisV2D]
        )

        assert len(rules) > 0, "Should produce at least one rule"

        from fuxi.Rete.Magic import pretty_print_rule
        for rule in rules:
            pretty_print_rule(rule)

    def test_enumerated_class_in_existential(self,
                                             ontology_graph,
                                             ex_ns,
                                             ex_factory):
        """Test enumerated class used within existential restriction."""
        has_coronary_bypass_conduit = Property(ex_ns.hasCoronaryBypassConduit)

        ita_left = ex_factory.ITALeft
        members = EnumeratedClass(members=[
            ex_ns.CoronaryBypassConduit_internal_thoracic_artery_left_insitu,
            ex_ns.CoronaryBypassConduit_internal_thoracic_artery_left_free])
        ita_left += has_coronary_bypass_conduit | some | members

        from fuxi.DLP.DLNormalization import normal_form_reduction

        initial_repr = repr(Class(first(ita_left.sub_sumptee_ids())))
        assert "Some Class" in initial_repr
        assert "SubClassOf" in initial_repr
        assert "ex:ITALeft" in initial_repr

        normal_form_reduction(ontology_graph)

        final_repr = repr(Class(first(ita_left.sub_sumptee_ids())))
        assert "Some Class" in final_repr
        assert "SubClassOf" in final_repr
        assert "ex:ITALeft" in final_repr
        assert "EquivalentTo" in final_repr
        assert "VALUE" in final_repr


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
