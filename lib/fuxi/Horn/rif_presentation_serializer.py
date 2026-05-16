from __future__ import annotations

import logging
from typing import Any

from fuxi.Horn.HornRules import Clause, Rule, Ruleset
from fuxi.Horn.PositiveConditions import (
    And,
    Equal,
    Exists,
    ExternalFunction,
    Or,
    Uniterm,
)
from rdflib import RDF, Literal, URIRef, Variable

logger = logging.getLogger(__name__)

_NIL = URIRef("http://www.w3.org/2007/rif#nil")


class RIFPresentationSerializer:
    def __init__(self, ns_mapping: dict[str, URIRef] | None = None) -> None:
        self._ns_mapping: dict[str, URIRef] = dict(ns_mapping) if ns_mapping else {}
        self._prefixes: dict[str, str] = {}
        for prefix, uri in self._ns_mapping.items():
            self._prefixes[prefix] = str(uri)

    def serialize(self, ruleset: Ruleset) -> str:
        parts = ["Document("]
        for prefix, uri in self._prefixes.items():
            parts.append(f"  Prefix({prefix} <{uri}>)")
        if ruleset.ns_mapping:
            for prefix, uri in ruleset.ns_mapping.items():
                if prefix not in self._prefixes:
                    parts.append(f"  Prefix({prefix} <{uri}>)")
                    self._prefixes[prefix] = str(uri)
        parts.append("")
        parts.append("  Group(")
        for rule in ruleset.formulae:
            if isinstance(rule, Rule):
                parts.append(f"    {self._serialize_rule(rule)}")
            else:
                logger.warning("Skipping non-Rule formula: %s", type(rule))
        parts.append("  )")
        parts.append(")")
        return "\n".join(parts)

    def _serialize_rule(self, rule: Rule) -> str:
        clause_str = self._serialize_clause(rule.formula)
        if rule.declare:
            vars_str = " ".join(self._serialize_term(v) for v in rule.declare)
            return f"Forall {vars_str} ( {clause_str} )"
        return clause_str

    def _serialize_clause(self, clause: Clause) -> str:
        head_str = self._serialize_condition(clause.head)
        body_str = self._serialize_condition(clause.body)
        if isinstance(clause.body, And) and not clause.body.formulae:
            return head_str
        return f"{head_str} :- {body_str}"

    def _serialize_condition(self, cond: Any) -> str:
        handler = self._COND_SERIALIZERS.get(type(cond))
        if handler:
            return handler(self, cond)
        logger.warning("Unknown condition type: %s", type(cond))
        return str(cond)

    def _serialize_uniterm(self, ut: Uniterm) -> str:
        pred_str = self._serialize_term(ut.op)
        args = [self._serialize_term(a) for a in ut.arg]
        if ut.op == RDF.type:
            subject, obj = args
            return f"{subject} a {obj}"
        return f"{pred_str}({' '.join(args)})"

    def _serialize_external(self, ext: ExternalFunction) -> str:
        if hasattr(ext, "builtin") and ext.builtin is not None:
            inner = self._serialize_uniterm(ext.builtin)
        else:
            inner = self._serialize_uniterm(ext)
        return f"External( {inner} )"

    def _serialize_term(self, term: Any) -> str:
        handler = self._TERM_SERIALIZERS.get(type(term))
        if handler:
            return handler(self, term)
        if isinstance(term, list):
            items = [self._serialize_term(i) for i in term]
            return f"List( {' '.join(items)} )"
        return str(term)

    def _serialize_literal(self, lit: Literal) -> str:
        if lit.language:
            return f'"{lit}"@{lit.language}'
        if lit.datatype:
            dt_str = self._serialize_uri(URIRef(str(lit.datatype)))
            return f'"{lit}"^^{dt_str}'
        return f'"{lit}"'

    def _serialize_uri(self, uri: URIRef) -> str:
        uri_str = str(uri)
        for prefix, ns in sorted(self._prefixes.items(), key=lambda x: -len(x[1])):
            if uri_str.startswith(ns) and uri_str != ns:
                local = uri_str[len(ns) :]
                return f"{prefix}:{local}"
        return f"<{uri_str}>"

    @staticmethod
    def _ser_uniterm(self, cond: Uniterm) -> str:
        return self._serialize_uniterm(cond)

    @staticmethod
    def _ser_external(self, cond: ExternalFunction) -> str:
        return self._serialize_external(cond)

    @staticmethod
    def _ser_and(self, cond: And) -> str:
        if not cond.formulae:
            return ""
        if len(cond.formulae) == 1:
            return self._serialize_condition(cond.formulae[0])
        parts = [self._serialize_condition(f) for f in cond.formulae]
        return f"And( {' '.join(parts)} )"

    @staticmethod
    def _ser_or(self, cond: Or) -> str:
        parts = [self._serialize_condition(f) for f in cond.formulae]
        return f"Or( {' '.join(parts)} )"

    @staticmethod
    def _ser_exists(self, cond: Exists) -> str:
        vars_str = " ".join(self._serialize_term(v) for v in cond.declare)
        formula_str = self._serialize_condition(cond.formula)
        return f"Exists {vars_str} ( {formula_str} )"

    @staticmethod
    def _ser_equal(self, cond: Equal) -> str:
        return f"{self._serialize_term(cond.lhs)} = {self._serialize_term(cond.rhs)}"

    _COND_SERIALIZERS = {
        Uniterm: _ser_uniterm,
        ExternalFunction: _ser_external,
        And: _ser_and,
        Or: _ser_or,
        Exists: _ser_exists,
        Equal: _ser_equal,
    }

    _TERM_SERIALIZERS = {
        Variable: lambda s, t: f"?{t}",
        Literal: lambda s, t: s._serialize_literal(t),
        URIRef: lambda s, t: s._serialize_uri(t),
        Uniterm: lambda s, t: s._serialize_uniterm(t),
        ExternalFunction: lambda s, t: s._serialize_external(t),
    }
