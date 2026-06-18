"""
Tests for builtin ordering in network_from_n3.

These tests verify that string and other builtin predicates work correctly
when rules are built from N3.
"""

from io import StringIO

import pytest

from fuxi.Horn.HornRules import network_from_n3
from fuxi.Rete.BuiltinPredicates import STRING_NS
from fuxi.Rete.RuleStore import setup_rule_store
from fuxi.Rete.Util import generate_token_set
from rdflib import Dataset, Literal, Namespace, URIRef, Variable

TEST_NS = Namespace("http://example.org/test#")
LOG = Namespace("http://www.w3.org/2000/10/swap/log#")


def string_starts_with(subject, object_):
    for term in (subject, object_):
        assert isinstance(term, (Variable, Literal, URIRef)), (
            "str:startsWith terms must be Variables, Literals, or URIRefs!"
        )

    def starts_with_f(subject_value, object_value):
        return subject_value.startswith(object_value)

    return starts_with_f


def extract_base_facts(cg):
    """
    Takes a conjunctive graph and returns
    a generator of RDF facts (excluding N3 facts
    involving log:implies and triples in QuotedGraphs)
    """
    try:
        from rdflib.graph import QuotedGraph

        has_quoted_graph = True
    except ImportError:
        has_quoted_graph = False

    for ctx in cg.graphs():
        if has_quoted_graph and isinstance(ctx, QuotedGraph):
            continue
        for s, p, o in ctx:
            if p != LOG.implies:
                yield s, p, o


def build_network(rules):
    if isinstance(rules, str):
        rules = StringIO(rules)
    graph = Dataset(default_union=True)
    graph.parse(rules, publicID="test", format="n3")
    network = network_from_n3(
        graph, additional_builtins={STRING_NS.startsWith: string_starts_with}
    )
    network.feed_facts_to_add(generate_token_set(extract_base_facts(graph)))
    return network


def build_network2(rules):
    graph = Dataset(default_union=True)
    graph.parse(StringIO(rules), publicID="test", format="n3")
    rule_store, rule_graph = setup_rule_store(
        StringIO(rules), additional_builtins={STRING_NS.startsWith: string_starts_with}
    )
    from fuxi.Rete.Network import ReteNetwork

    network = ReteNetwork(rule_store)
    network.feed_facts_to_add(generate_token_set(extract_base_facts(graph)))
    return network


LITERAL_RULES = """\
@prefix test: <http://example.org/test#> .
@prefix str: <http://www.w3.org/2000/10/swap/string#> .

test:example test:value "example" .
{ test:example test:value ?value .
  ?value str:startsWith "ex" } => { test:test test:passes 1 } ."""


LITERAL_FACT = (TEST_NS.test, TEST_NS.passes, Literal(1))


URIREF_RULES = """\
@prefix test: <http://example.org/test#> .
@prefix str: <http://www.w3.org/2000/10/swap/string#> .

test:example test:value test:example .
{ test:example test:value ?value .
  ?value str:startsWith "http://example.org/test#ex" } =>
        { test:test test:passes 1 } ."""


URIREF_FACT = (TEST_NS.test, TEST_NS.passes, Literal(1))


class TestLiteralStringStartsWith:
    """Test string:startsWith with literal values."""

    @pytest.fixture
    def network(self):
        return build_network(LITERAL_RULES)

    @pytest.fixture
    def network2(self):
        return build_network2(LITERAL_RULES)

    def test_literal_variable_startswith_literal_should_match(self, network):
        assert LITERAL_FACT in network.inferred_facts

    def test_literal_variable_startswith_literal_should_match2(self, network2):
        assert LITERAL_FACT in network2.inferred_facts


class TestURIRefStringStartsWith:
    """Test string:startsWith with URIRef values."""

    @pytest.fixture
    def network(self):
        return build_network(URIREF_RULES)

    @pytest.fixture
    def network2(self):
        return build_network2(URIREF_RULES)

    def test_uriref_variable_startswith_literal_should_match(self, network):
        assert URIREF_FACT in network.inferred_facts

    def test_uriref_variable_startswith_literal_should_match2(self, network2):
        assert URIREF_FACT in network2.inferred_facts


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
