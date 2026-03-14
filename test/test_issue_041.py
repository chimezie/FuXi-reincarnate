"""
http://code.google.com/p/fuxi/issues/detail?id=41

the network.registerAction method must check that the RHS
is a Uniterm and not a compound term (e.g. And, Empty, etc)
before trying to call rule.formula.head.toRDFTuple().
"""

from io import StringIO

from rdflib import Variable

from fuxi.Horn.HornRules import HornFromN3
from fuxi.Rete.RuleStore import SetupRuleStore

rule_fixture = """\
@prefix test: <http://example.org/>.

{ ?x a ?y } => {
 ?x test:value "hello" .
 ?x test:value "world"
}.
"""


def test_issue_41():
    rules = HornFromN3(StringIO(rule_fixture))
    rule_store, rule_graph, network = SetupRuleStore(makeNetwork=True)
    for rule in rules:
        network.buildNetworkFromClause(rule)

    def dummy(*av, **kw):
        pass

    head = (Variable("x"), Variable("y"), Variable("z"))
    network.registerReteAction(head, False, dummy)
