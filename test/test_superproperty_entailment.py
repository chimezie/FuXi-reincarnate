#!/usr/bin/env python
from io import StringIO
from pprint import pprint

import pytest

from fuxi.DLP.DLNormalization import normal_form_reduction
from fuxi.Rete.RuleStore import setup_rule_store
from fuxi.Rete.Util import generate_token_set
from rdflib import Graph, Namespace

EX = Namespace("http://example.org/")
EX_TERMS = Namespace("http://example.org/terms/")

expected_triples = [
    (EX.john, EX_TERMS.has_sibling, EX.jack),
    (EX.john, EX_TERMS.brother, EX.jack),
    (EX.jack, EX_TERMS.has_brother, EX.john),
]

ABOX = """\
@prefix exterms: <http://example.org/terms/> .
@prefix : <http://example.org/> .

:john exterms:has_brother :jack .
:jack exterms:brother     :john .
"""

TBOX = """\
@prefix exterms: <http://example.org/terms/> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl: <http://www.w3.org/2002/07/owl#>.

exterms:Agent
    a rdfs:Class .

exterms:Person
    a rdfs:Class ;
    rdfs:subClassOf exterms:Agent .

exterms:has_sibling
    a rdf:Property .

exterms:has_brother
    a rdf:Property ;
    rdfs:subPropertyOf exterms:has_sibling ;
    rdfs:domain exterms:Person ;
    rdfs:range exterms:Person .

exterms:brother
    a rdf:Property ;
    owl:equivalentProperty exterms:has_brother ;
    rdfs:domain exterms:Person ;
    rdfs:range exterms:Person .

"""


pytestmark = pytest.mark.integration


def test_superproperty_entailment():
    rule_store, rule_graph, network = setup_rule_store(make_network=True)
    tbox_graph = Graph().parse(StringIO(TBOX), format="n3")
    abox_graph = Graph().parse(StringIO(ABOX), format="n3")
    normal_form_reduction(tbox_graph)

    network.setup_description_logic_programming(tbox_graph)
    pprint(list(network.rules))

    network.feed_facts_to_add(generate_token_set(tbox_graph))
    network.feed_facts_to_add(generate_token_set(abox_graph))

    network.inferred_facts.bind("ex", EX)
    network.inferred_facts.bind("exterms", EX_TERMS)

    for triple in expected_triples:
        assert triple in network.inferred_facts, f"Missing {triple!r}"
