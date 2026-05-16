"""
Tests for the InfixOWL API demonstrating OWL class construction and operations.

These tests verify:
- Class creation and subClassOf relationships
- Boolean class operations (union, intersection)
- Enumerated classes
- Restrictions (allValuesFrom, some, max)
- Manchester OWL syntax infix operators
"""

import pytest
from rdflib.namespace import NamespaceManager

from fuxi.Syntax.InfixOWL import (
    OWL_NS,
    Class,
    EnumeratedClass,
    Property,
    Restriction,
    some,
)
from fuxi.Syntax.InfixOWL import max as max_cardinality
from rdflib import Graph, Literal, Namespace


@pytest.fixture
def ex_ns():
    """Provide example namespace."""
    return Namespace("http://example.com/")


@pytest.fixture
def namespace_manager(ex_ns):
    """Provide configured namespace manager with ex and owl prefixes."""
    nm = NamespaceManager(Graph())
    nm.bind("ex", ex_ns, override=False)
    nm.bind("owl", OWL_NS, override=False)
    return nm


@pytest.fixture
def graph(namespace_manager):
    """Provide empty graph with pre-configured namespace manager."""
    g = Graph()
    g.namespace_manager = namespace_manager
    return g


class TestClassCreation:
    """Tests for basic class creation and subClassOf relationships."""

    def test_class_creation_with_subclassof(self, graph, ex_ns):
        """Test that a class can be created with subClassOf assertion."""
        opera = Class(ex_ns.Opera, graph=graph)
        opera.sub_class_of = [ex_ns.MusicalWork]

        subclasses = list(opera.sub_class_of)
        assert len(subclasses) == 1
        assert subclasses[0].identifier == ex_ns.MusicalWork

    def test_subclassof_representation_format(self, graph, ex_ns):
        """Test that subClassOf is correctly formatted in string representation."""
        opera = Class(ex_ns.Opera, graph=graph)
        opera.sub_class_of = [ex_ns.MusicalWork]

        representation = str(opera)
        assert "Class: ex:Opera" in representation
        assert "SubClassOf: ex:MusicalWork" in representation

    def test_adding_class_to_another_class_extension(self, graph, ex_ns):
        """Test using += operator to add a class to another class's extension."""
        opera = Class(ex_ns.Opera, graph=graph)
        opera.sub_class_of = [ex_ns.MusicalWork]

        creative_work = Class(ex_ns.CreativeWork, graph=graph)
        creative_work += opera

        subclasses = list(opera.sub_class_of)
        identifiers = [sub.identifier for sub in subclasses]
        assert ex_ns.MusicalWork in identifiers
        assert ex_ns.CreativeWork in identifiers

    def test_removing_class_from_another_class_extension(self, graph, ex_ns):
        """Test using -= operator to remove a class from another class's extension."""
        opera = Class(ex_ns.Opera, graph=graph)
        opera.sub_class_of = [ex_ns.MusicalWork, ex_ns.CreativeWork]

        creative_work = Class(ex_ns.CreativeWork, graph=graph)
        creative_work -= opera

        subclasses = list(opera.sub_class_of)
        identifiers = [sub.identifier for sub in subclasses]
        assert ex_ns.MusicalWork in identifiers
        assert ex_ns.CreativeWork not in identifiers


class TestClassWithExistingGraph:
    """Tests using a pre-populated graph (OWL ontology)."""

    def test_access_existing_subclassof_relationships(self, ex_ns, namespace_manager):
        """Test accessing subClassOf relationships from existing OWL graph."""
        owl_graph = Graph().parse(OWL_NS)
        owl_graph.namespace_manager = namespace_manager

        owl_class = Class(OWL_NS.Class, graph=owl_graph)
        subclasses = list(owl_class.sub_class_of)

        assert len(subclasses) > 0, "OWL.Class should have at least one subclass"


class TestBooleanClassOperations:
    """Tests for boolean class operations (union, intersection, complement)."""

    def test_union_class_creation(self, graph, ex_ns):
        """Test creating a union class using | operator."""
        opera = Class(ex_ns.Opera, graph=graph)
        creative_work = Class(ex_ns.CreativeWork, graph=graph)
        work = Class(ex_ns.Work, graph=graph)

        union_class = opera | creative_work | work
        representation = str(union_class)

        assert "ex:Opera" in representation
        assert "ex:CreativeWork" in representation
        assert "ex:Work" in representation
        assert "OR" in representation

    def test_deleting_class_from_union(self, graph, ex_ns):
        """Test removing a class from a union using del."""
        opera = Class(ex_ns.Opera, graph=graph)
        creative_work = Class(ex_ns.CreativeWork, graph=graph)
        work = Class(ex_ns.Work, graph=graph)

        union_class = opera | creative_work | work
        del union_class[union_class.index(work)]

        representation = str(union_class)
        assert "ex:Opera" in representation
        assert "ex:CreativeWork" in representation
        assert "ex:Work" not in representation

    def test_intersection_class_creation(self, graph, ex_ns):
        """Test creating an intersection class using & operator."""
        female = Class(ex_ns.Female, graph=graph)
        human = Class(ex_ns.Human, graph=graph)

        woman = female & human
        woman.identifier = ex_ns.Woman

        representation = str(woman)
        assert "ex:Female" in representation
        assert "ex:Human" in representation
        assert "AND" in representation


class TestEnumeratedClass:
    """Tests for enumerated classes (oneOf)."""

    def test_enumerated_class_representation(self, graph, ex_ns):
        """Test that enumerated class is correctly formatted."""
        continents = [
            Class(ex_ns.Africa, graph=graph),
            Class(ex_ns.NorthAmerica, graph=graph),
        ]

        enumerated = EnumeratedClass(members=continents, graph=graph)
        representation = str(enumerated)

        assert "ex:Africa" in representation
        assert "ex:NorthAmerica" in representation


class TestRestrictions:
    """Tests for OWL restrictions (allValuesFrom, someValuesFrom, maxCardinality)."""

    def test_all_values_from_restriction(self, graph, ex_ns):
        """Test creating an allValuesFrom restriction."""
        has_parent_prop = Property(ex_ns.hasParent, graph=graph)
        restriction = Restriction(
            has_parent_prop,
            graph=graph,
            all_values_from=ex_ns.Human
        )

        representation = str(restriction)
        assert "ex:hasParent" in representation
        assert "ex:Human" in representation
        assert "ONLY" in representation

    def test_some_values_from_using_infix_operator(self, graph, ex_ns):
        """Test creating someValuesFrom restriction using |some| infix."""
        has_parent_prop = Property(ex_ns.hasParent, graph=graph)
        physician = Class(ex_ns.Physician, graph=graph)

        restriction = has_parent_prop | some | physician

        representation = str(restriction)
        assert "ex:hasParent" in representation
        assert "ex:Physician" in representation
        assert "SOME" in representation

    def test_max_cardinality_using_infix_operator(self, graph, ex_ns):
        """Test creating maxCardinality restriction using |max| infix."""
        restriction = Property(ex_ns.hasParent,
                               graph=graph) | max_cardinality | Literal(1)

        representation = str(restriction)
        assert "ex:hasParent" in representation
        assert "MAX" in representation
        assert "1" in representation


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
