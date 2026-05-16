from __future__ import annotations

from typing import Any

from fuxi.Horn.HornRules import Rule, Ruleset
from fuxi.Horn.PositiveConditions import (
    And,
    Condition,
    Exists,
    ExternalFunction,
    Or,
    SetOperator,
    Uniterm,
)
from rdflib import BNode, URIRef, Variable


class RIFValidationError(Exception):
    pass


class RIFValidator:
    def validate(self, ruleset: Ruleset) -> None:
        self._check_safeness(ruleset)

    def _check_safeness(self, ruleset: Ruleset) -> None:
        for rule in ruleset:
            if not rule.is_safe():
                raise RIFValidationError(f"Unsafe rule: {rule}")
            self._check_rule_consistency(rule)

    def _check_rule_consistency(self, rule: Rule) -> None:
        from fuxi.Rete.SidewaysInformationPassing import get_args, iter_condition

        head_vars = set(
            t for t in get_args(rule.formula.head) if isinstance(t, (Variable, BNode))
        )
        body_vars = set()
        for lit in iter_condition(rule.formula.body):
            for t in get_args(lit):
                if isinstance(t, (Variable, BNode)):
                    body_vars.add(t)
        if not head_vars.issubset(body_vars):
            unsafe = head_vars - body_vars
            raise RIFValidationError(f"Variables in head not bound in body: {unsafe}")

        self._check_no_bnodes_in_body(rule)

    def _check_no_bnodes_in_body(self, rule: Rule) -> None:
        from fuxi.Rete.SidewaysInformationPassing import get_args, iter_condition

        for lit in iter_condition(rule.formula.body):
            for t in get_args(lit):
                if isinstance(t, BNode):
                    raise RIFValidationError(f"Blank node in rule body: {t} in {rule}")

    def _check_single_context(self, ruleset: Ruleset) -> None:
        op_usage: dict[URIRef, set[str]] = {}

        def _record_usage(op: Any, ctx: str) -> None:
            if isinstance(op, URIRef):
                usages = op_usage.setdefault(op, set())
                usages.add(ctx)

        def _walk_term(term: Any) -> None:
            if isinstance(term, Uniterm):
                _record_usage(term.op, "predicate")
            elif isinstance(term, ExternalFunction):
                _record_usage(term.op, "external_predicate")

        for rule in ruleset:
            if isinstance(rule.formula.body, SetOperator):
                for f in rule.formula.body:
                    _walk_term(f)
            else:
                _walk_term(rule.formula.body)
            _walk_term(rule.formula.head)
            for v in rule.declare:
                pass

        for op, contexts in op_usage.items():
            if len(contexts) > 1:
                raise RIFValidationError(
                    f"Symbol {op} used in multiple contexts: {contexts}"
                )

    def _check_builtin_schemas(self, ruleset: Ruleset) -> None:
        for rule in ruleset:
            self._walk_for_builtins(rule.formula.body)
            self._walk_for_builtins(rule.formula.head)

    def _walk_for_builtins(self, condition: Condition) -> None:
        if isinstance(condition, Uniterm):
            pass
        elif isinstance(condition, ExternalFunction):
            verifiable_builtins = {
                URIRef("http://www.w3.org/2007/rif-builtin-predicate#numeric-add"),
            }
            if condition.op in verifiable_builtins and len(condition.arg) != 3:
                raise RIFValidationError(
                    f"Builtin {condition.op} expects specific arity"
                )
        elif isinstance(condition, And):
            for f in condition:
                self._walk_for_builtins(f)
        elif isinstance(condition, Or):
            for f in condition:
                self._walk_for_builtins(f)
        elif isinstance(condition, Exists):
            self._walk_for_builtins(condition.formula)
