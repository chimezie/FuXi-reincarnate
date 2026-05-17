# -*- coding: utf-8 -*-
# flake8: noqa
"""
Stratified Negation Semantics for DLP using SPARQL to handle the negation
"""

import copy
import itertools
import unittest
from rdflib.graph import Graph
from rdflib import Namespace, RDF, Variable, BNode
from rdflib.util import first
from fuxi.Rete.RuleStore import setup_rule_store
from fuxi.Horn.PositiveConditions import And

from fuxi.Syntax.InfixOWL import some
from fuxi.Syntax.InfixOWL import only
from fuxi.Syntax.InfixOWL import Class
from fuxi.Syntax.InfixOWL import ClassNamespaceFactory
from fuxi.Syntax.InfixOWL import EnumeratedClass
from fuxi.Syntax.InfixOWL import Individual
from fuxi.Syntax.InfixOWL import OWL_NS
from fuxi.Syntax.InfixOWL import Property


from fuxi.DLP import map_dlp_to_network
from .DLNormalization import normal_form_reduction
from functools import reduce


EX_NS = Namespace("http://example.com/")
EX = ClassNamespaceFactory(EX_NS)


def get_vars(atom):
    from fuxi.Rete.SidewaysInformationPassing import get_args

    return [term for term in get_args(atom) if isinstance(term, Variable)]


def calculate_stratified_model(network, ont_graph, derived_preds, edb=None):
    from fuxi.Rete.Util import generate_token_set
    pos_rules, ignored = map_dlp_to_network(network, ont_graph, construct_network=False, derived_preds=derived_preds,
                                           ignore_negative_stratus=True)
    for rule in pos_rules:
        network.build_network_from_clause(rule)
    network.feed_facts_to_add(generate_token_set(edb and edb or ont_graph))
    for i in ignored:
        # Evaluate the Graph pattern, and instanciate the head of the rule with
        # the solutions returned
        sel, compiler = stratified_sparql(i)
        query = compiler.compile(sel)
        i.stratifiedQuery = query
        vars = sel.projection
        for rt in (edb and edb or ont_graph).query(query):
            solutions = {}
            if isinstance(rt, tuple):
                solutions.update(dict([(vars[idx], i) for idx, i in enumerate(rt)]))
            else:
                solutions[vars[0]] = rt
            i.solutions = solutions
            head = copy.deepcopy(i.formula.head)
            head.ground(solutions)
            fact = head.to_rdf_tuple()
            network.inferred_facts.add(fact)
            network.feed_facts_to_add(generate_token_set([fact]))

    # Now we need to clear assertions that cross the individual,
    # concept, relation divide
    # toRemove=[]
    for s, p, o in network.inferred_facts.triples((None, RDF.type, None)):
        if s in (edb and edb or ont_graph).predicates() or s in [
            _s
            for _s, _p, _o in (edb and edb or ont_graph).triples_choices(
                (None, RDF.type, [OWL_NS.Class, OWL_NS.Restriction])
            )
        ]:
            network.inferred_facts.remove((s, p, o))
    return pos_rules, ignored


def create_copy_pattern(to_do):
    """
    "Let φ : V → V be a variable-renaming function. Given a graph pattern P, a
    copy pattern φ(P) is an isomorphic copy of P whose variables have been
    renamed according to φ and satisfying that var(P) ∩ var(φ(P)) = ∅."

    var_exprs maps variable expressions to variables
    vars     maps variables to variables

    """
    raise NotImplemented("Depends on telescope, which is no longer available")
    from telescope.sparql.helpers import v

    vars = {}
    var_exprs = {}
    copy_patterns = []
    for formula in to_do:
        for var in get_vars(formula):
            if var not in vars:
                newVar = Variable(BNode())
                var_exprs[v[var]] = newVar
                vars[var] = newVar
        copy_triple_pattern = copy.deepcopy(formula)
        copy_triple_pattern.rename_variables(vars)
        copy_patterns.append(copy_triple_pattern)
    return copy_patterns, vars, var_exprs


def stratified_sparql(rule, ns_mapping={EX_NS: "ex"}):
    """
    The SPARQL specification indicates that it is possible to test if a graph
    pattern does not match a dataset, via a combination of optional patterns
    and filter conditions (like negation as failure in logic programming)([9]
    Sec. 11.4.1).
    In this section we analyze in depth the scope and limitations of this
    approach. We will introduce a syntax for the “difference” of two graph
    patterns P1 and P2, denoted (P1 MINUS P2), with the intended informal
    meaning: “the set of mappings that match P1 and does not match P2”.

    Uses telescope to construct the SPARQL MINUS BGP expressions for body
    conditions with default negation formulae
    """
    raise NotImplemented("Depends on telescope, which is no longer available")
    from fuxi.Rete.SidewaysInformationPassing import get_args, find_full_sip, iter_condition

    # Find a sip order of the horn rule
    if isinstance(rule.formula.body, And):
        sipOrder = first(find_full_sip(([rule.formula.head], None), rule.formula.body))
    else:
        sipOrder = [rule.formula.head] + [rule.formula.body]
    from telescope import optional, op
    from telescope.sparql.queryforms import Select

    # from telescope.sparql.expressions import Expression
    from telescope.sparql.compiler import SelectCompiler
    from telescope.sparql.patterns import GroupGraphPattern

    toDo = []
    negativeVars = set()
    positiveLiterals = False
    for atom in sipOrder[1:]:
        if atom.naf:
            toDo.append(atom)
            negativeVars.update(get_vars(atom))
        else:
            positiveLiterals = True
    # The negative literas are moved to the back of the body conjunct
    # Intuitively, they should not be disconnected from the rest of rule
    # Due to the correlation between DL and guarded FOL
    [sipOrder.remove(toRemove) for toRemove in toDo]

    # posLiterals are all the positive literals leading up to the negated
    # literals (in left-to-right order)  There may be none, see below
    posLiterals = sipOrder[1:]

    posVarIgnore = []
    if not positiveLiterals:
        from fuxi.Horn.PositiveConditions import Uniterm

        # If there are no lead, positive literals (i.e. the LP is of the form:
        #   H :- not B1, not B2, ...
        # Then a 'phantom' triple pattern is needed as the left operand to the OPTIONAL
        # in order to properly implement P0 MINUS P where P0 is an empty
        # pattern
        keyVar = get_vars(rule.formula.head)[0]
        newVar1 = Variable(BNode())
        newVar2 = Variable(BNode())
        posVarIgnore.extend([newVar1, newVar2])
        phantomLiteral = Uniterm(newVar1, [keyVar, newVar2])
        posLiterals.insert(0, phantomLiteral)

    # The positive variables are collected
    positiveVars = set(
        reduce(lambda x, y: x + y, [get_vars(atom) for atom in posLiterals])
    )

    # vars = {}
    # varExprs = {}
    # copyPatterns = []
    print("%s =: { %s MINUS %s} " % (rule.formula.head, posLiterals, toDo))

    def collapseMINUS(left, right):
        negVars = set()
        for pred in iter_condition(right):
            negVars.update(
                [term for term in get_args(pred) if isinstance(term, Variable)]
            )
        innerCopyPatternNeeded = not negVars.difference(positiveVars)
        # A copy pattern is needed if the negative literals don't introduce new
        # vars
        if innerCopyPatternNeeded:
            innerCopyPatterns, innerVars, innerVarExprs = create_copy_pattern([right])
            # We use an arbitrary new variable as for the outer
            # FILTER(!BOUND(..))
            outerFilterVariable = list(innerVars.values())[0]
            optionalPatterns = [right] + innerCopyPatterns
            negatedBGP = optional(
                *[formula.to_rdf_tuple() for formula in optionalPatterns]
            )
            negatedBGP.filter(*[k == v for k, v in list(innerVarExprs.items())])
            positiveVars.update(
                [Variable(k.value[0:]) for k in list(innerVarExprs.keys())]
            )
            positiveVars.update(list(innerVarExprs.values()))
        else:
            # We use an arbitrary, 'independent' variable for the outer
            # FILTER(!BOUND(..))
            outerFilterVariable = negVars.difference(positiveVars).pop()
            optionalPatterns = [right]
            negatedBGP = optional(
                *[formula.to_rdf_tuple() for formula in optionalPatterns]
            )
            positiveVars.update(negVars)
        left = left.where(*[negatedBGP])
        left = left.filter(~op.bound(outerFilterVariable))
        return left

    topLevelQuery = Select(get_args(rule.formula.head)).where(
        GroupGraphPattern.from_obj([formula.to_rdf_tuple() for formula in posLiterals])
    )
    rt = reduce(collapseMINUS, [topLevelQuery] + toDo)
    return rt, SelectCompiler(ns_mapping)


def proper_sip_order_with_negation(body):
    """
    Ensures the list of literals has the negated literals
    at the end of the list
    """
    # from fuxi.Rete.SidewaysInformationPassing import iterCondition
    # import pdb; pdb.set_trace()
    first_neg_literal = None
    body_iterator = list(body)
    for idx, literal in enumerate(body_iterator):
        if literal.naf:
            first_neg_literal = literal
            break
    if first_neg_literal:
        # There is a first negative literal, are there subsequent positive
        # literals?
        subsequent_pos_lits = first(
            itertools.dropwhile(lambda i: i.naf, body_iterator[idx:])
        )
        if len(body) - idx > 1:
            # if this is not the last term in the body
            # then we succeed only if there are no subsequent positive literals
            return not subsequent_pos_lits
        else:
            # this is the last term, so we are successful
            return True
    else:
        # There are no negative literals
        return True


class UniversalRestrictionTest(unittest.TestCase):
    def setUp(self):
        self.ontGraph = Graph()
        self.ontGraph.bind("ex", EX_NS)
        self.ontGraph.bind("owl", OWL_NS)
        Individual.factoryGraph = self.ontGraph

    def test_negated_disjunction_test(self):
        contains = Property(EX_NS.contains)
        omega = EX.Omega
        alpha = EX.Alpha
        innerDisjunct = omega | alpha
        foo = EX.foo
        test_class1 = foo & (contains | only | ~innerDisjunct)
        test_class1.identifier = EX_NS.Bar

        self.assertEqual(
            repr(test_class1),
            "ex:foo THAT ( ex:contains ONLY ( NOT ( ex:Omega OR ex:Alpha ) ) )",
        )
        normal_form_reduction(self.ontGraph)
        self.assertEqual(
            repr(test_class1),
            "ex:foo THAT ( NOT ( ex:contains SOME ( ex:Omega OR ex:Alpha ) ) )",
        )

        individual1 = BNode()
        individual2 = BNode()
        foo.extent = [individual1]
        contains.extent = [(individual1, individual2)]
        (EX.Baz).extent = [individual2]
        rule_store, rule_graph, network = setup_rule_store(make_network=True)
        pos_rules, ignored = calculate_stratified_model(network, self.ontGraph, [EX_NS.Bar])
        self.failUnless(not pos_rules, "There should be no rules in the 0 strata.")
        self.assertEqual(len(ignored), 2, "There should be 2 'negative' rules")
        test_class1.graph = network.inferred_facts
        self.failUnless(
            individual1 in test_class1.extent,
            "%s should be in ex:Bar's extent" % individual1,
        )

    def testNominalPartition(self):
        partition = EnumeratedClass(
            EX_NS.part,
            members=[EX_NS.individual1, EX_NS.individual2, EX_NS.individual3],
        )
        sub_partition = EnumeratedClass(members=[EX_NS.individual1])
        partition_prop = Property(EX_NS.propFoo, range=partition.identifier)
        self.testClass = (EX.Bar) & (partition_prop | only | sub_partition)
        self.testClass.identifier = EX_NS.Foo
        self.assertEqual(
            repr(self.testClass), "ex:Bar THAT ( ex:propFoo ONLY { ex:individual1 } )"
        )
        self.assertEqual(
            repr(self.testClass.identifier),
            "rdflib.term.URIRef(u'http://example.com/Foo')",
        )
        normal_form_reduction(self.ontGraph)
        self.assertEqual(
            repr(self.testClass),
            "ex:Bar that ( not ( ex:propFoo value ex:individual2 ) ) and ( not ( ex:propFoo value ex:individual3 ) )",
        )
        rule_store, rule_graph, network = setup_rule_store(make_network=True)

        ex = BNode()
        (EX.Bar).extent = [ex]
        self.ontGraph.add((ex, EX_NS.propFoo, EX_NS.individual1))
        calculate_stratified_model(network, self.ontGraph, [EX_NS.Foo])
        self.failUnless(
            (ex, RDF.type, EX_NS.Foo) in network.inferred_facts,
            "Missing level 1 predicate (ex:Foo)",
        )


class NegatedExistentialRestrictionTest(unittest.TestCase):
    def setUp(self):
        self.ontGraph = Graph()
        self.ontGraph.bind("ex", EX_NS)
        self.ontGraph.bind("owl", OWL_NS)
        Individual.factoryGraph = self.ontGraph

    def testInConjunct(self):
        contains = Property(EX_NS.contains)
        test_case2 = (
            EX.Operation
            & ~(contains | some | EX.IsolatedCABGConcomitantExclusion)
            & (contains | some | EX.CoronaryArteryBypassGrafting)
        )
        test_case2.identifier = EX_NS.IsolatedCABGOperation
        normal_form_reduction(self.ontGraph)
        self.assertEqual(
            repr(test_case2),
            "ex:Operation THAT ( ex:contains SOME ex:CoronaryArteryBypassGrafting ) AND ( NOT ( ex:contains SOME ex:IsolatedCABGConcomitantExclusion ) )",
        )
        rule_store, rule_graph, network = setup_rule_store(make_network=True)
        op = BNode()
        (EX.Operation).extent = [op]
        grafting = BNode()
        (EX.CoronaryArteryBypassGrafting).extent = [grafting]
        test_case2.graph.add((op, EX_NS.contains, grafting))
        calculate_stratified_model(network, test_case2.graph, [EX_NS.Foo, EX_NS.IsolatedCABGOperation])
        test_case2.graph = network.inferred_facts
        self.failUnless(
            op in test_case2.extent,
            "%s should be in ex:IsolatedCABGOperation's extent" % op,
        )

    def testGeneralConceptInclusion(self):
        # Some Class
        #     ## Primitive Type  ##
        #     SubClassOf: Class: ex:NoExclusion  .
        # DisjointWith ( ex:contains some ex:IsolatedCABGConcomitantExclusion )
        contains = Property(EX_NS.contains)
        test_class = ~(contains | some | EX.Exclusion)
        test_class2 = EX.NoExclusion
        test_class2 += test_class
        normal_form_reduction(self.ontGraph)
        individual1 = BNode()
        individual2 = BNode()
        contains.extent = [(individual1, individual2)]
        rule_store, rule_graph, network = setup_rule_store(make_network=True)
        pos_rules, neg_rules = calculate_stratified_model(network, self.ontGraph, [EX_NS.NoExclusion])
        self.failUnless(not pos_rules, "There should be no rules in the 0 strata.")
        self.assertEqual(len(neg_rules), 2, "There should be 2 'negative' rules")
        Individual.factoryGraph = network.inferred_facts
        target_class = Class(EX_NS.NoExclusion, skip_owl_class_membership=False)
        self.failUnless(
            individual1 in target_class.extent,
            "There is a BNode that bears the contains relation with another individual that is not a member of Exclusion.",
        )
        self.assertEquals(
            len(list(target_class.extent)),
            1,
            "There should only be one member in NoExclusion",
        )


class NegatedDisjunctTest(unittest.TestCase):
    def setUp(self):
        self.ontGraph = Graph()
        self.ontGraph.bind("ex", EX_NS)
        self.ontGraph.bind("owl", OWL_NS)
        Individual.factoryGraph = self.ontGraph

    def testStratified(self):
        bar = EX.Bar
        baz = EX.Baz
        no_bar_or_baz = ~(bar | baz)
        omega = EX.Omega
        foo = omega & no_bar_or_baz
        foo.identifier = EX_NS.Foo
        ruleStore, ruleGraph, network = setup_rule_store(make_network=True)
        individual = BNode()
        omega.extent = [individual]
        normal_form_reduction(self.ontGraph)
        self.assertEqual(repr(foo), "ex:Omega THAT ( NOT ex:Bar ) AND ( NOT ex:Baz )")
        pos_rules, neg_rules = calculate_stratified_model(network, self.ontGraph, [EX_NS.Foo])
        foo.graph = network.inferred_facts
        self.failUnless(not pos_rules, "There should be no rules in the 0 strata.")
        self.assertEqual(
            repr(neg_rules[0]),
            "Forall ?X ( ex:Foo(?X) :- And( ex:Omega(?X) not ex:Bar(?X) not ex:Baz(?X) ) )",
        )
        self.failUnless(
            len(neg_rules) == 1,
            "There should only be one negative rule in a higher strata",
        )
        self.failUnless(
            individual in foo.extent, "%s should be a member of ex:Foo" % individual
        )


class NegationOfAtomicConcept(unittest.TestCase):
    def setUp(self):
        self.ont_graph = Graph()
        self.ont_graph.bind("ex", EX_NS)
        self.ont_graph.bind("owl", OWL_NS)
        Individual.factoryGraph = self.ont_graph

    def testAtomicNegation(self):
        bar = EX.Bar
        baz = ~bar
        baz.identifier = EX_NS.Baz
        rule_store, rule_graph, network = setup_rule_store(make_network=True)
        individual = BNode()
        individual2 = BNode()
        (EX.OtherClass).extent = [individual]
        bar.extent = [individual2]
        normal_form_reduction(self.ont_graph)
        self.assertEqual(repr(baz), "Class: ex:Baz DisjointWith ex:Bar\n")
        pos_rules, neg_rules = calculate_stratified_model(network, self.ont_graph, [EX_NS.Foo])
        self.failUnless(not pos_rules, "There should be no rules in the 0 strata.")
        self.failUnless(
            len(neg_rules) == 1,
            "There should only be one negative rule in a higher strata",
        )
        self.assertEqual(
            repr(neg_rules[0]), "Forall ?X ( ex:Baz(?X) :- not ex:Bar(?X) )"
        )
        baz.graph = network.inferred_facts
        self.failUnless(
            individual in baz.extent, "%s should be a member of ex:Baz" % individual
        )
        self.failUnless(
            individual2 not in baz.extent,
            "%s should *not* be a member of ex:Baz" % individual2,
        )


if __name__ == "__main__":
    unittest.main()
