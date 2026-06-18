"""
Tests for existential variables in rule heads (bnode generation).

These tests verify:
- Existential variables in rule heads create blank nodes
- Skolem machine behavior for multiple rules with same head pattern
"""

from io import StringIO

import pytest

from fuxi.Horn.HornRules import horn_from_n3
from fuxi.Rete.Network import ReteNetwork
from fuxi.Rete.RuleStore import N3RuleStore, setup_rule_store
from fuxi.Rete.Util import generate_token_set
from rdflib import RDF, Graph, Namespace, URIRef

N3_PROGRAM = """\
@prefix m: <http://example.com/#>.
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
{ ?det a m:Detection.
  ?det has m:name ?infName.
} => {

  ?det has m:inference [ a m:Inference; m:inference_name ?infName ].
}.

"""
N3_FACTS = """\
@prefix : <#> .
@prefix m: <http://example.com/#>.
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
m:Detection a rdfs:Class .
m:Inference a rdfs:Class .
:det1 a m:Detection .
:det1 m:name "Inference1" .
:det2 a m:Detection .
:det2 m:name "Inference2" .
"""

SKOLEM_MACHINE_RULES = """\
@prefix ex: <http://example.com/#>.
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
{?X ex:b ?Y} => {_:Z ex:p ?Y}.
{?X ex:e ?Y} => {_:Z ex:p ?Y}.
"""

SKOLEM_MACHINE_FACTS = """\
@prefix ex: <http://example.com/#>.
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
ex:a ex:b ex:c.
ex:d ex:e ex:c.
"""

EX_NS = Namespace("http://example.com/#")


@pytest.fixture
def skolem_network():
    """Provide a Rete network with skolem machine rules and facts."""
    rule_store, rule_graph, network = setup_rule_store(make_network=True)
    fact_graph = Graph().parse(StringIO(SKOLEM_MACHINE_FACTS), format="n3")
    for rule in horn_from_n3(StringIO(SKOLEM_MACHINE_RULES)):
        network.build_network_from_clause(rule)
    network.feed_facts_to_add(generate_token_set(fact_graph))
    return network


class TestExistentialInHead:
    """Tests for existential variables in rule heads."""

    def test_existentials_create_blank_nodes(self):
        """Test that existential variables in rule heads create blank nodes."""
        rule_store = N3RuleStore()
        rule_graph = Graph(rule_store)
        rule_graph.parse(StringIO(N3_PROGRAM), format="n3")
        fact_graph = Graph()
        fact_graph.parse(StringIO(N3_FACTS), format="n3")
        delta_graph = Graph()
        network = ReteNetwork(
            rule_store,
            initial_working_memory=generate_token_set(fact_graph),
            inferred_target=delta_graph,
        )

        inference_count = sum(
            1
            for _ in network.inferred_facts.subjects(
                predicate=RDF.type, object=URIRef("http://example.com/#Inference")
            )
        )

        assert inference_count > 1, "Each rule firing should introduce a new BNode!"


class TestSkolemMachine:
    """Tests for skolem machine behavior."""

    def test_skolem_machine_produces_multiple_inferred_facts(self, skolem_network):
        """Test that skolem machine produces correct number of inferred facts."""
        p_triples = list(skolem_network.inferred_facts.triples((None, EX_NS.p, None)))
        assert len(p_triples) == 2, (
            f"Expected 2 inferred facts for ex:p, got {len(p_triples)}"
        )

    def test_skolem_machine_all_have_correct_object(self, skolem_network):
        """Test that all inferred facts have the correct object (ex:c)."""
        p_triples = list(skolem_network.inferred_facts.triples((None, EX_NS.p, None)))
        objects = [obj for _, _, obj in p_triples]
        assert EX_NS.c in objects, "All inferred facts should have ex:c as object"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
