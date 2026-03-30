# -*- coding: utf-8 -*-
# flake8: noqa
import sys
from typing import Any, Mapping
from pprint import pprint

from pyparsing import ParseResults

from rdflib import RDF, URIRef, Variable
from rdflib.util import first
from rdflib.store import Store
from rdflib.plugins.stores.regexmatching import NATIVE_REGEX
from rdflib.query import Result
from rdflib.term import Identifier, IdentifiedNode

from fuxi.SPARQL.utilities import extract_triples_from_query, sparql_query_from_result
from rdflib.plugins.sparql.algebra import translateQuery
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

    def get_derived_predicates(self, expr, prologue):
        def iter_bgp_triples(bgp):
            if hasattr(bgp, "patterns") and bgp.patterns is not None:
                for item in bgp.patterns:
                    yield item
            else:
                for item in bgp.get("triples", []) or []:
                    yield item

        if isinstance(expr, NonSymmetricBinaryOperator):
            for term in self.get_derived_predicates(expr.left, prologue):
                yield term
            for term in self.get_derived_predicates(expr.right, prologue):
                yield term
            return
        if isinstance(expr, CompValue):
            if expr.name == "BGP":
                for item in iter_bgp_triples(expr):
                    if len(item) == 4:
                        s, p, o, _func = item
                    else:
                        s, p, o = item
                    derived_pred = self.derived_predicate_from_triple((s, p, o))
                    if derived_pred is not None:
                        yield derived_pred
            for key in expr.keys():
                for term in self.get_derived_predicates(expr.get(key), prologue):
                    yield term
            return
        if isinstance(expr, (list, tuple)):
            for item in expr:
                for term in self.get_derived_predicates(item, prologue):
                    yield term
            return

    def is_a_base_query(self, query_string, query_obj=None):
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

        if query_obj is not None:
            query = query_obj
        else:
            query = parseQuery(query_string)

        prologue = getattr(query, "prologue", None)
        if prologue is None:
            prologue = Prologue()
            query.prologue = prologue
        if not getattr(prologue, "namespace_manager", None):
            prologue.namespace_manager = NamespaceManager(Graph())
        for prefix, ns_inst in list(self.ns_bindings.items()):
            prologue.namespace_manager.bind(prefix, ns_inst, override=False)

        sparqlModule.prologue = prologue
        if hasattr(query, "algebra") and query.algebra is not None:
            algebra = query.algebra
        else:
            algebra = translateQuery(query, init_ns=self.ns_bindings).algebra

        return first(self.get_derived_predicates(algebra, prologue)) and algebra or query

    def __init__(
        self,
        store,
        edb,
        derived_predicates=None,
        idb=None,
        DEBUG=False,
        ns_bindings=None,
        decision_procedure=BFP_METHOD,
        template_map=None,
        identify_hybrid_predicates=False,
        hybrid_predicates=None,
    ):
        self.dataset = store
        if hasattr(store, "_db"):
            self._db = store._db
        self.idb = idb and idb or set()
        self.edb = edb
        if derived_predicates is None:
            self.derived_predicates = list(DerivedPredicateIterator(self.edb, self.idb))
        else:
            self.derived_predicates = derived_predicates
        self.DEBUG = DEBUG
        self.ns_bindings = ns_bindings if ns_bindings is not None else {}
        self.edb.template_map = (
            DEFAULT_BUILTIN_MAP if template_map is None else template_map
        )
        self.query_networks = []
        self.edb_queries = set()
        if identify_hybrid_predicates:
            self.hybrid_predicates = IdentifyHybridPredicates(
                edb, self.derived_predicates
            )
        else:
            self.hybrid_predicates = (
                hybrid_predicates if hybrid_predicates is not None else []
            )

        # Update derived predicate list for synchrony with hybrid predicate
        # rules
        for hybrid_pred in self.hybrid_predicates:
            if hybrid_pred in self.derived_predicates:
                self.derived_predicates.remove(hybrid_pred)
            if isinstance(self.derived_predicates, list):
                self.derived_predicates.append(URIRef(hybrid_pred + "_derived"))
            elif isinstance(self.derived_predicates, set):
                self.derived_predicates.add(URIRef(hybrid_pred + "_derived"))
            else:
                import warnings

                warnings.warn(
                    "Collection of derived predicates is neither a list or a set.",
                    RuntimeWarning,
                )

        # Add a cache of the namespace bindings to use later in coining Qnames in
        # generated queries
        self.edb.rev_ns_map = {}
        self.edb.ns_map = {}
        for k, v in list(ns_bindings.items()):
            self.edb.rev_ns_map[v] = k
            self.edb.ns_map[k] = v
        for key, uri in self.edb.namespaces():
            self.edb.rev_ns_map[uri] = key
            self.edb.ns_map[key] = uri

    def invoke_decision_procedure(self, tp, fact_graph, bindings, debug, sip_collection):
        is_not_ground = first(filter(lambda i: isinstance(i, Variable), tp))
        rule_store, rule_graph, network = SetupRuleStore(makeNetwork=True)
        bfp = BackwardFixpointProcedure(
            fact_graph,
            network,
            self.derived_predicates,
            tp,
            sip_collection,
            hybridPredicates=self.hybrid_predicates,
            debug=self.DEBUG,
        )
        bfp.createTopDownReteNetwork(self.DEBUG)
        response = bfp.answers(debug=self.DEBUG)
        self.query_networks.append((bfp.metaInterpNetwork, tp))
        self.edb_queries.update(bfp.edbQueries)
        if self.DEBUG:
            print("Goal/Query: ", tp)
            print(
                "Query was not ground"
                if is_not_ground is not None
                else "Query was ground"
            )
            print("Inferred facts from adorned rules:\n",
                  bfp.metaInterpNetwork.inferredFacts.serialize(format="turtle"))
        if is_not_ground is not None:
            for item in bfp.goalSolutions:
                yield item, None
        else:
            yield response, None
        if debug:
            print(bfp.metaInterpNetwork)
            bfp.metaInterpNetwork.reportConflictSet(True, sys.stderr, self.ns_bindings)
            for query in self.edb_queries:
                print("Dispatched query against dataset: ", query.as_sparql())

    def conjunctive_sip_strategy(self, goals_remaining, fact_graph, bindings=None):
        """
        Given a conjunctive set of triples, invoke sip-strategy passing
        on intermediate solutions to facilitate 'join' behavior
        """
        bindings = bindings if bindings else {}
        try:
            tp = next(goals_remaining)
            assert isinstance(bindings, dict)
            d_pred = self.derived_predicate_from_triple(tp)
            if d_pred is None:
                base_edb_query = EDBQuery(
                    [BuildUnitermFromTuple(tp)], self.edb, bindings=bindings
                )
                if self.DEBUG:
                    print("Evaluating TP against EDB:%s" % base_edb_query.as_sparql())
                query, rt = base_edb_query.evaluate()
                # _vars = base_edb_query.return_vars
                for item in rt:
                    bindings.update(item)
                for ans_dict in self.conjunctive_sip_strategy(
                    goals_remaining, fact_graph, bindings
                ):
                    yield ans_dict

            else:
                query_lit = BuildUnitermFromTuple(tp)
                current_op = GetOp(query_lit)
                query_lit.setOperator(current_op)
                query = EDBQuery([query_lit], self.edb, bindings=bindings)
                if bindings:
                    tp = first(query.formulae).toRDFTuple()
                if self.DEBUG:
                    print("Goal/Query: ", query.as_sparql())
                SetupDDLAndAdornProgram(
                    self.edb,
                    self.idb,
                    [tp],
                    derived_preds=self.derived_predicates,
                    ignore_unbound_d_preds=True,
                    hybrid_preds_2_replace=self.hybrid_predicates,
                )

                if self.hybrid_predicates:
                    lit = BuildUnitermFromTuple(tp)
                    op = GetOp(lit)
                    if op in self.hybrid_predicates:
                        lit.setOperator(URIRef(op + "_derived"))
                        tp = lit.toRDFTuple()

                sip_collection = PrepareSipCollection(self.edb.adorned_program)
                if self.DEBUG and sip_collection:
                    for sip in SIPRepresentation(sip_collection):
                        print(sip)
                    pprint(list(self.edb.adorned_program), sys.stderr)
                elif self.DEBUG:
                    print("No SIP graph.")
                for next_answer, ns in self.invoke_decision_procedure(
                    tp, fact_graph, bindings, self.DEBUG, sip_collection
                ):
                    non_ground_goal = isinstance(next_answer, dict)
                    if non_ground_goal or next_answer:
                        # Either we recieved bindings from top-down evaluation
                        # or we (successfully) proved a ground query
                        if not non_ground_goal:
                            # Attempt to prove a ground query, return the
                            # response
                            rt = next_answer
                        else:
                            # Recieved solutions to 'open' query, merge with given bindings
                            # and continue
                            rt = mergeMappings1To2(bindings, next_answer)
                        # either answers were provided (the goal wasn't grounded) or
                        # the goal was ground and successfully proved
                        for ans_dict in self.conjunctive_sip_strategy(
                            goals_remaining, fact_graph, rt
                        ):
                            yield ans_dict
        except StopIteration:
            yield bindings

    def derived_predicate_from_triple(self, triple):
        """
        Given a triple, return its predicate (if derived)
        or None otherwise
        """
        (s, p, o) = triple
        if p in self.derived_predicates or p in self.hybrid_predicates:
            return p
        elif (
            p == RDF.type
            and o != p
            and (o in self.derived_predicates or o in self.hybrid_predicates)
        ):
            return o
        else:
            return None

    def solve_triple_pattern(
        self,
        triples: list[tuple[Identifier, Identifier, Identifier]],
        init_ns: Mapping[str, Any],
        is_ask: bool = False,
        projected_vars: list[Variable] | None = None,
    ):
        select_bindings: list[Mapping[Variable, Identifier]] = []
        ground_conjunct = []
        derived_conjunct = []
        for item in triples:
            if len(item) == 4:
                s, p, o, _func = item
            else:
                s, p, o = item
            if self.derived_predicate_from_triple((s, p, o)) is None:
                ground_conjunct.append(BuildUnitermFromTuple((s, p, o), init_ns))
            else:
                derived_conjunct.append(BuildUnitermFromTuple((s, p, o), init_ns))
        ans = None
        ask_result = True
        if ground_conjunct:
            base_edb_query = EDBQuery(ground_conjunct, self.edb)
            sub_query, ans = base_edb_query.evaluate(self.DEBUG)
            if is_ask:
                if not bool(ans):
                    ask_result = False
            else:
                if ans:
                    for binding in ans:
                        select_bindings.append(binding)
        if not is_ask or ask_result:
            for derived_literal in derived_conjunct:
                goal = derived_literal.toRDFTuple()
                # Solve ground, derived goal directly
                SetupDDLAndAdornProgram(
                    self.edb,
                    self.idb,
                    [goal],
                    derivedPreds=self.derived_predicates,
                    ignoreUnboundDPreds=True,
                    hybridPreds2Replace=self.hybrid_predicates,
                )

                if self.hybrid_predicates:
                    lit = BuildUnitermFromTuple(goal)
                    op = GetOp(lit)
                    if op in self.hybrid_predicates:
                        lit.setOperator(URIRef(op + "_derived"))
                        goal = lit.toRDFTuple()

                sip_collection = PrepareSipCollection(self.edb.adornedProgram)
                if self.DEBUG and sip_collection:
                    for sip in SIPRepresentation(sip_collection):
                        print(sip)
                    pprint(list(self.edb.adornedProgram))
                elif self.DEBUG:
                    print("No SIP graph.")
                if is_ask:
                    rt, node = first(
                        self.invoke_decision_procedure(
                            goal, self.edb, {}, self.DEBUG, sip_collection
                        )
                    )
                    if not rt:
                        ask_result = False
                        break
                else:
                    for rt, node in self.invoke_decision_procedure(
                        goal, self.edb, {}, self.DEBUG, sip_collection
                    ):
                        if isinstance(rt, dict):
                            select_bindings.append(rt)
                        elif rt:
                            select_bindings.append({})
        if is_ask:
            ask_result_obj = Result("ASK")
            ask_result_obj.ask_answer = ask_result
            return sparql_query_from_result(ask_result_obj)
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
        init_ns: Mapping[str, Any],  # noqa: N803
        init_bindings: Mapping[str, Identifier],  # noqa: N803
        query_graph: str,  # noqa: N803
        **kwargs: Any,
    ):
        """
        The default 'native' SPARQL implementation is based on sparql-p's expansion trees
        layered on top of the read-only RDF APIs of the underlying store
        """
        from rdflib.plugins.sparql.evaluate import evalQuery

        if isinstance(query, ParseResults):
            parsed_result = query
            prologue, parsed_query = query
        else:
            parsed_result = parseQuery(query)
            prologue, parsed_query = parsed_result
        query_name = parsed_query.name
        if query_name == "AskQuery":
            _service_url, triples = extract_triples_from_query(parsed_query, init_ns)
            # This is a ground, BGP, involving IDB and can be solved directly
            # using top-down decision procedure
            # First separate out conjunct into EDB and IDB predicates
            # (solving the former first)
            from fuxi.SPARQL import EDBQuery

            return self.solve_triple_pattern(triples, init_ns, is_ask=True)
        else:
            query_object = translateQuery(parsed_result, None, init_ns)
            _service_url, triples = extract_triples_from_query(
                query_object.algebra, init_ns
            )
            projected_vars = None
            if hasattr(query_object.algebra, "PV"):
                projected_vars = list(query_object.algebra.PV)
            rt = self.solve_triple_pattern(
                triples, init_ns, projected_vars=projected_vars
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
        d_preds = set()
        goals = []
        for s, p, o, g in patterns:
            goals.append((s, p, o))
            d_pred = o if p == RDF.type else p
            if d_pred in self.hybrid_predicates:
                d_preds.add(URIRef(d_pred + "_derived"))
            else:
                d_preds.add(p == RDF.type and o or p)
        if set(d_preds).intersection(self.derived_predicates):
            # Patterns involve derived predicates
            self.batch_unification = False
            for ans_dict in self.conjunctive_sip_strategy(iter(goals), self.edb):
                yield ans_dict
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

            rt = self.edb.query(query, init_ns=self.ns_bindings)

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
        return self.solve_triple_pattern([triple], self.ns_bindings)

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
        self.ns_bindings[prefix] = namespace
        # self.targetGraph.bind(prefix, namespace)

    def prefix(self, namespace):
        rev_dict = dict([(v, k) for k, v in list(self.ns_bindings.items())])
        return rev_dict.get(namespace)

    def namespace(self, prefix):
        return self.ns_bindings.get(prefix)

    def namespaces(self):
        for prefix, ns_uri in list(self.ns_bindings.items()):
            yield prefix, ns_uri

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
