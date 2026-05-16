"""
Tests for skolemization of union classes in DLP.

These tests verify that skolem terms are not incorrectly applied to union classes.
"""

import pytest

from fuxi.DLP import SKOLEMIZED_CLASS_NS
from fuxi.Rete.Network import ReteNetwork
from fuxi.Rete.RuleStore import setup_rule_store
from fuxi.Syntax.InfixOWL import OWL_NS, BooleanClass, Class, Individual
from rdflib import Graph, Namespace

EX = Namespace('http://example.com#')


@pytest.fixture
def tbox_graph():
    """Provide a TBox graph with classes for skolemization testing."""
    graph = Graph()
    graph.namespace_manager.bind('ex', EX)
    graph.namespace_manager.bind('owl', OWL_NS)
    Individual.factoryGraph = graph
    class_b = Class(EX.b)
    class_e = Class(EX.e)
    class_f = Class(EX.f)
    class_a = BooleanClass(EX.a,
                           operator=OWL_NS.unionOf,
                           members=[class_e, class_f])
    BooleanClass(EX.c,
                 operator=OWL_NS.unionOf,
                 members=[class_a, class_b])
    return graph


@pytest.fixture
def rete_network(tbox_graph):
    """Provide a Rete network with DLP configured."""
    rule_store, rule_graph = setup_rule_store()
    network = ReteNetwork(rule_store)
    return network


class TestSkolemization:
    """Tests for skolemization behavior with union classes."""

    def test_union_skolemization(self, tbox_graph, rete_network):
        """Test that union classes don't get skolem terms in body."""
        network = rete_network
        program = network.setup_description_logic_programming(tbox_graph)
        for rule in program:
            if hasattr(rule.formula.body, 'arg'):
                assert not (rule.formula.body.arg[-1].find(SKOLEMIZED_CLASS_NS) > -1), \
                    f"Rule has a skolem term when it shouldn't!: {rule}"
            else:
                print(f"{rule.formula.body} - find(SKOLEMIZED_CLASS_NS)")


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
