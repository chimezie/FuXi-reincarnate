# -*- coding: utf-8 -*-
# flake8: noqa
"""
Proof Markup Language Construction: Proof Level Concepts (Abstract Syntax)

A set of Python objects which create a PML instance in order to serialize as
OWL/RDF

"""

from collections.abc import Mapping
from typing import Any, Optional, Tuple, Union, Iterable, List

from frozendict import frozendict
from rdflib.term import Identifier


def _get_graphviz():
    try:
        import graphviz
    except Exception as exc:
        raise ImportError("graphviz is required for proof rendering") from exc
    return graphviz


from fuxi.Horn.PositiveConditions import (
    build_uniTerm,
    Exists,
    SetOperator,
    Uniterm,
)
from fuxi.Horn.PositiveConditions import build_uniterm_from_tuple
from fuxi.types import Triple
from .BetaNode import project, BetaNode, PartialInstantiation
from fuxi.Rete.RuleStore import N3Builtin
from fuxi.Rete.AlphaNode import ReteToken
from fuxi.Rete.Magic import AdornedUniTerm
from rdflib import (
    BNode,
    Literal,
    Namespace,
    RDF,
    URIRef,
    Variable,
)


def fill_bindings(terms, bindings):
    for term in terms:
        if isinstance(term, Variable):
            yield bindings[term]
        else:
            yield term


def term_iterator(term):
    if isinstance(term, (Exists, SetOperator)):
        for i in term:
            yield i
    else:
        yield term


def _clause_from_justification(justification):
    """Resolve a clause from a proof justification.

    BFP uses BetaNode justifications without a ``.clause`` attribute, but each
    node carries a single rule with a ``.formula`` clause. Keep this strict to
    surface unexpected multi-rule justifications.
    """
    clause = getattr(justification, "clause", None)
    if clause is not None:
        return clause
    rules = getattr(justification, "rules", None)
    if not rules:
        raise RuntimeError("Missing clause and rules for proof justification")
    if len(rules) != 1:
        raise RuntimeError("Expected exactly one rule for proof justification")
    rule = next(iter(rules))
    clause = getattr(rule, "formula", None)
    if clause is None:
        raise RuntimeError("Rule does not expose a formula for proof justification")
    return clause


def _body_term_tuples(body_term):
    """Normalize a body term into RDF tuple(s) for binding checks."""
    if hasattr(body_term, "to_rdf_tuple"):
        return [body_term.to_rdf_tuple()]
    return [term.to_rdf_tuple() for term in term_iterator(body_term)]


def fetch_rete_justifications(goal, nodeset, builder, antecedent=None):
    """
    Takes a goal, a nodeset and an inference step the nodeset is the
    premise for the corresponding rule.  Returns a generator
    over the valid terminal nodes that are responsible for inferring
    the conclusion represented by the nodeset
    """
    # The justification indicated by the RETE network
    justification_for_goal = nodeset.network.justifications[goal]
    if antecedent:
        yielded = False
        # might not be a valid justification
        for rete_justification in justification_for_goal:
            valid_justification = True
            clause = _clause_from_justification(rete_justification)
            for body_term in clause.body:
                # is the premise already proven?
                failed_check = True
                try:
                    failed_check = any(
                        fill_bindings(term_tuple, antecedent.bindings) in builder.goals
                        for term_tuple in _body_term_tuples(body_term)
                    )
                except KeyError:
                    failed_check = False
                valid_justification = not failed_check
            if valid_justification:
                yielded = True
                yield rete_justification
        if not yielded:
            for t_node in nodeset.network.terminal_nodes:
                if t_node not in justification_for_goal:
                    try:
                        clause = _clause_from_justification(t_node)
                        if any(
                            tuple(fill_bindings(x.to_rdf_tuple(), antecedent.bindings))
                            == goal
                            for x in term_iterator(clause.head)
                        ):
                            yield t_node
                    except Exception:
                        pass
    else:
        for t_node in justification_for_goal:
            yield t_node


PML = Namespace("http://inferenceweb.stanford.edu/2004/07/iw.owl#")
PML_P = Namespace("http://inferenceweb.stanford.edu/2006/06/pml-provenance.owl#")
FUXI = URIRef("http://purl.org/net/chimezie/FuXi")
GMP_NS = Namespace("http://inferenceweb.stanford.edu/registry/DPR/GMP.owl#")


def generate_proof(network, goal, top_down_store=None):
    builder = ProofBuilder(network)
    proof = builder.build_node_set(goal, proof=True, top_down_store=top_down_store)
    issues = []
    proof.traverse_and_check(top_down_store.edb.ns_map, issues=issues)
    assert goal in network.inferred_facts
    return builder, proof


class ProofBuilder(object):
    """
    Recursively builds a Proof Markup Language (PML) proof tree from a fired RETE-UL
    network, maintaining state to avoid re-proving goals that have already been justified.

    The proof tree mirrors the structure defined by PML:

    - A **NodeSet** wraps a single conclusion (an RDF triple that was inferred or
      asserted) together with one or more **InferenceStep** objects that justify it.
    - An **InferenceStep** records the rule that was applied, the variable bindings
      used, and a list of antecedent NodeSets whose conclusions served as premises.
    - A proof of conclusion C is the NodeSet whose conclusion is C.  The proof is
      *conditional* on an assumption A if some step in the tree lists A as its
      conclusion with "assumption" as its justification, and A is never discharged
      by a later step.

    Building proceeds bottom-up from the original query goal:

    1. ``buildNodeSet`` creates (or retrieves) the NodeSet for a goal triple.
       - If the goal is not in ``network.justifications`` it is treated as an
         assertion (EDB fact or meta-interpretation seed).
       - Otherwise, ``fetchRETEJustifications`` yields the terminal BetaNode(s) whose
         firing inferred the goal, and ``buildInferenceStep`` is called for each.

    2. ``buildInferenceStep`` examines a single terminal node / rule that derived a
       goal, identifies the rule's body terms, and for each body term either:
       - marks it as asserted (if the ground triple is in working memory), or
       - recurses via ``buildNodeSet`` / ``build_non_evaluation_step`` to prove it.

       When the BFP (Backward Fixpoint Procedure) meta-interpreter is in use, goals
       and body terms may be *evaluate* triples (``bfp:evaluate(rule:M N)``).  The
       method contains special-case handling for three rule shapes:

       a. **evaluate :- evaluate + p(...)** -- a horn-clause evaluation step where the
          second body literal is a non-evaluate predicate that right-activated the
          terminal node.  Handled by grounding the predicate with proof-tracer
          bindings and delegating to ``buildNodeSet``.
       b. **evaluate :- evaluate** -- a pure evaluate chain where
          ``topDownStore.actionPropagationInfo`` links the evaluate action to the
          terminal node and token that fired it.
       c. **p(...) :- evaluate / p(...) :- ...** -- a derived predicate whose body
          may or may not contain evaluate literals.  Delegated to
          ``build_non_evaluation_step``.

    3. ``build_non_evaluation_step`` handles goals proved by "ordinary" (non-evaluate)
       RETE firings.  It iterates over the body terms of the justifying rule and, for
       each term, checks whether the derivation was mediated by a BFP meta-evaluation
       action, an EDB query action, or a plain RETE instantiation, and recurses
       accordingly.

    Attributes:
        goals:  ``{triple: NodeSet}`` -- maps each proven/asserted conclusion to its
                NodeSet, preventing duplicate work and infinite loops.
        network:  The ``ReteNetwork`` whose inferredFacts, justifications, proofTracers,
                  and workingMemory are consulted during proof construction.
        trace:  A human-readable log of proof-construction decisions (useful for
                debugging).
        serialized_node_sets:  Tracks which NodeSets have already been serialized to
                             RDF to avoid duplicates.
        query_predicates:  Predicates that originated from top-level queries (used
                          during serialization).
    """

    def __init__(self, network):
        self.goals = {}
        self.network = network
        self.trace = []
        self.serialized_node_sets = set()
        self.query_predicates = set()

    def extract_goals_from_node(self, node):
        """Walk an existing proof tree and register every NodeSet in ``self.goals``.

        This is used to import a previously-built (sub-)proof into the builder so
        that subsequent calls to ``buildNodeSet`` can detect already-proven goals
        and avoid redundant work.

        The traversal is polymorphic:

        - **NodeSet**: register its conclusion in ``self.goals``, then recurse into
          each of its inference steps.
        - **InferenceStep**: recurse into its parent NodeSet and each antecedent
          NodeSet.
        """
        if isinstance(node, NodeSet):
            if node.conclusion not in self.goals:
                self.goals[node.conclusion] = node
                for step in node.steps:
                    self.extract_goals_from_node(step)
        else:
            self.extract_goals_from_node(node.parent)
            for ant in node.antecedents:
                self.extract_goals_from_node(ant)

    def serialize(self, proof, proofGraph):
        proof.serialize(self, proofGraph)

    def render_proof(self, proof, ns_map=None, format="png"):
        """Render the proof tree as a graphviz directed graph (Digraph).

        Args:
            proof: The root NodeSet (the original query goal).  Used to mark the
                   root node specially in the graph.
            ns_map: Optional namespace mapping for constructing QNames in node labels.
            format: Output format for the graphviz Digraph (e.g. 'png', 'svg').
                    Defaults to 'png'.

        Returns:
            A ``graphviz.Digraph`` with two kinds of edges:

            - **Red "is the consequence of"** edges from a NodeSet to each of its
              InferenceStep justifications.
            - **Blue "has antecedent"** edges from an InferenceStep to each of its
              antecedent NodeSets.  When the justification is sourced from an
              assertion the edge direction is reversed (antecedent -> nodeset) to
              visually distinguish base facts.
        """
        if ns_map is None:
            ns_map = {}
        graphviz = _get_graphviz()
        dot = graphviz.Digraph(
            "Proof graph", comment=f"Proof graph for {proof}", format=format
        )
        visited_nodes = {}
        idx = 0
        binding_info = {}

        # --- Pass 1: create graph nodes for every NodeSet, InferenceStep, and
        #     antecedent NodeSet reachable from self.goals. ---
        for nodeset in list(self.goals.values()):
            if nodeset not in visited_nodes:
                idx += 1
                nodeset.generate_graph_node(dot, idx, nodeset is proof, ns_map=ns_map)
                visited_nodes[nodeset] = idx
            for justification in nodeset.steps:
                if justification not in visited_nodes:
                    idx += 1
                    # Inference Step
                    binding_info[idx] = justification.generate_graph_node(
                        dot, idx, ns_map=ns_map
                    )
                    visited_nodes[justification] = idx
                    for ant in justification.antecedents:
                        if ant not in visited_nodes:
                            idx += 1
                            ant.generate_graph_node(dot, idx, ns_map=ns_map)
                            visited_nodes[ant] = idx

        # --- Pass 2: create edges. ---
        for nodeset in list(self.goals.values()):
            for justification in nodeset.steps:
                # NodeSet --[is the consequence of]--> InferenceStep
                dot.edge(
                    str(visited_nodes[nodeset]),
                    str(visited_nodes[justification]),
                    label=binding_info[visited_nodes[justification]],
                    color="red",
                )
                for ant in justification.antecedents:
                    if justification.source == "some RDF graph":
                        # Assertion-backed justification: draw antecedent -> nodeset
                        dot.edge(
                            str(visited_nodes[ant.steps[0]]),
                            str(visited_nodes[nodeset]),
                            label="has antecedent",
                            color="blue",
                        )
                    else:
                        # Inferred justification: draw justification -> antecedent
                        dot.edge(
                            str(visited_nodes[justification]),
                            str(visited_nodes[ant]),
                            label="has antecedent",
                            color="blue",
                        )
        return dot

    def extract_meta_interpreter_actions(
        self,
        action_propagation_info: Mapping[
            Any,
            Mapping[BetaNode, Iterable[Tuple[BetaNode, PartialInstantiation]]],
        ],
        bindings: Mapping[Variable, Identifier],
        action: Optional[Any] = None,
        action_types: Optional[Tuple[type, ...]] = None,
        rule_index: Optional[int] = None,
        body_index: Optional[int] = None,
        terminal_node: Optional[BetaNode] = None,
    ):
        """
        Extracts and yields meta-interpreter actions with their associated data.

        This method evaluates the provided action propagation information to find
        matching actions based on the specified action types, rule index, body index,
        and terminal node. It filters the actions according to the compatibility of
        bindings and yields relevant information for each match.

        :param action_propagation_info: A dictionary mapping actions to their relevant
            rule derivation information.
        :param bindings: A dictionary of current variable bindings that will be used
            for compatibility checks with the derivation information.
        :param action: A meta-interpretation action to use to ensure only its rule derivation is considered
            otherwise all of them are considered (by default).
        :param action_types: Optional. A tuple of action types to filter the
            propagation information. Defaults to (EvaluateExecution, QueryExecution).
        :param rule_index: Optional. The specific rule index to match against the
            action's `rule_no` attribute. If None, this filter is ignored.
        :param body_index: Optional. The specific body index to match against the
            action's `body_idx` attribute. If None, this filter is ignored.
        :param terminal_node: Optional. A BetaNode that acts as a terminal node.
            If provided, only actions referencing the terminal node are considered.
        :return: A generator yielding tuples containing fired node, instantiations,
            antecedent node, and the action object when matches are found.
            Yields no items if no matches are found or the filtering criteria are unmet.
        """
        from ..LP.BackwardFixpointProcedure import QueryExecution, EvaluateExecution

        def compatible(tokens: PartialInstantiation) -> bool:
            return not any(
                bindings.get(key, value) != value
                for token_bindings in tokens.bindings
                for key, value in token_bindings.items()
            )

        if action_types is None:
            action_types = (EvaluateExecution, QueryExecution)

        if action is None:
            items = action_propagation_info.items()
        elif action in action_propagation_info:
            items = [(action, action_propagation_info[action])]
        else:
            items = []

        for stored_action, fired_node_info in items:
            if not isinstance(stored_action, action_types):
                continue
            if rule_index is not None and (
                stored_action.rule_no != rule_index
                or stored_action.body_idx != body_index
            ):
                continue
            if terminal_node is not None and terminal_node not in fired_node_info:
                continue
            node_iter = (
                [(terminal_node, fired_node_info[terminal_node])]
                if terminal_node is not None
                else fired_node_info.items()
            )
            for fired_node, instantiation_info in node_iter:
                for antecedent_node, instantiations in instantiation_info:
                    if compatible(instantiations):
                        yield fired_node, instantiations, antecedent_node, stored_action

    def build_inference_step(
        self, parent, terminal_node, goal, top_down_store=None, bindings=None
    ):
        """Build an InferenceStep that justifies *parent* (a NodeSet) via *terminalNode*.

        This is the core recursive method of proof construction.  Given a goal triple
        and the terminal BetaNode whose firing inferred it, it:

        1. Resolves the clause (rule) associated with *terminalNode*.
        2. Collects variable bindings -- from the caller and from
           ``network.proofTracers`` (which records the bindings the RETE network
           used when it originally inferred the goal).
        3. Creates an ``InferenceStep`` for the rule application.
        4. If the goal is already in working memory (i.e., it was asserted, not
           inferred), marks the step as sourced from an RDF graph and returns.
        5. Otherwise, examines the rule's body terms and dispatches to the
           appropriate handler depending on the shape of the rule -- see the class
           docstring for the three BFP rule shapes (a, b, c).

        Args:
            parent:        The NodeSet whose ``steps`` list this step will be added to.
            terminal_node:  The terminal BetaNode (from ``network.justifications``) whose
                           associated rule derived *goal*.
            goal:          The RDF triple ``(s, p, o)`` being justified.
            top_down_store:  The ``BFPAlgorithm`` instance holding BFP runtime state
                           (``actionPropagationInfo``, ``meta_evaluation``,
                           ``meta_interpretation_seeds``).
            bindings:      Optional pre-existing variable bindings (a dict or list of
                           dicts) inherited from the parent proof step.  When ``None``,
                           bindings are seeded solely from ``network.proofTracers``.

        Returns:
            The constructed ``InferenceStep``, with its ``antecedents`` list populated
            by recursively proven NodeSets for each body term.
        """
        from fuxi.LP.BackwardFixpointProcedure import (
            BFPQueryTerm,
            EvaluateExecution,
            BFP_NS,
            BFP_RULE,
        )
        from fuxi.Horn.PositiveConditions import And, Uniterm

        # --- Resolve the clause (rule) for this terminal node. ---
        # When the terminal node carries multiple rules (uncommon), pick the one
        # whose head matches the goal being proven.
        if len(terminal_node.rules) > 1:
            for clause in [
                r.formula
                for r in terminal_node.rules
                if r.formula.head.to_rdf_tuple() == goal
            ]:
                pass
        else:
            clause = _clause_from_justification(terminal_node)

        # --- Collect bindings. ---
        # Start with any caller-supplied bindings, then merge in the bindings that
        # the RETE network recorded when it originally inferred this goal (stored in
        # proofTracers).  The result is a dict {Variable -> ground value}.
        bindings = {} if bindings is None else bindings
        for _dict in self.network.proof_tracers.get(goal, []):
            bindings.update(_dict)
        step = InferenceStep(parent, clause, bindings=bindings)

        # --- Base case: goal was asserted (present in working memory). ---
        if ReteToken(goal) in self.network.working_memory:
            step.source = "some RDF graph"
            self.trace.append("Marking justification from assertion for " + repr(goal))
            return step

        s, p, o = goal

        # OpenQuery atoms are internal BFP mechanism goals produced by query-
        # propagation rules of the form:
        #   OpenQuery(P_derived) :- evaluate(ruleNo, K)
        # They appear in network.justifications but their derivation chain is
        # BFP bookkeeping, not domain reasoning.  Treat them as proved by the
        # BFP query mechanism rather than recursing into the evaluate chain,
        # which would fall through case (b) with no EvaluateExecution match.
        if o == BFP_RULE.OpenQuery:
            step.source = "BFP query mechanism"
            return step

        # Normalize the clause body into a list of Uniterm / BFPQueryTerm literals.
        body_terms = (
            [clause.body]
            if isinstance(clause.body, (BFPQueryTerm, Uniterm))
            else list(clause.body)
        )

        # =====================================================================
        # Identify non-evaluate body terms that immediately follow an evaluate
        # literal and whose predicate appears in inferredFacts.  These are the
        # "right-activating antecedents": body literals like ``p(?V1 ?V2)`` in a
        # rule of the form
        #
        #   bfp:evaluate(rule:M N+2) :- And( bfp:evaluate(rule:M N) p(?V1 ?V2) )
        #
        # The terminal node for such a rule is right-activated when a ground
        # instance of ``p(?V1 ?V2)`` is asserted into the alpha memory.  We use
        # the proof-tracer bindings (which record the substitution used when the
        # rule originally fired) to recover that ground instance and delegate its
        # proof to buildNodeSet.
        #
        # This check MUST come before the evaluate-dispatch below, because for
        # these rules the standard actionPropagationInfo path may not capture
        # right-activation firings.
        # =====================================================================
        derived_right_activating_antecedents = [
            t
            for i, t in enumerate(body_terms)
            if hasattr(t, "op")
            and t.op != BFP_NS.evaluate
            and any(self.network.inferred_facts.triples((None, t.op, None)))
            and (i > 0 and getattr(body_terms[i - 1], "op", None) == BFP_NS.evaluate)
        ]

        for term in derived_right_activating_antecedents:
            # Ground the right-activating body term by substituting variables
            # using the bindings already collected from proofTracers / the caller.
            term_triples = term.to_rdf_tuple()
            if isinstance(step.bindings, Mapping):
                grounded = tuple([step.bindings.get(arg, arg) for arg in term_triples])
            else:
                grounded = term_triples
                for binding in step.bindings:
                    grounded = tuple([binding.get(arg, arg) for arg in grounded])

            # Skip if any variables remain unbound (incomplete bindings).
            if any(isinstance(t, Variable) for t in grounded):
                continue
            # Skip if the grounded triple was never actually inferred.
            if not any(self.network.inferred_facts.triples(grounded)):
                continue

            # The grounded triple is confirmed as an inferred fact that
            # right-activated this rule.  Delegate its proof to buildNodeSet,
            # which will find the terminal node that actually derived it (a
            # different node from the current terminalNode) and recurse.
            new_rule_goal = grounded
            self.trace.append(
                "Right-activation confirmed: building nodeset for ground antecedent %s"
                % build_uniterm_from_tuple(new_rule_goal)
            )
            self.trace.append("Bindings: %s" % str(step.bindings))
            step.antecedents.append(
                self.build_node_set(
                    new_rule_goal, antecedent=step, top_down_store=top_down_store
                )
            )
            eval_goal = [t for t in body_terms if t != term][0].to_rdf_tuple()
            step.antecedents.append(
                self.build_node_set(
                    eval_goal, antecedent=step, top_down_store=top_down_store
                )
            )
            return step

        # =====================================================================
        # Dispatch based on the shape of the rule and the goal predicate.
        # =====================================================================

        if p == BFP_NS.evaluate and any(
            getattr(t, "op", None) == BFP_NS.evaluate for t in body_terms
        ):
            # -----------------------------------------------------------------
            # Case (a): evaluate(rule:M N) :- And( evaluate(rule:M K) ... )
            #
            # Both the head and at least one body literal are evaluate terms.
            # This represents an intermediate step in the BFP meta-evaluation
            # chain.  We look up the EvaluateExecution action using extract_meta_interpreter_actions
            # to find which terminal node and token (PartialInstantiation)
            # produced this evaluation step, then recurse into the preceding
            # evaluation goal.
            # -----------------------------------------------------------------
            eval_index = tuple(
                [
                    i.value if isinstance(i, Literal) else int(i.split("Rule#")[-1])
                    for i in [s, o]
                ]
            )
            rule_index, body_index = (eval_index[0], eval_index[1] - 1)
            new_rule_goal = (
                getattr(BFP_RULE, str(rule_index)),
                BFP_NS.evaluate,
                Literal(body_index),
            )

            matches = list(
                self.extract_meta_interpreter_actions(
                    top_down_store.action_propagation_info,
                    bindings,
                    action_types=(EvaluateExecution,),
                    rule_index=rule_index,
                    body_index=body_index,
                )
            )
            if matches:
                for fired_node, instantiations, antecedent_node, eval_action in matches:
                    self.trace.append(
                        f"Building nodeset around intermediate meta evaluation goal({rule_index} {body_index})"
                    )
                    token_bindings = list(instantiations.bindings)
                    merged_bindings = {}
                    for binding_dict in token_bindings:
                        merged_bindings.update(binding_dict)
                    self.trace.append("Bindings: %s" % token_bindings)
                    ns = self.goals.get(new_rule_goal)
                    if ns is None:
                        idx = BNode()
                        ns = NodeSet(
                            new_rule_goal, network=self.network, identifier=idx
                        )
                        self.goals[new_rule_goal] = ns
                        new_step = self.build_inference_step(
                            ns,
                            antecedent_node,
                            new_rule_goal,
                            top_down_store,
                            bindings=merged_bindings,
                        )
                        ns.steps.append(new_step)
                    step.antecedents.append(ns)
                    return step

            # Fallback: if no matching EvaluateExecution was found, ground the first non-evaluate body term
            # and treat it as a regular (non-evaluate) derivation.
            for term in [
                t for t in body_terms if getattr(t, "op", None) != BFP_NS.evaluate
            ]:
                term_triples = term.to_rdf_tuple()
                term_triples = tuple(
                    [step.bindings.get(arg, arg) for arg in term_triples]
                )
                goal = term_triples
                return self.build_non_evaluation_step(
                    goal, parent, step, bindings, top_down_store
                )

        else:
            # -----------------------------------------------------------------
            # The head is not an evaluate goal, OR the body contains no evaluate
            # literals.
            # -----------------------------------------------------------------

            if p == BFP_NS.evaluate:
                # The head IS an evaluate goal but no body term is evaluate.
                # This is a "leaf" evaluation rule like:
                #   evaluate(rule:M 1) :- p(...)
                # Ground each body term using step.bindings so we can check
                # whether the resulting triple is a meta-interpretation seed or
                # needs further proving.
                for term in body_terms:
                    self.trace.append(
                        f"Building nodeset around intermediate goal ({term})"
                    )
                    self.trace.append("Bindings: %s" % step.bindings)
                    term_triples = term.to_rdf_tuple()
                    term_triples = tuple(
                        [step.bindings.get(arg, arg) for arg in term_triples]
                    )

                    self.trace.append("Building inference step for %s" % parent)
                    self.trace.append("Inferred from RETE node via %s" % (clause))
                    self.trace.append("Bindings: %s" % step.bindings)

                    step.antecedents.append(
                        self.build_node_set(
                            term_triples, antecedent=step, top_down_store=top_down_store
                        )
                    )
                return step

            # --- Check if the (possibly re-grounded) goal is a seed. ---
            # Meta-interpretation seeds are the original query goals injected
            # by the BFP algorithm; they are axiomatically true and need no
            # further justification.
            if goal in top_down_store.meta_interpretation_seeds:
                idx = BNode()
                ns = self.goals.get(goal, None)
                if ns is None:
                    ns = NodeSet(goal, network=self.network, identifier=idx)
                    self.goals[goal] = ns
                    ns.steps.append(InferenceStep(ns, source="Goal query assertion"))
                step.antecedents.append(ns)
                self.trace.append(
                    "Marking justification from assertion for " + repr(goal)
                )
                return step

            elif (
                any(getattr(t, "op", None) == BFP_NS.evaluate for t in body_terms)
                and len(body_terms) == 1
            ):
                # -------------------------------------------------------------
                # Case (b): p_derived(...) :- evaluate(rule:M N)
                #
                # A derived predicate whose sole body literal is an evaluate
                # term.  Look up the corresponding EvaluateExecution in
                # actionPropagationInfo.  If found, recurse into the evaluation
                # chain.  Otherwise fall through to build_non_evaluation_step.
                # -------------------------------------------------------------
                s, p, o = body_terms[0].to_rdf_tuple()
                eval_index = tuple(
                    [
                        i.value if isinstance(i, Literal) else int(i.split("Rule#")[-1])
                        for i in [s, o]
                    ]
                )
                rule_index, body_index = eval_index[0], eval_index[1]
                new_rule_goal = (
                    getattr(BFP_RULE, str(rule_index)),
                    BFP_NS.evaluate,
                    Literal(body_index),
                )

                matches = list(
                    self.extract_meta_interpreter_actions(
                        top_down_store.action_propagation_info,
                        bindings,
                        action_types=(EvaluateExecution,),
                        rule_index=rule_index,
                        body_index=body_index,
                    )
                )
                if matches:
                    for (
                        fired_node,
                        instantiations,
                        antecedent_node,
                        eval_action,
                    ) in matches:
                        self.trace.append(
                            f"Building nodeset around intermediate meta evaluation goal({rule_index} {body_index})"
                        )
                        token_bindings = list(instantiations.bindings)
                        self.trace.append("Bindings: %s" % token_bindings)
                        ns = self.goals.get(new_rule_goal)
                        if ns is None:
                            idx = BNode()
                            ns = NodeSet(
                                new_rule_goal, network=self.network, identifier=idx
                            )
                            self.goals[new_rule_goal] = ns
                            merged_bindings = {}
                            for binding_dict in token_bindings:
                                merged_bindings.update(binding_dict)
                            new_step = self.build_inference_step(
                                ns,
                                antecedent_node,
                                new_rule_goal,
                                top_down_store,
                                bindings=merged_bindings,
                            )
                            ns.steps.append(new_step)
                        step.antecedents.append(ns)
                        return step

                # Fallback: ground the non-evaluate body terms and delegate.
                for term in [
                    t for t in body_terms if getattr(t, "op", None) != BFP_NS.evaluate
                ]:
                    term_triples = term.to_rdf_tuple()
                    term_triples = tuple(
                        [step.bindings.get(arg, arg) for arg in term_triples]
                    )
                    goal = term_triples
                    return self.build_non_evaluation_step(
                        goal, parent, step, bindings, top_down_store
                    )

            else:
                # -------------------------------------------------------------
                # Case (c): p_derived(...) :- <no evaluate literals>
                #            OR body has more than one literal (mixed).
                #
                # Delegate entirely to build_non_evaluation_step which handles
                # ordinary RETE-justified body terms.
                # -------------------------------------------------------------
                return self.build_non_evaluation_step(
                    goal, parent, step, bindings, top_down_store
                )

        raise SyntaxError(
            f"Unable to build inference step for {build_uniterm_from_tuple(goal)}"
        )

    def build_non_evaluation_step(
        self,
        goal: Tuple[Identifier, Identifier, Identifier],
        parent: "NodeSet",
        step: "InferenceStep",
        bindings: Mapping[Variable, Identifier],
        top_down_store,
    ):
        """Build proof antecedents for a goal derived by ordinary (non-evaluate) RETE rules.

        This method handles goals that were inferred through standard RETE network
        firings (as opposed to BFP meta-evaluation chains).  It iterates over the
        terminal BetaNodes that justify *goal* and, for each one that has recorded
        instantiations, walks the rule's body terms to build antecedent NodeSets.

        Each body term is handled according to how it was derived:

        1. **evaluate body term** -- The body literal is ``bfp:evaluate(rule:M N)``.
           The corresponding ``EvaluateExecution`` action is looked up in
           ``topDownStore.meta_evaluation`` and ``actionPropagationInfo`` to find the
           terminal node and token that fired it, then ``buildInferenceStep`` is
           called recursively to prove the evaluate goal.

        2. **Non-evaluate term derived via EDB query** -- A ``QueryExecution`` action
           in ``actionPropagationInfo`` records that this terminal node was fired as a
           consequence of EDB (extensional database) query results being propagated
           through the network.  The body term is grounded using the query bindings,
           and if the grounded predicate differs from the antecedent node's head
           predicate (due to magic-set rewriting), the goal is adjusted accordingly.

        3. **Non-evaluate term derived by plain RETE instantiation** -- The body term
           was derived purely through RETE pattern matching with no BFP involvement.
           Unbound variables are resolved from the terminal node's instantiating
           tokens, the body term is fully grounded, and ``buildNodeSet`` is called
           to recursively prove it.

        Args:
            goal:          The ground RDF triple ``(s, p, o)`` to justify.
            parent:        The NodeSet this step belongs to.
            step:          The InferenceStep being constructed (antecedents will be
                           appended to ``step.antecedents``).
            top_down_store:  The ``BFPAlgorithm`` instance with BFP runtime state.

        Returns:
            The populated ``InferenceStep`` if at least one antecedent was proven,
            or ``None`` if no justification could be established.
        """
        from fuxi.LP.BackwardFixpointProcedure import QueryExecution, BFP_NS
        from fuxi.Rete.SidewaysInformationPassing import get_op
        from fuxi.SPARQL import normalize_bindings_and_query, rdf_tuples_to_sparql

        for t_node in fetch_rete_justifications(goal, parent, self, step):
            clause = _clause_from_justification(t_node)

            if not self.network.instantiations.get(t_node):
                # This terminal node has no recorded instantiations for the goal;
                # skip it and try the next justifying node.
                continue

            # The goal was instantiated directly from this terminal node.
            # Walk each body term to build its antecedent proof.
            body_terms = list(clause.body)
            for body_term in body_terms:
                triple = body_term.to_rdf_tuple()

                if triple[1] == BFP_NS.evaluate:
                    # -------------------------------------------------------
                    # Body term is an evaluate literal.
                    # Look up which EvaluateExecution action(s) correspond to
                    # this evaluate index, then find the terminal node and
                    # token in actionPropagationInfo that fired it.
                    # -------------------------------------------------------
                    eval_index = tuple(
                        [
                            i.value
                            if isinstance(i, Literal)
                            else int(i.split("Rule#")[-1])
                            for i in body_term.arg
                        ]
                    )
                    for eval_action in top_down_store.meta_evaluation.get(
                        eval_index, set()
                    ):
                        matches = list(
                            self.extract_meta_interpreter_actions(
                                top_down_store.action_propagation_info,
                                bindings,
                                action=eval_action,
                            )
                        )
                        if matches:
                            for (
                                fired_node,
                                token,
                                antecedent_node,
                                eval_action,
                            ) in matches:
                                self.trace.append(
                                    "Building inference step for %s" % parent
                                )
                                self.trace.append(
                                    "Inferred from RETE via meta-evaluation rule %s"
                                    % (_clause_from_justification(antecedent_node))
                                )
                                token_bindings = list(token.bindings)
                                self.trace.append("Bindings: %s" % token_bindings)
                                ns = self.goals.get(triple)
                                if ns is None:
                                    idx = BNode()
                                    ns = NodeSet(
                                        triple, network=self.network, identifier=idx
                                    )
                                    self.goals[triple] = ns
                                    merged_bindings = {}
                                    for binding_dict in token_bindings:
                                        merged_bindings.update(binding_dict)
                                    new_step = self.build_inference_step(
                                        ns,
                                        antecedent_node,
                                        triple,
                                        top_down_store,
                                        bindings=merged_bindings,
                                    )
                                    ns.steps.append(new_step)
                                step.antecedents.append(ns)
                else:
                    # -------------------------------------------------------
                    # Body term is a non-evaluate literal.
                    # Check whether it was derived via an EDB QueryExecution
                    # or through plain RETE pattern matching.
                    # -------------------------------------------------------

                    matches = list(
                        self.extract_meta_interpreter_actions(
                            top_down_store.action_propagation_info,
                            bindings,
                            action_types=(QueryExecution,),
                            terminal_node=t_node,
                        )
                    )
                    if matches:
                        for (
                            fired_node,
                            instantiations,
                            antecedent_node,
                            action,
                        ) in matches:
                            # ---------------------------------------------------
                            # EDB query path: a QueryExecution action propagated
                            # bindings through t_node.  Ground the body term using
                            # those bindings.  If magic-set rewriting caused the
                            # grounded predicate to differ from the antecedent
                            # node's head, re-target to the correct goal.
                            # ---------------------------------------------------
                            self.trace.append(
                                f"Adding EDB query ({action}) solutions as bypassing antecedent {body_term}"
                            )
                            token_bindings = list(instantiations.bindings)
                            term_triples = body_term.to_rdf_tuple()
                            step_bindings = {}
                            for bindings in token_bindings + [
                                clause.head.unify_with(build_uniterm_from_tuple(goal))
                            ]:
                                step_bindings.update(bindings)
                                term_triples = tuple(
                                    [bindings.get(arg, arg) for arg in term_triples]
                                )
                            self.trace.append("Bindings: %s" % token_bindings)
                            idx = BNode()
                            antecedent_clause = _clause_from_justification(
                                antecedent_node
                            )
                            # If the grounded body term's predicate doesn't
                            # match the antecedent rule's head predicate
                            # (e.g. due to magic-set adorned rewriting),
                            # re-ground using the antecedent's head instead.
                            if get_op(build_uniterm_from_tuple(term_triples)) != get_op(
                                antecedent_clause.head
                            ):
                                new_goal = tuple(
                                    [
                                        step_bindings.get(arg, arg)
                                        for arg in antecedent_clause.head.to_rdf_tuple()
                                    ]
                                )
                                term_triples = new_goal
                            ns = self.goals.get(term_triples)

                            # [({f"?{k}": v.split('#')[-1] for k, v in bindings.items()}, literal) for bindings, literal
                            #  in action.fired_grounded_queries.items()]

                            def compatible_query_bindings(
                                query_bindings: Mapping[Variable, Identifier],
                            ) -> bool:
                                return not any(
                                    bindings.get(key, value) != value
                                    for key, value in query_bindings.items()
                                )

                            edb_query_literal = None
                            q_bindings = None
                            vars = []
                            for (
                                query_bindings,
                                literal,
                            ) in action.fired_grounded_queries.items():
                                if compatible_query_bindings(query_bindings):
                                    edb_query_literal = literal
                                    q_bindings = query_bindings
                                    break
                            assert edb_query_literal is not None, (
                                "No compatible query bindings found"
                            )

                            if bool(q_bindings):
                                open_vars, conj_ground_literals, bindings = (
                                    normalize_bindings_and_query(
                                        set(vars), bindings, edb_query_literal
                                    )
                                )
                                vars = list(open_vars)
                            else:
                                conj_ground_literals = edb_query_literal.formulae
                            is_ground = not vars
                            subquery = rdf_tuples_to_sparql(
                                conj_ground_literals,
                                top_down_store.edb,
                                is_ground,
                                [v for v in vars],
                            )
                            step.source = f"{subquery}"
                            if ns is None:
                                ns = NodeSet(
                                    term_triples, network=self.network, identifier=idx
                                )
                                self.goals[term_triples] = ns
                                self.trace.append("Building inference step for %s" % ns)
                                self.trace.append(
                                    "Inferred from RETE node via %s" % (clause)
                                )
                                self.trace.append("Bindings: %s" % step.bindings)
                                self.trace.append(
                                    f"Triggered by query action {action} triggered by {antecedent_clause}"
                                )
                                new_step = self.build_inference_step(
                                    ns,
                                    antecedent_node,
                                    term_triples,
                                    top_down_store,
                                    bindings=step_bindings,
                                )
                                ns.steps.append(new_step)
                            step.antecedents.append(ns)
                    else:
                        # ---------------------------------------------------
                        # Plain RETE instantiation path: no BFP action was
                        # involved.  Resolve any remaining unbound variables
                        # from the terminal node's instantiating tokens, then
                        # fully ground the body term and delegate to
                        # buildNodeSet.
                        # ---------------------------------------------------

                        # Identify variables in this body term that are not
                        # yet bound in step.bindings.
                        for termVar in term_iterator(body_term):
                            assert isinstance(termVar, (Uniterm, N3Builtin))
                            a = [
                                x
                                for x in termVar.to_rdf_tuple()
                                if isinstance(x, Variable) and x not in step.bindings
                            ]

                        # Project the missing variable bindings out of the
                        # terminal node's instantiating tokens.
                        binds = []
                        for t in t_node.instanciating_tokens:
                            binds.extend(
                                [project(binding, a) for binding in t.bindings]
                            )
                        binds = set([frozendict(bind) for bind in binds])
                        # There should be at most one consistent binding set;
                        # multiple would indicate ambiguity.
                        assert len(binds) < 2
                        for b in binds:
                            step.bindings.update(b)

                        # Verify that all variables in the body term are now
                        # bound (every variable must appear in step.bindings,
                        # every non-variable is already ground).
                        for termVar in term_iterator(body_term):
                            assert isinstance(termVar, (N3Builtin, Uniterm))
                            assert all(
                                isinstance(x, Variable)
                                and x in step.bindings
                                or not isinstance(x, Variable)
                                for x in termVar.to_rdf_tuple()
                            )

                        # Produce the fully ground antecedent triple and
                        # recursively build its proof via buildNodeSet.
                        ground_antecedent_assertion = tuple(
                            fill_bindings(triple, step.bindings)
                        )
                        self.trace.append("Building inference step for %s" % parent)
                        self.trace.append("Inferred from RETE node via %s" % (clause))
                        self.trace.append("Bindings: %s" % step.bindings)
                        step.antecedents.append(
                            self.build_node_set(
                                ground_antecedent_assertion,
                                antecedent=step,
                                top_down_store=top_down_store,
                            )
                        )

        return step if step.antecedents else None

    def build_node_set(self, goal, antecedent=None, proof=False, top_down_store=None):
        """Create or retrieve the NodeSet that proves *goal*.

        This is the main entry point for recursively building the proof tree.  It
        handles three situations:

        1. **Goal already proven** (present in ``self.goals``): returns the
           previously-built NodeSet to avoid duplicate work and infinite cycles.

        2. **Goal not in ``network.justifications``** (not inferred): the goal is
           treated as a base fact.  A NodeSet is created with a single
           InferenceStep whose source is either:
           - ``"Goal query assertion"`` if the goal is a BFP meta-interpretation
             seed (one of the original query goals injected into the network), or
           - ``"some RDF graph"`` for ordinary asserted triples.

        3. **Goal in ``network.justifications``** (inferred): the RETE network has
           one or more terminal BetaNodes that derived this goal.
           ``fetchRETEJustifications`` yields the valid ones, and
           ``buildInferenceStep`` is called for each to build a full inference step
           with recursively proven antecedents.

        Args:
            goal:          The ground RDF triple ``(s, p, o)`` to prove.
            antecedent:    Optional InferenceStep that depends on this goal (used by
                           ``fetchRETEJustifications`` to filter out circular
                           justifications).
            proof:         If ``True``, this is the root call (the original query
                           goal); affects only trace messages.
            top_down_store:  The ``BFPAlgorithm`` instance with BFP runtime state.

        Returns:
            The NodeSet for *goal*, with its ``steps`` list populated.
        """
        from fuxi.LP.BackwardFixpointProcedure import BFPQueryTerm
        from fuxi.Rete.SidewaysInformationPassing import get_op

        goal_uniterm = build_uniTerm(goal, self.network.ns_map)

        if goal not in self.network.justifications:
            # ---------------------------------------------------------------
            # The goal has no RETE justification -- it was never inferred, so
            # it must be an asserted fact (EDB) or a meta-interpretation seed.
            # ---------------------------------------------------------------
            self.trace.append(
                "Building %s around%sgoal (justified by a direct assertion): %s"
                % (
                    proof and "proof" or "nodeset",
                    antecedent and " antecedent " or "",
                    str(goal_uniterm),
                )
            )
            if goal in top_down_store.meta_interpretation_seeds:
                # The goal was injected by the BFP algorithm as one of the
                # original query goals.
                idx = BNode()
                ns = NodeSet(goal, network=self.network, identifier=idx)
                self.goals[goal] = ns
                ns.steps.append(InferenceStep(ns, source="Goal query assertion"))
                self.trace.append(
                    "Marking justification from assertion for " + repr(goal)
                )
            elif goal in self.goals:
                # Already built in a prior recursion; reuse it.
                ns = self.goals[goal]
                self.trace.append("Retrieving prior nodeset %s for %s" % (ns, goal))
            else:
                # Ordinary asserted triple from the RDF graph.
                idx = BNode()
                ns = NodeSet(goal, network=self.network, identifier=idx)
                self.goals[goal] = ns
                ns.steps.append(InferenceStep(ns, source="some RDF graph"))
                self.trace.append(
                    "Marking justification from assertion for " + repr(goal)
                )
        else:
            # ---------------------------------------------------------------
            # The goal was inferred by one or more terminal BetaNodes.
            # ---------------------------------------------------------------
            if goal in self.goals:
                # Already proven; return the cached NodeSet to break cycles.
                ns = self.goals[goal]
                self.trace.append("Retrieving prior nodeset %s for %s" % (ns, goal))
            else:
                self.trace.append(
                    "Building %s around%sgoal: %s"
                    % (
                        proof and "proof" or "nodeset",
                        antecedent and " antecedent " or " ",
                        str(goal_uniterm),
                    )
                )
                idx = BNode()
                ns = NodeSet(goal, network=self.network, identifier=idx)
                # Register early so recursive calls see it and avoid cycles.
                self.goals[goal] = ns
                self.top_down_store = top_down_store

                # Build an InferenceStep for each terminal node that derived
                # this goal.  fetchRETEJustifications filters out nodes whose
                # body terms would create circular proofs.
                ns.steps = [
                    self.build_inference_step(ns, tNode, goal, top_down_store)
                    for tNode in fetch_rete_justifications(goal, ns, self)
                ]
                assert ns.steps
        return ns


class NodeSet(object):
    """
    represents a step in a proof whose conclusion is justified by any
    of a set of inference steps associated with the NodeSet.

    The Conclusion of a node set represents the expression concluded by the
    proof step. Every node set has one conclusion, and a conclusion of a node
    set is of type Expression.

    Each inference step of a node set represents an application of an inference
    rule that justifies the node set's conclusion. A node set can have any
    number of inference steps, including none, and each inference step of a
    node set is of type InferenceStep. A node set without inference steps is of a special kind identifying an
    unproven goal in a reasoning process as described in Section 4.1.2 below.

    """

    def __init__(
        self, conclusion=None, steps=None, identifier=BNode(), network=None, naf=False
    ):
        if network:
            self.network = network
        else:
            self.network = self
            self.network.ns_map = {}
        self.identifier = identifier
        self.conclusion = conclusion
        self.language = None
        self.naf = naf
        self.steps = steps and steps or []

    def traverse_and_check(
        self,
        namespaces_dict: dict,
        goals: dict[Triple, Identifier] = None,
        issues: list[str] = None,
    ):
        """
        Recursively traverse the node set and the inference steps they are associated with to identify
        issues of the following kind:
        - Nodesets further down the proof chain that are redundant and should be re-used since
          the nodeset has already been proven (its goal is already the conclusion of another nodeset)

        :param namespaces_dict: the namespaces dictionary of the network
        :param goals: the goals identified along the traversal
        :param issues: the issues identified along the traversal
        :return:
        """
        goals = {} if goals is None else goals
        issues = [] if issues is None else issues
        extant_id = goals.get(self.conclusion)
        if extant_id is not None:
            if extant_id != self.identifier:
                issues.append(
                    f"Goal {
                        build_uniterm_from_tuple(
                            self.conclusion, new_nss=namespaces_dict
                        )
                    } is already proven "
                    f"{self.identifier} v.s. {extant_id}"
                )
            # else: same NodeSet reached via two proof paths — legitimate DAG sharing, skip
        else:
            goals[self.conclusion] = self.identifier
            for step in self.steps:
                step.traverse_and_check(namespaces_dict, goals, issues)

    def serialize(self, builder, proof_graph):
        conclusion_prefix = self.naf and "not " or ""
        proof_graph.add(
            (
                self.identifier,
                PML.hasConclusion,
                Literal(
                    "%s%s"
                    % (
                        conclusion_prefix,
                        repr(build_uniTerm(self.conclusion, self.network.ns_map)),
                    )
                ),
            )
        )
        # proofGraph.add((self.identifier, PML.hasLanguage, URIRef('http://inferenceweb.stanford.edu/registry/LG/RIF.owl')))
        proof_graph.add((self.identifier, RDF.type, PML.NodeSet))
        for step in self.steps:
            proof_graph.add((self.identifier, PML.isConsequentOf, step.identifier))
            builder.serialized_node_sets.add(self.identifier)
            step.serialize(builder, proof_graph)

    def generate_graph_node(self, dot, idx, proof_root=False, ns_map=None):
        ns_map = (
            ns_map
            if ns_map is not None
            else (self.network and self.network.ns_map or {})
        )
        dot.node(
            str(idx),
            label=str(build_uniTerm(self.conclusion, ns_map)),
            shape="component",
            root="true" if proof_root else "false",
        )
        for step in self.steps:
            step.generate_graph_node(dot, idx + 1, ns_map=ns_map)
        # vertex.shape = 'plaintext'
        # vertex.width = '5em'
        # vertex.peripheries = '1'

    def __repr__(self):
        # rt = "Proof step for %s with %s justifications" % (
        #    buildUniTerm(self.conclusion), len(self.steps))
        conclusion_prefix = self.naf and "not " or ""
        rt = "Proof step for %s%s" % (
            conclusion_prefix,
            build_uniTerm(self.conclusion, self.network and self.network.ns_map or {}),
        )
        return rt


class InferenceStep(object):
    """
    represents a justification for the conclusion of a node set.

    The rule of an inference step, which is the value of the property hasRule of
    the inference step, is the rule that was applied to produce the conclusion.
    Every inference step has one rule, and that rule is of type InferenceRule
    (see Section 3.3.3). Rules are in general registered in the IWBase by engine
    developers. However, PML specifies three special instances of rules:
    Assumption, DirectAssertion, and UnregisteredRule.

    The antecedents of an inference step is a sequence of node sets each of
    whose conclusions is a premise of the application of the inference step's
    rule. The sequence can contain any number of node sets including none.
    The sequence is the value of the property hasAntecedent of the inference
    step.

    Each binding of an inference step is a mapping from a variable to a term
    specifying the substitutions performed on the premises before the application
    of the step's rule. For instance, substitutions may be required to
    unify terms in premises in order to perform resolution. An inference step
    can have any number of bindings including none, and each binding is of
    type VariableBinding. The bindings are members of a collection that is the
    value of the property hasVariableMapping of the inference step.

    Each discharged assumption of an inference step is an expression that is
    discharged as an assumption by application of the step's rule. An inference
    step can have any number of discharged assumptions including none,
    and each discharged assumption is of type Expression. The discharged assumptions
    are members of a collection that is the value of the property
    hasDischargeAssumption of the inference step. This property supports
    the application of rules requiring the discharging of assumptions such as
    natural deduction's implication introduction. An assumption that is discharged
    at an inference step can be used as an assumption in the proof
    of an antecedent of the inference step without making the proof be conditional
    on that assumption.

    """

    def __init__(self, parent, rule=None, bindings=None, source=None):
        self.identifier = BNode()
        self.source = source
        self.parent = parent
        self.bindings = {} if bindings is None else bindings
        self.rule = rule
        self.antecedents: List[NodeSet] = []
        self.ground_query = None

    def traverse_and_check(
        self,
        namespaces_dict: dict,
        goals: dict[Triple, Identifier] = None,
        issues: list[str] = None,
    ):
        """
        Recursively traverse the inference step and the node set it is associated with to identify
        issues of the following kind:
        - Redundant antecedent nodesets

        :param namespaces_dict: the namespaces dictionary of the network
        :param goals: the goals identified along the traversal
        :param issues: the issues identified along the traversal
        :return:
        """
        issues = [] if issues is None else issues
        antecedent_goals = [n.conclusion for n in self.antecedents]
        if len(set(antecedent_goals)) != len(antecedent_goals):
            issues.append(f"{self} has redundant antecedents")
        for antecedent in self.antecedents:
            antecedent.traverse_and_check(namespaces_dict, goals, issues)

    def propagate_bindings(self, bindings):
        self.bindings.update(bindings)

    def serialize(self, builder, proof_graph):
        if self.rule and not self.source:
            proof_graph.add(
                (self.identifier, PML.englishDescription, Literal(repr(self)))
            )
        if self.ground_query and (self.identifier, None, None) not in proof_graph:
            query = BNode()
            info = BNode()
            proof_graph.add((self.identifier, PML.fromQuery, query))
            proof_graph.add((query, RDF.type, PML.Query))
            proof_graph.add((query, PML_P.hasContent, info))
            proof_graph.add((info, RDF.type, PML_P.Information))
            proof_graph.add((info, PML_P.hasRawString, Literal(self.ground_query)))
        elif self.source:
            some_doc = BNode()
            proof_graph.add((self.identifier, PML_P.hasSource, some_doc))
            proof_graph.add((some_doc, RDF.type, PML_P.Document))

        # proofGraph.add((self.identifier, PML.hasLanguage, URIRef('http://inferenceweb.stanford.edu/registry/LG/RIF.owl')))
        proof_graph.add((self.identifier, RDF.type, PML.InferenceStep))
        proof_graph.add((self.identifier, PML.hasInferenceEngine, FUXI))
        proof_graph.add((self.identifier, PML.hasRule, GMP_NS.GMP))
        proof_graph.add((self.identifier, PML.consequent, self.parent.identifier))
        for ant in self.antecedents:
            proof_graph.add((self.identifier, PML.hasAntecedent, ant.identifier))
            ant.serialize(builder, proof_graph)
        for k, v in list(self.bindings.items()):
            mapping = BNode()
            proof_graph.add((self.identifier, PML.hasVariableMapping, mapping))
            proof_graph.add((mapping, RDF.type, PML.Mapping))
            proof_graph.add((mapping, PML.mapFrom, k))
            proof_graph.add((mapping, PML.mapTo, v))

    def generate_graph_node(self, dot, idx, ns_map=None):
        longest_var_name = (
            max(len(str(k)) for k in self.bindings.keys()) if self.bindings else 0
        )
        binding_info = "".join(
            [
                f"\\l{' ' * (longest_var_name - len(str(k)))}?{k} -> {v.split('#')[-1]}"
                for k, v in self.bindings.items()
            ]
        )
        label = self._render_label(ns_map) if ns_map is not None else repr(self)
        dot.node(str(idx), label=label, shape="box")
        return binding_info

    def iter_condition(self, condition):
        return isinstance(condition, SetOperator) and condition or iter([condition])

    def pretty_print_rule(self):
        if len(list(self.iter_condition(self.rule.body))) > 2:
            return (
                "And(%s)" % repr(self.rule.head)
                + ":-"
                + "\\n\\t".join([repr(i) for i in self.rule.body])
            )
        return repr(self.rule)

    def _render_label(self, ns_map):
        if self.ground_query:
            return self.ground_query
        elif self.source:
            return self.source
        elif self.rule:
            if isinstance(self.rule.head, AdornedUniTerm) and self.rule.head.is_magic:
                head_str = repr(build_uniTerm(self.rule.head.to_rdf_tuple(), ns_map))
                return f"magic predicate justification\\n{head_str}"
            else:
                head_str = repr(build_uniTerm(self.rule.head.to_rdf_tuple(), ns_map))
                body_terms = list(term_iterator(self.rule.body))
                body_strs = [
                    repr(build_uniTerm(t.to_rdf_tuple(), ns_map))
                    if hasattr(t, "to_rdf_tuple")
                    else repr(t)
                    for t in body_terms
                ]
                if len(body_strs) == 1:
                    return f"{head_str} :- {body_strs[0]}"
                return f"{head_str} :- And( {' '.join(body_strs)} )"
        return repr(self)

    def __repr__(self):
        if self.ground_query:
            return self.ground_query
        elif self.source:
            return self.source
        elif self.rule:
            if isinstance(self.rule.head, AdornedUniTerm) and self.rule.head.is_magic:
                return "magic predicate justification\\n%s" % (self.rule)
            else:
                return repr(self.rule)  # self.prettyPrintRule()
