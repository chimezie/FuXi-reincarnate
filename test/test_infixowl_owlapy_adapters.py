"""
Tests for InfixOWL to owlapy adapter conversions.

These tests require the owlapy package for OWL class expression conversions.
"""

import pytest

from rdflib import Graph, Namespace

try:
    from owlapy.class_expression import (
        OWLClass,
        OWLObjectComplementOf,
        OWLObjectSomeValuesFrom,
        OWLObjectUnionOf,
    )
    from owlapy.owl_individual import OWLNamedIndividual
    from owlapy.owl_property import OWLObjectProperty

    owlapy_available = True
except ImportError:
    owlapy_available = False

pytestmark = pytest.mark.skipif(  # noqa: E402
    not owlapy_available,
    reason="owlapy package not installed - install with: pip install owlapy",
)

from fuxi.Syntax.InfixOWL import (  # noqa: E402
    Class,
    Individual,
    Property,
    Restriction,
    to_owlapy_class,
    to_owlapy_expression,
    to_owlapy_individual,
    to_owlapy_property,
)


@pytest.fixture
def graph():
    """Provide a clean graph for each test."""
    return Graph()


@pytest.fixture
def ex():
    """Provide example namespace."""
    return Namespace("http://example.org/")


@pytest.fixture
def setup_factory(graph, ex):
    """Set up Individual.factoryGraph."""
    Individual.factoryGraph = graph
    return graph, ex


class TestInfixOWLOwlapyAdapter:
    """Tests for InfixOWL to owlapy adapter conversions."""

    def test_to_owlapy_class_and_property(self, setup_factory):
        """Test converting Class and Property to owlapy types."""
        graph, ex = setup_factory
        person = Class(ex.Person, graph=graph)
        has_child = Property(ex.hasChild, graph=graph)

        owl_cls = to_owlapy_class(person)
        owl_prop = to_owlapy_property(has_child)

        assert isinstance(owl_cls, OWLClass)
        assert isinstance(owl_prop, OWLObjectProperty)

    def test_to_owlapy_individual(self, setup_factory):
        """Test converting Individual to owlapy types."""
        graph, ex = setup_factory
        ind = Individual(ex.Alice, graph=graph)
        owl_ind = to_owlapy_individual(ind)
        assert isinstance(owl_ind, OWLNamedIndividual)

    def test_to_owlapy_restriction_expression(self, setup_factory):
        """Test converting Restriction to owlapy expression."""
        graph, ex = setup_factory
        person = Class(ex.Person, graph=graph)
        has_child = Property(ex.hasChild, graph=graph)
        restriction = Restriction(has_child, graph=graph, some_values_from=person)

        expr = to_owlapy_expression(restriction)
        assert isinstance(expr, OWLObjectSomeValuesFrom)

    def test_to_owlapy_boolean_expression(self, setup_factory):
        """Test converting BooleanClass (union) to owlapy expression."""
        graph, ex = setup_factory
        a = Class(ex.A, graph=graph)
        b = Class(ex.B, graph=graph)
        union = a | b

        expr = to_owlapy_expression(union)
        assert isinstance(expr, OWLObjectUnionOf)

    def test_to_owlapy_complement_expression(self, setup_factory):
        """Test converting complement expression to owlapy."""
        graph, ex = setup_factory
        a = Class(ex.A, graph=graph)
        complement = ~a

        expr = to_owlapy_expression(complement)
        assert isinstance(expr, OWLObjectComplementOf)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
