"""
Tests for RETE action execution.

These tests verify:
- Custom actions registered with the RETE network are executed
- Action functions can add inferred facts to the network
"""

from hashlib import sha1
from io import StringIO

import pytest

from fuxi.Horn.HornRules import horn_from_n3
from fuxi.Rete.RuleStore import setup_rule_store
from fuxi.Rete.Util import generate_token_set
from rdflib import Graph, Literal, Namespace, Variable

FOAF = Namespace("http://xmlns.com/foaf/0.1/")
EX = Namespace("http://example.com/#")

N3_PROGRAM = """\
@prefix m: <http://example.com/#>.
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix foaf: <http://xmlns.com/foaf/0.1/> .

{ ?person foaf:mbox ?email } => { ?person foaf:mbox_sha1sum rdf:Literal } ."""
N3_FACTS = """\
@prefix m: <http://example.com/#>.
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix foaf: <http://xmlns.com/foaf/0.1/> .

m:chimezie foaf:mbox <mailto:chimezie@example.com> .
m:zoë foaf:mbox <mailto:zoë@example.com> .
"""

matching_head_triple = (Variable("person"), FOAF["mbox_sha1sum"], Literal)
expected_sha1_hex = "8f90d9335f967f58b40d5b6a49f8d9afca64b5ae"


def encode_action(t_node, inferred_triple, token, binding, debug=False):
    """Action function that computes sha1 hash of email and adds as inferred fact."""
    person = binding[Variable("person")]
    email = binding[Variable("email")]
    new_triple = (
        person,
        FOAF["mbox_sha1sum"],
        Literal(sha1(email.encode("utf-8")).hexdigest()),
    )
    t_node.network.inferred_facts.add(new_triple)


class TestReteAction:
    """Tests for RETE action execution."""

    def test_rete_action_infers_sha1_sum(self):
        """Test that RETE action correctly computes and infers sha1 hash of email."""
        fact_graph = Graph().parse(StringIO(N3_FACTS), format="n3")
        _rule_store, _rule_graph, network = setup_rule_store(make_network=True)
        for rule in horn_from_n3(StringIO(N3_PROGRAM), additional_builtins=None):
            network.build_network_from_clause(rule)
        network.register_rete_action(matching_head_triple, False, encode_action)
        network.feed_facts_to_add(generate_token_set(fact_graph))

        resulting_triple = (
            EX.chimezie,
            FOAF["mbox_sha1sum"],
            Literal(expected_sha1_hex),
        )
        assert resulting_triple in network.inferred_facts

    def test_rete_action_creates_four_inferred_facts(self):
        """
        Test that both facts trigger the RETE action
        (2 rule patterns + 2 computed hashes).
        """
        fact_graph = Graph().parse(StringIO(N3_FACTS), format="n3")
        _rule_store, _rule_graph, network = setup_rule_store(make_network=True)
        for rule in horn_from_n3(StringIO(N3_PROGRAM), additional_builtins=None):
            network.build_network_from_clause(rule)
        network.register_rete_action(matching_head_triple, False, encode_action)
        network.feed_facts_to_add(generate_token_set(fact_graph))

        sha1_triples = list(
            network.inferred_facts.triples((None, FOAF["mbox_sha1sum"], None))
        )
        assert len(sha1_triples) == 4


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
