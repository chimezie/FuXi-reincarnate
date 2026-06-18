"""
Tests for the InfixOWL API.

These tests verify that InfixOWL class constructors and helpers work correctly.
"""

import pytest

from fuxi.Syntax.InfixOWL import (
    OWL_NS,
    Class,
    GraphContext,
    Individual,
    Property,
    Restriction,
)
from rdflib import Graph, Literal, Namespace


@pytest.fixture
def graph():
    """Provide a clean graph for each test."""
    return Graph()


@pytest.fixture
def ex():
    """Provide example namespace."""
    return Namespace("http://example.org/")


class TestInfixOWLAPI:
    """Tests for InfixOWL API functionality."""

    def test_graph_context_sets_factory_graph(self, graph, ex):
        """Test that GraphContext updates Individual.factoryGraph."""
        previous = Individual.factoryGraph
        with GraphContext(graph, {"ex": ex}):
            assert Individual.factoryGraph is graph
            prefixes = dict(graph.namespace_manager.namespaces())
            assert "ex" in prefixes
        assert Individual.factoryGraph is previous

    def test_namespace_prop_helper(self, graph, ex):
        """Test Property helper creates correct property."""
        prop = ex.prop("hasChild", graph=graph)
        assert isinstance(prop, Property)
        assert prop.identifier == ex["hasChild"]
        assert prop.graph is graph

    def test_property_restriction_helpers(self, graph, ex):
        """Test all property restriction helpers."""
        person = Class(ex.Person, graph=graph)
        prop = Property(ex.hasChild, graph=graph)

        some_restr = prop.some(person)
        assert isinstance(some_restr, Restriction)
        assert some_restr.on_property == prop.identifier
        assert some_restr.restrictionType == OWL_NS.someValuesFrom

        only_restr = prop.only(person)
        assert only_restr.restrictionType == OWL_NS.allValuesFrom

        value_restr = prop.value(ex.Jane)
        assert value_restr.restrictionType == OWL_NS.hasValue

        min_restr = prop.min(Literal(1))
        assert min_restr.restrictionType == OWL_NS.minCardinality

        max_restr = prop.max(Literal(2))
        assert max_restr.restrictionType == OWL_NS.maxCardinality

        exact_restr = prop.exactly(Literal(3))
        assert exact_restr.restrictionType == OWL_NS.cardinality

        min_restr = prop.cardinality >= 1
        assert min_restr.restrictionType == OWL_NS.minCardinality

        max_restr = prop.cardinality <= 2
        assert max_restr.restrictionType == OWL_NS.maxCardinality

        exact_restr = prop.cardinality == 4
        assert exact_restr.restrictionType == OWL_NS.cardinality

        qualified_min = prop.cardinality(person) >= 2
        assert qualified_min.restrictionType == OWL_NS.minQualifiedCardinality
        assert (qualified_min.identifier, OWL_NS.onClass, person.identifier) in graph

        qualified_max = prop.cardinality(person) <= 3
        assert qualified_max.restrictionType == OWL_NS.maxQualifiedCardinality
        assert (qualified_max.identifier, OWL_NS.onClass, person.identifier) in graph

        qualified_exact = prop.cardinality(person) == 1
        assert qualified_exact.restrictionType == OWL_NS.qualifiedCardinality
        assert (qualified_exact.identifier, OWL_NS.onClass, person.identifier) in graph

        helper_min = prop.min_cardinality(2, person)
        assert helper_min.restrictionType == OWL_NS.minQualifiedCardinality
        assert (helper_min.identifier, OWL_NS.onClass, person.identifier) in graph

        helper_max = prop.max_cardinality(3, person)
        assert helper_max.restrictionType == OWL_NS.maxQualifiedCardinality
        assert (helper_max.identifier, OWL_NS.onClass, person.identifier) in graph

    def test_graph_context_uses_factory_graph(self, graph, ex):
        """Test that GraphContext uses factory graph for class creation."""
        other_graph = Graph()
        with GraphContext(other_graph, {"ex": ex}):
            person = Class(ex.Person)
            prop = Property(ex.hasChild)
            restr = Restriction(prop, some_values_from=person)

        assert person.graph is other_graph
        assert prop.graph is other_graph
        assert restr.graph is other_graph

    def test_camel_case_attributes_are_absent(self, graph, ex):
        """Test that camelCase attributes raise AttributeError."""
        person = Class(ex.Person, graph=graph)
        prop = Property(ex.hasChild, graph=graph)
        restr = Restriction(prop, graph=graph, some_values_from=person)

        with pytest.raises(AttributeError):
            _ = person.subClassOf
        with pytest.raises(AttributeError):
            _ = person.equivalentClass
        with pytest.raises(AttributeError):
            _ = person.disjointWith
        with pytest.raises(AttributeError):
            _ = person.complementOf

        with pytest.raises(AttributeError):
            _ = prop.subPropertyOf
        with pytest.raises(AttributeError):
            _ = prop.inverseOf

        with pytest.raises(AttributeError):
            _ = restr.onProperty
        with pytest.raises(AttributeError):
            _ = restr.someValuesFrom
        with pytest.raises(AttributeError):
            _ = restr.allValuesFrom
        with pytest.raises(AttributeError):
            _ = restr.hasValue
        with pytest.raises(AttributeError):
            _ = restr.maxCardinality
        with pytest.raises(AttributeError):
            _ = restr.minCardinality

        with pytest.raises(AttributeError):
            _ = person.seeAlso


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
