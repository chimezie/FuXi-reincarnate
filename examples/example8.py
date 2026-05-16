# https://groups.google.com/d/msg/fuxi-discussion/4r1Nt_o1Hco/4QQ7BaqBCH8J
from io import StringIO

from rdflib.graph import Graph

# from fuxi.DLP.DLNormalization import NormalFormReduction
from fuxi.Horn.HornRules import horn_from_n3
from fuxi.Rete.RuleStore import setup_rule_store
from fuxi.Rete.Util import generate_token_set

rule_store, rule_graph, network = setup_rule_store(make_network=True)

rules = """
@prefix owl: <http://www.w3.org/2002/07/owl#> .
{ ?x owl:sameAs ?y } => { ?y owl:sameAs ?x } .
{ ?x owl:sameAs ?y . ?x ?p ?o } => { ?y ?p ?o } .
"""

for rule in horn_from_n3(StringIO(rules)):
    network.build_network_from_clause(rule)

facts = """
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix ex: <http://example.org/> .
@prefix exterms: <http://example.org/terms/> .
ex:foo
        a exterms:Something ;
        exterms:hasX "blah blah" ;
        owl:sameAs ex:bar .
ex:bar
        exterms:hasY "yyyy" .
"""
g = Graph()
g.parse(data=facts, format="n3")

network.feed_facts_to_add(generate_token_set(g))

print(network.inferred_facts.serialize(format="n3"))
