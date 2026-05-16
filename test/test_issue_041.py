"""
http://code.google.com/p/fuxi/issues/detail?id=41

the network.registerAction method must check that the RHS
is a Uniterm and not a compound term (e.g. And, Empty, etc)
before trying to call rule.formula.head.to_rdf_tuple().
"""

from io import StringIO

from fuxi.Horn.HornRules import horn_from_n3
from fuxi.Rete.RuleStore import setup_rule_store
from rdflib import Variable

rule_fixture = """\
@prefix test: <http://example.org/>.

{ ?x a ?y } => {
 ?x test:value "hello" .
 ?x test:value "world"
}.
"""


def test_issue_41():
    rules = horn_from_n3(StringIO(rule_fixture))
    rule_store, rule_graph, network = setup_rule_store(make_network=True)
    for rule in rules:
        network.build_network_from_clause(rule)

    def dummy(*av, **kw):
        pass

    head = (Variable("x"), Variable("y"), Variable("z"))
    network.register_rete_action(head, False, dummy)
