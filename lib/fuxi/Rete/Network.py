from __future__ import annotations

# -*- coding: utf-8 -*-
# flake8: noqa
"""
A Rete Network Building and 'Evaluation' Implementation for RDFLib Graphs of
Notation 3 rules.

The DLP implementation uses this network to automatically building RETE
decision trees for OWL forms of DLP

Uses Python hashing mechanism to maximize the efficiency of the built
pattern network.

The network :
    - compiles an RDFLib N3 rule graph into AlphaNode and BetaNode instances
    - takes a fact (or the removal of a fact, perhaps?) and propagates down,
      starting from its alpha nodes
    - stores inferred triples in provided triple source (an RDFLib graph) or
      a temporary IOMemory Graph by default

"""

import atexit
import collections.abc
import logging
import os
import sys
import time
import tracemalloc
from itertools import chain
from pprint import pprint
from typing import TYPE_CHECKING

from io import StringIO

if TYPE_CHECKING:
    from typing import Iterable, Iterator, TextIO

from .BetaNode import BetaNode, LEFT_MEMORY, RIGHT_MEMORY
from .AlphaNode import (
    AlphaNode,
    BuiltInAlphaNode,
    ReteToken,
)
from fuxi.Horn import (
    complement_expansion,
    DATALOG_SAFETY_NONE,
)
from fuxi.Syntax.InfixOWL import Class
from fuxi.Horn.PositiveConditions import (
    Exists,
    get_uterm,
    SetOperator,
    Uniterm,
)
from fuxi.DLP import (
    map_dlp_to_network,
    NON_DHL_OWL_SEMANTICS,
)
from fuxi.DLP.ConditionalAxioms import additional_rules
from .Util import (
    generate_token_set,
    render_network,
    xcombine,
)

from rdflib.graph import (
    Dataset,
    Graph,
    ReadOnlyGraphAggregate,
)
from rdflib.namespace import NamespaceManager
from rdflib import (
    BNode,
    # Literal,
    Namespace,
    RDF,
    Variable,
)
from rdflib.util import first

from .RuleStore import (
    Formula,
    N3Builtin,
    N3RuleStore,
)
from fuxi.types import RDFTerm


OWL_NS = Namespace("http://www.w3.org/2002/07/owl#")
Any = None
LOG = Namespace("http://www.w3.org/2000/10/swap/log#")
logger = logging.getLogger(__name__)


def _env_flag(name: str) -> bool:
    value = os.environ.get(name, "")
    return value.lower() not in ("", "0", "false", "no")


def any_match(seq, pred=None):
    """Returns True if pred(x) is true for at least one element in the iterable"""
    for elem in filter(pred, seq):
        return True
    return False


class HashablePatternList(object):
    """
    A hashable list of N3 statements which are patterns of a rule.  Order is disregarded
    by sorting based on unicode value of the concatenation of the term strings
    (in both triples and function builtins invokations).
    This value is also used for the hash.  In this way, patterns with the same terms
    but in different order are considered equivalent and share the same Rete nodes

    >>> nodes = {}
    >>> a = HashablePatternList([(Variable('X'), Literal(1), Literal(2))])
    >>> nodes[a] = 1
    >>> nodes[HashablePatternList([None]) + a] = 2
    >>> b = HashablePatternList([(Variable('Y'), Literal(1), Literal(2))])
    >>> b in a  #doctest: +SKIP
    True
    >>> a == b  #doctest: +SKIP
    True

    """

    def __init__(
        self,
        items: "Iterable[tuple[RDFTerm, ...]] | None" = None,
        skip_b_nodes: bool = False,
    ) -> None:
        self.skip_b_nodes = skip_b_nodes
        self._l = list(items) if items is not None else []

    def __len__(self):
        return len(self._l)

    def __getitem__(self, key):
        if isinstance(key, slice):
            return HashablePatternList(self._l[key])
        else:
            return self._l[key]

    def __getslice__(self, beginIdx, endIdx):
        return HashablePatternList(self._l[beginIdx:endIdx])

    def _to_sort_key(self, val: Any) -> tuple:
        from fuxi.Horn.PositiveConditions import ExternalFunction, Uniterm

        if isinstance(val, (ExternalFunction, Uniterm)):
            return (type(val).__name__, repr(val))
        if isinstance(val, BNode):
            return ("BNode", str(val))
        if isinstance(val, (list, tuple)):
            return (type(val).__name__, str(val))
        if hasattr(val, "__lt__"):
            try:
                val < val
                return ("comparable", val)
            except TypeError:
                return (type(val).__name__, str(val))
        return (type(val).__name__, str(val))

    @staticmethod
    def _flatten_for_hash(val: Any, skip_b_nodes: bool = False) -> list:
        if isinstance(val, tuple):
            result = []
            for i in val:
                if skip_b_nodes and isinstance(i, BNode):
                    continue
                if isinstance(i, list):
                    result.append(
                        tuple(HashablePatternList._flatten_for_hash(i, skip_b_nodes))
                    )
                else:
                    result.append(i)
            return result
        if isinstance(val, list):
            return [
                tuple(
                    HashablePatternList._flatten_for_hash(v, skip_b_nodes) for v in val
                )
            ]
        return [val]

    def __hash__(self):
        out: list[Any] = []
        for item in self._l:
            if not item:
                out.append("None")
            elif isinstance(item, tuple):
                out.extend(self._flatten_for_hash(item, self.skip_b_nodes))
            elif isinstance(item, N3Builtin):
                out.extend([item.argument, item.result])
            else:
                raise NotImplementedError("don't know how to hash %r" % item)

        # nullify the impact of order in patterns
        try:
            out.sort()
        except TypeError:
            out.sort(key=self._to_sort_key)
        return hash(tuple(out))

    def __add__(self, other):
        assert isinstance(other, HashablePatternList), other
        return HashablePatternList(self._l + other._l)

    def __repr__(self):
        return repr(self._l)

    def extend(self, other):
        assert isinstance(other, HashablePatternList), other
        self._l.extend(other._l)

    def append(self, other):
        self._l.append(other)

    def __iter__(self):
        return iter(self._l)

    def __eq__(self, other):
        return hash(self) == hash(other)


def _mul_pattern_with_substitutions(tokens, consequent, termNode):
    """
    Takes a set of tokens and a pattern and returns an iterator over consequent
    triples, created by applying all the variable substitutions in the given tokens against the pattern

    >>> aNode = AlphaNode((Variable('S'), Variable('P'), Variable('O')))
    >>> token1 = ReteToken((URIRef('urn:uuid:alpha'), OWL_NS.differentFrom, URIRef('urn:uuid:beta')))
    >>> token2 = ReteToken((URIRef('urn:uuid:beta'), OWL_NS.differentFrom, URIRef('urn:uuid:alpha')))
    >>> token1 = token1.bind_variables(aNode)
    >>> token2 = token2.bind_variables(aNode)
    >>> inst = PartialInstantiation([token1, token2])
    """
    # success = False
    for binding in tokens.bindings:
        triple_vals = []
        # if any(consequent,
        # lambda term:isinstance(term, Variable) and term not in binding):#  not mismatchedTerms:
        #     return
        # else:
        for term in consequent:
            if isinstance(term, (Variable, BNode)) and term in binding:
                # try:
                triple_vals.append(binding[term])
                # except:
                #    pass
            else:
                triple_vals.append(term)
        yield tuple(triple_vals), binding


class InferredGoal(Exception):
    def __init__(self, msg):
        self.msg = msg

    def __repr__(self):
        return "Goal inferred.: %" % self.msg


class ReteNetwork:
    """
    The Rete network.  The constructor takes an N3 rule graph, an identifier (a BNode by default), an
    initial Set of Rete tokens that serve as the 'working memory', and an rdflib Graph to
    add inferred triples to - by forward-chaining via Rete evaluation algorithm).
    """

    def __init__(
        self,
        rule_store,
        name=None,
        initial_working_memory=None,
        inferred_target=None,
        ns_map=None,
        graph_viz_out_file=None,
        dont_finalize=False,
        goal=None,
    ):
        self._memstats_enabled = _env_flag("FUXI_RETE_MEM_STATS")
        self._memstats_interval = int(
            os.environ.get("FUXI_RETE_MEM_STATS_INTERVAL", "5000")
        )
        self._memstats_counter = 0
        self._memstats_next = self._memstats_interval
        self._memstats_tracemalloc = _env_flag("FUXI_RETE_TRACEMALLOC")
        if self._memstats_tracemalloc and not tracemalloc.is_tracing():
            tracemalloc.start()
        if self._memstats_enabled:
            atexit.register(self._report_memstats, "atexit")
        self.lean_check = {}
        self.goal = goal
        self.ns_map = ns_map if ns_map is not None else {}
        self.name = name and name or BNode()
        self.nodes = {}
        self.alpha_pattern_hash = {}
        self.rule_set = set()
        for alpha_pattern in xcombine(("1", "0"), ("1", "0"), ("1", "0")):
            self.alpha_pattern_hash[tuple(alpha_pattern)] = {}
        if inferred_target is None:
            self.inferred_facts = Graph()
            namespace_manager = NamespaceManager(self.inferred_facts)
            for k, v in list(self.ns_map.items()):
                namespace_manager.bind(k, v)
            self.inferred_facts.namespace_manager = namespace_manager
        else:
            self.inferred_facts = inferred_target
        self.working_memory = initial_working_memory and initial_working_memory or set()
        self.proof_tracers = {}
        self.terminal_nodes = set()
        self.instantiations = {}
        self.rule_store = rule_store
        self.justifications = {}
        self.discharged_bindings = {}
        if not dont_finalize:
            self.rule_store._finalize()
        self.filtered_facts = Graph()

        # 'Universal truths' for a rule set are rules where the LHS is empty.
        # Rather than automatically adding them to the working set, alpha nodes are 'notified'
        # of them, so they can be checked for while performing inter element
        # tests.
        self.universal_truths = []
        from fuxi.Horn.HornRules import Ruleset

        self.rules = set()
        self.neg_rules = set()
        for rule in Ruleset(n3_rules=self.rule_store.rules, ns_mapping=self.ns_map):
            import warnings

            warnings.warn(
                "Rules in a network should be built *after* construction via "
                + " self.build_network_from_clause(HornFromN3(n3graph)) for instance",
                DeprecationWarning,
                2,
            )
            self.build_network_from_clause(rule)
        self.alpha_nodes = [
            node for node in list(self.nodes.values()) if isinstance(node, AlphaNode)
        ]
        self.alpha_built_in_nodes = [
            node
            for node in list(self.nodes.values())
            if isinstance(node, BuiltInAlphaNode)
        ]
        self._setup_default_rules()
        if initial_working_memory:
            start = time.time()
            self.feed_facts_to_add(initial_working_memory)
            print(
                "Time to calculate closure on working memory: %s m seconds"
                % ((time.time() - start) * 1000)
            )
        if graph_viz_out_file:
            ext = os.path.splitext(graph_viz_out_file)[1].lstrip(".")
            fmt = ext if ext else "png"
            try:
                render_network(self, ns_map=self.ns_map, format=fmt).render(
                    filename=graph_viz_out_file, cleanup=True, format=fmt
                )
            except ImportError as exc:
                print(f"Cannot render RETE network: {exc}")

    def get_ns_bindings(self, ns_mgr):
        for prefix, Uri in ns_mgr.namespaces():
            self.ns_map[prefix] = Uri

    def build_filter_network_from_clause(self, rule):
        lhs = BNode()
        rhs = BNode()
        builtins = []
        for term in rule.formula.body:
            if isinstance(term, N3Builtin):
                # We want to move builtins to the 'end' of the body
                # so they only apply to the terminal nodes of
                # the corresponding network
                builtins.append(term)
            else:
                self.rule_store.formulae.setdefault(lhs, Formula(lhs)).append(
                    term.to_rdf_tuple()
                )
        for builtin in builtins:
            self.rule_store.formulae.setdefault(lhs, Formula(lhs)).append(
                builtin.to_rdf_tuple()
            )
        non_empty_head = False
        for term in rule.formula.head:
            non_empty_head = True
            assert not isinstance(term, collections.abc.Iterator)
            assert isinstance(term, Uniterm)
            self.rule_store.formulae.setdefault(rhs, Formula(rhs)).append(
                term.to_rdf_tuple()
            )
        assert non_empty_head, "Filters must conclude something."
        self.rule_store.rules.append(
            (self.rule_store.formulae[lhs], self.rule_store.formulae[rhs])
        )
        t_node = self.build_network(
            iter(self.rule_store.formulae[lhs]),
            iter(self.rule_store.formulae[rhs]),
            rule,
            a_filter=True,
        )
        self.alpha_nodes = [
            node for node in list(self.nodes.values()) if isinstance(node, AlphaNode)
        ]
        self.rules.add(rule)
        return t_node

    def build_network_from_clause(self, rule):
        lhs = BNode()
        rhs = BNode()
        builtins = []
        for term in rule.formula.body:
            if isinstance(term, N3Builtin):
                # We want to move builtins to the 'end' of the body
                # so they only apply to the terminal nodes of
                # the corresponding network
                builtins.append(term)
            else:
                self.rule_store.formulae.setdefault(lhs, Formula(lhs)).append(
                    term.to_rdf_tuple()
                )
        for builtin in builtins:
            self.rule_store.formulae.setdefault(lhs, Formula(lhs)).append(
                builtin.to_rdf_tuple()
            )
        non_empty_head = False
        for term in rule.formula.head:
            non_empty_head = True
            assert not isinstance(term, collections.abc.Iterator)
            assert isinstance(term, Uniterm)
            self.rule_store.formulae.setdefault(rhs, Formula(rhs)).append(
                term.to_rdf_tuple()
            )
        if not non_empty_head:
            import warnings

            warnings.warn(
                "Integrity constraints (rules with empty heads) are not supported: %s"
                % rule,
                SyntaxWarning,
                2,
            )
            return
        self.rule_store.rules.append(
            (self.rule_store.formulae[lhs], self.rule_store.formulae[rhs])
        )
        t_node = self.build_network(
            iter(self.rule_store.formulae[lhs]),
            iter(self.rule_store.formulae[rhs]),
            rule,
        )
        self.alpha_nodes = [
            node for node in list(self.nodes.values()) if isinstance(node, AlphaNode)
        ]
        self.rules.add(rule)
        return t_node

    def calculate_stratified_model(self, database):
        """
        Stratified Negation Semantics for DLP using SPARQL to handle the negation
        """
        if not self.neg_rules:
            return
        from fuxi.DLP.Negation import stratified_sparql

        import copy

        no_neg_facts = 0
        for i in self.neg_rules:
            # Evaluate the Graph pattern, and instanciate the head of the rule with
            # the solutions returned
            ns_mapping = dict([(v, k) for k, v in list(self.ns_map.items())])
            sel, compiler = stratified_sparql(i, ns_mapping)
            query = compiler.compile(sel)
            i.stratifiedQuery = query
            vars = sel.projection
            union_closure_g = self.closure_graph(database)
            for rt in union_closure_g.query(query):
                solutions = {}
                if isinstance(rt, tuple):
                    solutions.update(dict([(vars[idx], i) for idx, i in enumerate(rt)]))
                else:
                    solutions[vars[0]] = rt
                i.solutions = solutions
                head = copy.deepcopy(i.formula.head)
                head.ground(solutions)
                fact = head.to_rdf_tuple()
                self.inferred_facts.add(fact)
                self.feed_facts_to_add(generate_token_set([fact]))
                no_neg_facts += 1
        # Now we need to clear assertions that cross the individual, concept, relation divide
        for s, p, o in self.inferred_facts.triples((None, RDF.type, None)):
            if s in union_closure_g.predicates() or s in [
                _s
                for _s, _p, _o in union_closure_g.triples_choices(
                    (None, RDF.type, [OWL_NS.Class, OWL_NS.Restriction])
                )
            ]:
                self.inferred_facts.remove((s, p, o))
        return no_neg_facts

    def setup_description_logic_programming(
        self,
        owl_n3_graph,
        expanded=None,
        add_pd_semantics=True,
        classify_t_box=False,
        construct_network=True,
        derived_preds=None,
        ignore_negative_stratus=False,
        safety=DATALOG_SAFETY_NONE,
    ):
        if expanded is None:
            expanded = []
        if derived_preds is None:
            derived_preds = []
        rt = [
            rule
            for rule in map_dlp_to_network(
                self,
                owl_n3_graph,
                complement_expansions=expanded,
                construct_network=construct_network,
                derived_preds=derived_preds,
                ignore_negative_stratus=ignore_negative_stratus,
                safety=safety,
            )
        ]
        if ignore_negative_stratus:
            rules, neg_rules = rt
            rules = set(rules)
            self.neg_rules = set(neg_rules)
        else:
            rules = set(rt)
        if construct_network:
            self.rules.update(rules)
        _additional_rules = set(additional_rules(owl_n3_graph))
        if add_pd_semantics:
            from fuxi.Horn.HornRules import horn_from_n3

            _additional_rules.update(horn_from_n3(StringIO(NON_DHL_OWL_SEMANTICS)))

        if construct_network:
            for rule in _additional_rules:
                self.build_network(
                    iter(rule.formula.body), iter(rule.formula.head), rule
                )
                self.rules.add(rule)
        else:
            rules.update(_additional_rules)

        if construct_network:
            rules = self.rules

        if classify_t_box:
            self.feed_facts_to_add(generate_token_set(owl_n3_graph))
        return rules

    def report_size(self, token_size_threshold=1200, stream=sys.stdout):
        for pattern, node in list(self.nodes.items()):
            if isinstance(node, BetaNode):
                for largeMem in [
                    i
                    for i in iter(node.memories.values())
                    if len(i) > token_size_threshold
                ]:
                    if largeMem:
                        print("Large apha node memory extent: ")
                        pprint(pattern)
                        print(len(largeMem))

    def report_conflict_set(
        self,
        closure_summary: bool = False,
        stream: "TextIO | None" = sys.stdout,
        ns_bindings: dict[str, str] | None = None,
    ):
        t_node_order = [
            tNode for tNode in self.terminal_nodes if self.instantiations.get(tNode, 0)
        ]
        t_node_order.sort(key=lambda x: self.instantiations[x], reverse=True)
        for term_node in t_node_order:
            print(term_node)
            print("\t", term_node.clause_representation())
            print("\t\t%s instantiations" % self.instantiations[term_node])
        if closure_summary:
            if ns_bindings:
                for prefix, url in ns_bindings.items():
                    self.inferred_facts.bind(prefix, url)
            ttl = self.inferred_facts.serialize(format="turtle")
            print(ttl, file=stream)

    def parse_n3_logic(self, src):
        store = N3RuleStore(additional_builtins=self.rule_store.filters)
        Graph(store).parse(src, format="n3")
        store._finalize()
        assert len(store.rules), "There are no rules passed in."
        from fuxi.Horn.HornRules import Ruleset

        for rule in Ruleset(n3_rules=store.rules, ns_mapping=self.ns_map):
            self.build_network(iter(rule.formula.body), iter(rule.formula.head), rule)
            self.rules.add(rule)
        self.alpha_nodes = [
            node for node in list(self.nodes.values()) if isinstance(node, AlphaNode)
        ]
        self.alpha_built_in_nodes = [
            node
            for node in list(self.nodes.values())
            if isinstance(node, BuiltInAlphaNode)
        ]

    def __repr__(self):
        total = 0
        for node in list(self.nodes.values()):
            if isinstance(node, BetaNode):
                total += len(node.memories[LEFT_MEMORY])
                total += len(node.memories[RIGHT_MEMORY])

        return (
            "<Network: %s rules, %s nodes, %s tokens in working memory, %s inferred tokens>"
            % (
                len(self.terminal_nodes),
                len(self.nodes),
                total,
                len(self.inferred_facts),
            )
        )

    def closure_graph(self, source_graph, read_only=True, store=None):
        if read_only:
            if store is None and not source_graph:
                store = Graph().store
            store = store is None and source_graph.store or store
            ro_graph = ReadOnlyGraphAggregate(
                [source_graph, self.inferred_facts], store=store
            )
            ro_graph.namespace_manager = NamespaceManager(ro_graph)
            for srcGraph in [source_graph, self.inferred_facts]:
                for prefix, uri in srcGraph.namespaces():
                    ro_graph.namespace_manager.bind(prefix, uri)
            return ro_graph
        else:
            cg = Dataset(default_union=True)
            if isinstance(source_graph, Dataset):
                cg += source_graph
            else:
                cg.default_graph += source_graph
            if isinstance(self.inferred_facts, Dataset):
                cg += self.inferred_facts
            else:
                cg.default_graph += self.inferred_facts
            return cg

    def _setup_default_rules(self):
        """
        Checks every alpha node to see if it may match against a 'universal truth' (one w/out a LHS)
        """
        for node in list(self.nodes.values()):
            if isinstance(node, AlphaNode):
                node.check_default_rule(self.universal_truths)

    def clear(self):
        self.nodes = {}
        self.alpha_pattern_hash = {}
        self.rules = set()
        for alphaPattern in xcombine(("1", "0"), ("1", "0"), ("1", "0")):
            self.alpha_pattern_hash[tuple(alphaPattern)] = {}
        self.proof_tracers = {}
        self.terminal_nodes = set()
        self.justifications = {}
        self._reset_instantiation_stats()
        self.working_memory = set()
        self.discharged_bindings = {}

    def reset(self, new_inferred_facts=None):
        "Reset the network by emptying the memory associated with all Beta Nodes nodes"
        for node in list(self.nodes.values()):
            if isinstance(node, BetaNode):
                node.memories[LEFT_MEMORY].reset()
                node.memories[RIGHT_MEMORY].reset()
        self.justifications = {}
        self.proof_tracers = {}
        self.inferred_facts = (
            new_inferred_facts if new_inferred_facts is not None else Graph()
        )
        self.working_memory = set()
        self._reset_instantiation_stats()

    def fire_consequent(self, tokens, term_node, debug=False):
        """
        "In general, a p-node also contains a specification of what production it corresponds to - the
        name of the production, its right-hand-side actions, etc. A p-node may also contain information
        about the names of the variables that occur in the production. Note that variable names
        are not mentioned in any of the Rete node data structures we describe in this chapter. This is
        intentional - it enables nodes to be shared when two productions have conditions with the same
        basic form, but with different variable names."

        Takes a set of tokens and the terminal Beta node they came from
        and fires the inferred statements using the patterns associated
        with the terminal node.  Statements that have been previously inferred
        or already exist in the working memory are not asserted
        """
        if debug:
            print("%s from %s" % (tokens, term_node))

        # newTokens = []
        term_node.instanciating_tokens.add(tokens)

        # replace existentials in the head with new BNodes!
        b_node_replacement = {}
        for rule in term_node.rules:
            if isinstance(rule.formula.head, Exists):
                for bN in rule.formula.head.declare:
                    if (
                        not isinstance(rule.formula.body, Exists)
                        or bN not in rule.formula.body.declare
                    ):
                        b_node_replacement[bN] = BNode()
        for rhs_triple in term_node.consequent:
            if b_node_replacement:
                rhs_triple = tuple(
                    [b_node_replacement.get(term, term) for term in rhs_triple]
                )
            if debug:
                if not tokens.bindings:
                    tokens._generate_bindings()
            key = tuple(
                [None if isinstance(item, BNode) else item for item in rhs_triple]
            )
            override, execute_fn = term_node.execute_actions.get(key, (None, None))

            if override:
                # There is an execute action associated with this production
                # that is attaced to the given consequent triple and
                # is meant to perform all of the production duties
                # (bypassing the inference of triples, etc.)
                execute_fn(term_node, None, tokens, None, debug)
            else:
                for inferred_triple, binding in _mul_pattern_with_substitutions(
                    tokens, rhs_triple, term_node
                ):
                    if [term for term in inferred_triple if isinstance(term, Variable)]:
                        # Unfullfilled bindings (skip non-ground head literals)
                        if execute_fn:
                            # The indicated execute action is supposed to be triggered
                            # when the indicates RHS triple is inferred for the
                            # (even if it is not ground)
                            execute_fn(
                                term_node, inferred_triple, tokens, binding, debug
                            )
                        continue
                    # if rhs_triple[1].find('subClassOf_derived')+1:import pdb;pdb.set_trace()
                    inferredToken = ReteToken(inferred_triple)
                    self.proof_tracers.setdefault(inferred_triple, []).append(binding)
                    self.justifications.setdefault(inferred_triple, set()).add(
                        term_node
                    )
                    if term_node.filter and inferred_triple not in self.filtered_facts:
                        self.filtered_facts.add(inferred_triple)
                    if (
                        inferred_triple not in self.inferred_facts
                        and inferredToken not in self.working_memory
                    ):
                        # if (rhs_triple == (Variable('A'), RDFS.RDFSNS['subClassOf_derived'], Variable('B'))):
                        #     import pdb;pdb.set_trace()
                        if debug:
                            print(
                                "Inferred triple: ",
                                inferred_triple,
                                " from ",
                                term_node.clause_representation(),
                            )
                            inferredToken.debug = True
                        self.inferred_facts.add(inferred_triple)
                        curr_idx = self.instantiations.get(term_node, 0)
                        curr_idx += 1
                        self.instantiations[term_node] = curr_idx
                        self.add_wme(inferredToken)
                        if execute_fn:
                            # The indicated execute action is supposed to be triggered
                            # when the indicates RHS triple is inferred for the
                            # first time
                            execute_fn(
                                term_node, inferred_triple, tokens, binding, debug
                            )
                        if self.goal is not None and self.goal in self.inferred_facts:
                            raise InferredGoal("Proved goal " + repr(self.goal))
                    else:
                        if debug:
                            print("Inferred triple skipped: ", inferred_triple)
                        if execute_fn:
                            # The indicated execute action is supposed to be triggered
                            # when the indicates RHS triple is inferred for the
                            # first time
                            execute_fn(
                                term_node, inferred_triple, tokens, binding, debug
                            )

    def add_wme(self, wme):
        """
        procedure add-wme (w: WME) exhaustive hash table versioning::

            let v1, v2, and v3 be the symbols in the three fields of w
            alpha-mem = lookup-in-hash-table (v1, v2, v3)
            if alpha-mem then alpha-memory-activation (alpha-mem, w)
            alpha-mem = lookup-in-hash-table (v1, v2, *)
            if alpha-mem then alpha-memory-activation (alpha-mem, w)
            alpha-mem = lookup-in-hash-table (v1, *, v3)
            if alpha-mem then alpha-memory-activation (alpha-mem, w)
            ...
            alpha-mem = lookup-in-hash-table (*, *, *)
            if alpha-mem then alpha-memory-activation (alpha-mem, w)
            end
        """
        for term_comb, term_dict in self.alpha_pattern_hash.items():
            for alpha_node in term_dict.get(wme.alpha_network_hash(term_comb), []):
                alpha_node.activate(wme.unbound_copy())

    def feed_facts_to_add(self, token_iterator):
        """
        Feeds the network an iterator of facts / tokens which are fed to the alpha nodes
        which propagate the matching process through the network
        """
        for token in token_iterator:
            self.working_memory.add(token)
            self.add_wme(token)
            if self._memstats_enabled:
                self._memstats_counter += 1
                if self._memstats_counter >= self._memstats_next:
                    self._report_memstats("tokens=%d" % self._memstats_counter)
                    self._memstats_next += self._memstats_interval

    def _find_patterns(self, pattern_list):
        rt = []
        for beta_node_pattern, alpha_node_patterns in [
            (
                pattern_list.__getslice__(0, -i),
                pattern_list.__getslice__(-i, len(pattern_list)),
            )
            for i in range(1, len(pattern_list))
        ]:
            assert isinstance(beta_node_pattern, HashablePatternList)
            assert isinstance(alpha_node_patterns, HashablePatternList)
            if beta_node_pattern in self.nodes:
                rt.append(beta_node_pattern)
                rt.extend(
                    [
                        HashablePatternList([aPattern])
                        for aPattern in alpha_node_patterns
                    ]
                )
                return rt
        for alpha_node_pattern in pattern_list:
            rt.append(HashablePatternList([alpha_node_pattern]))
        return rt

    def create_alpha_node(self, current_pattern):
        """ """
        if isinstance(current_pattern, N3Builtin):
            node = BuiltInAlphaNode(current_pattern)
        else:
            node = AlphaNode(current_pattern, self.rule_store.filters)
        self.alpha_pattern_hash[node.alpha_network_hash()].setdefault(
            node.alpha_network_hash(ground_term_hash=True), []
        ).append(node)
        if not isinstance(node, BuiltInAlphaNode) and node.builtin:
            s, p, o = current_pattern
            node = BuiltInAlphaNode(
                N3Builtin(p, self.rule_store.filters[p](s, o), s, o)
            )
        return node

    def _reset_instantiation_stats(self):
        self.instantiations = dict([(tNode, 0) for tNode in self.terminal_nodes])

    def check_duplicate_rules(self):
        checked_clauses = {}
        for t_node in self.terminal_nodes:
            for rule in t_node.rules:
                collision = checked_clauses.get(rule.formula)
                assert collision is None, "%s collides with %s" % (
                    t_node,
                    checked_clauses[rule.formula],
                )
                checked_clauses.setdefault(t_node.rule.formula, []).append(t_node)

    def register_rete_action(self, head_triple, override, execute_fn):
        """
        Register the given execute function for any rule with the
        given head using the override argument to determine whether or
        not the action completely handles the firing of the rule.

        The signature of the execute action is as follows:

        def someExecuteAction(t_node, inferredTriple, token, binding):
            .. pass ..
        """
        for t_node in self.terminal_nodes:
            for rule in t_node.rules:
                if not isinstance(rule.formula.head, (Exists, Uniterm)):
                    continue
                head_triple = get_uterm(rule.formula.head).to_rdf_tuple()
                head_triple = tuple(
                    [None if isinstance(item, BNode) else item for item in head_triple]
                )
                t_node.execute_actions[head_triple] = (override, execute_fn)

    def build_network(self, lhs_iterator, rhs_iterator, rule, a_filter=False):
        """
        Takes an iterator of triples in the LHS of an N3 rule and an iterator of the RHS and extends
        the Rete network, building / reusing Alpha
        and Beta nodes along the way (via a dictionary mapping of patterns to the built nodes)
        """
        matched_patterns = HashablePatternList()
        attached_patterns = []
        # hasBuiltin = False
        LHS = []
        while True:
            try:
                current_pattern = next(lhs_iterator)

                # The LHS isn't done yet, stow away the current pattern
                # We need to convert the Uniterm into a triple
                if isinstance(current_pattern, Uniterm):
                    current_pattern = current_pattern.to_rdf_tuple()
                LHS.append(current_pattern)
            except StopIteration:
                # The LHS is done, need to initiate second pass to recursively build join / beta
                # nodes towards a terminal node

                # We need to convert the Uniterm into a triple
                consequents = [
                    isinstance(fact, Uniterm) and fact.to_rdf_tuple() or fact
                    for fact in rhs_iterator
                ]
                if matched_patterns and matched_patterns in self.nodes:
                    attached_patterns.append(matched_patterns)
                elif matched_patterns:
                    rt = self._find_patterns(matched_patterns)
                    attached_patterns.extend(rt)
                if len(attached_patterns) == 1:
                    node = self.nodes[attached_patterns[0]]
                    if isinstance(node, BetaNode):
                        terminal_node = node
                    else:
                        paddedLHSPattern = (
                            HashablePatternList([None]) + attached_patterns[0]
                        )
                        terminal_node = self.nodes.get(paddedLHSPattern)
                        if terminal_node is None:
                            # New terminal node
                            terminal_node = BetaNode(None, node, a_pass_thru=True)
                            self.nodes[paddedLHSPattern] = terminal_node
                            node.connect_to_beta_node(terminal_node, RIGHT_MEMORY)
                    terminal_node.consequent.update(consequents)
                    terminal_node.rules.add(rule)
                    terminal_node.antecedent = rule.formula.body
                    terminal_node.network = self
                    terminal_node.head_atoms.update(rule.formula.head)
                    terminal_node.filter = a_filter
                    self.terminal_nodes.add(terminal_node)
                else:
                    move_to_end = []
                    # endIdx = len(attached_patterns) - 1
                    final_pattern_list = []
                    for idx, pattern in enumerate(attached_patterns):
                        assert isinstance(pattern, HashablePatternList), repr(pattern)
                        curr_node = self.nodes[pattern]
                        if (
                            isinstance(curr_node, BuiltInAlphaNode)
                            or isinstance(curr_node, BetaNode)
                            and curr_node.fed_by_builtin
                        ):
                            move_to_end.append(pattern)
                        else:
                            final_pattern_list.append(pattern)
                    terminal_node = self.attach_beta_nodes(
                        chain(final_pattern_list, move_to_end)
                    )
                    terminal_node.consequent.update(consequents)
                    terminal_node.rules.add(rule)
                    terminal_node.antecedent = rule.formula.body
                    terminal_node.network = self
                    terminal_node.head_atoms.update(rule.formula.head)
                    terminal_node.filter = a_filter
                    self.terminal_nodes.add(terminal_node)
                    self._reset_instantiation_stats()
                # self.checkDuplicateRules()
                return terminal_node
            if HashablePatternList([current_pattern]) in self.nodes:
                # Current pattern matches an existing alpha node
                matched_patterns.append(current_pattern)
            elif matched_patterns in self.nodes:
                # preceding patterns match an existing join/beta node
                new_node = self.create_alpha_node(current_pattern)
                if (
                    len(matched_patterns) == 1
                    and HashablePatternList([None]) + matched_patterns in self.nodes
                ):
                    existing_node = self.nodes[
                        HashablePatternList([None]) + matched_patterns
                    ]
                    new_beta_node = BetaNode(existing_node, new_node)
                    self.nodes[
                        HashablePatternList([None])
                        + matched_patterns
                        + HashablePatternList([current_pattern])
                    ] = new_beta_node
                    matched_patterns = (
                        HashablePatternList([None])
                        + matched_patterns
                        + HashablePatternList([current_pattern])
                    )
                else:
                    existing_node = self.nodes[matched_patterns]
                    new_beta_node = BetaNode(existing_node, new_node)
                    self.nodes[
                        matched_patterns + HashablePatternList([current_pattern])
                    ] = new_beta_node
                    matched_patterns.append(current_pattern)

                self.nodes[HashablePatternList([current_pattern])] = new_node
                new_beta_node.connect_incoming_nodes(existing_node, new_node)
                # Extend the match list with the current pattern and add it
                # to the list of attached patterns for the second pass
                attached_patterns.append(matched_patterns)
                matched_patterns = HashablePatternList()
            else:
                # The current pattern is not in the network and the match list isn't
                # either.  Add an alpha node
                new_node = self.create_alpha_node(current_pattern)
                self.nodes[HashablePatternList([current_pattern])] = new_node
                # Add to list of attached patterns for the second pass
                attached_patterns.append(HashablePatternList([current_pattern]))

    def attach_beta_nodes(self, pattern_iterator, last_beta_nodePattern=None):
        """
        The second 'pass' in the Rete network compilation algorithm:
        Attaches Beta nodes to the alpha nodes associated with all the patterns
        in a rule's LHS recursively towards a 'root' Beta node - the terminal node
        for the rule.  This root / terminal node is returned
        """
        try:
            next_pattern = next(pattern_iterator)
        except StopIteration:
            assert last_beta_nodePattern
            if last_beta_nodePattern:
                return self.nodes[last_beta_nodePattern]
            else:
                assert len(self.universal_truths), "should be empty LHSs"
                terminalNode = BetaNode(None, None, a_pass_thru=True)
                self.nodes[HashablePatternList([None])] = terminalNode
                return terminalNode  # raise Exception("Ehh. Why are we here?")
        if last_beta_nodePattern:
            first_node = self.nodes[last_beta_nodePattern]
            second_node = self.nodes[next_pattern]
            new_b_node_pattern = last_beta_nodePattern + next_pattern
            new_beta_node = BetaNode(first_node, second_node)
            self.nodes[new_b_node_pattern] = new_beta_node
        else:
            first_node = self.nodes[next_pattern]
            old_anchor = self.nodes.get(HashablePatternList([None]) + next_pattern)
            if not old_anchor:
                if isinstance(first_node, AlphaNode):
                    newfirst_node = BetaNode(None, first_node, a_pass_thru=True)
                    newfirst_node.connect_incoming_nodes(None, first_node)
                    self.nodes[HashablePatternList([None]) + next_pattern] = (
                        newfirst_node
                    )
                else:
                    newfirst_node = first_node
            else:
                newfirst_node = old_anchor
            first_node = newfirst_node
            second_pattern = next(pattern_iterator)
            second_node = self.nodes[second_pattern]
            new_beta_node = BetaNode(first_node, second_node)
            new_b_node_pattern = (
                HashablePatternList([None]) + next_pattern + second_pattern
            )
            self.nodes[new_b_node_pattern] = new_beta_node

        new_beta_node.connect_incoming_nodes(first_node, second_node)
        return self.attach_beta_nodes(pattern_iterator, new_b_node_pattern)

    def _report_memstats(self, reason):
        if not self._memstats_enabled:
            return
        left_mem = 0
        right_mem = 0
        substitution_keys = 0
        substitution_values = 0
        for node in list(self.nodes.values()):
            if isinstance(node, BetaNode):
                left_mem += len(node.memories[LEFT_MEMORY])
                right_mem += len(node.memories[RIGHT_MEMORY])
                for memory in node.memories.values():
                    substitution_keys += len(memory.substitution_dict)
                    substitution_values += sum(
                        len(vals) for vals in memory.substitution_dict.values()
                    )
        logger.warning(
            "Rete memstats (%s): working=%d inferred=%d nodes=%d terminals=%d",
            reason,
            len(self.working_memory),
            len(self.inferred_facts),
            len(self.nodes),
            len(self.terminal_nodes),
        )
        logger.warning(
            "Rete memstats index: left=%d right=%d subs_keys=%d subs_vals=%d",
            left_mem,
            right_mem,
            substitution_keys,
            substitution_values,
        )
        if self._memstats_tracemalloc and tracemalloc.is_tracing():
            snapshot = tracemalloc.take_snapshot()
            top_stats = snapshot.statistics("lineno")[:10]
            logger.warning("Rete tracemalloc top10 (%s)", reason)
            for stat in top_stats:
                logger.warning("  %s", stat)


def complement_expand(t_box_graph, complement_annotation):
    complement_expanded = []
    for negative_class in t_box_graph.subjects(predicate=OWL_NS.complementOf):
        containing_list = first(t_box_graph.subjects(RDF.first, negative_class))
        prev_link = None
        while containing_list:
            prev_link = containing_list
            containing_list = first(t_box_graph.subjects(RDF.rest, containing_list))
        if prev_link:
            for s, p, o in t_box_graph.triples_choices(
                (None, [OWL_NS.intersectionOf, OWL_NS.unionOf], prev_link)
            ):
                if (s, complement_annotation, None) in t_box_graph:
                    continue
                _class = Class(s)
                complement_expanded.append(s)
                print("Added %s to complement expansion" % _class)
                complement_expansion(_class)


def test():
    import doctest

    doctest.testmod()


if __name__ == "__main__":
    test()
