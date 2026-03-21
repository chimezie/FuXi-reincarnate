# -*- coding: utf-8 -*-
# flake8: noqa
import sys
from typing import Any, Mapping, Tuple, Union, List
from pprint import pprint
from rdflib import RDF, URIRef, Variable
from rdflib.util import first
from rdflib.store import Store
from rdflib.plugins.stores.regexmatching import NATIVE_REGEX
from rdflib.query import Result
from rdflib.term import Identifier, IdentifiedNode

from fuxi.SPARQL.utilities import (
    extract_triples_from_query,
    sparql_query_from_result,
)
from rdflib.plugins.sparql.algebra import translateQuery
from rdflib.plugins.sparql.algebra import translateQuery as RenderSPARQLAlgebra
from rdflib.plugins.sparql.parser import parseQuery

from fuxi.Rete.Magic import SetupDDLAndAdornProgram
from fuxi.Rete.Magic import DerivedPredicateIterator
from fuxi.Rete.RuleStore import SetupRuleStore
from fuxi.Rete.TopDown import PrepareSipCollection
from fuxi.Rete.TopDown import RDFTuplesToSPARQL
from fuxi.Rete.TopDown import mergeMappings1To2
from fuxi.Rete.SidewaysInformationPassing import GetOp
from fuxi.Rete.SidewaysInformationPassing import SIPRepresentation
from fuxi.Rete.Util import LOG
from fuxi.LP.BackwardFixpointProcedure import BackwardFixpointProcedure
from fuxi.LP import IdentifyHybridPredicates
from fuxi.Horn.PositiveConditions import BuildUnitermFromTuple
from fuxi.SPARQL import EDBQuery

# for docstring/test purposes
from rdflib import Graph

assert Graph
from rdflib import RDFS

assert RDFS
from rdflib.plugins.sparql.parserutils import Expr as AlgebraExpression
from rdflib.plugins.sparql.parserutils import CompValue

assert AlgebraExpression
from rdflib.plugins.sparql.sparql import Query

assert Query

TOP_DOWN_METHOD = 0
BFP_METHOD = 1

DEFAULT_BUILTIN_MAP = {LOG.equal: "%s  = %s", LOG.notEqualTo: "%s != %s"}


class NonSymmetricBinaryOperator(AlgebraExpression):
    def fetchTerminalExpression(self):
        if self.right.name == "BGP":
            yield self.right
        else:
            for i in self.right.fetchTerminalExpression():
                yield i


class TopDownSPARQLEntailingStore(Store):
    """
    A Store which uses FuXi's magic set "sip strategies" and the in-memory SPARQL Algebra
    implementation as a store-agnostic, top-down decision procedure for
    semanic web SPARQL (OWL2-RL/RIF/N3) entailment regimes.  Exposed
    as a rdflib / layercake-python API for SPARQL datasets with entailment regimes
    Queries are mediated over the SPARQL protocol using global schemas captured
    as SW theories which describe and distinguish their predicate symbols
    """

    context_aware = True
    formula_aware = True
    transaction_aware = True
    regex_matching = NATIVE_REGEX
    batch_unification = True

    def getDerivedPredicates(self, expr, prologue):
        def iter_bgp_triples(bgp):
            if hasattr(bgp, "patterns") and bgp.patterns is not None:
                for item in bgp.patterns:
                    yield item
            else:
                for item in bgp.get("triples", []) or []:
                    yield item

        if isinstance(expr, NonSymmetricBinaryOperator):
            for term in self.getDerivedPredicates(expr.left, prologue):
                yield term
            for term in self.getDerivedPredicates(expr.right, prologue):
                yield term
            return
        if isinstance(expr, CompValue):
            if expr.name == "BGP":
                for item in iter_bgp_triples(expr):
                    if len(item) == 4:
                        s, p, o, _func = item
                    else:
                        s, p, o = item
                    derivedPred = self.derivedPredicateFromTriple((s, p, o))
                    if derivedPred is not None:
                        yield derivedPred
            for key in expr.keys():
                for term in self.getDerivedPredicates(expr.get(key), prologue):
                    yield term
            return
        if isinstance(expr, (list, tuple)):
            for item in expr:
                for term in self.getDerivedPredicates(item, prologue):
                    yield term
            return

    def isaBaseQuery(self, queryString, queryObj=None):
        """
        If the given SPARQL query involves purely base predicates
        it returns it (as a parsed string), otherwise it returns a SPARQL algebra
        instance for top-down evaluation using this store

        >>> graph=Graph()
        >>> topDownStore = TopDownSPARQLEntailingStore(graph.store, graph, derivedPredicates=[RDFS.seeAlso], nsBindings={u"rdfs": str(RDFS)})
        >>> rt=topDownStore.isaBaseQuery("SELECT * { [] rdfs:seeAlso [] }")
        >>> isinstance(rt,(BasicGraphPattern, AlgebraExpression))
        True
        >>> rt=topDownStore.isaBaseQuery("SELECT * { [] a [] }")
        >>> isinstance(rt,(Query, str)) #doctest: +SKIP
        True
        >>> rt=topDownStore.isaBaseQuery("SELECT * { [] a [] OPTIONAL { [] rdfs:seeAlso [] } }")
        >>> isinstance(rt,(BasicGraphPattern, AlgebraExpression))
        True
        """
        from rdflib.graph import Graph
        from rdflib.namespace import NamespaceManager
        from rdflib.plugins.sparql.sparql import Prologue
        from rdflib.plugins.sparql.parser import parseQuery
        from rdflib.plugins.sparql import sparql as sparqlModule

        if queryObj is not None:
            query = queryObj
        else:
            query = parseQuery(queryString)

        prologue = getattr(query, "prologue", None)
        if prologue is None:
            prologue = Prologue()
            query.prologue = prologue
        if not getattr(prologue, "namespace_manager", None):
            prologue.namespace_manager = NamespaceManager(Graph())
        for prefix, nsInst in list(self.nsBindings.items()):
            prologue.namespace_manager.bind(prefix, nsInst, override=False)

        sparqlModule.prologue = prologue
        if hasattr(query, "algebra") and query.algebra is not None:
            algebra = query.algebra
        else:
            algebra = RenderSPARQLAlgebra(query, initNs=self.nsBindings).algebra

        return first(self.getDerivedPredicates(algebra, prologue)) and algebra or query

    def __init__(
        self,
        store,
        edb,
        derivedPredicates=None,
        idb=None,
        DEBUG=False,
        nsBindings={},
        decisionProcedure=BFP_METHOD,
        templateMap=None,
        identifyHybridPredicates=False,
        hybridPredicates=[],
    ):
        self.dataset = store
        if hasattr(store, "_db"):
            self._db = store._db
        self.idb = idb and idb or set()
        self.edb = edb
        if derivedPredicates is None:
            self.derivedPredicates = list(DerivedPredicateIterator(self.edb, self.idb))
        else:
            self.derivedPredicates = derivedPredicates
        self.DEBUG = DEBUG
        self.nsBindings = nsBindings
        self.edb.templateMap = (
            DEFAULT_BUILTIN_MAP if templateMap is None else templateMap
        )
        self.queryNetworks = []
        self.edbQueries = set()
        if identifyHybridPredicates:
            self.hybridPredicates = IdentifyHybridPredicates(
                edb, self.derivedPredicates
            )
        else:
            self.hybridPredicates = hybridPredicates if hybridPredicates else []

        # Update derived predicate list for synchrony with hybrid predicate
        # rules
        for hybridPred in self.hybridPredicates:
            self.derivedPredicates.remove(hybridPred)
            if isinstance(self.derivedPredicates, list):
                self.derivedPredicates.append(URIRef(hybridPred + "_derived"))
            elif isinstance(self.derivedPredicates, set):
                self.derivedPredicates.add(URIRef(hybridPred + "_derived"))
            else:
                import warnings

                warnings.warn(
                    "Collection of derived predicates is neither a list or a set.",
                    RuntimeWarning,
                )

        # Add a cache of the namespace bindings to use later in coining Qnames in
        # generated queries
        self.edb.revNsMap = {}
        self.edb.nsMap = {}
        for k, v in list(nsBindings.items()):
            self.edb.revNsMap[v] = k
            self.edb.nsMap[k] = v
        for key, uri in self.edb.namespaces():
            self.edb.revNsMap[uri] = key
            self.edb.nsMap[key] = uri

    def invokeDecisionProcedure(self, tp, factGraph, bindings, debug, sipCollection):
        isNotGround = first(filter(lambda i: isinstance(i, Variable), tp))
        rule_store, rule_graph, network = SetupRuleStore(makeNetwork=True)
        bfp = BackwardFixpointProcedure(
            factGraph,
            network,
            self.derivedPredicates,
            tp,
            sipCollection,
            hybridPredicates=self.hybridPredicates,
            debug=self.DEBUG,
        )
        bfp.createTopDownReteNetwork(self.DEBUG)
        bfp.answers(debug=self.DEBUG)
        self.queryNetworks.append((bfp.metaInterpNetwork, tp))
        self.edbQueries.update(bfp.edbQueries)
        if self.DEBUG:
            print("Goal/Query: ", tp)
            print(
                "Query was not ground"
                if isNotGround is not None
                else "Query was ground"
            )
        if isNotGround is not None:
            for item in bfp.goalSolutions:
                yield item, None
        else:
            yield True, None
        if debug:
            print(bfp.metaInterpNetwork)
            bfp.metaInterpNetwork.reportConflictSet(True, sys.stderr, self.nsBindings)
            for query in self.edbQueries:
                print("Dispatched query against dataset: ", query.asSPARQL())

    def conjunctiveSipStrategy(self, goalsRemaining, factGraph, bindings=None):
        """
        Given a conjunctive set of triples, invoke sip-strategy passing
        on intermediate solutions to facilitate 'join' behavior
        """
        bindings = bindings if bindings else {}
        try:
            tp = next(goalsRemaining)
            assert isinstance(bindings, dict)
            dPred = self.derivedPredicateFromTriple(tp)
            if dPred is None:
                baseEDBQuery = EDBQuery(
                    [BuildUnitermFromTuple(tp)], self.edb, bindings=bindings
                )
                if self.DEBUG:
                    print("Evaluating TP against EDB:%s" % baseEDBQuery.asSPARQL())
                query, rt = baseEDBQuery.evaluate()
                # _vars = baseEDBQuery.returnVars
                for item in rt:
                    bindings.update(item)
                for ansDict in self.conjunctiveSipStrategy(
                    goalsRemaining, factGraph, bindings
                ):
                    yield ansDict

            else:
                queryLit = BuildUnitermFromTuple(tp)
                currentOp = GetOp(queryLit)
                queryLit.setOperator(currentOp)
                query = EDBQuery([queryLit], self.edb, bindings=bindings)
                if bindings:
                    tp = first(query.formulae).toRDFTuple()
                if self.DEBUG:
                    print("Goal/Query: ", query.asSPARQL())
                SetupDDLAndAdornProgram(
                    self.edb,
                    self.idb,
                    [tp],
                    derivedPreds=self.derivedPredicates,
                    ignoreUnboundDPreds=True,
                    hybridPreds2Replace=self.hybridPredicates,
                )

                if self.hybridPredicates:
                    lit = BuildUnitermFromTuple(tp)
                    op = GetOp(lit)
                    if op in self.hybridPredicates:
                        lit.setOperator(URIRef(op + "_derived"))
                        tp = lit.toRDFTuple()

                sipCollection = PrepareSipCollection(self.edb.adornedProgram)
                if self.DEBUG and sipCollection:
                    for sip in SIPRepresentation(sipCollection):
                        print(sip)
                    pprint(list(self.edb.adornedProgram), sys.stderr)
                elif self.DEBUG:
                    print("No SIP graph.")
                for nextAnswer, ns in self.invokeDecisionProcedure(
                    tp, factGraph, bindings, self.DEBUG, sipCollection
                ):
                    nonGroundGoal = isinstance(nextAnswer, dict)
                    if nonGroundGoal or nextAnswer:
                        # Either we recieved bindings from top-down evaluation
                        # or we (successfully) proved a ground query
                        if not nonGroundGoal:
                            # Attempt to prove a ground query, return the
                            # response
                            rt = nextAnswer
                        else:
                            # Recieved solutions to 'open' query, merge with given bindings
                            # and continue
                            rt = mergeMappings1To2(bindings, nextAnswer)
                        # either answers were provided (the goal wasn't grounded) or
                        # the goal was ground and successfully proved
                        for ansDict in self.conjunctiveSipStrategy(
                            goalsRemaining, factGraph, rt
                        ):
                            yield ansDict
        except StopIteration:
            yield bindings

    def derivedPredicateFromTriple(self, triple):
        """
        Given a triple, return its predicate (if derived)
        or None otherwise
        """
        (s, p, o) = triple
        if p in self.derivedPredicates or p in self.hybridPredicates:
            return p
        elif (
            p == RDF.type
            and o != p
            and (o in self.derivedPredicates or o in self.hybridPredicates)
        ):
            return o
        else:
            return None

    def solve_triple_pattern(
        self,
        triples: List[Tuple[Identifier, Identifier, Identifier]],
        initNs: Mapping[str, Any],
        is_ask: bool = False,
        projected_vars: List[Variable] | None = None,
    ):
        select_bindings: List[Mapping[Variable, Identifier]] = []
        groundConjunct = []
        derivedConjunct = []
        for item in triples:
            if len(item) == 4:
                s, p, o, _func = item
            else:
                s, p, o = item
            if self.derivedPredicateFromTriple((s, p, o)) is None:
                groundConjunct.append(BuildUnitermFromTuple((s, p, o), initNs))
            else:
                derivedConjunct.append(BuildUnitermFromTuple((s, p, o), initNs))
        ans = None
        askResult = True
        if groundConjunct:
            baseEDBQuery = EDBQuery(groundConjunct, self.edb)
            subQuery, ans = baseEDBQuery.evaluate(self.DEBUG)
            if is_ask:
                if not bool(ans):
                    askResult = False
            else:
                if ans:
                    for binding in ans:
                        select_bindings.append(binding)
        if not is_ask or askResult:
            for derivedLiteral in derivedConjunct:
                goal = derivedLiteral.toRDFTuple()
                # Solve ground, derived goal directly
                SetupDDLAndAdornProgram(
                    self.edb,
                    self.idb,
                    [goal],
                    derivedPreds=self.derivedPredicates,
                    ignoreUnboundDPreds=True,
                    hybridPreds2Replace=self.hybridPredicates,
                )

                if self.hybridPredicates:
                    lit = BuildUnitermFromTuple(goal)
                    op = GetOp(lit)
                    if op in self.hybridPredicates:
                        lit.setOperator(URIRef(op + "_derived"))
                        goal = lit.toRDFTuple()

                sipCollection = PrepareSipCollection(self.edb.adornedProgram)
                if self.DEBUG and sipCollection:
                    for sip in SIPRepresentation(sipCollection):
                        print(sip)
                    pprint(list(self.edb.adornedProgram))
                elif self.DEBUG:
                    print("No SIP graph.")
                if is_ask:
                    rt, node = first(
                        self.invokeDecisionProcedure(
                            goal, self.edb, {}, self.DEBUG, sipCollection
                        )
                    )
                    if not rt:
                        askResult = False
                        break
                else:
                    for rt, node in self.invokeDecisionProcedure(
                        goal, self.edb, {}, self.DEBUG, sipCollection
                    ):
                        if isinstance(rt, dict):
                            select_bindings.append(rt)
                        elif rt:
                            select_bindings.append({})
        if is_ask:
            ask_result = Result("ASK")
            ask_result.askAnswer = askResult
            return sparql_query_from_result(ask_result)
        else:
            select_result = Result("SELECT")
            if projected_vars is None:
                projected_vars = []
                for binding in select_bindings:
                    for var in binding:
                        if var not in projected_vars:
                            projected_vars.append(var)

            if projected_vars:
                projected_bindings = []
                for binding in select_bindings:
                    projected_bindings.append(
                        {var: binding[var] for var in projected_vars if var in binding}
                    )
            else:
                projected_bindings = select_bindings

            select_result.vars = projected_vars
            select_result.bindings = projected_bindings
            return sparql_query_from_result(select_result)

    def query(
        self,
        query: Query | str,
        # dataSetBase,
        # extensionFunctions,
        initNs: Mapping[str, Any],  # noqa: N803
        initBindings: Mapping[str, Identifier],  # noqa: N803
        queryGraph: str,  # noqa: N803
        **kwargs: Any,
    ):
        """
        The default 'native' SPARQL implementation is based on sparql-p's expansion trees
        layered on top of the read-only RDF APIs of the underlying store
        """
        from rdflib.plugins.sparql.evaluate import evalQuery

        if isinstance(query, Query):
            raise NotImplementedError("Query object not supported")
        query_string = query
        parsed_query = parseQuery(query_string)
        prologue, query = parsed_query
        query_name = query.name
        if query_name == "AskQuery":
            triples = extract_triples_from_query(query, initNs)
            # This is a ground, BGP, involving IDB and can be solved directly
            # using top-down decision procedure
            # First separate out conjunct into EDB and IDB predicates
            # (solving the former first)
            from fuxi.SPARQL import EDBQuery

            return self.solve_triple_pattern(triples, initNs, is_ask=True)
        else:
            query_object = translateQuery(parsed_query, None, initNs)
            triples = extract_triples_from_query(query_object.algebra, initNs)
            projected_vars = None
            if hasattr(query_object.algebra, "PV"):
                projected_vars = list(query_object.algebra.PV)
            rt = self.solve_triple_pattern(
                triples, initNs, projected_vars=projected_vars
            )
            return rt

    def batch_unify(self, patterns):
        """
        Perform RDF triple store-level unification of a list of triple
        patterns (4-item tuples which correspond to a SPARQL triple pattern
        with an additional constraint for the graph name).

        Uses a SW sip-strategy implementation to solve the conjunctive goal
        and yield unified bindings

        :Parameters:
        - `patterns`: a list of 4-item tuples where any of the items can be
           one of: Variable, URIRef, BNode, or Literal.

        Returns a generator over dictionaries of solutions to the list of
        triple patterns that are entailed by the regime.
        """
        dPreds = set()
        goals = []
        for s, p, o, g in patterns:
            goals.append((s, p, o))
            dPred = o if p == RDF.type else p
            if dPred in self.hybridPredicates:
                dPreds.add(URIRef(dPred + "_derived"))
            else:
                dPreds.add(p == RDF.type and o or p)
        if set(dPreds).intersection(self.derivedPredicates):
            # Patterns involve derived predicates
            self.batch_unification = False
            for ansDict in self.conjunctiveSipStrategy(iter(goals), self.edb):
                yield ansDict
            self.batch_unification = True
        else:
            # conjunctive query involving EDB predicateso only
            vars = []
            triples = []
            for pat in patterns:
                triples.append(BuildUnitermFromTuple(pat[:3]))
                vars.extend([term for term in pat[:3] if isinstance(term, Variable)])

            query = RDFTuplesToSPARQL(triples, self.edb, vars=vars)
            if self.DEBUG:
                print("Batch unify resolved against EDB")
                print(query)

            rt = self.edb.query(query, initNs=self.nsBindings)

            rt = (
                len(vars) > 1
                and (dict([(vars[idx], i) for idx, i in enumerate(v)]) for v in rt)
                or (dict([(vars[0], v)]) for v in rt)
            )
            for item in rt:
                yield item

    def close(self, commit_pending_transaction=False):
        """
        This closes the database connection. The commit_pending_transaction parameter specifies whether to
        commit all pending transactions before closing (if the store is transactional).
        """
        return self.dataset.close(commit_pending_transaction)

    def destroy(self, configuration):
        """
        This destroys the instance of the store identified by the configuration string.
        """
        return self.dataset.destroy(configuration)

    def triples_choices(self, triple, context=None):
        """
        A variant of triples that can take a list of terms instead of a single
        term in any slot.  Stores can implement this to optimize the response time
        from the default 'fallback' implementation, which will iterate
        over each term in the list and dispatch to tripless
        """
        for rt in self.dataset.triples_choices(triple, context):
            yield rt

    def triples(self, triple, context=None):
        """
        A generator over all the triples matching the pattern. Pattern can
        include any objects for used for comparing against nodes in the store, for
        example, REGEXTerm, URIRef, Literal, BNode, Variable, Graph, QuotedGraph, Date? DateRange?

        A conjunctive query can be indicated by either providing a value of None
        for the context or the identifier associated with the Conjunctive Graph (if it's context aware).
        """
        return self.solve_triple_pattern([triple], self.nsBindings)

    def __len__(self, context=None):
        """
        Number of statements in the store. This should only account for non-quoted (asserted) statements
        if the context is not specified, otherwise it should return the number of statements in the formula or context given.
        """
        return len(self.dataset)

    def contexts(self, triple=None):
        """
        Generator over all contexts in the graph. If triple is specified, a generator over all
        contexts the triple is in.
        """
        for ctx in self.dataset.contexts(triple):
            yield ctx

    # Optional Namespace methods

    def bind(self, prefix, namespace):
        self.nsBindings[prefix] = namespace
        # self.targetGraph.bind(prefix, namespace)

    def prefix(self, namespace):
        revDict = dict([(v, k) for k, v in list(self.nsBindings.items())])
        return revDict.get(namespace)

    def namespace(self, prefix):
        return self.nsBindings.get(prefix)

    def namespaces(self):
        for prefix, nsUri in list(self.nsBindings.items()):
            yield prefix, nsUri

    # Optional Transactional methods

    def commit(self):
        self.dataset.commit()

    def rollback(self):
        self.dataset.rollback()


def test():
    import doctest

    doctest.testmod()


if __name__ == "__main__":
    test()

# from fuxi.SPARQL.BackwardChainingStore import TopDownSPARQLEntailingStore
