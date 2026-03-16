#!/usr/bin/env python
# encoding: utf-8
import pytest
from io import StringIO
from pprint import pprint
from rdflib import Graph, Namespace
from fuxi.Rete.RuleStore import SetupRuleStore
from fuxi.Rete.Util import generateTokenSet
from fuxi.DLP.DLNormalization import NormalFormReduction

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
    rule_store, rule_graph, network = SetupRuleStore(makeNetwork=True)
    tbox_graph = Graph().parse(StringIO(TBOX), format="n3")
    abox_graph = Graph().parse(StringIO(ABOX), format="n3")
    NormalFormReduction(tbox_graph)

    network.setupDescriptionLogicProgramming(tbox_graph)
    pprint(list(network.rules))

    network.feedFactsToAdd(generateTokenSet(tbox_graph))
    network.feedFactsToAdd(generateTokenSet(abox_graph))

    network.inferredFacts.bind("ex", EX)
    network.inferredFacts.bind("exterms", EX_TERMS)

    for triple in expected_triples:
        assert triple in network.inferredFacts, f"Missing {triple!r}"
