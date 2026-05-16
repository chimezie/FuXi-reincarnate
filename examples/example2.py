from rdflib.graph import Graph

from fuxi.Horn.HornRules import horn_from_n3
from fuxi.Rete.Magic import adorn_literal, magic_set_transformation
from fuxi.Rete.RuleStore import setup_rule_store
from fuxi.Rete.Util import generate_token_set
from fuxi.SPARQL import EDBQuery
from rdflib import Namespace, Variable

ex_ns = Namespace('http://dev.w3.org/2000/10/swap/test/cwm/fam.n3#')

rules = horn_from_n3('https://raw.githubusercontent.com/linkeddata/swap/refs/heads/master/test/cwm/fam-rules.n3')
fact_graph = Graph().parse('https://raw.githubusercontent.com/linkeddata/swap/refs/heads/master/test/cwm/fam.n3',
                           format='n3')
fact_graph.bind('ex', ex_ns)
derived_preds = [ex_ns.ancestor]

# Then we setup the RETE-UL network that will be used for calculating the
# closure (or fixpoint) of the magic set-rewritten rules over the fact graph

rule_store, rule_graph, network = setup_rule_store(make_network=True)
network.ns_map = {'ex': ex_ns}
closure_delta_graph = Graph()
network.inferred_facts = closure_delta_graph

# Then we build the network from the re-written rules, using our query
# (or goal): "who are the descendants of david"

goals = [(ex_ns.david, ex_ns.ancestor, Variable('ANCESTOR'))]

for rule in magic_set_transformation(fact_graph, rules, goals, derived_preds):
    network.build_network_from_clause(rule)
    # network.rules.add(rule)
    print(f"\t{rule}")

# Then we create a 'magic seed' from the goal and print the goal
# as a SPARQL query

goal_lit = adorn_literal(goals[0])
adorned_goal_seed = goal_lit.make_magic_pred()
goal = adorned_goal_seed.to_rdf_tuple()
print(EDBQuery([goal_lit], fact_graph, return_vars=[Variable('ANCESTOR')]).as_sparql())

# Finally we run the seed fact and the original facts through the magic
# set RETE-UL network

network.feed_facts_to_add(generate_token_set([goal]))
network.feed_facts_to_add(generate_token_set(fact_graph))
network.report_conflict_set(closure_summary=True)
