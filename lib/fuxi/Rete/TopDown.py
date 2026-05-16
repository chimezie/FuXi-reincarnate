# -*- coding: utf-8 -*-
# flake8: noqa
"""
Implements a Sip-Strategy formed from a basic graph pattern and a RIF-Core
ruleset as a series of top-down derived SPARQL evaluations against a fact
graph, generating a walk through the proof space in the process.

Native Prolog-like Python implementation for RIF-Core, OWL 2, and SPARQL.
"""

import copy
import itertools
import sys
from collections.abc import Mapping
from pprint import pprint

from frozendict import frozendict

from fuxi.Rete.AlphaNode import AlphaNode
from fuxi.Horn.PositiveConditions import Uniterm
from fuxi.Horn.PositiveConditions import build_uniterm_from_tuple
from fuxi.Rete.Proof import NodeSet
from fuxi.Rete.Proof import InferenceStep
from fuxi.Rete.RuleStore import N3Builtin
from fuxi.Rete.SidewaysInformationPassing import make_md5_digest
from fuxi.Rete.SidewaysInformationPassing import iter_condition
from fuxi.Rete.SidewaysInformationPassing import get_op
from fuxi.Rete.SidewaysInformationPassing import get_variables
from fuxi.Rete.SidewaysInformationPassing import get_args
from fuxi.Rete.SidewaysInformationPassing import incoming_sip_arcs
from fuxi.Rete.SidewaysInformationPassing import sip_representation
from fuxi.Rete.Magic import adorn_literal
from fuxi.Rete.Util import selective_memoize, lazy_generator_peek
from fuxi.SPARQL import EDBQuery, normalize_bindings_and_query

from rdflib import (
    BNode,
    RDF,
    URIRef,
    Variable,
)
from rdflib.util import first
from rdflib.graph import ReadOnlyGraphAggregate
from rdflib.namespace import split_uri
from functools import reduce


def prepare_sip_collection(adorned_ruleset):
    """
    Takes adorned ruleset and returns an RDF dataset
    formed from the sips associated with each adorned
    rule as named graphs.  Also returns a mapping from
    the head predicates of each rule to the rules that match
    it - for efficient retrieval later
    """
    head_to_rule = {}
    graphs = []
    second_order_rules = set()

    for rule in adorned_ruleset:
        ruleHead = get_op(rule.formula.head)

        if isinstance(ruleHead, Variable):
            # We store second order rules (i.e., rules whose head is a
            # predicate occurrence whose predicate symbol is a variable) aside
            second_order_rules.add(rule)

        head_to_rule.setdefault(ruleHead, set()).add(rule)

        if hasattr(rule, "sip"):
            graphs.append(rule.sip)

    # Second order rules are mapped from a None key (in order
    # to indicate they are wildcards)

    head_to_rule[None] = second_order_rules

    if not graphs:
        return

    graph = ReadOnlyGraphAggregate(graphs)
    graph.head_to_rule = head_to_rule

    return graph


def get_bindings_from_literal(ground_tuple, unground_literal):
    """
    Takes a ground fact and a query literal and returns
    the mappings from variables in the query literal
    to terms in the ground fact
    """
    unground_tuple = unground_literal.to_rdf_tuple()
    return frozendict(
        [
            (term, ground_tuple[idx])
            for idx, term in enumerate(unground_tuple)
            if isinstance(term, Variable) and not isinstance(ground_tuple[idx], Variable)
        ]
    )


def triple_to_triple_pattern(graph, term):
    if isinstance(term, N3Builtin):
        template = graph.template_map[term.uri]
        return "FILTER(%s)" % (template % (term.argument.n3(), term.result.n3()))
    else:
        return "%s %s %s" % tuple([render_term(graph, trm) for trm in term.to_rdf_tuple()])


@selective_memoize([0])
def normalize_uri(rdf_term, rev_ns_map):
    """
    Takes an RDF Term and 'normalizes' it into a QName (using the registered
    prefix) or (unlike compute_qname) the Notation 3 form for
    URIs: <...URI...>
    """
    try:
        namespace, name = split_uri(rdf_term)
        namespace = URIRef(namespace)
    except:
        if isinstance(rdf_term, Variable):
            return "?%s" % rdf_term
        else:
            return "<%s>" % rdf_term
    prefix = rev_ns_map.get(namespace)

    if prefix is None and isinstance(rdf_term, Variable):
        return "?%s" % rdf_term
    elif prefix is None:
        return "<%s>" % rdf_term
    else:
        q_name_parts = compute_qname(rdf_term, rev_ns_map)
        return ":".join([q_name_parts[0], q_name_parts[-1]])


@selective_memoize([0])
def compute_qname(uri, rev_ns_map):
    namespace, name = split_uri(uri)
    namespace = URIRef(namespace)
    prefix = rev_ns_map.get(namespace)
    if prefix is None:
        prefix = "_%s" % len(rev_ns_map)
        rev_ns_map[namespace] = prefix
    return prefix, namespace, name


def render_term(graph, term):
    if term == RDF.type:
        return " a "
    elif isinstance(term, URIRef):
        qname = normalize_uri(term, hasattr(graph, "revNsMap")
                              and graph.revNsMap
                              or dict([(u, p) for p, u in graph.namespaces()]))
        return qname[0] == "_" and "<%s>" % term or qname
    else:
        try:
            return isinstance(term, BNode) and term.n3() or graph.qname(term)
        except:
            return term.n3()


def rdf_tuples_to_sparql(
    conjunct, edb, is_ground=False, vars=[], symm_atomic_inclusion=False
):
    """
    Takes a conjunction of Horn literals and returns the
    corresponding SPARQL query
    """
    query_type = is_ground and "ASK" or "SELECT %s" % (" ".join([v.n3() for v in vars]))
    query_shell = len(conjunct) > 1 and "%s {\n%s\n}" or "%s { %s }"
    if symm_atomic_inclusion:
        if vars:
            var = vars.pop()
            prefix = "%s a ?KIND" % var.n3()
        else:
            prefix = "%s a ?KIND" % first([lit.arg[0].n3() for lit in conjunct])
        subquery = query_shell % (
            query_type,
            "%s\nFILTER(%s)"
            % (
                prefix,
                " ||\n".join(
                    ["?KIND = %s" % edb.qname(get_op(lit)) for lit in conjunct]
                ),
            ),
        )
    else:
        subquery = query_shell % (
            query_type,
            " .\n".join(["\t" + triple_to_triple_pattern(edb, lit) for lit in conjunct]),
        )
    return subquery


def lazy_collapse_boolean_proofs(left, right):
    """
    Function for reduce that (lazily) performs
    boolean conjunction operator on a list
    of 2-tuples, a boolean value and some object
    . The boolean conjunction is applied on the
    first item in each 2-tuple
    """
    (left_bool, left_node) = left
    (right_bool, right_node) = right
    if not left_bool:
        return False, None
    else:
        return (left_bool and right_bool) and (True, right_node) or (False, None)


def literal_is_ground(literal):
    """
    Whether or not the given literal has
    any variables for terms
    """
    return not [
        term
        for term in get_args(literal, second_order=True)
        if isinstance(term, Variable)
    ]


def merge_mappings1_to2(mapping1, mapping2, make_immutable=False):
    """
    Mapping merge.  A 'safe' update (i.e., if the key
    exists and the value is different, raise an exception)
    An immutable mapping can be returned if requested
    """
    newMap = {}
    for k, v in list(mapping1.items()):
        val2 = mapping2.get(k)
        if val2:
            assert v == val2, "Failure merging %s to %s" % (mapping1, mapping2)
            continue
        else:
            newMap[k] = mapping1[k]
    newMap.update(mapping2)
    return frozendict(newMap) if make_immutable else newMap


class RuleFailure(Exception):
    def __init__(self, msg):
        self.msg = msg

    def __repr__(self):
        return "RuleFailure: %" % self.msg


class Parameterizedpredicate:
    def __init__(self, externalVar):
        self.external_var = externalVar

    def __call__(self, f):
        def _func(item):
            return f(item, self.external_var)

        return _func


def invoke_rule(
    prior_answers,
    body_literal_iterator,
    sip,
    other_args,
    prior_boolean_goal_success=False,
    step=None,
    debug=False,
    build_proof=False,
):
    """
    Continue invokation of rule using (given) prior answers and list of
    remaining body literals (& rule sip).  If prior answers is a list,
    computation is split disjunctively

    [..] By combining the answers to all these subqueries, we generate
    answers for the original query involving the rule head

    Can also takes a PML step and updates it as it navigates the
    top-down proof tree (passing it on and updating it where necessary)

    """
    assert not build_proof or step is not None

    (
        proof_level,
        memoize_memory,
        sip_collection,
        fact_graph,
        derived_preds,
        processed_rules,
    ) = other_args

    remaining_body_list = [i for i in body_literal_iterator]
    lazy_generator = lazy_generator_peek(prior_answers, 2)
    if lazy_generator.successful:
        # There are multiple answers in this step, we need to call invokeRule
        # recursively for each answer, returning the first positive attempt
        success = False
        _step = None
        ans_no = 0
        for prior_ans in lazy_generator:
            ans_no += 1
            try:
                if build_proof:
                    new_step = InferenceStep(step.parent, step.rule, source=step.source)
                    new_step.antecedents = [ant for ant in step.antecedents]
                else:
                    new_step = None
                for rt, _step in invoke_rule(
                    [prior_ans],
                    iter([i for i in remaining_body_list]),
                    sip,
                    other_args,
                    prior_boolean_goal_success,
                    new_step,
                    debug=debug,
                    build_proof=build_proof,
                ):
                    if rt:
                        yield rt, _step
            except RuleFailure:
                pass
        if not success:
            # None of prior answers were successful
            # indicate termination of rule processing
            raise RuleFailure(
                "Unable to solve either of %s against remainder of rule: %s"
                % (ans_no, remaining_body_list)
            )
            # yield False, _InferenceStep(step.parent, step.rule,
            # source=step.source)
    else:
        lazy_generator = lazy_generator_peek(lazy_generator)
        projected_bindings = lazy_generator.successful and first(lazy_generator) or {}

        # First we check if we can combine a large group of subsequent body literals
        # into a single query
        # if we have a template map then we use it to further
        # distinguish which builtins can be solved via
        # cumulative SPARQl query - else we solve
        # builtins one at a time
        def sparql_resolvable(literal):
            if isinstance(literal, Uniterm):
                return not literal.naf and get_op(literal) not in derived_preds
            else:
                return (
                    isinstance(literal, N3Builtin)
                    and literal.uri in fact_graph.template_map
                )

        def sparql_resolvable_no_templates(literal):
            if isinstance(literal, Uniterm):
                return not literal.naf and get_op(literal) not in derived_preds
            else:
                return False

        conj_ground_literals = list(
            itertools.takewhile(
                hasattr(fact_graph, "template_map")
                and sparql_resolvable
                or sparql_resolvable_no_templates,
                remaining_body_list,
            )
        )

        body_literal_iterator = iter(remaining_body_list)

        if len(conj_ground_literals) > 1:
            # If there are literals to combine *and* a mapping from rule
            # builtins to SPARQL FILTER templates ..
            base_predicate_vars = set(
                reduce(
                    lambda x, y: x + y,
                    [
                        list(get_variables(arg, second_order=True))
                        for arg in conj_ground_literals
                    ],
                )
            )
            if projected_bindings:
                open_vars = base_predicate_vars.intersection(projected_bindings)
            else:
                # We don't have any given bindings, so we need to treat
                # the body as an open query
                open_vars = base_predicate_vars

            query_conj = EDBQuery([copy.deepcopy(lit) for lit in conj_ground_literals], fact_graph, open_vars,
                                  projected_bindings)

            query, answers = query_conj.evaluate(debug)

            if isinstance(answers, bool):
                combined_answers = {}
                rt_check = answers
            else:
                if projected_bindings:
                    combined_answers = (
                        merge_mappings1_to2(ans, projected_bindings, make_immutable=True)
                        for ans in answers
                    )
                else:
                    combined_answers = (frozendict(ans) for ans in answers)
                combined_ans_lazy_generator = lazy_generator_peek(combined_answers)
                rt_check = combined_ans_lazy_generator.successful

            if not rt_check:
                raise RuleFailure("No answers for combined SPARQL query: %s" % query)
            else:
                # We have solved the previous N body literals with a single
                # conjunctive query, now we need to make each of the literals
                # an antecedent to a 'query' step.
                if build_proof:
                    query_step = InferenceStep(None, source="some RDF graph")
                    # FIXME: subquery undefined
                    query_step.ground_query = subquery
                    query_step.bindings = {}  # combined_answers[-1]
                    # FIXME: subquery undefined
                    query_hash = URIRef(
                        "tag:info@fuxi.googlecode.com:Queries#"
                        + make_md5_digest(subquery)
                    )
                    query_step.identifier = query_hash
                    for sub_goal in conj_ground_literals:
                        sub_ns = NodeSet(sub_goal.to_rdf_tuple(), identifier=BNode())
                        sub_ns.steps.append(query_step)
                        step.antecedents.append(sub_ns)
                        query_step.parent = sub_ns
                for rt, _step in invoke_rule(
                    isinstance(answers, bool)
                    and [projected_bindings]
                    or combined_ans_lazy_generator,
                    iter(remaining_body_list[len(conj_ground_literals) :]),
                    sip,
                    other_args,
                    isinstance(answers, bool),
                    step,
                    debug=debug,
                    build_proof=build_proof,
                ):
                    yield rt, _step

        else:
            # Continue processing rule body condition
            # one literal at a time
            try:
                body_literal = next(body_literal_iterator)
                # if a N3 builtin, execute it using given bindings for boolean answer
                # builtins are moved to end of rule when evaluating rules via
                # sip
                if isinstance(body_literal, N3Builtin):
                    lhs = body_literal.argument
                    rhs = body_literal.result
                    lhs = isinstance(lhs, Variable) and projected_bindings[lhs] or lhs
                    rhs = isinstance(rhs, Variable) and projected_bindings[rhs] or rhs
                    assert lhs is not None and rhs is not None
                    if body_literal.func(lhs, rhs):
                        if debug:
                            print(
                                "Invoked %s(%s, %s) -> True"
                                % (body_literal.uri, lhs, rhs)
                            )
                        # positive answer means we can continue processing the
                        # rule body
                        if build_proof:
                            ns = NodeSet(body_literal.to_rdf_tuple(), identifier=BNode())
                            step.antecedents.append(ns)
                        for rt, _step in invoke_rule(
                            [projected_bindings],
                            body_literal_iterator,
                            sip,
                            other_args,
                            step,
                            prior_boolean_goal_success,
                            debug=debug,
                            build_proof=build_proof,
                        ):
                            yield rt, _step
                    else:
                        if debug:
                            print(
                                "Successfully invoked %s(%s, %s) -> False"
                                % (body_literal.uri, lhs, rhs)
                            )
                        raise RuleFailure(
                            "Failed builtin invokation %s(%s, %s)"
                            % (body_literal.uri, lhs, rhs)
                        )
                else:
                    # For every body literal, subqueries are generated according
                    # to the sip
                    sip_arc_pred = URIRef(
                        get_op(body_literal) + "_" + "_".join(get_args(body_literal))
                    )
                    assert len(list(incoming_sip_arcs(sip, sip_arc_pred))) < 2
                    subquery = copy.deepcopy(body_literal)
                    subquery.ground(projected_bindings)

                    for N, x in incoming_sip_arcs(sip, sip_arc_pred):
                        # That is, each subquery contains values for the bound arguments
                        # that are passed through the sip arcs entering the node
                        # corresponding to that literal

                        # Create query out of body literal and apply
                        # sip-provided bindings
                        subquery = copy.deepcopy(body_literal)
                        subquery.ground(projected_bindings)
                    if literal_is_ground(subquery):
                        # subquery is ground, so there will only be boolean answers
                        # we return the conjunction of the answers for the current
                        # subquery

                        answer = False
                        ns = None

                        answers = first(
                            itertools.dropwhile(
                                lambda item: not item[0],
                                sip_strategy(
                                    subquery.to_rdf_tuple(),
                                    sip_collection,
                                    fact_graph,
                                    derived_preds,
                                    frozendict(projected_bindings),
                                    processed_rules,
                                    network=step is not None
                                    and step.parent.network
                                    or None,
                                    debug=debug,
                                    build_proof=build_proof,
                                    memoize_memory=memoize_memory,
                                    proof_level=proof_level,
                                ),
                            )
                        )
                        if answers:
                            answer, ns = answers
                        if (
                            not answer
                            and not body_literal.naf
                            or (answer and body_literal.naf)
                        ):
                            # negative answer means the invokation of the rule fails
                            # either because we have a positive literal and there
                            # is no answer for the subgoal or the literal is
                            # negative and there is an answer for the subgoal
                            raise RuleFailure(
                                "No solutions solving ground query %s" % subquery
                            )
                        else:
                            if build_proof:
                                if not answer and body_literal.naf:
                                    ns.naf = True
                                step.antecedents.append(ns)
                            # positive answer means we can continue processing the rule body
                            # either because we have a positive literal and answers
                            # for subgoal or a negative literal and no answers for the
                            # the goal
                            for rt, _step in invoke_rule(
                                [projected_bindings],
                                body_literal_iterator,
                                sip,
                                other_args,
                                True,
                                step,
                                debug=debug,
                            ):
                                yield rt, _step
                    else:
                        _answers = sip_strategy(
                            subquery.to_rdf_tuple(),
                            sip_collection,
                            fact_graph,
                            derived_preds,
                            frozendict(projected_bindings),
                            processed_rules,
                            network=step is not None and step.parent.network or None,
                            debug=debug,
                            build_proof=build_proof,
                            memoize_memory=memoize_memory,
                            proof_level=proof_level,
                        )

                        # solve (non-ground) subgoal
                        def collect_answers(_ans):
                            for ans, ns in _ans:
                                if isinstance(ans, Mapping):
                                    try:
                                        map = merge_mappings1_to2(
                                            ans, projected_bindings, make_immutable=True
                                        )
                                        yield map
                                    except:
                                        pass

                        combined_answers = collect_answers(_answers)
                        answers = lazy_generator_peek(combined_answers)
                        if (
                            not answers.successful
                            and not body_literal.naf
                            or (body_literal.naf and answers.successful)
                        ):
                            raise RuleFailure(
                                "No solutions solving ground query %s" % subquery
                            )
                        else:
                            # Either we have a positive subgoal and answers
                            # or a negative subgoal and no answers
                            if build_proof:
                                if answers.successful:
                                    goals = set([g for a, g in answers])
                                    assert len(goals) == 1
                                    step.antecedents.append(goals.pop())
                                else:
                                    new_ns = NodeSet(
                                        body_literal.to_rdf_tuple(),
                                        network=step.parent.network,
                                        identifier=BNode(),
                                        naf=True,
                                    )
                                    step.antecedents.append(new_ns)
                            for rt, _step in invoke_rule(
                                answers,
                                body_literal_iterator,
                                sip,
                                other_args,
                                prior_boolean_goal_success,
                                step,
                                debug=debug,
                                build_proof=build_proof,
                            ):
                                yield rt, _step
            except StopIteration:
                # Finished processing rule
                if prior_boolean_goal_success:
                    yield projected_bindings and projected_bindings or True, step
                elif projected_bindings:
                    # Return the most recent (cumulative) answers and the given
                    # step
                    yield projected_bindings, step
                else:
                    raise RuleFailure("Finished processing rule unsuccessfully")


def refactor_mapping(key_mapping, orig_mapping):
    """
    Takes a mapping from one mapping domain (D1)
    to another mapping domain (D2) as well as a mapping
    whose keys are in D1 and returns a new
    """
    if key_mapping:
        refactored_mapping = {}
        for inKey, outKey in list(key_mapping.items()):
            if inKey in orig_mapping:
                refactored_mapping[outKey] = orig_mapping[inKey]
        return refactored_mapping
    else:
        return orig_mapping


def prep_memiozed_ans(ans):
    return frozendict(ans) if isinstance(ans, dict) else ans


def sip_strategy(
    query,
    sip_collection,
    fact_graph,
    derived_preds,
    bindings={},
    processed_rules=None,
    network=None,
    debug=False,
    build_proof=False,
    memoize_memory=None,
    proof_level=1,
):
    """
    Accordingly, we define a sip-strategy for computing the answers to a query
    expressed using a set of Datalog rules, and a set of sips, one for each
    adornment of a rule head, as follows...

    Each evaluation uses memoization (via Python decorators) but also relies on well-formed
    rewrites for using semi-naive bottom up method over large SPARQL data.

    """
    memoize_memory = memoize_memory and memoize_memory or {}
    query_literal = build_uniterm_from_tuple(query)
    processed_rules = processed_rules and processed_rules or set()
    if bindings:
        # There are bindings.  Apply them to the terms in the query
        query_literal.ground(bindings)

    if debug:
        print("%sSolving" % ("\t" * proof_level), query_literal, bindings)
    # Only consider ground triple pattern isomorphism with matching bindings
    goal_rdf_statement = query_literal.to_rdf_tuple()

    if query_literal in memoize_memory:
        if debug:
            print(
                "%sReturning previously calculated results for " % ("\t" * proof_level),
                query_literal,
            )
        for answers in memoize_memory[query_literal]:
            yield answers
    elif AlphaNode(goal_rdf_statement).alpha_network_hash(True, skolem_terms=list(bindings.values())) in [
        AlphaNode(r.to_rdf_tuple()).alpha_network_hash(True, skolem_terms=list(bindings.values()))
        for r in processed_rules
        if adorn_literal(goal_rdf_statement).adornment == r.adornment
    ]:
        if debug:
            print("%s Goal already processed..." % ("\t" * proof_level))
    else:
        is_ground = literal_is_ground(query_literal)
        if build_proof:
            ns = NodeSet(goal_rdf_statement, network=network, identifier=BNode())
        else:
            ns = None
        queryPred = get_op(query_literal)
        if sip_collection is None:
            rules = []
        else:
            # For every rule head matching the query, we invoke the rule,
            # thus determining an adornment, and selecting a sip to follow
            rules = sip_collection.head_to_rule.get(queryPred, set())
            if None in sip_collection.head_to_rule:
                # If there are second order rules, we add them
                # since they are a 'wildcard'
                rules.update(sip_collection.head_to_rule[None])

        # maintained list of rules that haven't been processed before and
        # match the query
        valid_rules = []

        # each subquery contains values for the bound arguments that are passed
        # through the sip arcs entering the node corresponding to that literal. For
        # each subquery generated, there is a set of answers.
        answers = []

        # variableMapping = {}

        # Some TBox queries can be 'joined' together into SPARQL queries against
        # 'base' predicates via an RDF dataset
        # These atomic concept inclusion axioms can be evaluated together
        # using a disjunctive operator at the body of a horn clause
        # where each item is a query of the form uniPredicate(?X):
        # Or( uniPredicate1(?X1), uniPredicate2(?X), uniPredicate3(?X), ..)
        # In this way massive, conjunctive joins can be 'mediated'
        # between the stated facts and the top-down solver
        @Parameterizedpredicate([i for i in derived_preds])
        def is_atomic_inclusion_axiom_rhs(rule, d_preds):
            """
            This is an atomic inclusion axiom with
            a variable (or bound) RHS:  uniPred(?ENTITY)
            """
            body_list = list(iter_condition(rule.formula.body))
            body = first(body_list)
            return (
                    get_op(body) not in d_preds and len(body_list) == 1 and body.op == RDF.type
            )

        atomic_inclusion_axioms = list(filter(is_atomic_inclusion_axiom_rhs, rules))
        if atomic_inclusion_axioms and len(atomic_inclusion_axioms) > 1:
            if debug:
                print("\tCombining atomic inclusion axioms: ")
                pprint(atomic_inclusion_axioms, sys.stderr)
            if build_proof:
                fact_step = InferenceStep(ns, source="some RDF graph")
                ns.steps.append(fact_step)

            axioms = [rule.formula.body for rule in atomic_inclusion_axioms]

            # attempt to exaustively apply any available substitutions
            # and determine if query if fully ground
            vars = [
                v
                for v in get_args(query_literal, second_order=True)
                if isinstance(v, Variable)
            ]
            open_vars, axioms, _bindings = normalize_bindings_and_query(
                vars, bindings, axioms
            )
            if open_vars:
                # mappings = {}
                # See if we need to do any variable mappings from the query literals
                # to the literals in the applicable rules
                query, rt = EDBQuery(axioms, fact_graph, open_vars, _bindings).evaluate(
                    debug, symm_atomic_inclusion=True
                )
                if build_proof:
                    # FIXME: subquery undefined
                    fact_step.ground_query = subquery
                for ans in rt:
                    if build_proof:
                        fact_step.bindings.update(ans)
                    memoize_memory.setdefault(query_literal, set()).add(
                        (prep_memiozed_ans(ans), ns)
                    )
                    yield ans, ns
            else:
                # All the relevant derivations have been explored and the result
                # is a ground query we can directly execute against the facts
                if build_proof:
                    fact_step.bindings.update(bindings)
                query, rt = EDBQuery(axioms, fact_graph, _bindings).evaluate(
                    debug, symm_atomic_inclusion=True
                )
                if build_proof:
                    # FIXME: subquery undefined
                    fact_step.ground_query = subquery
                memoize_memory.setdefault(query_literal, set()).add(
                    (prep_memiozed_ans(rt), ns)
                )
                yield rt, ns
            rules = filter(lambda i: not is_atomic_inclusion_axiom_rhs(i), rules)
        for rule in rules:
            # An exception is the special predicate ph; it is treated as a base
            # predicate and the tuples in it are those supplied for qb by
            # unification.
            head_bindings = get_bindings_from_literal(goal_rdf_statement, rule.formula.head)
            # comboBindings = dict([(k, v) for k, v in itertools.chain(
            #                                           bindings.items(),
            #                                           head_bindings.items())])
            var_map = rule.formula.head.get_var_mapping(query_literal)
            if head_bindings and [
                term
                for term in rule.formula.head.get_distinguished_variables(True)
                if var_map.get(term, term) not in head_bindings
            ]:
                continue
            # subQueryAnswers = []
            # dontStop = True
            # projectedBindings = comboBindings.copy()
            if debug:
                print("%sProcessing rule" % ("\t" * proof_level), rule.formula)
                if debug and sip_collection:
                    print(
                        "Sideways Information Passing (sip) graph for %s: "
                        % query_literal
                    )
                    print(sip_collection.serialize(format="n3"))
                    for sip in sip_representation(sip_collection):
                        print(sip)
            try:
                # Invoke the rule
                if build_proof:
                    step = InferenceStep(ns, rule.formula)
                else:
                    step = None
                for rt, step in invoke_rule(
                    [head_bindings],
                    iter(iter_condition(rule.formula.body)),
                    rule.sip,
                    (
                            proof_level + 1,
                            memoize_memory,
                            sip_collection,
                            fact_graph,
                            derived_preds,
                            processed_rules.union([adorn_literal(query)]),
                    ),
                    step=step,
                    debug=debug,
                ):
                    if rt:
                        if isinstance(rt, Mapping):
                            # We received a mapping and must rewrite it via
                            # correlation between the variables in the rule head
                            # and the variables in the original query (after applying
                            # bindings)
                            var_map = rule.formula.head.get_var_mapping(query_literal)
                            if var_map:
                                rt = frozendict(refactor_mapping(var_map, rt))
                            if build_proof:
                                step.bindings = rt
                        else:
                            if build_proof:
                                step.bindings = head_bindings
                        valid_rules.append(rule)
                        if build_proof:
                            ns.steps.append(step)
                        if is_ground:
                            yield True, ns
                        else:
                            memoize_memory.setdefault(query_literal, set()).add(
                                (prep_memiozed_ans(rt), ns)
                            )
                            yield rt, ns

            except RuleFailure:
                # Clean up failed antecedents
                if build_proof:
                    if ns in step.antecedents:
                        step.antecedents.remove(ns)
        if not valid_rules:
            # No rules matching, query factGraph for answers
            successful = False
            if build_proof:
                fact_step = InferenceStep(ns, source="some RDF graph")
                ns.steps.append(fact_step)
            if not is_ground:
                subquery, rt = EDBQuery([query_literal], fact_graph, [
                    v
                    for v in get_args(query_literal, second_order=True)
                    if isinstance(v, Variable)
                ], bindings).evaluate(debug)
                if build_proof:
                    fact_step.ground_query = subquery
                for ans in rt:
                    successful = True
                    if build_proof:
                        fact_step.bindings.update(ans)
                    memoize_memory.setdefault(query_literal, set()).add(
                        (prep_memiozed_ans(ans), ns)
                    )
                    yield ans, ns
                if not successful and queryPred not in derived_preds:
                    # Open query didn't return any results and the predicate
                    # is ostensibly marked as derived predicate, so we have
                    # failed
                    memoize_memory.setdefault(query_literal, set()).add((False, ns))
                    yield False, ns
            else:
                # All the relevant derivations have been explored and the result
                # is a ground query we can directly execute against the facts
                if build_proof:
                    fact_step.bindings.update(bindings)

                subquery, rt = EDBQuery([query_literal], fact_graph, bindings).evaluate(
                    debug
                )
                if build_proof:
                    fact_step.ground_query = subquery
                memoize_memory.setdefault(query_literal, set()).add(
                    (prep_memiozed_ans(rt), ns)
                )
                yield rt, ns


def test():
    import doctest

    doctest.testmod()


if __name__ == "__main__":
    test()

