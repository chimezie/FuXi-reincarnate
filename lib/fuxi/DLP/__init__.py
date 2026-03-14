# -*- coding: utf-8 -*-
"""
This module implements a Description Horn Logic implementation as defined
by Grosof, B. et.al. ("Description Logic Programs: Combining Logic Programs with
Description Logic" [1]) in section 4.4.  As such, it implements recursive mapping
functions "T", "Th" and "Tb" which result in "custom" (dynamic) rulesets, RIF Basic
Logic Dialect: Horn rulesets [2], [3].  The rulesets are evaluated against an
efficient RETE-UL network.

It is a Description Logic Programming [1] Implementation on top of RETE-UL:

"A DLP is directly defined as the LP-correspondent of a def-Horn
ruleset that results from applying the mapping T ."

The mapping is as follows:

== Core (Description Horn Logic) ==

== Class Equivalence ==

T(owl:equivalentClass(C, D)) -> { T(rdfs:subClassOf(C, D)
                                 T(rdfs:subClassOf(D, C) }

== Domain and Range Axioms (Base Description Logic: "ALC") ==

T(rdfs:range(P, D))  -> D(y) := P(x, y)
T(rdfs:domain(P, D)) -> D(x) := P(x, y)

== Property Axioms (Role constructors: "I") ==

T(rdfs:subPropertyOf(P, Q))     -> Q(x, y) :- P(x, y)
T(owl:equivalentProperty(P, Q)) -> { Q(x, y) :- P(x, y)
                                    P(x, y) :- Q(x, y) }
T(owl:inverseOf(P, Q))          -> { Q(x, y) :- P(y, x)
                                    P(y, x) :- Q(x, y) }
T(owl:TransitiveProperty(P))   -> P(x, z) :- P(x, y) ^ P(y, z)

[1] http://www.cs.man.ac.uk/~horrocks/Publications/download/2003/p117-grosof.pdf
[2] http://www.w3.org/2005/rules/wg/wiki/Core/Positive_Conditions
[3] http://www.w3.org/2005/rules/wg/wiki/asn06

"""

from rdflib.collection import Collection
from rdflib.namespace import Namespace, RDF, RDFS
from rdflib import BNode, Variable, URIRef
from rdflib.util import first

import copy
import warnings

from fuxi.Horn.PositiveConditions import (
    And,
    Or,
    Uniterm,
    Condition,
    Atomic,
    SetOperator,
    Exists,
)
from fuxi.Horn import DATALOG_SAFETY_NONE, DATALOG_SAFETY_STRICT, DATALOG_SAFETY_LOOSE
from .LPNormalForms import NormalizeDisjunctions
from fuxi.Horn.HornRules import Clause as OriginalClause, Rule

try:
    from functools import reduce
except ImportError:
    pass


SKOLEMIZED_CLASS_NS = Namespace("http://code.google.com/p/python-dlp/wiki/SkolemTerm#")

non_DHL_OWL_Semantics = """
@prefix log: <http://www.w3.org/2000/10/swap/log#>.
@prefix math: <http://www.w3.org/2000/10/swap/math#>.
@prefix owl: <http://www.w3.org/2002/07/owl#>.
@prefix xsd: <http://www.w3.org/2001/XMLSchema#>.
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#>.
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>.
@prefix : <http://eulersharp.sourceforge.net/2003/03swap/owl-rules#>.
@prefix list: <http://www.w3.org/2000/10/swap/list#>.
#Additional OWL-compliant semantics, mappable to Production Rules

#Subsumption (purely for TBOX classification)
{?C rdfs:subClassOf ?SC. ?A rdfs:subClassOf ?C} => {?A rdfs:subClassOf ?SC}.
{?C owl:equivalentClass ?A} => {?C rdfs:subClassOf ?A. ?A rdfs:subClassOf ?C}.
{?C rdfs:subClassOf ?SC. ?SC rdfs:subClassOf ?C} => {?C owl:equivalentClass ?SC}.

{?C owl:disjointWith ?B. ?M a ?C. ?Y a ?B } => {?M owl:differentFrom ?Y}.

{?P owl:inverseOf ?Q. ?P a owl:InverseFunctionalProperty} => {?Q a owl:FunctionalProperty}.
{?P owl:inverseOf ?Q. ?P a owl:FunctionalProperty} => {?Q a owl:InverseFunctionalProperty}.

#For OWL/InverseFunctionalProperty/premises004
{?C owl:oneOf ?L. ?L rdf:first ?X; rdf:rest rdf:nil. ?P rdfs:domain ?C} => {?P a owl:InverseFunctionalProperty}.
#For OWL/InverseFunctionalProperty/premises004
{?C owl:oneOf ?L. ?L rdf:first ?X; rdf:rest rdf:nil. ?P rdfs:range ?C} => {?P a owl:FunctionalProperty}.

{?S owl:differentFrom ?O} => {?O owl:differentFrom ?S}.
{?S owl:complementOf ?O} => {?O owl:complementOf ?S}.
{?S owl:disjointWith ?O} => {?O owl:disjointWith ?S}.

"""

OWL_NS = Namespace("http://www.w3.org/2002/07/owl#")

LOG = Namespace("http://www.w3.org/2000/10/swap/log#")
Any = None

LHS = 0
RHS = 1


def reduceAnd(left, right):
    if isinstance(left, And):
        left = reduce(reduceAnd, left)
    elif isinstance(right, And):
        right = reduce(reduceAnd, right)
    if isinstance(left, list) and not isinstance(right, list):
        return left + [right]
    elif isinstance(left, list) and isinstance(right, list):
        return left + right
    elif isinstance(left, list) and not isinstance(right, list):
        return left + [right]
    elif not isinstance(left, list) and isinstance(right, list):
        return [left] + right
    else:
        return [left, right]


def NormalizeClause(clause):
    def fetchFirst(gen):
        rt = first(gen)
        assert rt is not None
        return rt

    if hasattr(clause.head, "next"):
        clause.head = fetchFirst(clause.head)
    if hasattr(clause.body, "next"):
        clause.body = fetchFirst(clause.body)
    if isinstance(clause.head, And):
        clause.head.formulae = reduce(reduceAnd, clause.head, [])
    if isinstance(clause.body, And):
        clause.body.formulae = reduce(reduceAnd, clause.body)
    return clause


class UnsupportedNegation(Exception):
    def __init__(self, msg):
        super(UnsupportedNegation, self).__init__(msg)


class Clause(OriginalClause):
    """
    The RETE-UL algorithm supports conjunctions of facts in the head of a rule
    i.e.:   H1 ^ H2 ^ ... ^ H3 :- B1 ^  ^ Bm
    The Clause definition is overridden to permit this syntax (not allowed
    in definite LP or Horn rules)

    In addition, since we allow (in definite Horn) entailments beyond simple facts
    we ease restrictions on the form of the head to include Clauses
    """

    def __init__(self, body, head):
        self.body = body
        self.head = head
        if isinstance(head, Uniterm):
            from fuxi.Rete.Network import HashablePatternList

            try:
                antHash = HashablePatternList(
                    [term.toRDFTuple() for term in body], skipBNodes=True
                )
                consHash = HashablePatternList(
                    [term.toRDFTuple() for term in head], skipBNodes=True
                )
                self._bodyHash = hash(antHash)
                self._headHash = hash(consHash)
                self._hash = hash((self._headHash, self._bodyHash))
            except Exception:
                self._hash = None
        else:
            self._hash = None

    def __hash__(self):
        if self._hash is None:
            from fuxi.Rete.Network import HashablePatternList

            antHash = HashablePatternList(
                [term.toRDFTuple() for term in self.body], skipBNodes=True
            )
            consHash = HashablePatternList(
                [term.toRDFTuple() for term in self.head], skipBNodes=True
            )
            self._bodyHash = hash(antHash)
            self._headHash = hash(consHash)
            self._hash = hash((self._headHash, self._bodyHash))
        return self._hash

    def __repr__(self):
        return "%r :- %r" % (self.head, self.body)

    def n3(self):
        return "{ %s } => { %s }" % (self.body.n3(), self.head.n3())


def makeRule(clause, nsMap):
    vars = set()
    for child in clause.head:
        if isinstance(child, Or):
            return None
        assert isinstance(child, Uniterm), repr(child)
        vars.update([term for term in child.toRDFTuple() if isinstance(term, Variable)])
    negativeStratus = False
    for child in clause.body:
        if hasattr(child, "naf") and child.naf:
            negativeStratus = True
        elif not hasattr(child, "naf"):
            child.naf = False
        vars.update([term for term in child.toRDFTuple() if isinstance(term, Variable)])
    return Rule(clause, declare=vars, nsMapping=nsMap, negativeStratus=negativeStratus)


def DisjunctiveNormalForm(program, safety=DATALOG_SAFETY_NONE, network=None):
    for rule in program:
        tx_horn_clause = NormalizeClause(rule.formula)
        for tx_horn_clause in LloydToporTransformation(tx_horn_clause, True):
            if safety in [DATALOG_SAFETY_LOOSE, DATALOG_SAFETY_STRICT]:
                rule = Rule(tx_horn_clause, nsMapping=network and network.nsMap or {})
                if not rule.isSafe():
                    if safety == DATALOG_SAFETY_LOOSE:
                        warnings.warn(
                            "Ignoring unsafe rule (%s)" % rule, SyntaxWarning, 3
                        )
                        continue
                    elif safety == DATALOG_SAFETY_STRICT:
                        raise SyntaxError("Unsafe RIF Core rule: %s" % rule)
            disj = [i for i in breadth_first(tx_horn_clause.body) if isinstance(i, Or)]
            if len(disj) > 0:
                NormalizeDisjunctions(disj, tx_horn_clause, program, network)
            elif isinstance(tx_horn_clause.head, (And, Uniterm)):
                for hc in ExtendN3Rules(network, NormalizeClause(tx_horn_clause)):
                    yield makeRule(hc, network and network.nsMap or {})


def MapDLPtoNetwork(
    network,
    factGraph,
    complementExpansions=[],
    constructNetwork=False,
    derivedPreds=[],
    ignoreNegativeStratus=False,
    safety=DATALOG_SAFETY_NONE,
):
    ruleset = set()
    negativeStratus = []
    for horn_clause in T(
        factGraph,
        complementExpansions=complementExpansions,
        derivedPreds=derivedPreds,
    ):
        fullReduce = True
        for tx_horn_clause in LloydToporTransformation(horn_clause, fullReduce):
            tx_horn_clause = NormalizeClause(tx_horn_clause)
            disj = [i for i in breadth_first(tx_horn_clause.body) if isinstance(i, Or)]
            if len(disj) > 0:
                NormalizeDisjunctions(
                    disj,
                    tx_horn_clause,
                    ruleset,
                    network,
                    constructNetwork,
                    negativeStratus,
                    ignoreNegativeStratus,
                )
            elif isinstance(tx_horn_clause.head, (And, Uniterm)):
                for hc in ExtendN3Rules(
                    network, NormalizeClause(tx_horn_clause), constructNetwork
                ):
                    if safety in [DATALOG_SAFETY_LOOSE, DATALOG_SAFETY_STRICT]:
                        rule = Rule(hc, nsMapping=network.nsMap)
                        if not rule.isSafe():
                            if safety == DATALOG_SAFETY_LOOSE:
                                warnings.warn(
                                    "Ignoring unsafe rule (%s)" % rule, SyntaxWarning, 3
                                )
                                continue
                            elif safety == DATALOG_SAFETY_STRICT:
                                raise SyntaxError("Unsafe RIF Core rule: %s" % rule)
                    _rule = makeRule(hc, network.nsMap)
                    if _rule.negativeStratus:
                        negativeStratus.append(_rule)
                    if _rule is not None and (
                        not _rule.negativeStratus or not ignoreNegativeStratus
                    ):
                        ruleset.add(_rule)
    if ignoreNegativeStratus:
        return ruleset, negativeStratus
    else:
        return iter(ruleset)


def IsaFactFormingConclusion(head):
    if isinstance(head, And):
        for i in head:
            if not IsaFactFormingConclusion(i):
                return False
        return True
    elif isinstance(head, Or):
        return False
    elif isinstance(head, Atomic):
        return True
    elif isinstance(head, OriginalClause):
        return False
    else:
        print(head)
        raise


def traverseClause(condition):
    if isinstance(condition, SetOperator):
        for i in iter(condition):
            yield i
    elif isinstance(condition, Atomic):
        return


def breadth_first(condition, children=traverseClause):
    yield condition
    last = condition
    for node in breadth_first(condition, children):
        for child in children(node):
            yield child
            last = child
        if last == node:
            return


def breadth_first_replace(
    condition, children=traverseClause, candidate=None, replacement=None
):
    yield condition
    last = condition
    for node in breadth_first_replace(condition, children, candidate, replacement):
        for child in children(node):
            yield child
            if candidate and child is candidate:
                i = node.formulae.index(child)
                node.formulae[i] = replacement
                return
            last = child
        if last == node:
            return


def ExtendN3Rules(network, horn_clause, constructNetwork=False):
    from fuxi.Rete.RuleStore import Formula
    from fuxi.Rete.AlphaNode import AlphaNode

    rt = []
    if constructNetwork:
        ruleStore = network.ruleStore
        lhs = BNode()
        rhs = BNode()
    assert isinstance(horn_clause.body, (And, Uniterm)), list(horn_clause.body)
    assert len(list(horn_clause.body))
    if constructNetwork:
        for term in horn_clause.body:
            ruleStore.formulae.setdefault(lhs, Formula(lhs)).append(term.toRDFTuple())
    assert isinstance(horn_clause.head, (And, Uniterm)), repr(horn_clause.head)

    if IsaFactFormingConclusion(horn_clause.head):
        PrepareHornClauseForRETE(horn_clause)
        if constructNetwork:
            for term in horn_clause.head:
                assert not hasattr(term, "next")
                if isinstance(term, Or):
                    ruleStore.formulae.setdefault(rhs, Formula(rhs)).append(term)
                else:
                    ruleStore.formulae.setdefault(rhs, Formula(rhs)).append(
                        term.toRDFTuple()
                    )
            ruleStore.rules.append((ruleStore.formulae[lhs], ruleStore.formulae[rhs]))
            network.buildNetwork(
                iter(ruleStore.formulae[lhs]),
                iter(ruleStore.formulae[rhs]),
                Rule(horn_clause),
            )
            network.alphaNodes = [
                node
                for node in list(network.nodes.values())
                if isinstance(node, AlphaNode)
            ]
        rt.append(horn_clause)
    else:
        for hC in LloydToporTransformation(horn_clause, fullReduction=True):
            rt.append(hC)
            for i in ExtendN3Rules(network, hC, constructNetwork):
                rt.append(hC)
    return rt


def PrepareHeadExistential(clause):
    from fuxi.Rete.SidewaysInformationPassing import GetArgs

    skolemsInHead = [
        list(filter(lambda term: isinstance(term, BNode), GetArgs(lit)))
        for lit in iterCondition(clause.head)
    ]
    skolemsInHead = reduce(lambda x, y: x + y, skolemsInHead, [])
    if skolemsInHead:
        newHead = copy.deepcopy(clause.head)
        _e = Exists(formula=newHead, declare=set(skolemsInHead))
        clause.head = _e
    return clause


def PrepareHornClauseForRETE(horn_clause):
    if isinstance(horn_clause, Rule):
        horn_clause = horn_clause.formula

    def extractVariables(term, existential=True):
        if isinstance(term, existential and BNode or Variable):
            yield term
        elif isinstance(term, Uniterm):
            for t in term.toRDFTuple():
                if isinstance(t, existential and BNode or Variable):
                    yield t

    from fuxi.Rete.SidewaysInformationPassing import iterCondition, GetArgs

    bodyVars = set(
        reduce(
            lambda x, y: x + y,
            [
                list(extractVariables(i, existential=False))
                for i in iterCondition(horn_clause.body)
            ],
        )
    )

    headVars = set(
        reduce(
            lambda x, y: x + y,
            [
                list(extractVariables(i, existential=False))
                for i in iterCondition(horn_clause.head)
            ],
        )
    )

    updateDict = dict([(var, BNode()) for var in headVars if var not in bodyVars])

    if set(updateDict.keys()).intersection(GetArgs(horn_clause.head)):
        newHead = copy.deepcopy(horn_clause.head)
        for uniTerm in iterCondition(newHead):
            newArg = [updateDict.get(i, i) for i in uniTerm.arg]
            uniTerm.arg = newArg
        horn_clause.head = newHead

    skolemsInBody = [
        list(filter(lambda term: isinstance(term, BNode), GetArgs(lit)))
        for lit in iterCondition(horn_clause.body)
    ]
    skolemsInBody = reduce(lambda x, y: x + y, skolemsInBody, [])
    if skolemsInBody:
        newBody = copy.deepcopy(horn_clause.body)
        _e = Exists(formula=newBody, declare=set(skolemsInBody))
        horn_clause.body = _e

    PrepareHeadExistential(horn_clause)


def generatorFlattener(gen):
    assert hasattr(gen, "next")
    i = list(gen)
    i = (
        len(i) > 1
        and [hasattr(i2, "next") and generatorFlattener(i2) or i2 for i2 in i]
        or i[0]
    )
    if hasattr(i, "next"):
        i = listOrThingGenerator(i)
        return i
    elif isinstance(i, SetOperator):
        i.formulae = [
            hasattr(i2, "next") and generatorFlattener(i2) or i2 for i2 in i.formulae
        ]
        return i
    else:
        return i


def SkolemizeExistentialClasses(term, check=True):
    if check:
        return isinstance(term, BNode) and SKOLEMIZED_CLASS_NS[term] or term
    return SKOLEMIZED_CLASS_NS[term]


def NormalizeBooleanClassOperand(term, owlGraph):
    return (
        (
            (isinstance(term, BNode) and IsaBooleanClassDescription(term, owlGraph))
            or IsaRestriction(term, owlGraph)
        )
        and SkolemizeExistentialClasses(term)
        or term
    )


def IsaBooleanClassDescription(term, owlGraph):
    for s, p, o in owlGraph.triples_choices(
        (term, [OWL_NS.unionOf, OWL_NS.intersectionOf], None)
    ):
        return True


def IsaRestriction(term, owlGraph):
    return (term, RDF.type, OWL_NS.Restriction) in owlGraph


def iterCondition(condition):
    return isinstance(condition, SetOperator) and condition or iter([condition])


def Tc(owlGraph, negatedFormula):
    if (negatedFormula, OWL_NS.hasValue, None) in owlGraph:
        bodyUniTerm = Uniterm(
            RDF.type,
            [Variable("X"), NormalizeBooleanClassOperand(negatedFormula, owlGraph)],
            newNss=owlGraph.namespaces(),
        )

        condition = NormalizeClause(
            Clause(Tb(owlGraph, negatedFormula), bodyUniTerm)
        ).body
        assert isinstance(condition, Uniterm)
        condition.naf = True
        return condition
    elif (negatedFormula, OWL_NS.someValuesFrom, None) in owlGraph:
        binaryRel, unaryRel = Tb(owlGraph, negatedFormula)
        negatedBinaryRel = copy.deepcopy(binaryRel)
        negatedBinaryRel.naf = True
        negatedUnaryRel = copy.deepcopy(unaryRel)
        negatedUnaryRel.naf = True
        return Or([negatedBinaryRel, And([binaryRel, negatedUnaryRel])])
    elif isinstance(negatedFormula, URIRef):
        return Uniterm(
            RDF.type,
            [Variable("X"), NormalizeBooleanClassOperand(negatedFormula, owlGraph)],
            newNss=owlGraph.namespaces(),
            naf=True,
        )
    else:
        raise UnsupportedNegation("Unsupported negated concept: %s" % negatedFormula)


class MalformedDLPFormulaError(NotImplementedError):
    def __init__(self, message):
        self.message = message


def handleConjunct(conjunction, owlGraph, o, conjunctVar=Variable("X")):
    for bodyTerm in Collection(owlGraph, o):
        negatedFormula = False
        addToConjunct = None
        for negatedFormula in owlGraph.objects(
            subject=bodyTerm, predicate=OWL_NS.complementOf
        ):
            addToConjunct = Tc(owlGraph, negatedFormula)
        if negatedFormula:
            conjunction.append(addToConjunct)
        else:
            normalizedBodyTerm = NormalizeBooleanClassOperand(bodyTerm, owlGraph)
            bodyUniTerm = Uniterm(
                RDF.type,
                [conjunctVar, normalizedBodyTerm],
                newNss=owlGraph.namespaces(),
            )
            processedBodyTerm = Tb(owlGraph, bodyTerm, conjunctVar)
            classifyingClause = NormalizeClause(Clause(processedBodyTerm, bodyUniTerm))
            if (
                isinstance(normalizedBodyTerm, URIRef)
                and normalizedBodyTerm.find(SKOLEMIZED_CLASS_NS) == -1
            ):
                conjunction.append(bodyUniTerm)
            elif (bodyTerm, OWL_NS.someValuesFrom, None) in owlGraph or (
                bodyTerm,
                OWL_NS.hasValue,
                None,
            ) in owlGraph:
                conjunction.extend(classifyingClause.body)
            elif (bodyTerm, OWL_NS.allValuesFrom, None) in owlGraph:
                raise MalformedDLPFormulaError(
                    "Universal restrictions can only be used as the second argument to rdfs:subClassOf (GCIs)"
                )
            elif (bodyTerm, OWL_NS.unionOf, None) in owlGraph:
                conjunction.append(classifyingClause.body)
            elif (bodyTerm, OWL_NS.intersectionOf, None) in owlGraph:
                conjunction.append(bodyUniTerm)


def T(owlGraph, complementExpansions=[], derivedPreds=[]):
    for s, p, o in owlGraph.triples((None, OWL_NS.complementOf, None)):
        if isinstance(o, URIRef) and isinstance(s, URIRef):
            headLiteral = Uniterm(
                RDF.type,
                [Variable("X"), SkolemizeExistentialClasses(s)],
                newNss=owlGraph.namespaces(),
            )
            yield NormalizeClause(Clause(Tc(owlGraph, o), headLiteral))
    for c, p, d in owlGraph.triples((None, RDFS.subClassOf, None)):
        try:
            yield NormalizeClause(Clause(Tb(owlGraph, c), Th(owlGraph, d)))
        except UnsupportedNegation:
            warnings.warn(
                "Unable to handle negation in DL axiom (%s), skipping" % c,
                SyntaxWarning,
                3,
            )
    for c, p, d in owlGraph.triples((None, OWL_NS.equivalentClass, None)):
        if c not in derivedPreds:
            yield NormalizeClause(Clause(Tb(owlGraph, c), Th(owlGraph, d)))
        yield NormalizeClause(Clause(Tb(owlGraph, d), Th(owlGraph, c)))
    for s, p, o in owlGraph.triples((None, OWL_NS.intersectionOf, None)):
        try:
            if s not in complementExpansions:
                if s in derivedPreds:
                    warnings.warn(
                        "Derived predicate (%s) is defined via a conjunction (consider using a complex GCI) "
                        % owlGraph.qname(s),
                        SyntaxWarning,
                        3,
                    )
                elif isinstance(s, BNode):
                    continue
                conjunction = []
                handleConjunct(conjunction, owlGraph, o)
                body = And(conjunction)
                head = Uniterm(
                    RDF.type,
                    [Variable("X"), SkolemizeExistentialClasses(s)],
                    newNss=owlGraph.namespaces(),
                )
                yield Clause(body, head)
                if isinstance(s, URIRef):
                    if s not in derivedPreds:
                        yield Clause(head, body)
        except UnsupportedNegation:
            warnings.warn(
                "Unable to handle negation in DL axiom (%s), skipping" % s,
                SyntaxWarning,
                3,
            )

    for s, p, o in owlGraph.triples((None, OWL_NS.unionOf, None)):
        if isinstance(s, URIRef):
            body = Or(
                [
                    Uniterm(
                        RDF.type,
                        [Variable("X"), NormalizeBooleanClassOperand(i, owlGraph)],
                        newNss=owlGraph.namespaces(),
                    )
                    for i in Collection(owlGraph, o)
                ]
            )
            head = Uniterm(RDF.type, [Variable("X"), s], newNss=owlGraph.namespaces())
            yield Clause(body, head)
    for s, p, o in owlGraph.triples((None, OWL_NS.inverseOf, None)):
        newVar = Variable(BNode())

        s = SkolemizeExistentialClasses(s) if isinstance(s, BNode) else s
        o = SkolemizeExistentialClasses(o) if isinstance(o, BNode) else o

        body1 = Uniterm(s, [newVar, Variable("X")], newNss=owlGraph.namespaces())
        head1 = Uniterm(o, [Variable("X"), newVar], newNss=owlGraph.namespaces())
        yield Clause(body1, head1)
        newVar = Variable(BNode())
        body2 = Uniterm(o, [Variable("X"), newVar], newNss=owlGraph.namespaces())
        head2 = Uniterm(s, [newVar, Variable("X")], newNss=owlGraph.namespaces())
        yield Clause(body2, head2)
    for s, p, o in owlGraph.triples((None, RDF.type, OWL_NS.TransitiveProperty)):
        y = Variable(BNode())
        z = Variable(BNode())
        x = Variable("X")

        s = SkolemizeExistentialClasses(s) if isinstance(s, BNode) else s

        body = And(
            [
                Uniterm(s, [x, y], newNss=owlGraph.namespaces()),
                Uniterm(s, [y, z], newNss=owlGraph.namespaces()),
            ]
        )
        head = Uniterm(s, [x, z], newNss=owlGraph.namespaces())
        yield Clause(body, head)
    for s, p, o in owlGraph.triples((None, RDFS.subPropertyOf, None)):
        x = Variable("X")
        y = Variable("Y")

        s = SkolemizeExistentialClasses(s) if isinstance(s, BNode) else s
        o = SkolemizeExistentialClasses(o) if isinstance(o, BNode) else o

        body = Uniterm(s, [x, y], newNss=owlGraph.namespaces())
        head = Uniterm(o, [x, y], newNss=owlGraph.namespaces())

        yield Clause(body, head)
    for s, p, o in owlGraph.triples((None, OWL_NS.equivalentProperty, None)):
        x = Variable("X")
        y = Variable("Y")

        s = SkolemizeExistentialClasses(s) if isinstance(s, BNode) else s
        o = SkolemizeExistentialClasses(o) if isinstance(o, BNode) else o

        body = Uniterm(s, [x, y], newNss=owlGraph.namespaces())
        head = Uniterm(o, [x, y], newNss=owlGraph.namespaces())
        yield Clause(body, head)
        yield Clause(head, body)

    for s, p, o in owlGraph.triples((None, RDF.type, OWL_NS.SymmetricProperty)):
        y = Variable("Y")
        x = Variable("X")

        s = SkolemizeExistentialClasses(s) if isinstance(s, BNode) else s

        body = Uniterm(s, [x, y], newNss=owlGraph.namespaces())
        head = Uniterm(s, [y, x], newNss=owlGraph.namespaces())
        yield Clause(body, head)

    for s, p, o in owlGraph.triples_choices((None, [RDFS.range, RDFS.domain], None)):
        s = SkolemizeExistentialClasses(s) if isinstance(s, BNode) else s

        if p == RDFS.range:
            x = Variable("X")
            y = Variable(BNode())
            body = Uniterm(s, [x, y], newNss=owlGraph.namespaces())
            head = Uniterm(RDF.type, [y, o], newNss=owlGraph.namespaces())
            yield Clause(body, head)
        else:
            x = Variable("X")
            y = Variable(BNode())
            body = Uniterm(s, [x, y], newNss=owlGraph.namespaces())
            head = Uniterm(RDF.type, [x, o], newNss=owlGraph.namespaces())
            yield Clause(body, head)


def LloydToporTransformation(clause, fullReduction=True):
    assert isinstance(clause, OriginalClause), repr(clause)
    assert isinstance(clause.body, Condition), repr(clause.body)
    if isinstance(clause.body, Or):
        for atom in clause.body.formulae:
            if hasattr(atom, "next"):
                atom = first(atom)
            for clz in LloydToporTransformation(
                NormalizeClause(Clause(atom, clause.head)), fullReduction=fullReduction
            ):
                yield clz
    elif isinstance(clause.head, OriginalClause):
        yield NormalizeClause(
            Clause(And([clause.body, clause.head.body]), clause.head.head)
        )
    elif fullReduction and (
        (isinstance(clause.head, Exists) and isinstance(clause.head.formula, And))
        or isinstance(clause.head, And)
    ):
        if isinstance(clause.head, Exists):
            head = clause.head.formula
        elif isinstance(clause.head, And):
            head = clause.head
        for i in head:
            for j in LloydToporTransformation(
                Clause(clause.body, i), fullReduction=fullReduction
            ):
                if [i for i in breadth_first(j.head) if isinstance(i, And)]:
                    yield PrepareHeadExistential(NormalizeClause(j))
                else:
                    yield PrepareHeadExistential(j)
    else:
        yield clause


def Th(owlGraph, _class, variable=Variable("X"), position=LHS):
    props = list(set(owlGraph.predicates(subject=_class)))
    if OWL_NS.allValuesFrom in props:
        for s, p, o in owlGraph.triples((_class, OWL_NS.allValuesFrom, None)):
            prop = list(owlGraph.objects(subject=_class, predicate=OWL_NS.onProperty))[
                0
            ]
            newVar = Variable(BNode())
            body = Uniterm(prop, [variable, newVar], newNss=owlGraph.namespaces())
            for head in Th(owlGraph, o, variable=newVar):
                yield Clause(body, head)
    elif OWL_NS.hasValue in props:
        prop = list(owlGraph.objects(subject=_class, predicate=OWL_NS.onProperty))[0]
        o = first(owlGraph.objects(subject=_class, predicate=OWL_NS.hasValue))
        yield Uniterm(prop, [variable, o], newNss=owlGraph.namespaces())
    elif OWL_NS.someValuesFrom in props:
        for s, p, o in owlGraph.triples((_class, OWL_NS.someValuesFrom, None)):
            prop = list(owlGraph.objects(subject=_class, predicate=OWL_NS.onProperty))[
                0
            ]
            newVar = BNode()
            yield And(
                [
                    Uniterm(prop, [variable, newVar], newNss=owlGraph.namespaces()),
                    generatorFlattener(Th(owlGraph, o, variable=newVar)),
                ]
            )
    elif OWL_NS.intersectionOf in props:
        from fuxi.Syntax.InfixOWL import BooleanClass

        yield And([first(Th(owlGraph, h, variable)) for h in BooleanClass(_class)])
    else:
        yield Uniterm(
            RDF.type,
            [
                variable,
                isinstance(_class, BNode)
                and SkolemizeExistentialClasses(_class)
                or _class,
            ],
            newNss=owlGraph.namespaces(),
        )


def Tb(owlGraph, _class, variable=Variable("X")):
    props = list(set(owlGraph.predicates(subject=_class)))
    if OWL_NS.intersectionOf in props and not isinstance(_class, URIRef):
        for s, p, o in owlGraph.triples((_class, OWL_NS.intersectionOf, None)):
            conj = []
            handleConjunct(conj, owlGraph, o, variable)
            return And(conj)
    elif OWL_NS.unionOf in props and not isinstance(_class, URIRef):
        for s, p, o in owlGraph.triples((_class, OWL_NS.unionOf, None)):
            return Or(
                [Tb(owlGraph, c, variable=variable) for c in Collection(owlGraph, o)]
            )
    elif OWL_NS.someValuesFrom in props:
        prop = list(owlGraph.objects(subject=_class, predicate=OWL_NS.onProperty))[0]
        o = list(owlGraph.objects(subject=_class, predicate=OWL_NS.someValuesFrom))[0]
        newVar = Variable(BNode())
        return And(
            [
                Uniterm(prop, [variable, newVar], newNss=owlGraph.namespaces()),
                Tb(owlGraph, o, variable=newVar),
            ]
        )
    elif OWL_NS.hasValue in props:
        prop = list(owlGraph.objects(subject=_class, predicate=OWL_NS.onProperty))[0]
        o = first(owlGraph.objects(subject=_class, predicate=OWL_NS.hasValue))
        return Uniterm(prop, [variable, o], newNss=owlGraph.namespaces())
    elif OWL_NS.complementOf in props:
        return Tc(owlGraph, first(owlGraph.objects(_class, OWL_NS.complementOf)))
    else:
        _classTerm = SkolemizeExistentialClasses(_class)
        return Uniterm(RDF.type, [variable, _classTerm], newNss=owlGraph.namespaces())
