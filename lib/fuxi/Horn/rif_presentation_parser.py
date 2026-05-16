from __future__ import annotations

import os
from typing import Any

from lark import Lark, Token, Transformer, v_args

from fuxi.Horn.HornRules import Clause, Rule, Ruleset
from fuxi.Horn.PositiveConditions import (
    And,
    Equal,
    Exists,
    ExternalFunction,
    Or,
    Uniterm,
)
from rdflib import RDF, RDFS, Literal, Namespace, URIRef, Variable

RIF_NS = Namespace("http://www.w3.org/2007/rif#")
XSD_NS = Namespace("http://www.w3.org/2001/XMLSchema#")

_GRAMMAR_PATH = os.path.join(os.path.dirname(__file__), "rif_grammar.lark")


class RIFTransformer(Transformer):
    def __init__(self, ns_mapping: dict[str, URIRef] | None = None) -> None:
        super().__init__()
        self._ns_mapping = dict(ns_mapping) if ns_mapping else {}
        self._prefixes: dict[str, URIRef] = {}

    def _resolve_curie(self, curie: str) -> URIRef:
        prefix, local = curie.split(":", 1)
        ns = self._prefixes.get(prefix) or self._ns_mapping.get(prefix)
        if ns is None:
            raise ValueError(f"Unknown prefix: {prefix}")
        return URIRef(str(ns) + local)

    def _make_const(self, token: Token | str) -> URIRef | Literal:
        value = str(token) if isinstance(token, Token) else token
        if ":" in value and not value.startswith("?"):
            prefix, _ = value.split(":", 1)
            if prefix in self._prefixes or prefix in self._ns_mapping:
                return self._resolve_curie(value)
        if value.startswith("<") and value.endswith(">"):
            return URIRef(value[1:-1])
        # short form: bare name treated as IRI reference (rif:local)
        return URIRef(RIF_NS[value])

    # --- Document ---
    @v_args(inline=True)
    def document(self, *children: Any) -> Ruleset:
        rules: list[Rule] = []
        ns_binds: dict[str, URIRef] = {}
        for child in children:
            if isinstance(child, tuple) and child[0] == "prefix":
                _, prefix, uri = child
                ns_binds[prefix] = uri
                self._prefixes[prefix] = uri
            elif isinstance(child, Ruleset):
                rules.extend(child.formulae)
            elif isinstance(child, Rule):
                rules.append(child)
            elif isinstance(child, list):
                for item in child:
                    if isinstance(item, Rule):
                        rules.append(item)
        merged = dict(self._ns_mapping)
        merged.update(ns_binds)
        return Ruleset(formulae=rules, ns_mapping=merged)

    @v_args(inline=True)
    def base(self, iri: Token) -> tuple:
        return ("base", str(iri))

    @v_args(inline=True)
    def prefix(self, pname: Token, iri: Token) -> tuple:
        return ("prefix", str(pname), URIRef(str(iri)[1:-1]))

    @v_args(inline=True)
    def import_(self, *children: Any) -> tuple:
        return ("import",)

    @v_args(inline=True)
    def group(self, *children: Any) -> list[Rule]:
        rules: list[Rule] = []
        for child in children:
            if isinstance(child, Rule):
                rules.append(child)
            elif isinstance(child, list):
                rules.extend(child)
        return rules

    # --- Rules ---
    @v_args(inline=True)
    def rule(self, *children: Any) -> Rule:
        clause_children = [
            c for c in children if isinstance(c, (Clause, list, And, Uniterm))
        ]  # noqa: E501
        if not clause_children:
            raise ValueError("rule without clause")
        clause = clause_children[0]
        if isinstance(clause, list):
            clause = clause[0]
        if isinstance(clause, Uniterm):
            clause = Clause(And([]), clause)
        all_vars: list[Variable] = []
        for c in children:
            if isinstance(c, Variable):
                all_vars.append(c)
        return Rule(clause, declare=all_vars, ns_mapping=self._prefixes)

    @v_args(inline=True)
    def clause(self, *children: Any) -> Clause | Uniterm:
        for c in children:
            if isinstance(c, Clause):
                return c
            if isinstance(c, Uniterm):
                return c
            if isinstance(c, And):
                return c
        if children:
            return children[0]
        raise ValueError("empty clause")

    @v_args(inline=True)
    def implies(self, head: Any, body: Any) -> Clause:
        if isinstance(head, list):
            head = head[0]
        if isinstance(body, list):
            body = body[0]
        if not isinstance(head, (Uniterm, And)):
            hl = []
            for c in head if isinstance(head, list) else [head]:
                if isinstance(c, (Uniterm, And)):
                    hl.append(c)
            head = hl[0] if len(hl) == 1 else And(hl)
        if not isinstance(body, (And, Or, Exists, Uniterm, Equal)):
            if isinstance(body, list):
                body = body[0]
        b = body if isinstance(body, (And, Or, Exists, Uniterm, Equal)) else And([body])
        return Clause(b, head)

    # --- Formulas ---
    @v_args(inline=True)
    def and_formula(self, *children: Any) -> And:
        formulae = [
            c for c in children if isinstance(c, (Uniterm, And, Or, Exists, Equal))
        ]  # noqa: E501
        return And(formulae)

    @v_args(inline=True)
    def or_formula(self, *children: Any) -> Or:
        formulae = [
            c for c in children if isinstance(c, (Uniterm, And, Or, Exists, Equal))
        ]  # noqa: E501
        return Or(formulae)

    @v_args(inline=True)
    def exists_formula(self, *children: Any) -> Exists:
        vars_list: list[Variable] = []
        formula = None
        for c in children:
            if isinstance(c, Variable):
                vars_list.append(c)
            elif isinstance(c, (And, Or, Exists, Uniterm, Equal)):
                formula = c
        if formula is None:
            raise ValueError("Exists without formula")
        return Exists(formula=formula, declare=vars_list)

    # --- Atomic ---
    @v_args(inline=True)
    def atomic(self, *children: Any) -> Uniterm | Equal:
        for c in children:
            if isinstance(c, (Uniterm, Equal)):
                return c
        raise ValueError("empty atomic")

    @v_args(inline=True)
    def atom(self, uniterm: Uniterm) -> Uniterm:
        return uniterm

    @v_args(inline=True)
    def uniterm(self, op: URIRef | Literal, *args: Any) -> Uniterm:
        arg_list: list = []
        for a in args:
            if isinstance(a, list):
                arg_list.extend(a)
            elif a is not None:
                arg_list.append(a)
        return Uniterm(op, arg_list, new_nss=list(self._prefixes.items()))

    @v_args(inline=True)
    def equal(self, left: Any, right: Any) -> Equal:
        return Equal(left, right)

    @v_args(inline=True)
    def member(self, instance: Any, cls: Any) -> Uniterm:
        return Uniterm(RDF.type, [instance, cls])

    @v_args(inline=True)
    def subclass(self, sub: Any, sup: Any) -> Uniterm:
        return Uniterm(RDFS.subClassOf, [sub, sup])

    @v_args(inline=True)
    def frame(self, obj: Any, *slots: Any) -> list[Uniterm]:
        terms: list[Uniterm] = []
        if not slots:
            pass
        elif isinstance(slots[0], list):
            for key, val in slots[0]:
                terms.append(Uniterm(key, [obj, val]))
        else:
            for key, val in slots:
                terms.append(Uniterm(key, [obj, val]))
        if len(terms) == 1:
            return terms[0]
        return terms

    @v_args(inline=True)
    def slot(self, key: Any, val: Any) -> tuple:
        return (key, val)

    # --- Terms ---
    @v_args(inline=True)
    def term(self, *children: Any) -> Any:
        for c in children:
            if c is not None:
                return c
        return None

    @v_args(inline=True)
    def expr(self, uniterm: Uniterm) -> Uniterm:
        return uniterm

    @v_args(inline=True)
    def list_(self, *terms: Any) -> list:
        head_terms: list = []
        for t in terms:
            if isinstance(t, list):
                head_terms.extend(t)
            elif t is not None:
                head_terms.append(t)
        return head_terms

    @v_args(inline=True)
    def typed_const(self, value: Token, symspace: Token | str) -> URIRef | Literal:
        v = str(value)[1:-1]  # strip quotes
        ss = str(symspace)
        if ss.startswith("<") and ss.endswith(">"):
            datatype = URIRef(ss[1:-1])
        elif ":" in ss:
            datatype = self._resolve_curie(ss)
        else:
            datatype = URIRef(ss)
        if datatype == RIF_NS.iri or datatype == URIRef(
            "http://www.w3.org/2007/rif#iri"
        ):
            return URIRef(v)
        return Literal(v, datatype=datatype)

    @v_args(inline=True)
    def lang_const(self, value: Token, lang: Token) -> Literal:
        v = str(value)[1:-1]
        return Literal(v, lang=str(lang))

    @v_args(inline=True)
    def iri_const(self, iri: Token) -> URIRef:
        return URIRef(str(iri)[1:-1])

    @v_args(inline=True)
    def curie_const(self, curie: Token) -> URIRef:
        return self._resolve_curie(str(curie))

    @v_args(inline=True)
    def short_const(self, name: Token) -> URIRef:
        val = str(name)
        if val in ("true", "false"):
            return Literal(val, datatype=XSD_NS.boolean)
        return URIRef(RIF_NS[val])

    @v_args(inline=True)
    def numeric_const(self, num: Token) -> Literal:
        val = str(num)
        if "." in val:
            return Literal(val, datatype=XSD_NS.decimal)
        return Literal(val, datatype=XSD_NS.integer)

    # --- Variables ---
    @v_args(inline=True)
    def var(self, name: Token) -> Variable:
        return Variable(str(name))

    # --- External ---
    @v_args(inline=True)
    def external_atom(self, atom: Uniterm) -> ExternalFunction:
        return ExternalFunction(atom)

    @v_args(inline=True)
    def external_expr(self, expr: Uniterm) -> ExternalFunction:
        return ExternalFunction(expr)

    # --- Named args ---
    @v_args(inline=True)
    def named_arg(self, name: Token, value: Any) -> tuple:
        return (str(name), value)

    # --- Symbol space ---
    @v_args(inline=True)
    def symspace(self, *children: Any) -> str:
        for c in children:
            return str(c) if isinstance(c, Token) else c
        return ""

    # --- Annotations ---
    @v_args(inline=True)
    def irimeta(self, *children: Any) -> None:
        return None

    @v_args(inline=True)
    def iriconst(self, const: Any) -> Any:
        return const

    @v_args(inline=True)
    def frame_ann(self, *children: Any) -> None:
        return None


class RIFPresentationParser:
    def __init__(self, grammar_path: str | None = None) -> None:
        gpath = grammar_path or _GRAMMAR_PATH
        with open(gpath) as f:
            grammar = f.read()
        self._parser = Lark(
            grammar,
            parser="earley",
            start="document",
            maybe_placeholders=False,
        )

    def parse(self, text: str, ns_mapping: dict[str, URIRef] | None = None) -> Ruleset:
        tree = self._parser.parse(text)
        transformer = RIFTransformer(ns_mapping=ns_mapping)
        result = transformer.transform(tree)
        if isinstance(result, list) and result and isinstance(result[0], Rule):
            return Ruleset(formulae=result)
        return result if isinstance(result, Ruleset) else Ruleset(formulae=[])
