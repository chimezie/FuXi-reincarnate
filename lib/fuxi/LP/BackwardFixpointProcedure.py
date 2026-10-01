# encoding: utf-8
# flake8: noqa
"""
BackwardFixpointProcedure.py

.. A sound and complete query answering method for recursive databases
based on meta-interpretation called Backward Fixpoint Procedure ..

Uses RETE-UL as the RIF PRD implementation of
a meta-interpreter of an adorned ruleset that builds large, conjunctive
(BGPs) SPARQL queries.

Facts are only generated in a bottom up evaluation of the interpreter if a
query has been issued for that fact or if an appropriate sub-query has
been generated. Sub-queries for rule bodies are generated if a sub-query
for the corresponding rule head already exists. Sub-queries for conjuncts
are generated from sub-queries of conjunctions they appear in

Evaluate condition and ACTION:

Evaluate consults the already generated facts, and may take a single atom
or a conjunction as its argument, returning true if all of the conjuncts have
already been generated.

"""

import copy
import unittest
from functools import reduce
from io import StringIO

from pprint import pprint

from rdflib.graph import ReadOnlyGraphAggregate
from rdflib import Literal, Namespace, RDF, Variable, URIRef
from rdflib.util import first

from fuxi.SPARQL import EDBQuery, edb_query_from_body_iterator, ConjunctiveQueryMemoize
from fuxi.Rete.SidewaysInformationPassing import (
    get_args,
    get_variables,
    sip_representation,
)
from fuxi.Rete.SidewaysInformationPassing import iter_condition, get_op
from fuxi.Rete.BetaNode import ReteMemory, BetaNode, RIGHT_MEMORY, LEFT_MEMORY
from fuxi.Rete.AlphaNode import AlphaNode, ReteToken, BuiltInAlphaNode
from fuxi.Rete.Network import HashablePatternList, InferredGoal
from frozendict import frozendict
from fuxi.Rete.Magic import AdornedRule, AdornedUniTerm, is_hybrid_predicate
from fuxi.Rete.Util import generate_token_set
from fuxi.Horn.HornRules import Clause
from fuxi.Rete.RuleStore import N3Builtin, FILTERS

from fuxi.Horn.PositiveConditions import And, update_ns_managers
from fuxi.Horn.PositiveConditions import Uniterm
from fuxi.Horn.PositiveConditions import build_uniterm_from_tuple


BFP_NS = Namespace("http://dx.doi.org/10.1016/0169-023X(90)90017-8#")
BFP_RULE = Namespace("http://code.google.com/p/python-dlp/wiki/BFPSpecializedRule#")
HIGHER_ORDER_QUERY = BFP_RULE.SecondOrderPredicateQuery


class EvaluateConjunctiveQueryMemory(ReteMemory):
    """
    The extension of the evaluate predicate for a particular specialized rule

    "Whenever a new WME is filtered through the alpha network and reaches an alpha memory, we
    simply add it to the list of other WMEs in that memory, and inform each of the attached join
    nodes"

    A beta memory node stores a list of the tokens it contains, plus a list of its children (other
    nodes in the beta part of the network). Before we give its data structure, though, recall that
    we were going to do our procedure calls for left and right activations through a switch or case
    statement or a jumptable indexed according to the type of node being activated. Thus, given
    a (pointer to a) node, we need to be able to determine its type. This is straightforward if we
    use variant records to represent nodes. (A variant record is a record that can contain any one
    of several different sets of fields.) Each node in the beta part of the net will be represented by
    a rete-node structure:

    Whenever a beta memory is informed of a new match (consisting of an existing token and some
    WME), we build a token, add it to the list in the beta memory, and inform each of the beta
    memory's children:
    """

    def __init__(self, betaNode, memoryPos, _filter=None):
        super(EvaluateConjunctiveQueryMemory, self).__init__(
            betaNode, memoryPos, _filter
        )

    def __repr__(self):
        return "<Evaluate Memory: %s item(s)>" % (len(self))


class MalformedQeryPredicate(Exception):
    """An exception raised when a malformed quer predicate is created"""

    def __init__(self, msg):
        super(MalformedQeryPredicate, self).__init__(msg)


class GoalSolutionAction(object):
    def __init__(self, bfp, var_map):
        self.bfp = bfp
        self.var_map = var_map
        self.solution_set = set()

    def __repr__(self):
        stream = StringIO()
        return stream.getvalue()

    def __call__(self, t_node, inferred_triple, token, binding, debug):
        """
        Called when the BFP triggers a p-node associated with a goal
        , storing the solutions for later retrieval
        """
        self.bfp.goal_solutions.add(
            frozendict(
                [
                    (self.var_map[key], binding[key])
                    for key in binding
                    if key in self.var_map
                ]
            )
        )


class EvaluateExecution(object):
    """Handles the inference of evaluate literals in BFP"""

    def __init__(self, tpl, bfp, termNodes):
        self.rule_no, self.body_idx = tpl
        self.bfp = bfp
        self.term_nodes = termNodes
        for term_node in self.term_nodes:
            assert [
                (s, p, o)
                for s, p, o in term_node.consequent
                if p == BFP_NS.evaluate
                and s == BFP_RULE[str(self.rule_no)]
                and o == Literal(self.body_idx)
            ], "%s %s" % (self, term_node)

    def __call__(self, t_node, inferred_triple, token, binding, debug):
        """
        Called when an evaluate literal is inferred and
        given the relevant bindings

        Add entailed evaluate bindings (as high-arity predicates)
        directly into RETE-UL beta node memories in a circular fashion
        propagating their sucessor
        """
        for s, p, o in t_node.consequent:
            if p == BFP_NS.evaluate:
                for memory in self.bfp.eval_hash[(self.rule_no, self.body_idx)]:
                    for bindings in token.bindings:
                        memory.add_token(token, debug)
                        self.bfp.action_propagation_info.setdefault(
                            self, {}
                        ).setdefault(memory.successor, set()).add((t_node, token))
                        if memory.position == LEFT_MEMORY:
                            memory.successor.propagate(memory.position, debug, token)
                        else:
                            memory.successor.propagate(None, debug, token)

    def __repr__(self):
        return "Evaluate(%s %s)" % (self.rule_no, self.body_idx)


class QueryExecution(object):
    """
    Called when an evaluate literal is inferred and
    given the relevant bindings
    """

    def __init__(self, bfp, query_literal, conjoined_token_mem=None, edb_conj=None):
        self.fact_graph = bfp.fact_graph
        self.bfp = bfp
        self.query_literal = query_literal
        self.edb_conj = edb_conj
        self.conjoined_token_mem = conjoined_token_mem
        self.fired_grounded_queries = {}

    def __call__(self, t_node, inferred_triple, token, binding, debug=False):
        """
        Called when a (EDB) query literal is triggered with
        given bindings.
        """
        assert len(t_node.consequent) == 1
        key = (self.query_literal, t_node, token)
        if key not in self.bfp.fired_edb_queries:
            self.bfp.fired_edb_queries.add(key)
            for token_binding in token.bindings:
                _bindings = dict(
                    [(k, v) for k, v in list(token_binding.items()) if v is not None]
                )

                closure = ReadOnlyGraphAggregate(
                    [self.fact_graph, self.bfp.meta_interp_network.inferred_facts]
                )
                closure.templateMap = self.fact_graph.template_map
                # For each mapping that unifies with theory
                if self.edb_conj:
                    _vars = set()
                    for lit in self.edb_conj:
                        _vars.update(list(get_variables(lit, second_order=True)))
                    _qLit = EDBQuery(
                        [copy.deepcopy(lit) for lit in self.edb_conj],
                        self.fact_graph,
                        _vars,
                    )
                else:
                    _qLit = copy.deepcopy(self.query_literal)
                    _qLit = EDBQuery(
                        [_qLit],
                        self.fact_graph,
                        list(get_variables(_qLit, second_order=True)),
                    )
                orig_query = _qLit.copy()
                _qLit.ground(_bindings)
                self.fired_grounded_queries[frozendict(_bindings)] = _qLit
                if self.bfp.debug:
                    print(
                        "%sQuery triggered for "
                        % (" maximal db conjunction " if self.edb_conj else ""),
                        t_node.clause_representation(),
                    )
                self.bfp.edb_queries.add(_qLit)
                is_ground = not _qLit.return_vars
                rt = self.tabled_query(_qLit)
                if is_ground:
                    if first(rt):
                        self.handle_query_answer(
                            orig_query,
                            token,
                            self.bfp.debug,
                            t_node,
                            ({}, token_binding),
                        )
                else:
                    for ans in rt:
                        if self.bfp.debug:
                            pprint(ans)
                        self.handle_query_answer(
                            orig_query,
                            token,
                            self.bfp.debug,
                            t_node,
                            (ans, token_binding),
                        )

    @ConjunctiveQueryMemoize()
    def tabled_query(self, conj_query):
        query_str, rt = conj_query.evaluate(self.bfp.debug)
        if isinstance(rt, bool):
            yield rt
        else:
            for item in rt:
                yield item

    def handle_query_answer(self, literal, token, debug, t_node, bindings=None):
        edb_result = literal.copy()
        if self.conjoined_token_mem:
            assert bindings is not None
            # identify join variables amongst EDB query
            join_vars = set()

            def collect_join_vars(left, right):
                if isinstance(left, set):
                    # collection of vars on left, update commulative joinvar set
                    # with vars in right in this collection
                    right_vars = set()
                    for var in get_variables(right, second_order=True):
                        if var in left:
                            join_vars.add(var)
                        right_vars.add(var)
                    return left.union(right_vars)
                else:
                    # left and right are base atoms, get their variables,
                    # update cumulative joinvar with the intersection
                    left_vars = set(
                        [var for var in get_variables(left, second_order=True)]
                    )
                    right_vars = set(
                        [var for var in get_variables(right, second_order=True)]
                    )
                    _jVars = left_vars.intersection(right_vars)
                    join_vars.update(_jVars)
                    return _jVars

            base_atoms = [atom for atom in edb_result if isinstance(atom, Uniterm)]

            if len(literal) == 1:
                join_vars = set()
            else:
                reduce(collect_join_vars, base_atoms)

            # clone partially instanciated token, add to eval memory, and propagate
            # the succesor join node
            token_clone = token.copy()

            query_bindings, token_bindings = bindings
            # Defensive: unwrap any ResultRow objects that may have leaked into bindings
            from rdflib.query import ResultRow

            query_bindings = {
                k: (v[0] if isinstance(v, ResultRow) and len(v) == 1 else v)
                for k, v in query_bindings.items()
            }
            # toDo = []
            for fact in base_atoms:
                query_literal = copy.deepcopy(fact)
                fact.ground(token_bindings)
                fact.ground(query_bindings)
                assert fact.is_ground()
                wme = ReteToken(
                    tuple([term for term in fact.to_rdf_tuple()]), debug=debug
                )
                wme_copy = copy.deepcopy(wme)
                for (
                    term_comb,
                    term_dict,
                ) in self.bfp.meta_interp_network.alpha_pattern_hash.items():
                    for alpha_node in term_dict.get(
                        wme_copy.alpha_network_hash(term_comb), []
                    ):
                        alpha_node.activate(wme_copy)
                wme.bind_variables(AlphaNode(query_literal.to_rdf_tuple()))
                token_clone.tokens.add(wme)
            token_clone.joined_bindings = dict(
                [
                    (key, token.joined_bindings[key])
                    for key in join_vars.intersection(set(token.joined_bindings))
                ]
            )
            token_clone._generate_hash()
            token_clone._generate_bindings()
            for memory in self.associated_beta_memories():
                memory.add_token(token_clone, debug)
                self.bfp.action_propagation_info.setdefault(self, {}).setdefault(
                    memory.successor, set()
                ).add((t_node, token))
                if memory.position == LEFT_MEMORY:
                    memory.successor.propagate(memory.position, debug, token_clone)
                else:
                    memory.successor.propagate(None, debug, token_clone)

        else:
            if bindings:
                edb_result.ground(bindings)
            assert len(edb_result) == 1
            inferred_token = ReteToken(
                edb_result.formulae[0].to_rdf_tuple(), debug=debug
            )
            if inferred_token not in self.bfp.meta_interp_network.working_memory:
                # if self.bfp.debug or debug:
                #     print("\tAnswer to BFP triggered query %s : %s" % (edb_result, bindings))
                self.bfp.meta_interp_network.add_wme(inferred_token)

    def associated_beta_memories(self):
        return self.bfp.eval_hash[self.conjoined_token_mem]

    def __repr__(self):
        return "QueryExecution%s%s" % (
            "( against EDB: %s )"
            % (
                EDBQuery(self.edb_conj, self.fact_graph)
                if self.edb_conj
                else self.query_literal
            ),
            " -> %s" % (repr(self.conjoined_token_mem))
            if self.conjoined_token_mem
            else "",
        )


def setup_evaluation_beta_node(existing_beta_node, rule, network):
    """
    Take a BetaNode (and a BFP rule) that joins values from an evaluate condition
    with other conditions and replace the alpha node (and memory) used
    to represent the condition with a pass-thru beta with no parent nodes
    but whose right memory will be used to add bindings instanciated
    from evaluate assertions in the BFP algorithm

      Rete Network
      ------------

       ...
          \\     memory <-- eval_alpha_node
           \\   /
         existingBetaNode


          evalMemory <-- evaluate(ruleNo, bodyPos, vars)
           /
      existingBetaNode
    """
    # Delete the existing alpha node (and memory) for the evaluate condition

    new_mem = EvaluateConjunctiveQueryMemory(existing_beta_node, RIGHT_MEMORY)
    existing_beta_node.memories[RIGHT_MEMORY] = new_mem
    eval_alpha_node = existing_beta_node.right_node
    network.alpha_pattern_hash[eval_alpha_node.alpha_network_hash()][
        eval_alpha_node.alpha_network_hash(ground_term_hash=True)
    ].remove(eval_alpha_node)
    network.alpha_nodes.remove(eval_alpha_node)
    for mem in eval_alpha_node.descendent_memory:
        del mem
    pattern = HashablePatternList([eval_alpha_node.triple_pattern])
    if pattern in network.nodes:
        del network.nodes[pattern]
    del eval_alpha_node
    existing_beta_node.right_node = None

    # The common variables are those in the original rule intersected
    # with those in the left node of the successor
    existing_beta_node.right_variables = set(rule.declare)
    existing_beta_node.common_variables = [
        leftVar
        for leftVar in existing_beta_node.left_variables
        if leftVar in existing_beta_node.right_variables
    ]
    return new_mem


def noop_callback_fn(term_node, inferred_triple, tokens, debug=False):
    pass


OPEN_QUERY_VARIABLE = BFP_NS.NonDistinguishedVariable


class BackwardFixpointProcedure(object):
    """
    Uses RETE-UL as a production rule system implementation of
    a meta-interpreter of an adorned RIF Core ruleset that builds solves conjunctive (BGPs)
    SPARQL queries.

    Facts are only generated in a bottom up evaluation of the interpreter if a
    query has been issued for that fact or if an appropriate sub-query has been generated.
    Sub-queries for rule bodies (conditions) are generated if a sub-query for
    the corresponding rule head already exists. Sub-queries for conjuncts are
    generated from sub-queries of conjunctions they appear in (queries are collected).
    """

    def __init__(
        self,
        fact_graph,
        network,
        derived_predicates,
        goal,
        sip_collection=None,
        hybrid_predicates=None,
        debug=False,
        push_down_mdbq=True,
    ):
        if sip_collection is None:
            sip_collection = []
        self.debug = debug
        self.meta_rule2_network = {}
        self.push_down_mdbq = push_down_mdbq
        self.push_down_queries = {}
        self.max_edb_front2_end = {}
        self.query_predicates = set()
        self.sip_collection = sip_collection
        self.goal = build_uniterm_from_tuple(goal)
        self.fact_graph = fact_graph
        self.rules = list(fact_graph.adorned_program)
        self.discarded_rules = set()
        self.rule_labels = {}
        self.bfp_lookup = {}
        self.action_hash = {}
        self.namespaces = {"bfp": BFP_NS, "rule": BFP_RULE}
        self.meta_interp_network = network
        self.derived_predicates = (
            set(derived_predicates)
            if isinstance(derived_predicates, list)
            else derived_predicates
        )
        self.hybrid_predicates = hybrid_predicates if hybrid_predicates else []
        self.fired_edb_queries = set()
        self.edb_queries = set()
        self.goal_solutions = set()
        self.action_propagation_info = {}
        self.meta_interpretation_seeds = {}
        self.meta_evaluation = {}

    def answers(self, debug=False, solution_callback=noop_callback_fn):
        """
        Takes a conjunctive query, a sip collection
        and initiates the meta-interpreter for a given
        goal (at a time), propagating evaluate procedures
        explicitely if no bindings are given from the query
        to trigger subsequent subqueries via EDB predicates

        @TODO:
        Add a PRD externally defined action to the
        production of rules that produce answers
        for the query predicate.
        The action is a user specified callback that can be used
        to signal InferredGoal and halt RETE/UL evaluation prematurely
        otherwise, it is left to reach a stable state and the
        answers collected along the way are added and returned

        """
        # solutions = []

        # queryOp = GetOp(self.goal)
        if self.goal.is_ground():
            # Mark ground goal so, production rule engine
            # halts when goal is inferred
            self.meta_interp_network.goal = self.goal.to_rdf_tuple()

        adornment = [
            "f" if isinstance(v, Variable) else "b"
            for v in get_args(self.goal, second_order=True)
        ]
        adornment = reduce(lambda x, y: x + y, adornment)
        adorned_query = AdornedUniTerm(self.goal, adornment)
        bfp_top_query = self.make_derived_query_predicate(adorned_query)
        if debug:
            print("Asserting initial BFP query ", bfp_top_query)

        assert bfp_top_query.is_ground()
        self.meta_interpretation_seeds[bfp_top_query.to_rdf_tuple()] = None
        # Add BFP query atom to working memory, triggering procedure
        try:
            self.meta_interp_network.feed_facts_to_add(
                generate_token_set(
                    [bfp_top_query.to_rdf_tuple()],
                    debug_triples=[bfp_top_query.to_rdf_tuple()] if debug else [],
                )
            )
        except InferredGoal:
            if debug:
                print("Reached ground goal. Terminated BFP.")
            return True
        else:
            if self.goal.is_ground():
                # Ground goal, but didn't trigger it, response must be negative
                return False

    def specialize_conjuncts(self, rule, idx, eval_vars):
        """
        Extends the (vanilla) meta-interpreter for magic set and alexander rewriting
        sip strategies with capabilities for collapsing chains of extensional
        predicate queries (frames whose attributes are in EDB and externally-defined
        predicates) into a single SPARQL query
        """
        # _len = len(rule.formula.body)
        body = list(iter_condition(rule.formula.body))

        skip_mdbq_count = 0
        for bodyIdx, bodyLiteral in enumerate(body):
            conjunct = []
            # V_{j} = V_{j-1} UNION vars(Literal(..)) where j <> 0
            eval_vars[(idx + 1, bodyIdx + 1)] = (
                list(get_variables(bodyLiteral, second_order=True))
                + eval_vars[(idx + 1, bodyIdx)]
            )
            if skip_mdbq_count > 0:
                skip_mdbq_count -= 1
                continue

            # remainingBodyList = body[bodyIdx+1:] if bodyIdx+1<_len else []
            conjunct = edb_query_from_body_iterator(
                self.fact_graph,
                rule.formula.body.formulae[bodyIdx:],
                self.derived_predicates,
                self.hybrid_predicates,
            )

            lazy_base_conjunct = self.push_down_mdbq and conjunct
            pattern = HashablePatternList(
                [(BFP_RULE[str(idx + 1)], BFP_NS.evaluate, Literal(bodyIdx))]
            )
            pattern2 = HashablePatternList(
                [
                    None,
                    (BFP_RULE[str(idx + 1)], BFP_NS.evaluate, Literal(bodyIdx)),
                    bodyLiteral.to_rdf_tuple(),
                ]
            )
            a_node_dk = self.meta_interp_network.nodes[pattern]

            # Rule d^k
            # query_Literal(x0, ..., xj) :- evaluate(ruleNo, j, X)
            # query invokation
            t_node = first(a_node_dk.descendent_beta_nodes)
            assert len(a_node_dk.descendent_beta_nodes) == 1
            new_eval_memory = setup_evaluation_beta_node(
                t_node, rule, self.meta_interp_network
            )

            is_base = (
                bodyLiteral.adornment is None
                if isinstance(bodyLiteral, AdornedUniTerm)
                else True
            )
            if isinstance(bodyLiteral, N3Builtin):
                if a_node_dk in self.meta_interp_network.alpha_nodes:
                    self.meta_interp_network.alpha_nodes.remove(a_node_dk)
                # evalTerm = (BFP_RULE[str(idx+1)], BFP_NS.evaluate, Literal(bodyIdx))
                del a_node_dk

                execute_action = EvaluateExecution((idx + 1, bodyIdx), self, [])
                built_in_node = self.meta_rule2_network[
                    self.bfp_lookup[("c", idx + 1, bodyIdx + 1)]
                ]
                assert isinstance(built_in_node.right_node, BuiltInAlphaNode)
                built_in_node.execute_actions[bodyLiteral.to_rdf_tuple()] = (
                    True,
                    execute_action,
                )

                # We bypass d^k, so when evaluate(ruleNo, j, X) is inferred
                # it is added to left memory of pNode associated with c^k
                self.eval_hash.setdefault((idx + 1, bodyIdx), []).append(
                    built_in_node.memories[LEFT_MEMORY]
                )

                self.action_hash.setdefault((idx + 1, bodyIdx + 1), set()).add(
                    built_in_node
                )
            elif conjunct and (is_base or lazy_base_conjunct):
                single_conj = EDBQuery(
                    [copy.deepcopy(item) for item in conjunct], self.fact_graph
                )
                matching_triple = first(t_node.consequent)
                assert len(t_node.consequent) == 1
                new_action = QueryExecution(
                    self,
                    bodyLiteral,
                    conjoined_token_mem=self.max_edb_front2_end[(idx + 1, bodyIdx + 1)]
                    if lazy_base_conjunct
                    else None,
                    edb_conj=conjunct if lazy_base_conjunct else single_conj,
                )

                self.eval_hash.setdefault((idx + 1, bodyIdx), []).append(
                    new_eval_memory
                )
                # If the body predicate is a 2nd order predicate, we don't infer the
                # second order query predicate (since it will trigger a query into
                # the EDB and thus there is no need to trigger subsequent
                # rules)
                t_node.execute_actions[matching_triple] = (True, new_action)
            else:
                self.eval_hash.setdefault((idx + 1, bodyIdx), []).append(
                    new_eval_memory
                )
            if is_hybrid_predicate(bodyLiteral, self.hybrid_predicates) or (
                (get_op(bodyLiteral) in self.derived_predicates)
                and not (is_base and len(conjunct) > 1)
            ):
                # if pattern2 not in self.metaInterpNetwork.nodes: import pdb;pdb.set_trace()
                assert pattern2 in self.meta_interp_network.nodes
                term_node_ck = self.meta_interp_network.nodes[pattern2]
                # Rule c^k
                # evaluate(ruleNo, j+1, X) :- evaluate(ruleNo, j, X),
                # bodyLiteral
                self.action_hash.setdefault((idx + 1, bodyIdx + 1), set()).add(
                    term_node_ck
                )

                assert isinstance(term_node_ck.right_node, AlphaNode)
                term_node_ck.left_variables = set(eval_vars[(idx + 1, bodyIdx)])
                term_node_ck.right_variables = set(
                    get_variables(bodyLiteral, second_order=True)
                )
                term_node_ck.common_variables = (
                    term_node_ck.right_variables.intersection(
                        term_node_ck.left_variables
                    )
                )
            if lazy_base_conjunct and len(conjunct) > 1:
                end_idx = self.max_edb_front2_end[(idx + 1, bodyIdx + 1)][-1]
                skip_mdbq_count = end_idx - bodyIdx - 1

    def check_network_wellformedness(self):
        for key, rule in list(self.bfp_lookup.items()):
            if len(key) == 2:
                rule_type, rule_idx = key
                body_idx = None
            else:
                rule_type, rule_idx, body_idx = key

            term_node = self.meta_rule2_network[rule]
            head_tuple = rule.formula.head.to_rdf_tuple()

            # p(..) :- q_1(..), q_2(..), ..., q_n(..)
            if get_op(rule.formula.head) == BFP_NS.evaluate:
                # evaluate(.., ..) :-

                override, execute_fn = term_node.execute_actions.get(
                    head_tuple, (None, None)
                )
                assert override and isinstance(execute_fn, EvaluateExecution), term_node
                assert execute_fn.rule_no == rule_idx
                assert execute_fn.body_idx == head_tuple[-1]
                assert body_idx is None or execute_fn.body_idx == int(body_idx), (
                    body_idx
                )

                if isinstance(rule.formula.body, And):
                    # c^{rule_idx}_{body_idx}
                    # evaluate(.., j+1) :- evaluate(.., j), q_{j+1}(..)
                    # @@ force check builtins or derived predicate c rules
                    if isinstance(term_node.left_node, AlphaNode):
                        # alphaNode = term_node.leftNode
                        beta_node = term_node.right_node
                        assert isinstance(
                            term_node.memories[RIGHT_MEMORY],
                            EvaluateConjunctiveQueryMemory,
                        ), term_node
                        assert isinstance(beta_node, BetaNode)
                    elif not term_node.fed_by_builtin:
                        # alphaNode = term_node.rightNode
                        beta_node = term_node.left_node

                        assert (
                            isinstance(
                                term_node.memories[LEFT_MEMORY],
                                EvaluateConjunctiveQueryMemory,
                            )
                            or self.eval_hash[(rule_idx, body_idx - 1)][0].successor
                            != term_node
                        ), term_node
                        assert isinstance(beta_node, BetaNode)
                else:
                    # b^{rule_idx}
                    # evaluate(.., j+1) :- query-p(..)
                    assert term_node.a_pass_thru

            elif isinstance(rule.formula.body, And):
                # a^{rule_idx}
                # p(..) :- query-p(..), evaluate(.., n)
                assert isinstance(
                    term_node.memories[RIGHT_MEMORY], EvaluateConjunctiveQueryMemory
                )
            else:
                # d^{rule_idx}_{body_idx}
                # query-q_{j+1}(..) :- evaluate(.., j)
                query_literal = list(
                    iter_condition(self.rules[rule_idx - 1].formula.body)
                )[body_idx - 1]
                if isinstance(query_literal, N3Builtin):
                    head_tuple = query_literal.to_rdf_tuple()
                    execute_kind = EvaluateExecution
                else:
                    execute_kind = QueryExecution
                if get_op(query_literal) not in self.derived_predicates:
                    override, execute_fn = term_node.execute_actions.get(
                        head_tuple, (None, None)
                    )
                    assert override and isinstance(execute_fn, execute_kind), (
                        "%s %s %s"
                        % (term_node.consequent, term_node.execute_actions, term_node)
                    )
                    if not isinstance(query_literal, N3Builtin):
                        assert execute_fn.query_literal == query_literal
                        # self.bfp.evalHash[self.conjoinedTokenMem]
                        assert execute_fn.conjoined_token_mem[0] == int(rule_idx), (
                            "%s %s %s" % (term_node, execute_fn, key)
                        )

    def create_top_down_rete_network(self, debug=False):
        """
        Uses the specialized BFP meta-interpretation rules to build a RETE-UL decision
        network that is modified to support the propagation of bindings from the evaluate
        predicates into a supplimental magic set sip strategy and the generation of subqueries.
        The end result is a bottom-up simulation of SLD resolution with complete, sound, and safe
        memoization in the face of recursion
        """
        for rule in set(self.specialize_adorned_ruleset(debug)):
            self.meta_rule2_network[rule] = (
                self.meta_interp_network.build_network_from_clause(rule)
            )
        if debug:
            sortedBFPRules = [
                str("%s : %s") % (key, self.bfp_lookup[key])
                for key in sorted(
                    self.bfp_lookup, key=lambda items: str(items[1]) + items[0]
                )
            ]
            for _ruleStr in sortedBFPRules:
                print(_ruleStr)

        self.eval_hash = {}
        self.action_hash = {}
        eval_vars = {}
        self.productions = {}
        for idx, rule in enumerate(self.rules):
            if rule in self.discarded_rules:
                continue

            # label = BFP_RULE[str(idx+1)]
            conjunct_length = len(list(iter_condition(rule.formula.body)))

            # Rule a^k
            # p(x0, ..., xn) :- And(query_p(x0, ..., xn) evaluate(rule_no, n,
            # X))
            current_pattern = HashablePatternList(
                [(BFP_RULE[str(idx + 1)], BFP_NS.evaluate, Literal(conjunct_length))]
            )
            assert rule.declare
            # Find alpha node associated with evaluate condition
            node = self.meta_interp_network.nodes[current_pattern]
            # evaluate(k, n, X) is a condition in only 1 bfp rule
            assert len(node.descendent_beta_nodes) == 1
            b_node = first(node.descendent_beta_nodes)
            assert b_node.left_node.a_pass_thru
            assert len(b_node.consequent) == 1
            new_eval_memory = setup_evaluation_beta_node(
                b_node, rule, self.meta_interp_network
            )
            self.eval_hash.setdefault((idx + 1, conjunct_length), []).append(
                new_eval_memory
            )

            if get_op(rule.formula.head) == get_op(self.goal):
                # This rule matches a goal, add a solution collecting action
                goal_solution_action = GoalSolutionAction(
                    self, rule.formula.head.get_var_mapping(self.goal)
                )
                b_node.execute_actions[rule.formula.head.to_rdf_tuple()] = (
                    False,
                    goal_solution_action,
                )

            self.productions.setdefault(get_op(rule.formula.head), []).append(
                (idx, b_node)
            )

            # Rule b^k
            # evaluate(rule_no, 0, X) :- query_p(x0, ..., xn)
            _rule = self.bfp_lookup[("b", idx + 1)]
            # alpha node associated with query predicate for head of original
            # rule
            _body_alpha_node = self.meta_interp_network.nodes[
                HashablePatternList([_rule.formula.body.to_rdf_tuple()])
            ]

            assert len(_body_alpha_node.descendent_beta_nodes) == 1
            t_node = first(_body_alpha_node.descendent_beta_nodes)
            self.action_hash.setdefault((idx + 1, 0), set()).add(t_node)

            # V_{0} = vars(query_p(..))
            head_query_pred = list(iter_condition(_rule.formula.body))[0]
            try:
                eval_vars[(idx + 1, 0)] = list(head_query_pred.terms)
            except IndexError:
                raise
                self.discarded_rules.add(rule)
                continue

            self.specialize_conjuncts(rule, idx, eval_vars)

        for (rule_no, body_idx), t_nodes in list(self.action_hash.items()):
            # Attach evaluate action to p-node that propagates
            # token to beta memory associated with evaluate(rule_no, body_idx)
            execute_action = EvaluateExecution((rule_no, body_idx), self, t_nodes)
            evaluation_stmt = (
                BFP_RULE[str(rule_no)],
                BFP_NS.evaluate,
                Literal(body_idx),
            )
            eval_index = tuple(
                [
                    i.value if isinstance(i, Literal) else int(i.split("Rule#")[-1])
                    for i in [evaluation_stmt[0], evaluation_stmt[-1]]
                ]
            )
            self.meta_evaluation.setdefault(eval_index, set()).add(execute_action)
            for t_node in t_nodes:
                t_node.execute_actions[evaluation_stmt] = (True, execute_action)
                # execute_action = EvaluateExecution(evalHash, (idx+1, body_idx+1), self, termNodeCk)
                # assert len(termNodeCk.consequent)==1
                # termNodeCk.execute_action = (None, execute_action)

        # Fix join variables for BetaNodes involving evaluate predicates
        for idx, rule in enumerate(self.rules):
            if rule in self.discarded_rules:
                continue

            # Rule a^k
            # p(x0, ..., xn) :- And(query_p(x0, ..., xn) evaluate(rule_no, n, X))
            # Join vars = vars(query_p) AND V_{n}
            head_query_pred = self.bfp_lookup[("b", idx + 1)].formula.body
            rule_body_len = len(list(iter_condition(rule.formula.body)))
            term_node = first(self.eval_hash[idx + 1, rule_body_len]).successor
            term_node.common_variables = list(
                set(eval_vars[(idx + 1, rule_body_len)]).intersection(
                    get_variables(head_query_pred, second_order=True)
                )
            )
            skip_mdbq_count = 0
            for body_idx, body_literal in enumerate(iter_condition(rule.formula.body)):
                if skip_mdbq_count > 0:
                    skip_mdbq_count -= 1
                    continue

                if (idx + 1, body_idx + 1) in self.action_hash:
                    # Rule c^k
                    # evaluate(rule_no, j+1, X) :- And(evaluate(rule_no, j, X) Literal(x0, ..., xj))
                    # Join vars = vars(Literal) AND V_{j}
                    term_node2 = self.action_hash[(idx + 1, body_idx + 1)]
                    assert len(term_node2) == 1
                    term_node2 = first(term_node2)
                    term_node2.common_variables = list(
                        set(eval_vars[(idx + 1, body_idx)]).intersection(
                            get_variables(body_literal, second_order=True)
                        )
                    )
                if (idx + 1, body_idx + 1) in self.max_edb_front2_end:
                    end_idx = self.max_edb_front2_end[(idx + 1, body_idx + 1)][-1]
                    skip_mdbq_count = end_idx - body_idx - 1

    def make_derived_query_predicate(self, predicate):
        if isinstance(predicate, AdornedUniTerm):
            new_adorned_pred = BFPQueryTerm(predicate, predicate.adornment)
        elif isinstance(predicate, N3Builtin):
            new_adorned_pred = BFPQueryTerm(predicate, builtin=predicate)
        else:
            new_adorned_pred = BFPQueryTerm(predicate, None)
        if isinstance(new_adorned_pred, Uniterm):
            if isinstance(get_op(new_adorned_pred), Variable):
                new_adorned_pred.set_operator(HIGHER_ORDER_QUERY)
            new_adorned_pred.finalize()
        self.query_predicates.add(new_adorned_pred)
        return new_adorned_pred

    def specialize_adorned_ruleset(self, debug=False):
        """
        Specialization is applied to the BFP meta-interpreter with respect to the
        rules of the object program. For each rule of the meta-interpreter
        that includes a premise referring to a rule of the object program, one
        specialized version is created for each rule of the object program.

        """
        rules = set()
        for idx, rule in enumerate(self.rules):
            label = BFP_RULE[str(idx + 1)]
            rule_body_len = len(list(iter_condition(rule.formula.body)))

            if debug:
                print("\t%s. %s" % (idx + 1, rule))
                for _sip in sip_representation(rule.sip):
                    print("\t\t", _sip)
            new_rule1 = self.rule1(rule, label, rule_body_len)
            self.bfp_lookup[("a", idx + 1)] = new_rule1
            rules.add(new_rule1)
            new_rule2 = self.rule2(rule, label, rule_body_len)
            self.bfp_lookup[("b", idx + 1)] = new_rule2
            rules.add(new_rule2)

            # indicate no skipping is ongoing
            skip_mdbq_count = -1
            m_db_conj_front = None
            # _len = len(rule.formula.body)
            for body_idx, body_literal in enumerate(iter_condition(rule.formula.body)):
                body_pred_symbol = get_op(body_literal)
                if skip_mdbq_count > 0:
                    skip_mdbq_count -= 1
                    continue
                elif skip_mdbq_count == 0:
                    # finished skipping maximal db conjuncts, mark end of skipped
                    # conjuncts and indicate that no skipping is ongoing
                    self.max_edb_front2_end[m_db_conj_front] = (idx + 1, body_idx)
                    m_db_conj_front = None
                    skip_mdbq_count = -1

                evaluate_term = Uniterm(
                    BFP_NS.evaluate,
                    [label, Literal(body_idx + 1)],
                    new_nss=self.namespaces,
                )
                prior_evaluate_term = Uniterm(
                    BFP_NS.evaluate, [label, Literal(body_idx)], new_nss=self.namespaces
                )
                conj = edb_query_from_body_iterator(
                    self.fact_graph,
                    rule.formula.body.formulae[body_idx:],
                    self.derived_predicates,
                    self.hybrid_predicates,
                )
                if self.push_down_mdbq and conj:
                    # There is a maximal db conjunction, indicate skipping of rules involving
                    # conjuncts
                    m_db_conj_front = (idx + 1, body_idx + 1)
                    if len(conj) > 1:
                        skip_mdbq_count = len(conj) - 1
                        self.push_down_queries[m_db_conj_front] = EDBQuery(
                            [copy.deepcopy(item) for item in conj], self.fact_graph
                        )
                    else:
                        self.max_edb_front2_end[m_db_conj_front] = (
                            idx + 1,
                            body_idx + 1,
                        )
                    if debug and skip_mdbq_count > 0:
                        print(
                            "maximal db query: ",
                            self.push_down_queries[m_db_conj_front],
                        )
                        print(
                            "skipping %s literals, starting from the %s"
                            % (body_idx + 1, skip_mdbq_count)
                        )
                    if len(conj) + body_idx == len(rule.formula.body):
                        # maximal db conjunction takes up rest of body
                        # tokens should go into (k, n) - where n is the body
                        # length
                        self.max_edb_front2_end[m_db_conj_front] = (
                            idx + 1,
                            len(rule.formula.body),
                        )
                if (
                    not self.push_down_mdbq
                    or (
                        (body_pred_symbol in FILTERS and len(conj) == 1)
                        or (
                            body_pred_symbol in self.derived_predicates
                            or is_hybrid_predicate(body_literal, self.hybrid_predicates)
                        )
                    )
                ) and skip_mdbq_count in (1, -1):
                    # Either not pushing down or:
                    # 1. It is a lone filter
                    # 2. It is a derived predicate (need continuation BFP rule)
                    # evaluate(ruleNo, j+1, X) :- evaluate(ruleNo, j, X)
                    # body_literal(..)
                    new_rule = self.make_adorned_rule(
                        And([prior_evaluate_term, body_literal]),
                        evaluate_term,
                        rule.ns_mapping,
                        ns_mgd_uniterm=body_literal,
                    )
                    self.bfp_lookup[("c", idx + 1, body_idx + 1)] = new_rule
                    rules.add(new_rule)
                elif body_pred_symbol in FILTERS and len(conj) > 2:
                    raise NotImplementedError(repr(rule))
                if body_pred_symbol not in FILTERS:
                    # query_Literal(x0, ..., xj) :- evaluate(ruleNo, j, X)
                    # OpenQuery(query_Literal)
                    new_rule = self.make_adorned_rule(
                        prior_evaluate_term,
                        self.make_derived_query_predicate(body_literal),
                        rule.ns_mapping,
                        ns_mgd_uniterm=body_literal,
                    )
                    self.bfp_lookup[("d", idx + 1, body_idx + 1)] = new_rule
                    rules.add(new_rule)
        return rules

    def make_adorned_rule(self, body, head, ns_mapping=None, ns_mgd_uniterm=None):
        ns_mapping = (
            ns_mapping
            if ns_mapping is not None and ns_mapping
            else (dict(ns_mgd_uniterm.ns_manager.namespaces()))
            if ns_mgd_uniterm is not None
            else None
        )
        all_vars = set()
        update_ns_managers(body, ns_mapping)
        update_ns_managers(head, ns_mapping)
        return AdornedRule(Clause(body, head), declare=all_vars, ns_mapping=ns_mapping)

    def rule1(self, rule, label, body_len):
        """
        'Facts are only generated in a bottom up evaluation of the interpreter if a query has been issued
         for that fact or if an appropriate sub-query has been generated by the metainterpreter
         itself.'

        a^{k}

        p(x0, ..., xn) :- And(query_p(x0, ..., xn) evaluate(ruleNo, n, X))
                            OpenQuery(query_p)

        If there are no bindings posed with the query, then OpenQuery(query_p)
        is used instead of query_p(x0, ..., xn), indicating that there are no bindings
        but we wish to evaluate this derived predicate.  However, despite the fact
        that it has no bindings, we want to continue to (openly) solve predicates
        in a depth-first fashion until we hit an EDB query.

        """
        evaluate_term = Uniterm(
            BFP_NS.evaluate, [label, Literal(body_len)], new_nss=self.namespaces
        )
        return self.make_adorned_rule(
            And([self.make_derived_query_predicate(rule.formula.head), evaluate_term]),
            rule.formula.head,
            rule.ns_mapping,
            ns_mgd_uniterm=rule.formula.head,
        )

    def rule2(self, rule, label, body_len):
        """
        When a query is matched, collect answers (begin to evaluate)

        b^{k}

        evaluate(ruleNo, 0, X) :- query_p(x0, ..., xn)
                                OpenQuery(query_p)

        If there are no bindings posed with the query, then OpenQuery(query_p)
        is used instead of query_p(x0, ..., xn), indicating that there are no bindings
        but we wish to evaluate this derived predicate.  However, despite the fact
        that it has no bindings, we want to continue to (openly) solve predicates
        in a depth-first fashion until we hit an EDB query.

        """
        evaluate_term = Uniterm(
            BFP_NS.evaluate, [label, Literal(0)], new_nss=self.namespaces
        )
        return self.make_adorned_rule(
            self.make_derived_query_predicate(rule.formula.head),
            evaluate_term,
            rule.ns_mapping,
            ns_mgd_uniterm=rule.formula.head,
        )


class BFPQueryTerm(Uniterm):
    def __init__(self, uterm, adornment=None, naf=False, builtin=None):
        self.adornment = adornment
        self.ns_mgr = uterm.ns_manager if hasattr(uterm, "nsMgr") else None
        if builtin:
            new_args = [builtin.argument, builtin.result]
            op = builtin.uri
            self.builtin = builtin
        else:
            new_args = copy.deepcopy(uterm.arg)
            op = uterm.op
            self.builtin = None
        super(BFPQueryTerm, self).__init__(op, new_args, naf=naf)

    def clone(self):
        return BFPQueryTerm(self, self.adornment, self.naf)

    def _recalculate_hash(self):
        self._hash = hash(
            reduce(
                lambda x, y: str(x) + str(y),
                len(self.arg) == 2 and self.to_rdf_tuple() or [self.op] + self.arg,
            )
        )

    def __hash__(self):
        if self.adornment is None:
            return self._hash
        else:
            return self._hash ^ hash(reduce(lambda x, y: x + y, self.adornment))

    def finalize(self):
        if self.adornment:
            if self.has_bindings():
                if len(self.adornment) == 1:
                    # adorned predicate occurrence with one out of two arguments bound
                    # convert: It becomes a unary predicate (an rdf:type
                    # assertion)
                    self.arg[-1] = URIRef(
                        get_op(self) + "_query_" + first(self.adornment)
                    )
                    self.arg[0] = first(self.get_distinguished_variables())
                    self.op = RDF.type
                elif "".join(self.adornment) == "bb":
                    # Two bound args
                    self.set_operator(URIRef(self.op + "_query_bb"))
                else:
                    # remove unbound argument, and reduce arity
                    single_arg = first(self.get_distinguished_variables())
                    self.arg[-1] = URIRef(
                        get_op(self) + "_query_" + "".join(self.adornment)
                    )
                    self.arg[0] = single_arg
                    self.op = RDF.type

            else:
                current_op = get_op(self)
                self.op = RDF.type
                self.arg = [current_op, BFP_RULE.OpenQuery]
        else:
            if get_op(self) != HIGHER_ORDER_QUERY:
                self.set_operator(URIRef(get_op(self) + "_query"))
        self._recalculate_hash()

    def has_bindings(self):
        if self.adornment:
            for idx, term in enumerate(get_args(self)):
                if self.adornment[idx] == "b":
                    return True
            return False

    def get_distinguished_variables(self, vars_only=False):
        if self.op == RDF.type:
            for idx, term in enumerate(get_args(self)):
                if self.adornment[idx] in ["b", "fb", "bf"]:
                    if not vars_only or isinstance(term, Variable):
                        yield term
        else:
            for idx, term in enumerate(self.arg):
                if self.adornment[idx] == "b":
                    if not vars_only or isinstance(term, Variable):
                        yield term

    def get_bindings(self, uniterm):
        rt = {}
        for idx, term in enumerate(self.arg):
            goal_arg = self.arg[idx]
            candidate_arg = uniterm.arg[idx]
            if self.adornment is None or (
                self.adornment[idx] == "b" and isinstance(candidate_arg, Variable)
            ):
                # binding
                rt[candidate_arg] = goal_arg
        return rt

    def __repr__(self):
        if self.builtin:
            return repr(self.builtin)
        else:
            pred = self.normalize_term(self.op)
            if self.op == RDF.type:
                # if self.adornment is None else '_'+self.adornment[0]
                adorn_suffix = ""
            else:
                # if self.adornment is None else '_'+''.join(self.adornment)
                adorn_suffix = ""
            if self.op == RDF.type:
                return "%s%s(%s)" % (
                    self.normalize_term(self.arg[-1]),
                    adorn_suffix,
                    self.normalize_term(self.arg[0]),
                )
            else:
                return "%s%s(%s)" % (
                    pred,
                    adorn_suffix,
                    " ".join([self.normalize_term(i) for i in self.arg]),
                )


class BackwardFixpointProcedureTests(unittest.TestCase):
    def setUp(self):
        pass


if __name__ == "__main__":
    unittest.main()
