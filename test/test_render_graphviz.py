"""Unit tests for graphviz-based rendering of RETE networks and SIP collections."""

from rdflib.collection import Collection

from fuxi.Horn.HornRules import horn_from_n3
from fuxi.Rete.RuleStore import setup_rule_store
from fuxi.Rete.SidewaysInformationPassing import MAGIC, render_sip_collection
from fuxi.Rete.Util import render_network
from rdflib import RDF, BNode, Graph, URIRef, Variable

TEST_DIR_RULES = "test/command_line_test_rules.n3"
FAM_NS = "http://dev.w3.org/2000/10/swap/test/cwm/fam.n3#"


def test_render_network_returns_digraph():
    """render_network should return a graphviz.Digraph instance."""
    import graphviz

    rule_store, rule_graph, network = setup_rule_store(make_network=True)
    ns_binds = {"fam": URIRef(FAM_NS)}
    network.ns_map = ns_binds
    rs = horn_from_n3(TEST_DIR_RULES)
    for rule in rs:
        network.build_network_from_clause(rule)
    dot = render_network(network, ns_map=ns_binds, format="svg")
    assert isinstance(dot, graphviz.Digraph), (
        f"Expected graphviz.Digraph, got {type(dot)}"
    )


def test_render_network_dot_source():
    """render_network should produce DOT source containing node definitions."""
    rule_store, rule_graph, network = setup_rule_store(make_network=True)
    ns_binds = {"fam": URIRef(FAM_NS)}
    network.ns_map = ns_binds
    rs = horn_from_n3(TEST_DIR_RULES)
    for rule in rs:
        network.build_network_from_clause(rule)
    dot = render_network(network, ns_map=ns_binds, format="svg")
    source = dot.source
    assert "digraph" in source, f"DOT source should contain 'digraph': {source[:200]}"
    assert "RETE Network" in source


def test_render_sip_collection_returns_digraph():
    """render_sip_collection should return a graphviz.Digraph instance."""
    import graphviz

    sip_graph = _build_minimal_sip_graph()
    dot = render_sip_collection(sip_graph, format="svg")
    assert isinstance(dot, graphviz.Digraph), (
        f"Expected graphviz.Digraph, got {type(dot)}"
    )


def test_render_sip_collection_dot_source():
    """render_sip_collection should produce DOT source with edges."""
    sip_graph = _build_minimal_sip_graph()
    dot = render_sip_collection(sip_graph, format="svg")
    source = dot.source
    assert "digraph" in source, "DOT source should contain 'digraph'"
    assert "->" in source, "DOT source should contain edges"


def _build_minimal_sip_graph():
    sip_graph = Graph()
    left = URIRef(FAM_NS + "up")
    right = URIRef(FAM_NS + "sg")
    arc = URIRef("http://example.org/arc1")
    sip_graph.add((arc, RDF.type, MAGIC.SipArc))
    sip_graph.add((left, arc, right))
    vars_col = Collection(sip_graph, BNode())
    vars_col.append(Variable("X"))
    sip_graph.add((arc, MAGIC.bindings, vars_col.uri))
    return sip_graph
