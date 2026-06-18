from __future__ import annotations

import pathlib

from rdflib.parser import InputSource
from rdflib.term import Identifier

# -*- coding: utf-8 -*-
# flake8: noqa
"""
This section defines Horn rules for RIF Phase 1. The syntax and semantics
incorporates RIF Positive Conditions defined in Section Positive Conditions
"""

from typing import Any, TYPE_CHECKING, Callable, IO, TextIO

from fuxi.Horn.PositiveConditions import (
    And,
    Atomic,
    Exists,
    ExternalFunction,
    SetOperator,
    Uniterm,
)

if TYPE_CHECKING:
    from typing import Iterator, Mapping
    from fuxi.Horn.PositiveConditions import Condition

from fuxi.Horn import (
    DATALOG_SAFETY_NONE,
)

from rdflib.graph import Dataset
from rdflib import (
    BNode,
    Variable,
)

from functools import reduce

import itertools


def format_doctest_out(obj: Any) -> Any:
    return obj


def network_from_n3(n3_source, additional_builtins=None):
    """
    Build a ReteNetwork from an N3 / RDF conjunctive graph.

    This parses rules from the given graph (or dataset), installs any
    additional builtins, and compiles the rules into a RETE-UL network.

    :param n3_source: A conjunctive graph or dataset containing N3 rules.
    :param additional_builtins: Optional mapping of builtin predicates to
        Python callables.
    :return: A :class:`~fuxi.Rete.Network.ReteNetwork` instance.
    """
    from fuxi.Rete.RuleStore import setup_rule_store

    rule_store, rule_graph, network = setup_rule_store(
        additional_builtins=additional_builtins, make_network=True
    )
    if isinstance(n3_source, Dataset):
        for ctx in n3_source.graphs():
            for s, p, o in ctx:
                rule_store.add((s, p, o), ctx)
    else:
        for s, p, o in n3_source:
            rule_store.add((s, p, o), n3_source)
    rule_store._finalize()
    for rule in Ruleset(n3_rules=rule_store.rules, ns_mapping=rule_store.ns_mgr):
        network.build_network_from_clause(rule)
    return network


def horn_from_dl(
    owl_graph,
    safety: int = DATALOG_SAFETY_NONE,
    derived_preds: list | None = None,
    compl_skip: list | None = None,
):
    """
    Convert an OWL/RDF graph into a Ruleset of Horn clauses.

    The OWL graph is translated using a variation of the OWL 2 RL
    transformation. Use ``derivedPreds`` to restrict the rule set to a
    known set of derived predicates and ``safety`` to control rule safety.

    :param owl_graph: OWL/RDF graph to translate.
    :param safety: Rule safety level (see DATALOG_SAFETY_* constants).
    :param derived_preds: Optional list of derived predicates (IDB).
    :param compl_skip: Optional list of predicates to skip during
        complement expansion.
    :return: Iterable of Horn rules (Ruleset).
    """
    from fuxi.Rete.RuleStore import setup_rule_store

    rule_store, rule_graph, network = setup_rule_store(make_network=True)
    return network.setup_description_logic_programming(
        owl_graph,
        expanded=compl_skip,
        add_pd_semantics=False,
        construct_network=False,
        derived_preds=derived_preds,
        safety=safety,
    )


def horn_from_n3(
    n3_source: IO[bytes]
    | TextIO
    | InputSource
    | str
    | bytes
    | pathlib.PurePath
    | Dataset,
    additional_builtins: Mapping[Identifier, Callable] = None,
) -> Ruleset:
    """
    Load a Ruleset from an N3 document or dataset.

    :param n3_source: Path, URL, or RDF dataset/graph with N3 rules.
    :param additional_builtins: Optional mapping of builtin predicates to
        Python callables.
    :return: A :class:`Ruleset` instance.
    """
    from fuxi.Rete.RuleStore import setup_rule_store, N3RuleStore

    if isinstance(n3_source, Dataset):
        store = N3RuleStore(additional_builtins=additional_builtins)
        for ctx in n3_source.graphs():
            for s, p, o in ctx:
                store.add((s, p, o), ctx)
    else:
        store, graph = setup_rule_store(
            n3_source, additional_builtins=additional_builtins
        )
    store._finalize()
    return Ruleset(n3_rules=store.rules, ns_mapping=store.ns_mgr)


def extract_variables(term, existential=True):
    if isinstance(term, existential and BNode or Variable):
        yield term
    elif isinstance(term, Uniterm):
        for t in term.to_rdf_tuple():
            if isinstance(t, existential and BNode or Variable):
                yield t


def iter_condition(condition: "Condition") -> "Iterator[Condition]":
    return isinstance(condition, SetOperator) and condition or iter([condition])


class Ruleset(object):
    """
    Ruleset ::= RULE*
    """

    def __init__(
        self,
        formulae: list | None = None,
        n3_rules: list | None = None,
        ns_mapping: "Mapping[str, Any] | None" = None,
    ) -> None:
        from fuxi.Rete.RuleStore import N3Builtin

        self.ns_mapping = ns_mapping and ns_mapping or {}
        self.formulae = formulae and formulae or []
        if n3_rules:
            from fuxi.DLP import breadth_first

            # Convert a N3 abstract model (parsed from N3) into a RIF BLD
            for lhs, rhs in n3_rules:
                all_vars = set()
                for rule_condition in [lhs, rhs]:
                    for stmt in rule_condition:
                        if isinstance(stmt, N3Builtin):
                            ExternalFunction(stmt, new_nss=self.ns_mapping)
                            # print(stmt)
                            # raise
                        all_vars.update(
                            [
                                term
                                for term in stmt
                                if isinstance(term, (BNode, Variable))
                            ]
                        )
                body = [
                    isinstance(term, N3Builtin)
                    and term
                    or Uniterm(
                        list(term)[1],
                        [list(term)[0], list(term)[-1]],
                        new_nss=ns_mapping,
                    )
                    for term in lhs
                ]
                body = len(body) == 1 and body[0] or And(body)
                head = [Uniterm(p, [s, o], new_nss=ns_mapping) for s, p, o in rhs]
                head = len(head) == 1 and head[0] or And(head)

                # first we identify body variables
                body_vars = set(
                    reduce(
                        lambda x, y: x + y,
                        [
                            list(extract_variables(i, existential=False))
                            for i in iter_condition(body)
                        ],
                    )
                )
                # then we identify head variables
                head_vars = set(
                    reduce(
                        lambda x, y: x + y,
                        [
                            list(extract_variables(i, existential=False))
                            for i in iter_condition(head)
                        ],
                    )
                )

                # then we identify those variables that should (or should not)
                # be converted to skolem terms
                update_dict = dict(
                    [(var, BNode()) for var in head_vars if var not in body_vars]
                )

                for uni_term in iter_condition(head):

                    def update_uniterm(uterm):
                        new_arg = [update_dict.get(i, i) for i in uni_term.arg]
                        uni_term.arg = new_arg

                    if isinstance(uni_term, Uniterm):
                        update_uniterm(uni_term)
                    else:
                        for u in uni_term:
                            update_uniterm(u)

                exist = [list(extract_variables(i)) for i in breadth_first(head)]
                e = Exists(
                    formula=head, declare=set(reduce(lambda x, y: x + y, exist, []))
                )
                if reduce(lambda x, y: x + y, exist):
                    head = e
                    assert e.declare, exist

                self.formulae.append(Rule(Clause(body, head), declare=all_vars))

    def __iter__(self):
        for f in self.formulae:
            yield f


class Rule(object):
    """
    RULE ::= 'Forall' Var* CLAUSE

    Example: {?C rdfs:subClassOf ?SC. ?M a ?C} => {?M a ?SC}.

    >>> clause = Clause(And([Uniterm(RDFS.subClassOf, [Variable('C'), Variable('SC')]),
    ...                      Uniterm(RDF.type, [Variable('M'), Variable('C')])]),
    ...                 Uniterm(RDF.type, [Variable('M'), Variable('SC')]))
    >>> Rule(clause, [Variable('M'), Variable('SC'), Variable('C')])
    Forall ?M ?SC ?C ( ?SC(?M) :- And( rdfs:subClassOf(?C ?SC) ?C(?M) ) )

    """

    def __init__(self, clause, declare=None, ns_mapping=None, negative_stratus=False):
        self.negative_stratus = negative_stratus
        self.ns_mapping = ns_mapping and ns_mapping or {}
        self.formula = clause
        self.declare = declare and declare or []

    def is_second_order(self):
        second_order = [
            pred
            for pred in itertools.chain(
                iter_condition(self.formula.head), iter_condition(self.formula.body)
            )
            if pred.is_second_order()
        ]
        return bool(second_order)

    def is_safe(self):
        """
        A RIF-Core rule, r is safe if and only if
        - r is a rule implication, φ :- ψ, and all the variables that occur
          in φ are safe in ψ, and all the variables that occur in ψ are bound in ψ;
        - or r is a universal rule, Forall v1, ..., vn (r'), n ≥ 1, and r' is safe.

        >>> clause1 = Clause(And([Uniterm(RDFS.subClassOf, [Variable('C'), Variable('SC')]),
        ...                      Uniterm(RDF.type, [Variable('M'), Variable('C')])]),
        ...                 Uniterm(RDF.type, [Variable('M'), Variable('SC')]))
        >>> r1 = Rule(clause1, [Variable('M'), Variable('SC'), Variable('C')])
        >>> clause2 = Clause(And([Uniterm(RDFS.subClassOf, [Variable('C'), Variable('SC')])]),
        ...                 Uniterm(RDF.type, [Variable('M'), Variable('SC')]))
        >>> r2 = Rule(clause2, [Variable('M'), Variable('SC'), Variable('C')])
        >>> r1.is_safe()
        True
        >>> r2.is_safe()
        False

        >>> skolemTerm = BNode()
        >>> e = Exists(Uniterm(RDFS.subClassOf, [skolemTerm, Variable('C')]), declare=[skolemTerm])
        >>> r1.formula.head = e
        >>> r1.is_safe()
        False
        """
        from fuxi.Rete.SidewaysInformationPassing import get_args, iter_condition

        assert isinstance(self.formula.head, (Exists, Atomic)), (
            "Safety can only be checked on rules in normal form"
        )
        for var in filter(
            lambda term: isinstance(term, (Variable, BNode)),
            get_args(self.formula.head),
        ):
            if not self.formula.body.is_safe_for_variable(var):
                return False
        for var in filter(
            lambda term: isinstance(term, (Variable, BNode)),
            reduce(
                lambda l, r: l + r,
                [get_args(lit) for lit in iter_condition(self.formula.body)],
            ),
        ):
            if not self.formula.body.binds(var):
                return False
        return True

    @format_doctest_out
    def n3(self):
        """
        Render a rule as N3 (careful to use e:tuple (_: ?X) skolem functions for existentials in the head)

        >>> clause = Clause(And([Uniterm(RDFS.subClassOf, [Variable('C'), Variable('SC')]),
        ...                      Uniterm(RDF.type, [Variable('M'), Variable('C')])]),
        ...                 Uniterm(RDF.type, [Variable('M'), Variable('SC')]))
        >>> Rule(clause, [Variable('M'), Variable('SC'), Variable('C')]).n3()
        %(u)s'{ ?C rdfs:subClassOf ?SC .\\n ?M a ?C } => { ?M a ?SC }'

        """
        return "{ %s } => { %s }" % (self.formula.body.n3(), self.formula.head.n3())
        # "Forall %s ( %r )"%(' '.join([var.n3() for var in self.declare]),
        #                        self.formula)

    def __eq__(self, other):
        return hash(self.formula) == hash(other.formula)

    def __hash__(self):
        """
        >>> a=Clause(And([Uniterm(RDFS.subClassOf, [Variable('C'), Variable('SC')]),
        ...             Uniterm(RDF.type, [Variable('M'), Variable('C')])]),
        ...        Uniterm(RDF.type, [Variable('M'), Variable('SC')]))
        >>> b=Clause(And([Uniterm(RDFS.subClassOf, [Variable('C'), Variable('SC')]),
        ...             Uniterm(RDF.type, [Variable('M'), Variable('C')])]),
        ...        Uniterm(RDF.type, [Variable('M'), Variable('SC')]))
        >>> d=set()
        >>> d.add(a)
        >>> b in d
        True
        >>> hash(a) == hash(b)
        True
        >>> EX_NS = Namespace('http://example.com/')
        >>> a=Clause(Uniterm(RDF.type, [Variable('C'), EX_NS.Foo]),
        ...          Uniterm(RDF.type, [Variable('C'), EX_NS.Bar]))
        >>> b=Clause(Uniterm(RDF.type, [Variable('C'), EX_NS.Bar]),
        ...          Uniterm(RDF.type, [Variable('C'), EX_NS.Foo]))
        >>> a == b
        False
        """
        return hash(self.formula)

    def __repr__(self):
        return "Forall %s ( %r )" % (
            " ".join([var.n3() for var in self.declare]),
            self.formula,
        )


def normalize_body(rule):
    from fuxi.Rete.RuleStore import N3Builtin

    # from itertools import groupby, chain
    new_body = []
    built_ins = []
    if isinstance(rule.formula.body, And):
        for lit in rule.formula.body:
            if isinstance(lit, N3Builtin):
                built_ins.append(lit)
            else:
                new_body.append(lit)
        new_body.extend(built_ins)
        rule.formula.body = And(new_body)
    return rule


class Clause(object):
    """
    Facts are *not* modelled formally as rules with empty bodies

    Implies ::= ATOMIC ':-' CONDITION

    Use body / head instead of if/then (native language clash)

    Example: {?C rdfs:subClassOf ?SC. ?M a ?C} => {?M a ?SC}.

    >>> Clause(And([Uniterm(RDFS.subClassOf, [Variable('C'), Variable('SC')]),
    ...             Uniterm(RDF.type, [Variable('M'), Variable('C')])]),
    ...        Uniterm(RDF.type, [Variable('M'), Variable('SC')]))
    ?SC(?M) :- And( rdfs:subClassOf(?C ?SC) ?C(?M) )
    """

    def __init__(self, body, head):
        self.body = body
        self.head = head
        from fuxi.Rete.Network import HashablePatternList

        ant_hash = HashablePatternList(
            [term.to_rdf_tuple() for term in body], skip_b_nodes=True
        )
        cons_hash = HashablePatternList(
            [term.to_rdf_tuple() for term in head], skip_b_nodes=True
        )
        self._body_hash = hash(ant_hash)
        self._head_hash = hash(cons_hash)
        self._hash = hash((self._head_hash, self._body_hash))

    def __eq__(self, other):
        return hash(self) == hash(other)

    def __hash__(self):
        """
        >>> a=Clause(And([Uniterm(RDFS.subClassOf, [Variable('C'), Variable('SC')]),
        ...             Uniterm(RDF.type, [Variable('M'), Variable('C')])]),
        ...        Uniterm(RDF.type, [Variable('M'), Variable('SC')]))
        >>> b=Clause(And([Uniterm(RDFS.subClassOf, [Variable('C'), Variable('SC')]),
        ...             Uniterm(RDF.type, [Variable('M'), Variable('C')])]),
        ...        Uniterm(RDF.type, [Variable('M'), Variable('SC')]))
        >>> d=set()
        >>> d.add(a)
        >>> b in d
        True
        >>> hash(a) == hash(b)
        True

        >>> d={a:True}
        >>> b in d
        True
        """
        return self._hash

    def as_tuple(self):
        return self.body, self.head

    def __repr__(self):
        if isinstance(self.body, SetOperator) and not len(self.body):
            return "%r :-" % self.head
        return "%r :- %r" % (self.head, self.body)

    def n3(self):
        return "{ %s } => { %s }" % (self.body.n3(), self.head.n3())


def test():
    import doctest

    doctest.testmod()


if __name__ == "__main__":
    test()
