# -*- coding: utf-8 -*-
# flake8: noqa
import copy
import sys
import warnings
from collections.abc import Mapping
from typing import Any, Iterable
from pprint import pprint

from pyparsing import ParseResults
from fuxi.types import Triple
from fuxi.Horn.HornRules import Rule, Ruleset
from rdflib import RDF, URIRef, Variable
from rdflib.util import first
from rdflib.store import Store
from rdflib.plugins.stores.regexmatching import NATIVE_REGEX
from rdflib.query import Result
from rdflib.term import Identifier

from fuxi.SPARQL.utilities import extract_triples_from_query, sparql_query_from_result
from rdflib.plugins.sparql.algebra import translateQuery
from rdflib.plugins.sparql.parser import parseQuery

from fuxi.Rete.Magic import setup_ddl_and_adorn_program
from fuxi.Rete.Magic import derived_predicate_iterator
from fuxi.Rete.RuleStore import setup_rule_store
from fuxi.Rete.TopDown import prepare_sip_collection
from fuxi.Rete.TopDown import rdf_tuples_to_sparql
from fuxi.Rete.TopDown import merge_mappings1_to2
from fuxi.Rete.SidewaysInformationPassing import get_op
from fuxi.Rete.SidewaysInformationPassing import sip_representation
from fuxi.Rete.Util import LOG
from fuxi.LP.BackwardFixpointProcedure import BackwardFixpointProcedure
from fuxi.LP import identify_hybrid_predicates as identify_hybrid_predicates_fn
from fuxi.Horn.PositiveConditions import build_uniterm_from_tuple
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
    def fetch_terminal_expression(self):
        if self.right.name == "BGP":
            yield self.right
        else:
            for i in self.right.fetch_terminal_expression():
                yield i


class TopDownSPARQLEntailingStore(Store):
    """
    A SPARQL store that mediates queries via top-down entailment.

    This store uses FuXi's magic set (SIP) strategies and SPARQL algebra
    rewriting to answer queries against derived predicates without
    materializing full closure. It supports OWL2-RL, RIF-Core, and N3
    entailment regimes by delegating base predicates to the underlying
    RDF store and evaluating derived predicates via the ruleset.

    Key configuration:

    - ``derived_predicates`` (or ``derivedPredicates``): IDB predicates.
    - ``decision_procedure``: choose BFP vs top-down methods.
    - ``identify_hybrid_predicates``: detect predicates that are both IDB
      and EDB for SIP optimization.
    - ``ns_bindings``: namespace bindings for query mediation.
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
        >>> topDownStore = TopDownSPARQLEntailingStore(graph.store,graph)
        >>> rt=topDownStore.is_a_base_query("SELECT * { [] rdfs:seeAlso [] }")
        >>> isinstance(rt,(BasicGraphPattern, AlgebraExpression))
        True
        >>> rt=topDownStore.is_a_base_query("SELECT * { [] a [] }")
        >>> isinstance(rt,(Query, str)) #doctest: +SKIP
        True
        >>> rt=topDownStore.is_a_base_query("SELECT * { [] a [] OPTIONAL { [] rdfs:seeAlso [] } }")
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

        return (
            first(self.get_derived_predicates(algebra, prologue)) and algebra or query
        )

    def __init__(
        self,
        store: Store,
        edb: Graph,
        derived_predicates: list[Identifier] = None,
        idb: Iterable[Rule] | Ruleset = None,
        debug: bool = False,
        ns_bindings: dict[str, Identifier] = None,
        template_map: dict[Identifier, str] = None,
        identify_hybrid_predicates: bool = False,
        hybrid_predicates: Iterable[Identifier] = None,
    ):
        self.action_propagation_info = None
        self.meta_evaluation = None
        self.meta_interpretation_seeds = None
        self.query_propagation_info = None
        self.dataset = store
        if hasattr(store, "_db"):
            self._db = store._db
        self.idb = idb and idb or set()
        self.edb = edb
        if derived_predicates is None:
            self.derived_predicates = list(
                derived_predicate_iterator(self.edb, self.idb)
            )
        else:
            self.derived_predicates = derived_predicates
        self.debug = debug
        self.ns_bindings = ns_bindings if ns_bindings is not None else {}
        self.edb.template_map = (
            DEFAULT_BUILTIN_MAP if template_map is None else template_map
        )
        self.query_networks = []
        self.edb_queries = set()
        if identify_hybrid_predicates:
            self.hybrid_predicates = identify_hybrid_predicates_fn(
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
                warnings.warn(
                    "Collection of derived predicates is neither a list or a set.",
                    RuntimeWarning,
                )

        # Add a cache of the namespace bindings to use later in coining Qnames in
        # generated queries
        self.edb.rev_ns_map = {}
        self.edb.ns_map = {}
        for k, v in list(self.ns_bindings.items()):
            self.edb.rev_ns_map[v] = k
            self.edb.ns_map[k] = v
        for key, uri in self.edb.namespaces():
            self.edb.rev_ns_map[uri] = key
            self.edb.ns_map[key] = uri
        # Mapping from goal triple pattern to its Uniterm representation, the adorned program and SIP collections
        # used to solve the goal, the inferred facts, and the meta interpretation network
        self.goal_rule_sip_info: dict[Triple, tuple] = {}

    def invoke_decision_procedure(
        self, tp, fact_graph, bindings, debug, sip_collection
    ):
        is_not_ground = first(filter(lambda i: isinstance(i, Variable), tp))
        rule_store, rule_graph, network = setup_rule_store(make_network=True)
        bfp = BackwardFixpointProcedure(
            fact_graph,
            network,
            self.derived_predicates,
            tp,
            sip_collection,
            hybrid_predicates=self.hybrid_predicates,
            debug=self.debug,
        )
        bfp.create_top_down_rete_network(self.debug)
        bfp.meta_interp_network.inferred_facts.namespace_manager = (
            fact_graph.namespace_manager
        )
        response = bfp.answers(debug=self.debug)

        goal_lit, adorned_program, sip_collections, _, _ = self.goal_rule_sip_info[tp]
        self.goal_rule_sip_info[tp] = (
            goal_lit,
            adorned_program,
            sip_collections,
            bfp.meta_interp_network.inferred_facts,
            bfp.meta_interp_network,
        )
        # Save information used for proof generation to the store
        self.query_propagation_info = bfp.action_propagation_info
        self.meta_interpretation_seeds = bfp.meta_interpretation_seeds
        self.meta_evaluation = bfp.meta_evaluation
        self.action_propagation_info = bfp.action_propagation_info
        self.query_networks.append((bfp.meta_interp_network, tp))
        self.edb_queries.update(bfp.edb_queries)
        if self.debug:
            print("Goal/Query: ", tp)
            print(
                "Query was not ground"
                if is_not_ground is not None
                else "Query was ground"
            )
            print(
                "Inferred facts from adorned rules:\n",
                bfp.meta_interp_network.inferred_facts.serialize(format="turtle"),
            )
        if is_not_ground is not None:
            if any(len(l) for l in bfp.goal_solutions):
                for item in bfp.goal_solutions:
                    yield item, None
            else:
                # Yield any facts previously inferred as a result of queries dispatched on behalf of the goal
                goal_literal = build_uniterm_from_tuple(tp)
                variables = list(goal_literal.variables)
                query = EDBQuery(
                    [goal_literal], bfp.meta_interp_network.inferred_facts
                ).as_sparql()
                for item in bfp.meta_interp_network.inferred_facts.query(query):
                    yield (
                        {variables[idx]: item[idx] for idx in range(len(variables))},
                        None,
                    )
        else:
            yield response, None
        if debug:
            print(bfp.meta_interp_network)
            bfp.meta_interp_network.report_conflict_set(
                True, sys.stderr, self.ns_bindings
            )
            for query in self.edb_queries:
                print("Dispatched query against dataset: ", query)

    def conjunctive_sip_strategy(self, goals_remaining, fact_graph, bindings=None):
        """
        Evaluate a conjunctive set of triple patterns using the SIP (Sideways
        Information Passing) strategy, yielding one binding dict per complete
        solution that satisfies all patterns simultaneously.

        This is the core join engine for top-down entailment.  It works left-to-right
        through the pattern list, solving each triple pattern in turn and threading
        the resulting variable bindings forward into the remaining patterns — exactly
        the same join semantics as a SPARQL BGP evaluation, but driven by the
        backward-chaining procedure instead of a SPARQL engine.

        The recursion structure mirrors a nested-loop join:

            for each solution to pattern[0]:
                for each solution to pattern[1] given solution[0]:
                    ...
                        yield combined_solution

        ``goals_remaining`` — the ordered list of (s, p, o) triple patterns still
            to be solved.  Each term is either a bound RDF node or a Variable.
        ``fact_graph`` — the EDB (extensional / base-fact) graph used by the
            backward-fixpoint procedure for ground look-ups.
        ``bindings`` — a dict mapping Variable → RDF node for bindings already
            established by previously solved patterns in this conjunction.  None
            is treated as an empty mapping.
        """
        bindings = bindings if bindings is not None else {}

        # Materialise goals into a list so each solution branch receives an
        # independent *slice* of the remaining work.  If we kept a shared
        # iterator, the first recursive branch would advance it and subsequent
        # solution branches (from additional answers to the same pattern) would
        # silently skip patterns, breaking join correctness.
        if not isinstance(goals_remaining, list):
            goals_remaining = list(goals_remaining)

        # Base case: all patterns have been satisfied.  The accumulated
        # bindings dict is a complete, consistent solution — yield it.
        if not goals_remaining:
            yield bindings
            return

        # Take the next pattern to solve and leave the rest for recursive calls.
        tp = goals_remaining[0]
        rest = goals_remaining[1:]

        assert isinstance(bindings, Mapping)

        # Determine whether the predicate of this triple pattern is a derived
        # (IDB) predicate — one whose truth depends on the ruleset — or a base
        # (EDB) predicate that can be answered directly from the store.
        d_pred = self.derived_predicate_from_triple(tp)

        if d_pred is None:
            # ----------------------------------------------------------------
            # EDB branch: the predicate is a base predicate.
            # Substitute any already-known variable bindings into the pattern
            # and issue a SPARQL query directly against the underlying store.
            # ----------------------------------------------------------------
            base_edb_query = EDBQuery(
                [build_uniterm_from_tuple(tp)], self.edb, bindings=bindings
            )
            if self.debug:
                print("Evaluating TP against EDB:%s" % base_edb_query.as_sparql())
            query, rt = base_edb_query.evaluate()
            # For each row returned by the store, merge the new variable
            # bindings with the bindings accumulated so far, then recurse to
            # solve the remaining patterns under that combined environment.
            for item in rt:
                next_bindings = dict(bindings)
                next_bindings.update(item)
                for ans_dict in self.conjunctive_sip_strategy(
                    rest, fact_graph, next_bindings
                ):
                    yield ans_dict

        else:
            # ----------------------------------------------------------------
            # IDB branch: the predicate is derived — it requires the top-down
            # backward-chaining (BFP) procedure to evaluate.
            # ----------------------------------------------------------------

            # Build a uniterm (structured literal) from the triple pattern so
            # we can manipulate it as a logic-programming goal term.
            query_lit = build_uniterm_from_tuple(tp)
            current_op = get_op(query_lit)
            query_lit.set_operator(current_op)

            # Wrap the goal in an EDBQuery so that any already-bound variables
            # in ``bindings`` get substituted into the pattern before we hand
            # it off to the adornment / SIP machinery.
            query = EDBQuery([query_lit], self.edb, bindings=bindings)
            if bindings:
                # Re-extract the triple after substitution so that bound
                # variables appear as concrete RDF terms in the adorned goal.
                tp = first(query.formulae).to_rdf_tuple()
            if self.debug:
                print("Goal/Query: ", query.as_sparql())

            # Adornment analysis: label each argument of the goal as Bound or
            # Free (the "adornment"), then rewrite the relevant rules so the
            # planner knows which arguments carry information sideways into
            # sub-goals (Sideways Information Passing).  This step also
            # populates ``self.edb.adorned_program`` with the rewritten rules.
            setup_ddl_and_adorn_program(
                self.edb,
                self.idb,
                [tp],
                derived_preds=self.derived_predicates,
                ignore_unbound_d_preds=True,
                hybrid_preds_to_replace=self.hybrid_predicates,
            )

            # Hybrid predicates appear in both EDB and IDB.  The adornment
            # machinery renames the IDB variant to "<pred>_derived" so the two
            # roles stay separate.  Rewrite the goal accordingly.
            if self.hybrid_predicates:
                lit = build_uniterm_from_tuple(tp)
                op = get_op(lit)
                if op in self.hybrid_predicates:
                    lit.set_operator(URIRef(op + "_derived"))
                    tp = lit.to_rdf_tuple()

            # Build the SIP graph: a directed graph that encodes, for each
            # adorned rule head, which bound arguments should be passed
            # sideways into each body sub-goal.  The BFP uses this graph to
            # guide its top-down search and avoid redundant EDB queries.
            sip_collection = prepare_sip_collection(self.edb.adorned_program)
            if self.debug and sip_collection:
                for sip in sip_representation(sip_collection):
                    print(sip)
                pprint(list(self.edb.adorned_program), sys.stderr)
            elif self.debug:
                print("No SIP graph.")

            goal = tp
            self.goal_rule_sip_info[goal] = (
                query_lit,
                copy.deepcopy(self.edb.adorned_program),
                sip_collection,
                None,
                None,
            )

            # Run the backward-fixpoint procedure for this single goal.
            # ``invoke_decision_procedure`` yields (answer, node) pairs where
            # ``answer`` is either:
            #   - a dict (Variable → value) for an open (non-ground) goal, or
            #   - a truthy/falsy scalar for a ground goal (proved or not).
            for next_answer, ns in self.invoke_decision_procedure(
                tp, fact_graph, bindings, self.debug, sip_collection
            ):
                # Distinguish open goals (variables remain) from ground goals
                # (all terms were already concrete — just True/False proof).
                non_ground_goal = isinstance(next_answer, Mapping)
                if non_ground_goal or next_answer:
                    # The BFP either returned variable bindings (open goal) or
                    # confirmed a ground goal as provable.
                    if not non_ground_goal:
                        # Ground goal was proved: no new variable bindings to
                        # add; carry the existing ``bindings`` forward as-is.
                        rt = next_answer
                    else:
                        # Open goal: merge the BFP's answer bindings with the
                        # bindings already established by prior patterns so
                        # that later patterns can use all bound variables.
                        rt = merge_mappings1_to2(bindings, next_answer)

                    # Recurse: solve the remaining patterns under the now-
                    # extended binding environment.  Each answer from this
                    # call is a fully consistent solution to the entire
                    # original conjunction (this pattern plus all that follow).
                    for ans_dict in self.conjunctive_sip_strategy(rest, fact_graph, rt):
                        yield ans_dict

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
        triples: list[Triple],
        init_ns: Mapping[str, Any],
        is_ask: bool = False,
        projected_vars: list[Variable] | None = None,
    ):
        """
        Evaluate a list of triple patterns against this store's entailment regime
        and return the result as an rdflib ``Result`` object (SELECT or ASK).

        This is the single-shot evaluation path used by ``query()``.  It differs
        from ``conjunctive_sip_strategy`` in that it does *not* thread bindings
        between patterns incrementally; instead it separates EDB from IDB patterns,
        evaluates the EDB group first (as a single SPARQL query), and then evaluates
        each IDB pattern independently via the BFP, accumulating all bindings into
        a flat list that is returned as the final result set.

        Strategy overview
        -----------------
        1. Partition ``triples`` into two groups:

           - ``ground_conjunct``: patterns whose predicate is an EDB (base) predicate,
             answerable directly from the RDF store.
           - ``derived_conjunct``: patterns whose predicate is a derived (IDB) predicate,
             requiring the backward-chaining / SIP procedure.

        2. Evaluate the EDB group first.  A single SPARQL query covers all EDB
           patterns together, exploiting the store's native join and index machinery.

        3. Only if the EDB group succeeds (or is empty) do we proceed to the IDB
           patterns.  For ASK queries this short-circuits as soon as any pattern fails.

        4. For each IDB pattern, run the full adornment + SIP + BFP pipeline and
           collect the resulting bindings.

        5. Project the collected bindings onto ``projected_vars`` and wrap them in
           an rdflib ``Result``.

        Parameters
        ----------
        triples :
            The triple patterns to evaluate.  Each element is a 3- or 4-tuple
            ``(s, p, o[, filter_fn])``; the optional fourth element is ignored.
            Any term may be a ``Variable`` (open) or a concrete RDF node (bound).
        init_ns :
            Namespace prefix bindings used when building uniterm representations
            of the patterns.
        is_ask :
            If True, return an ASK result (boolean) rather than a SELECT result
            (binding rows).  Evaluation short-circuits on the first failure.
        projected_vars :
            The variables to include in SELECT results.  If None, all variables
            found in the returned bindings are used.
        """
        select_bindings: list[Mapping[Variable, Identifier]] = []

        # Step 1 — partition patterns into EDB (base store) vs IDB (derived).
        ground_conjunct = []
        derived_conjunct = []
        for item in triples:
            if len(item) == 4:
                s, p, o, _func = item
            else:
                s, p, o = item
            if self.derived_predicate_from_triple((s, p, o)) is None:
                ground_conjunct.append(build_uniterm_from_tuple((s, p, o), init_ns))
            else:
                derived_conjunct.append(build_uniterm_from_tuple((s, p, o), init_ns))

        ans = None
        # Default to True so that if there are no EDB patterns the derived
        # evaluation proceeds unconditionally.
        ask_result = True

        # Step 2 — evaluate EDB patterns as a single SPARQL query.
        if ground_conjunct:
            base_edb_query = EDBQuery(ground_conjunct, self.edb)
            sub_query, ans = base_edb_query.evaluate(self.debug)
            if is_ask:
                # For ASK: if the store returns no results the answer is False;
                # skip IDB evaluation entirely (short-circuit).
                if not bool(ans):
                    ask_result = False
            else:
                # For SELECT: seed the binding list with every row returned by
                # the EDB query.  IDB results are appended below.
                if ans:
                    for binding in ans:
                        select_bindings.append(binding)

        # Step 3 — evaluate IDB (derived) patterns, but only if we still have
        # a chance of overall success (EDB didn't already falsify an ASK).
        if not is_ask or ask_result:
            for derived_literal in derived_conjunct:
                # Convert the uniterm back to a plain (s, p, o) tuple so the
                # adornment and SIP machinery can process it.
                goal = derived_literal.to_rdf_tuple()

                # Step 3a — adornment: rewrite the relevant rules with Bound/Free
                # argument labels based on which terms in ``goal`` are already
                # concrete.  This populates ``self.edb.adorned_program``.
                setup_ddl_and_adorn_program(
                    self.edb,
                    self.idb,
                    [goal],
                    derived_preds=self.derived_predicates,
                    ignore_unbound_d_preds=True,
                    hybrid_preds_to_replace=self.hybrid_predicates,
                )

                # Step 3b — hybrid-predicate renaming: if this goal's predicate
                # also appears in the EDB (a "hybrid" predicate), the adornment
                # step renamed the IDB variant to "<pred>_derived".  Rewrite the
                # goal to match so the BFP targets the right adorned rules.
                lit = build_uniterm_from_tuple(goal)
                if self.hybrid_predicates:
                    op = get_op(lit)
                    if op in self.hybrid_predicates:
                        lit.set_operator(URIRef(op + "_derived"))
                        goal = lit.to_rdf_tuple()

                # Step 3c — build the SIP graph from the adorned rules.
                # The SIP graph encodes which bound arguments are passed sideways
                # (as "magic" facts) into each body sub-goal, restricting the
                # search to only the relevant portion of the derivation space.
                sip_collection = prepare_sip_collection(self.edb.adorned_program)
                if self.debug and sip_collection:
                    print("Adorned Program:")
                    print("Adorned Program:")
                    for rule in self.edb.adorned_program:
                        print("\t", rule)
                    print(f"{len(sip_collection)} SIP Collection(s)")
                    print(sip_collection.serialize(format="turtle"))
                    for sip in sip_representation(sip_collection):
                        print(sip)
                    pprint(list(self.edb.adorned_program))
                elif self.debug:
                    print("No SIP graph.")
                self.goal_rule_sip_info[goal] = (
                    lit,
                    copy.deepcopy(self.edb.adorned_program),
                    sip_collection,
                    None,
                    None,
                )

                # Step 3d — run the BFP for this single derived goal.
                if is_ask:
                    # For ASK we only need the first answer; if the BFP cannot
                    # prove the goal the result is falsy and we stop immediately.
                    rt, node = first(
                        self.invoke_decision_procedure(
                            goal, self.edb, {}, self.debug, sip_collection
                        )
                    )
                    if not rt:
                        ask_result = False
                        break  # short-circuit: one unprovable pattern falsifies the conjunction
                else:
                    # For SELECT, collect every solution the BFP produces.
                    # ``rt`` is either a dict (Variable → value) for an open goal
                    # or a truthy scalar for a ground goal that was proved.
                    for rt, node in self.invoke_decision_procedure(
                        goal, self.edb, {}, self.debug, sip_collection
                    ):
                        if isinstance(rt, Mapping):
                            select_bindings.append(rt)
                        elif rt:
                            # Ground goal proved with no new variable bindings;
                            # record an empty binding row so the result is non-empty.
                            select_bindings.append({})

        # Step 4 — package results as an rdflib Result object.
        if is_ask:
            ask_result_obj = Result("ASK")
            ask_result_obj.askAnswer = ask_result
            return sparql_query_from_result(ask_result_obj)
        else:
            select_result = Result("SELECT")

            # If the caller did not specify which variables to project, infer
            # them from the union of all keys across all binding dicts.
            if projected_vars is None:
                projected_vars = []
                for binding in select_bindings:
                    for var in binding:
                        if var not in projected_vars:
                            projected_vars.append(var)

            if projected_vars:
                # Drop any variables not requested by the projection, and fill
                # in only the variables that actually appear in each binding
                # (some patterns may leave certain variables unbound).
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
            query_object = translateQuery(parsed_result, None, init_ns)
            _service_url, triples = extract_triples_from_query(
                query_object.algebra.p, init_ns
            )
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

        :param patterns: A list of 4-item tuples where any of the items can be
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
            for ans_dict in self.conjunctive_sip_strategy(goals, self.edb):
                yield ans_dict
            self.batch_unification = True
        else:
            # conjunctive query involving EDB predicateso only
            vars = []
            triples = []
            for pat in patterns:
                triples.append(build_uniterm_from_tuple(pat[:3]))
                vars.extend([term for term in pat[:3] if isinstance(term, Variable)])

            query = rdf_tuples_to_sparql(triples, self.edb, vars=vars)
            if self.debug:
                print("Batch unify resolved against EDB")
                print(query)

            rt = self.edb.query(query, initNs=self.ns_bindings)

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
        """Bind a namespace prefix for generated queries."""
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
