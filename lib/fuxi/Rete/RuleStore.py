from __future__ import annotations

import pathlib
# -*- coding: utf-8 -*-
# flake8: noqa

from functools import reduce
from typing import TYPE_CHECKING, IO, TextIO, Callable

from rdflib import (
    BNode,
    Literal,
    Namespace,
    RDF,
    URIRef,
    Variable,
)
from rdflib.parser import InputSource
from rdflib.store import Store
from rdflib.graph import QuotedGraph, Graph
from rdflib.namespace import NamespaceManager
from rdflib.term import Identifier

from .BuiltinPredicates import FILTERS
from fuxi.types import MutableBindings, RDFNode, RDFTerm, Triple

if TYPE_CHECKING:
    from typing import Iterable, Iterator, Mapping


def format_doctest_out(obj):
    return obj


LOG = Namespace("http://www.w3.org/2000/10/swap/log#")
Any = None

RULE_LHS = 0
RULE_RHS = 1


class N3Builtin(object):
    """
    An binary N3 Filter: A built-in which evaluates to a boolean
    """

    def __init__(
        self,
        uri: URIRef,
        func,
        argument: RDFTerm,
        result: RDFTerm,
    ) -> None:
        self.uri = uri
        self.argument = argument
        self.result = result
        self.func = func
        self.variables = [
            arg for arg in [self.argument, self.result] if isinstance(arg, Variable)
        ]

    def is_second_order(self) -> bool:
        return False

    def ground(self, var_mapping: "Mapping[RDFTerm, RDFTerm]") -> set[RDFTerm]:
        applied_keys = set([self.argument, self.result]).intersection(
            list(var_mapping.keys())
        )
        self.argument = var_mapping.get(self.argument, self.argument)
        self.result = var_mapping.get(self.result, self.result)
        return applied_keys

    def is_ground(self) -> bool:
        for term in [self.result, self.argument]:
            if isinstance(term, Variable):
                return False
        return True

    def rename_variables(self, var_mapping: "Mapping[RDFTerm, RDFTerm]") -> None:
        if var_mapping:
            self.argument = var_mapping.get(self.argument, self.argument)
            self.result = var_mapping.get(self.result, self.result)

    def binds(self, var: Variable) -> bool:
        return True

    def to_rdf_tuple(self) -> tuple[RDFTerm, RDFTerm, RDFTerm]:
        return (self.argument, self.uri, self.result)

    def render(self, argument, result):
        return "<%s>(%s, %s)" % (self.uri, argument, result)

    def __iter__(self) -> "Iterator[RDFTerm]":
        for f in [self.uri, self.argument, self.result]:
            yield f

    def __repr__(self):
        return "<%s>(%s, %s)" % (
            self.uri,
            isinstance(self.argument, Variable)
            and "?%s" % self.argument
            or self.argument,
            isinstance(self.result, Variable) and "?%s" % self.result or self.result,
        )


class Formula(object):
    """
    An N3 Formula.  Consists of an (internal) identifier
    and a *list* of triples
    """

    def __init__(self, identifier: RDFTerm) -> None:
        self.identifier = identifier
        self.triples: list[Triple | N3Builtin] = []

    def __len__(self) -> int:
        return len(self.triples)

    def __repr__(self):
        return "{%s}" % (repr(self.triples))

    def __getitem__(self, key: int) -> Triple | N3Builtin:
        return self.triples[key]

    def __iter__(self) -> "Iterator[Triple | N3Builtin]":
        for item in self.triples:
            yield item

    def extend(self, other: "Iterable[Triple | N3Builtin]") -> None:
        self.triples.extend(other)

    def append(self, other):
        self.triples.append(other)


class Rule(object):
    """
    An N3 Rule.  consists of two formulae associated via log:implies
    """

    def __init__(self, lhs, rhs):
        self.lhs = lhs
        self.rhs = rhs

    def __repr__(self):
        return "{%s} => {%s}" % (self.lhs, self.rhs)


def setup_rule_store(n3_stream: IO[bytes] | TextIO | InputSource | str | bytes | pathlib.PurePath | None = None,
                     additional_builtins: Mapping[Identifier, Callable] = None,
                     make_network: bool = False):
    """
    Create a N3RuleStore and a backing Graph, optionally a ReteNetwork.

    This is the main entry point for building a RETE-UL network from N3
    rules. When ``n3Stream`` is provided, the graph is populated from the
    source before the store is finalized.

    :param n3_stream: N3 source to parse (path, URL, or file-like).
    :param additional_builtins: Optional mapping of builtin predicates to
        Python callables.
    :param make_network: If True, also create and return a ReteNetwork with
        an empty inferred-facts graph.
    :return: ``(rule_store, rule_graph)`` or
        ``(rule_store, rule_graph, rete_network)`` when ``makeNetwork`` is
        True.

    Example:
    >>> from fuxi.Horn.HornRules import horn_from_n3
    >>> store, graph, net = setup_rule_store(make_network=True)
    >>> for rule in horn_from_n3('test/sameAsTestRules.n3'):
    ...     net.build_network_from_clause(rule)
    """
    rule_store = N3RuleStore(additional_builtins=additional_builtins)
    ns_mgr = NamespaceManager(Graph(rule_store))
    rule_graph = Graph(rule_store, namespace_manager=ns_mgr)
    if n3_stream:
        rule_graph.parse(n3_stream, format="n3")
    if make_network:
        from .Network import ReteNetwork

        closure_delta_graph = Graph()
        network = ReteNetwork(rule_store, inferred_target=closure_delta_graph)
        return rule_store, rule_graph, network
    return rule_store, rule_graph


class N3RuleStore(Store):
    doc = """
    A specialized Store which maintains order of statements
    and creates N3Filters, Rules, Formula objects, and other facts
    Ensures builtin filters refer to variables that have preceded

    >>> s = N3RuleStore()
    >>> g = Graph(s)
    >>> src = \"\"\"
    ... @prefix : <http://metacognition.info/FuXi/test#>.
    ... @prefix str:   <http://www.w3.org/2000/10/swap/string#>.
    ... @prefix math: <http://www.w3.org/2000/10/swap/math#>.
    ... @prefix log:   <http://www.w3.org/2000/10/swap/log#>.
    ... @prefix m: <http://metacognition.info/FuXi/test#>.
    ... @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#>.
    ... @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>.
    ... @prefix owl: <http://www.w3.org/2002/07/owl#>.
    ... m:a a rdfs:Class;
    ...    m:prop1 1;
    ...    m:prop2 4.
    ... m:b a owl:Class;
    ...    m:prop1 2;
    ...    m:prop2 4, 1, 5.
    ... (1 2) :relatedTo (3 4).
    ... { ?X a owl:Class. ?X :prop1 ?M. ?X :prop2 ?N. ?N math:equalTo 3 } => { [] :selected (?M ?N) }.\"\"\"
    >>> g = g.parse(data=src, format='n3')
    >>> s._finalize()
    >>> len([pred for subj, pred, obj in s.facts if pred == %(u)s'http://metacognition.info/FuXi/test#relatedTo']) #doctest: +SKIP
    1
    >>> len(s.rules)
    1
    >>> print(len(s.rules[0][RULE_LHS]))
    4
    >>> print(len(s.rules[0][RULE_RHS]))
    5
    >>> print(s.rules[0][RULE_LHS][1])
    (?X, rdflib.term.URIRef(%(u)s'http://metacognition.info/FuXi/test#prop1'), ?M)
    >>> print(s.rules[0][RULE_LHS][-1])
    <http://www.w3.org/2000/10/swap/math#equalTo>(?N, 3)

Description Rule Patterns Compilation
    >>> s = N3RuleStore()
    >>> g = Graph(s)
    >>> src = \"\"\"
    ... @prefix math: <http://www.w3.org/2000/10/swap/math#>.
    ... @prefix : <http://metacognition.info/FuXi/test#>.
    ... @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#>.
    ... @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>.
    ... @prefix owl: <http://www.w3.org/2002/07/owl#>.
    ... { ?S a [ rdfs:subClassOf ?C ] } => { ?S a ?C }.\"\"\"
    >>> g = g.parse(data=src, format='n3')
    >>> s._finalize()
    >>> assert s.rules
    >>> assert [pattern for pattern in s.rules[0][RULE_LHS] if isinstance(pattern, tuple) and [term for term in pattern if isinstance(term, BNode) ]], repr(s.rules[0][RULE_LHS])


Test single fact with collection

    >>> s = N3RuleStore()
    >>> g = Graph(s)
    >>> src = \"\"\"
    ... @prefix math: <http://www.w3.org/2000/10/swap/math#>.
    ... @prefix : <http://metacognition.info/FuXi/test#>.
    ... @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#>.
    ... @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>.
    ... @prefix owl: <http://www.w3.org/2002/07/owl#>.
    ... (1 2) :relatedTo owl:Class.\"\"\"
    >>> g = g.parse(data=src, format='n3')
    >>> s._finalize()
    >>> print(len(s.facts))
    5

RHS can only include RDF triples

    >>> s = N3RuleStore()
    >>> g = Graph(s)
    >>> src = \"\"\"
    ... @prefix math: <http://www.w3.org/2000/10/swap/math#>.
    ... @prefix : <http://metacognition.info/FuXi/test#>.
    ... @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#>.
    ... @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>.
    ... @prefix owl: <http://www.w3.org/2002/07/owl#>.
    ... {} => { 3 math:lessThan 2}.\"\"\"
    >>> g = g.parse(data=src, format='n3')
    >>> try:
    ...   s._finalize()
    ... except Exception as e:
    ...   print(e)
    Rule RHS must only include RDF triples (<http://www.w3.org/2000/10/swap/math#lessThan>(3, 2))

BuiltIn used out of order

    >>> s = N3RuleStore()
    >>> g = Graph(s)
    >>> src = \"\"\"
    ... @prefix math: <http://www.w3.org/2000/10/swap/math#>.
    ... @prefix : <http://metacognition.info/FuXi/test#>.
    ... { ?M math:lessThan ?Z.  ?R :value ?M; :value2 ?Z} => { ?R a :Selected.  }.\"\"\"
    >>> try:
    ...   g = g.parse(data=src, format='n3')
    ... except Exception as e:
    ...   print(e)  #doctest: +SKIP
    Builtin refers to variables without previous reference (<http://www.w3.org/2000/10/swap/math#lessThan>(?M, ?Z))

    Empty LHS & RHS
    >>> s = N3RuleStore()
    >>> g = Graph(s)
    >>> src = \"\"\"
    ... @prefix math: <http://www.w3.org/2000/10/swap/math#>.
    ... @prefix : <http://metacognition.info/FuXi/test#>.
    ... @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#>.
    ... @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>.
    ... @prefix owl: <http://www.w3.org/2002/07/owl#>.
    ... {} => {rdf:nil :allClasses ?C}.
    ... {?C owl:oneOf ?L. ?X a ?C. ?L :notItem ?X} => {}.\"\"\"
    >>> g = g.parse(data=src, format='n3')
    >>> len(s.formulae)
    2
    >>> s._finalize()
    >>> len(s.rules[0][0])
    0
    >>> len(s.rules[1][-1])
    0
    """

    __doc__ = format_doctest_out(doc)

    context_aware = True
    graph_aware = True
    formula_aware = True

    def __init__(self, identifier=None, additional_builtins=None):
        self.formulae = {}
        self.facts = []
        self.root_formula = None
        self._lists = {}
        self.current_list = None
        self._list_buffer = []
        self.rules = []
        self.referenced_variables = set()
        self.ns_mgr = {
            "skolem": URIRef("http://code.google.com/p/python-dlp/wiki/SkolemTerm#")
        }
        self.filters = {}
        self.filters.update(FILTERS)
        if additional_builtins:
            self.filters.update(additional_builtins)

    def namespace(self, prefix):
        return self.ns_mgr.get(prefix)

    def bind(self, prefix, namespace, override=True):
        if override or prefix not in self.ns_mgr:
            self.ns_mgr[prefix] = namespace

    def prefix(self, namespace):
        return dict([(v, k) for k, v in list(self.ns_mgr.items())]).get(namespace)

    def _unroll_list(self, l, list_name):
        list_triples = []
        last_item_name = None
        for link_item in l:
            link_name = l.index(link_item) == 0 and list_name or BNode()
            if last_item_name:
                list_triples.append((last_item_name, RDF.rest, link_name))
            list_triples.append((link_name, RDF.first, link_item))
            last_item_name = link_name
        list_triples.append((last_item_name, RDF.rest, RDF.nil))
        return list_triples

    def _finalize(self):
        def unroll_func(left, right):
            left_lists_to_unroll = []
            right_lists_to_unroll = []
            if isinstance(left, tuple):
                s, p, o = left
                left_lists_to_unroll = [term for term in [s, o] if term in self._lists]
                if left_lists_to_unroll:
                    left_lists_to_unroll = reduce(
                        lambda x, y: x + y,
                        [
                            self._unroll_list(self._lists[l], l)
                            for l in left_lists_to_unroll
                        ],
                    )
                left = [left]
            elif isinstance(left, N3Builtin):
                left = [left]
            if isinstance(right, tuple):
                s, p, o = right
                right_lists_to_unroll = [term for term in [s, o] if term in self._lists]
                if right_lists_to_unroll:
                    right_lists_to_unroll = reduce(
                        lambda x, y: x + y,
                        [
                            self._unroll_list(self._lists[l], l)
                            for l in right_lists_to_unroll
                        ],
                    )
                right = [right]
            elif isinstance(right, N3Builtin):
                right = [right]
            return left + left_lists_to_unroll + right + right_lists_to_unroll

        if len(self.facts) == 1:
            s, p, o = self.facts[0]
            lists_to_unroll = [term for term in [s, o] if term in self._lists]
            if lists_to_unroll:
                self.facts.extend(
                    reduce(
                        lambda x, y: x + y,
                        [self._unroll_list(self._lists[l], l) for l in lists_to_unroll],
                    )
                )
        elif self.facts:
            self.facts = reduce(unroll_func, self.facts)
        for formula in list(self.formulae.values()):
            if len(formula) == 1:
                if isinstance(formula[0], tuple):
                    s, p, o = formula[0]
                    lists_to_unroll = [term for term in [s, o] if term in self._lists]
                    if lists_to_unroll:
                        list_triples = reduce(
                            lambda x, y: x + y,
                            [
                                self._unroll_list(self._lists[l], l)
                                for l in lists_to_unroll
                            ],
                        )
                        formula.extend(list_triples)
            elif len(formula):
                formula.triples = reduce(unroll_func, [i for i in formula])
        for lhs, rhs in self.rules:
            for item in self.formulae.get(rhs, []):
                assert isinstance(item, tuple), (
                    "Rule RHS must only include RDF triples (%s)" % item
                )
        self.rules = [
            (self.formulae.get(lhs, Formula(lhs)), self.formulae.get(rhs, Formula(rhs)))
            for lhs, rhs in self.rules
        ]

    def _check_variable_references(self, referenced_variables, terms, func_obj):
        for term in [i for i in terms if isinstance(i, Variable)]:
            if term not in referenced_variables:
                raise Exception(
                    "Builtin refers to variables without previous reference (%s)"
                    % func_obj
                )

    def add(self, triple, context=None, quoted=False):
        (subject, predicate, obj) = triple
        if (
            predicate == RDF.first
            and not isinstance(subject, Variable)
            and not isinstance(object, Variable)
        ):
            if not self.current_list:
                self._list_buffer.append(obj)
                self.current_list = subject
            else:
                self._list_buffer.append(obj)
        elif (
            predicate == RDF.rest
            and not isinstance(subject, Variable)
            and not isinstance(object, Variable)
        ):
            if obj == RDF.nil:
                self._lists[self.current_list] = [item for item in self._list_buffer]
                self._list_buffer = []
                self.current_list = None
        elif not isinstance(context, QuotedGraph):
            if not self.root_formula:
                self.root_formula = context.identifier
            if predicate == LOG.implies:
                self.rules.append(
                    (
                        isinstance(subject, URIRef) and subject or subject.identifier,
                        isinstance(obj, (URIRef, Literal)) and obj or obj.identifier,
                    )
                )
            else:
                self.facts.append((subject, predicate, obj))
        else:
            formula = self.formulae.get(context.identifier, Formula(context.identifier))
            if predicate in self.filters:
                new_filter = N3Builtin(
                    predicate, self.filters[predicate](subject, obj), subject, obj
                )
                # @attention: The non-deterministic parse order of an RDF graph makes this
                # check hard to enforce
                # self._checkVariableReferences(self.referencedVariables, [subject, obj], new_filter)
                formula.append(new_filter)
            else:
                # print("(%s, %s, %s) pattern in %s"%(subject, predicate, obj, context.identifier))
                variables = [
                    arg
                    for arg in [subject, predicate, obj]
                    if isinstance(arg, Variable)
                ]
                self.referenced_variables.update(variables)
                formula.append((subject, predicate, obj))
            self.formulae[context.identifier] = formula

    def __repr__(self):
        return ""

    def __len__(self, context=None):
        return 0

    def optimize_rules(self):
        pattern_dict = {}
        for lhs, rhs in self.rules:
            for pattern in lhs:
                if not isinstance(pattern, N3Builtin):
                    _hashList = [
                        isinstance(term, (Variable, BNode)) and "\t" or term
                        for term in pattern
                    ]
                    pattern_dict.setdefault(
                        reduce(lambda x, y: x + y, _hashList), set()
                    ).add(pattern)
        for key, vals in list(pattern_dict.items()):
            if len(vals) > 1:
                print("###### Similar Patterns ######")
                for val in vals:
                    print(val)
                print("##############################")


def test():
    import doctest

    doctest.testmod()


def test2():
    s = N3RuleStore()
    g = Graph(s)
    src = """
    @prefix math: <http://www.w3.org/2000/10/swap/math#>.
    @prefix : <http://metacognition.info/FuXi/test#>.
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#>.
    @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>.
    @prefix owl: <http://www.w3.org/2002/07/owl#>.
    :subj :pred obj.
    {} => { 3 math:lessThan 2}."""
    g = g.parse(data=src, format="n3")
    s._finalize()


if __name__ == "__main__":
    test()
