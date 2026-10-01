# -*- coding: utf-8 -*-
# flake8: noqa
""" """

import copy
from fuxi.Horn.PositiveConditions import (
    And,
    Or,
    Uniterm,
)


def has_nested_conjunction(conjunct):
    rt = False
    for item in conjunct:
        if isinstance(item, And):
            rt = True
            break
    return rt


def flatten_helper(condition):
    to_do = [item for item in condition if isinstance(item, And)]
    for i in to_do:
        condition.formulae.remove(i)
    for i in to_do:
        condition.formulae.extend(i)


def has_breadth_first_nested_conj(condition):
    from fuxi.DLP import breadth_first

    return has_nested_conjunction(condition) or [
        i
        for i in breadth_first(condition)
        if isinstance(i, And) and has_nested_conjunction(i)
    ]


def flatten_conjunctions(condition, is_nested=False):
    from fuxi.DLP import breadth_first

    if is_nested or has_nested_conjunction(condition):
        flatten_helper(condition)
    for nested_conj in [
        i
        for i in breadth_first(condition)
        if isinstance(i, And) and has_nested_conjunction(i)
    ]:
        flatten_conjunctions(nested_conj, is_nested=True)


def apply_demorgans(clause):
    """
    >>> from fuxi.DLP import Clause
    >>> EX_NS = Namespace('http://example.com/')
    >>> ns = {'ex' : EX_NS}
    >>> pred1 = PredicateExtentFactory(EX_NS.somePredicate,newNss=ns)
    >>> pred2 = PredicateExtentFactory(EX_NS.somePredicate2,newNss=ns)
    >>> pred3 = PredicateExtentFactory(EX_NS.somePredicate3,binary=False,newNss=ns)
    >>> pred4 = PredicateExtentFactory(EX_NS.somePredicate4,binary=False,newNss=ns)
    >>> clause = Clause(And([pred1[(Variable('X'),Variable('Y'))],
    ...                      Or([pred2[(Variable('X'),EX_NS.individual1)],
    ...                          pred3[(Variable('Y'))]],naf=True)]),
    ...                 pred4[Variable('X')])
    >>> clause
    ex:somePredicate4(?X) :- And( ex:somePredicate(?X ?Y) not Or( ex:somePredicate2(?X ex:individual1) ex:somePredicate3(?Y) ) )
    >>> apply_demorgans(clause)
    >>> clause
    ex:somePredicate4(?X) :- And( ex:somePredicate(?X ?Y) And( not ex:somePredicate2(?X ex:individual1) not ex:somePredicate3(?Y) ) )
    >>> flatten_conjunctions(clause.body)
    >>> clause
    ex:somePredicate4(?X) :- And( ex:somePredicate(?X ?Y) not ex:somePredicate2(?X ex:individual1) not ex:somePredicate3(?Y) )
    """
    from fuxi.DLP import breadth_first, breadth_first_replace

    replacement_map = {}
    for negDisj in [
        i for i in breadth_first(clause.body) if isinstance(i, Or) and i.naf
    ]:
        replacement_list = []
        for innerTerm in negDisj:
            assert isinstance(negDisj, Uniterm)
            innerTerm.naf = not innerTerm.naf
            replacement_list.append(innerTerm)
        replacement_map[negDisj] = And(replacement_list)
    for old, new in list(replacement_map.items()):
        list(breadth_first_replace(clause.body, candidate=old, replacement=new))


def handle_non_disjunctive_clauses(
    ruleset,
    network,
    construct_network,
    negative_stratus,
    ignore_negative_stratus,
    clause,
):
    from fuxi.DLP import normalize_clause, extend_n3_rules, make_rule

    for hc in extend_n3_rules(network, normalize_clause(clause), construct_network):
        rule = make_rule(hc, network.ns_map)
        if rule.negative_stratus:
            negative_stratus.append(rule)
        if not rule.negative_stratus or not ignore_negative_stratus:
            ruleset.add(rule)


def normalize_disjunctions(
    disj,
    clause,
    ruleset,
    network,
    construct_network,
    negative_stratus,
    ignore_negative_stratus=False,
):
    """
    Removes disjunctions from logic programs (if possible)
    """
    from fuxi.DLP import breadth_first, breadth_first_replace

    #    disj = [i for i in breadth_first(clause.body) if isinstance(i,Or)]
    while len(disj) > 1:
        apply_demorgans(clause)
        if has_breadth_first_nested_conj(clause.body):
            flatten_conjunctions(clause.body)
        disj = [i for i in breadth_first(clause.body) if isinstance(i, Or)]
        assert len(disj) < 2, "Unable to effectively reduce disjunctions"
    if len(disj) == 1:
        # There is one disjunction in the body, we can reduce from:
        # H :- B1 V B2  to H : - B1 and H :- B2
        orig_disj = disj[0]
        for item in orig_disj:
            # First we want to replace the entire disjunct with an item within
            # it
            list(
                breadth_first_replace(
                    clause.body, candidate=orig_disj, replacement=item
                )
            )
            clause_clone = copy.deepcopy(clause)
            disj = [i for i in breadth_first(clause_clone.body) if isinstance(i, Or)]
            if len(disj) > 0:
                # If the formula has disjunctions of it's own, we handle them
                # recursively
                normalize_disjunctions(
                    disj,
                    clause_clone,
                    ruleset,
                    network,
                    construct_network,
                    negative_stratus,
                    ignore_negative_stratus,
                )
            else:
                if has_breadth_first_nested_conj(clause_clone.body):
                    flatten_conjunctions(clause_clone.body)
                # Otherwise handle normally
                handle_non_disjunctive_clauses(
                    ruleset,
                    network,
                    construct_network,
                    negative_stratus,
                    ignore_negative_stratus,
                    clause_clone,
                )
            # restore the replaced term (for the subsequent iteration)
            list(
                breadth_first_replace(
                    clause.body, candidate=item, replacement=orig_disj
                )
            )
    else:
        # The disjunction has been handled by normal form transformation, we just need to
        # handle normally
        clause_clone = copy.deepcopy(clause)
        if has_breadth_first_nested_conj(clause_clone.body):
            flatten_conjunctions(clause_clone.body)
        handle_non_disjunctive_clauses(
            ruleset,
            network,
            construct_network,
            negative_stratus,
            ignore_negative_stratus,
            clause,
        )


def test():
    import doctest

    doctest.testmod()


if __name__ == "__main__":
    test()
