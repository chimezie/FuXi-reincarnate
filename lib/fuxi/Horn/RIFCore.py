from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from lxml import etree

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

logger = logging.getLogger(__name__)

RIF_NS = Namespace("http://www.w3.org/2007/rif#")
XSD_NS = Namespace("http://www.w3.org/2001/XMLSchema#")

_RIF_XML_NS = "http://www.w3.org/2007/rif#"
_XSD = "http://www.w3.org/2001/XMLSchema#"

_NIL = URIRef("http://www.w3.org/2007/rif#nil")
_EQ_PRED = URIRef("http://www.w3.org/2007/rif#Equal")
_TRIVIAL = URIRef("http://www.w3.org/2007/rif#trivial")

_WRAPPER_TAGS = frozenset(
    {
        f"{{{_RIF_XML_NS}}}object",
        f"{{{_RIF_XML_NS}}}op",
        f"{{{_RIF_XML_NS}}}arg",
        f"{{{_RIF_XML_NS}}}left",
        f"{{{_RIF_XML_NS}}}right",
        f"{{{_RIF_XML_NS}}}instance",
        f"{{{_RIF_XML_NS}}}class",
        f"{{{_RIF_XML_NS}}}sub",
        f"{{{_RIF_XML_NS}}}super",
    }
)


def _rif_tag(tag: str) -> str:
    return f"{{{_RIF_XML_NS}}}{tag}"


def _make_term(element: Any, ns_mapping: dict[str, URIRef] | None = None) -> Any:
    tag = element.tag
    handler = _TERM_HANDLERS.get(tag)
    if handler:
        return handler(element, ns_mapping)
    if tag in _WRAPPER_TAGS:
        for child in element:
            return _make_term(child, ns_mapping)
    if element.text:
        text = element.text.strip()
        if text.startswith("?"):
            return Variable(text[1:])
    return None


def _term_var(elem: Any, ns_mapping: dict | None = None) -> Variable:
    return Variable(str(elem.text).strip())


def _term_const(elem: Any, ns_mapping: dict | None = None) -> URIRef | Literal:
    return _make_const(elem)


def _term_external(
    elem: Any, ns_mapping: dict | None = None
) -> ExternalFunction | None:
    content = elem.find(_rif_tag("content"))
    if content is not None:
        inner = content[0] if len(content) > 0 else None
        if inner is not None:
            if inner.tag in (_rif_tag("Atom"), _rif_tag("Expr")):
                ut = _make_uniterm(inner, ns_mapping)
                if ut is not None:
                    return ExternalFunction(
                        ut, new_nss=list((ns_mapping or {}).items())
                    )
    return None


def _term_list(elem: Any, ns_mapping: dict | None = None) -> list:
    return _collect_args(elem, ns_mapping)


def _term_expr(elem: Any, ns_mapping: dict | None = None) -> Uniterm | None:
    return _make_uniterm(elem, ns_mapping)


_TERM_HANDLERS = {
    _rif_tag("Var"): _term_var,
    _rif_tag("Const"): _term_const,
    _rif_tag("External"): _term_external,
    _rif_tag("List"): _term_list,
    _rif_tag("Expr"): _term_expr,
}


def _make_const(element: Any) -> URIRef | Literal:
    const_type = element.get("type", "")
    text = str(element.text or "").strip()
    if const_type == f"{_RIF_XML_NS}iri":
        return URIRef(text)
    if const_type.startswith(_XSD):
        dt = URIRef(const_type)
        return Literal(text, datatype=dt)
    if const_type == "http://www.w3.org/1999/02/22-rdf-syntax-ns#PlainLiteral":
        return Literal(text, datatype=RDF.PlainLiteral)
    return Literal(text)


def _ensure_binary_args(args: list) -> list:
    if len(args) >= 2:
        return args[:2]
    if len(args) == 1:
        return [args[0], args[0]]
    return [_NIL, _NIL]


def _make_uniterm(
    atom_elem: Any, ns_mapping: dict[str, URIRef] | None = None
) -> Uniterm | None:
    op_elem = atom_elem.find(_rif_tag("op"))
    if op_elem is None:
        return None
    op = _make_term(op_elem, ns_mapping)
    if op is None:
        return None
    args = _ensure_binary_args(_collect_args(atom_elem, ns_mapping))
    return Uniterm(op, args, new_nss=list((ns_mapping or {}).items()))


def _collect_args(parent: Any, ns_mapping: dict[str, URIRef] | None = None) -> list:
    args_elem = parent.find(_rif_tag("args"))
    if args_elem is not None:
        return [_make_term(child, ns_mapping) for child in args_elem]
    args = []
    for child in parent:
        if child.tag == _rif_tag("arg"):
            term = _make_term(child, ns_mapping)
            if term is not None:
                args.append(term)
    return args


def _parse_sentence(
    sentence: Any, ns_mapping: dict[str, URIRef] | None = None
) -> Rule | Any | list:
    if sentence.tag == _rif_tag("sentence"):
        for child in sentence:
            return _parse_sentence(child, ns_mapping)
        return []
    handler = _SENTENCE_HANDLERS.get(sentence.tag)
    if handler:
        return handler(sentence, ns_mapping)
    return []


def _sent_forall(elem: Any, ns_mapping: dict | None = None) -> Rule:
    return _parse_forall(elem, ns_mapping)


def _sent_implies(elem: Any, ns_mapping: dict | None = None) -> Rule:
    return _parse_implies(elem, ns_mapping)


def _sent_atom(elem: Any, ns_mapping: dict | None = None) -> Uniterm | list:
    ut = _make_uniterm(elem, ns_mapping)
    return ut if ut is not None else []


def _sent_member(elem: Any, ns_mapping: dict | None = None) -> Uniterm:
    instance = _make_term(elem.find(_rif_tag("instance")), ns_mapping)
    cls = _make_term(elem.find(_rif_tag("class")), ns_mapping)
    return Uniterm(RDF.type, [instance, cls])


def _sent_subclass(elem: Any, ns_mapping: dict | None = None) -> Uniterm:
    sub = _make_term(elem.find(_rif_tag("sub")), ns_mapping)
    sup = _make_term(elem.find(_rif_tag("super")), ns_mapping)
    return Uniterm(RDFS.subClassOf, [sub, sup])


def _sent_external(elem: Any, ns_mapping: dict | None = None) -> Any:
    return _make_term(elem, ns_mapping)


def _sent_frame(elem: Any, ns_mapping: dict | None = None) -> Uniterm | list:
    obj = _make_term(elem.find(_rif_tag("object")), ns_mapping)
    terms = []
    for slot in elem.findall(_rif_tag("slot")):
        slot_children = list(slot)
        if len(slot_children) >= 2:
            key = _make_term(slot_children[0], ns_mapping)
            val = _make_term(slot_children[1], ns_mapping)
            terms.append(Uniterm(key, [obj, val]))
    if terms:
        return terms[0]
    return []


_SENTENCE_HANDLERS = {
    _rif_tag("Forall"): _sent_forall,
    _rif_tag("Implies"): _sent_implies,
    _rif_tag("Atom"): _sent_atom,
    _rif_tag("Member"): _sent_member,
    _rif_tag("Equal"): lambda e, n: _parse_equal(e, n),
    _rif_tag("Subclass"): _sent_subclass,
    _rif_tag("External"): _sent_external,
    _rif_tag("Frame"): _sent_frame,
}


def _parse_set_operator(
    container: Any, cls: type, ns_mapping: dict | None = None
) -> And | Or:
    formulae = []
    for child in container.findall(_rif_tag("formula")):
        sub = _parse_formula(child, ns_mapping)
        if isinstance(sub, list):
            formulae.extend(sub)
        elif sub is not None:
            formulae.append(sub)
    return cls(formulae)


def _parse_forall(
    forall_elem: Any, ns_mapping: dict[str, URIRef] | None = None
) -> Rule:
    declare_vars: list[Variable] = []
    for declare in forall_elem.findall(_rif_tag("declare")):
        for var_elem in declare:
            if var_elem.tag == _rif_tag("Var"):
                declare_vars.append(Variable(str(var_elem.text or "").strip()))
    formula_wrapper = forall_elem.find(_rif_tag("formula"))
    if formula_wrapper is not None:
        for child in formula_wrapper:
            if child.tag == _rif_tag("Implies"):
                clause = _parse_implies_clause(child, ns_mapping)
                if clause is not None:
                    return Rule(clause, declare=declare_vars, ns_mapping=ns_mapping)
            elif child.tag == _rif_tag("Atom"):
                ut = _make_uniterm(child, ns_mapping)
                if ut is not None:
                    return Rule(
                        Clause(And([]), ut), declare=declare_vars, ns_mapping=ns_mapping
                    )
            elif child.tag == _rif_tag("Frame"):
                obj = _make_term(child.find(_rif_tag("object")), ns_mapping)
                terms = [
                    _extract_slot(slot, obj, ns_mapping)
                    for slot in child.findall(_rif_tag("slot"))
                ]
                if terms:
                    return Rule(
                        Clause(And([]), terms[0]),
                        declare=declare_vars,
                        ns_mapping=ns_mapping,
                    )
    fallback = Uniterm(_TRIVIAL, [Variable("x"), Variable("x")])
    return Rule(Clause(And([]), fallback), declare=declare_vars, ns_mapping=ns_mapping)


def _parse_implies(
    implies_elem: Any, ns_mapping: dict[str, URIRef] | None = None
) -> Rule:
    clause = _parse_implies_clause(implies_elem, ns_mapping)
    if clause is not None:
        return Rule(clause, declare=[], ns_mapping=ns_mapping)
    fallback = Uniterm(_TRIVIAL, [Variable("x"), Variable("x")])
    return Rule(Clause(And([]), fallback), declare=[])


def _parse_implies_clause(
    parent: Any, ns_mapping: dict[str, URIRef] | None = None
) -> Clause | None:
    if_elem = parent.find(_rif_tag("if"))
    then_elem = parent.find(_rif_tag("then"))
    if then_elem is None:
        return None
    head = _parse_formula(then_elem, ns_mapping)
    body = And([])
    if if_elem is not None:
        body = _parse_formula(if_elem, ns_mapping)
        body = _normalize_to_condition(body)
    head = _normalize_to_condition(head, is_head=True)
    return Clause(body, head)


def _normalize_to_condition(val: Any, is_head: bool = False) -> Any:
    if isinstance(val, (And, Or, Exists, Uniterm, Equal, ExternalFunction)):
        return val
    if isinstance(val, list):
        flat = []
        for item in val:
            sub = _normalize_to_condition(item, is_head)
            if isinstance(sub, list):
                flat.extend(sub)
            elif sub is not None:
                flat.append(sub)
        if not flat:
            return And([])
        if len(flat) == 1:
            return flat[0]
        return And(flat)
    if val is None:
        return And([])
    return And([])


def _parse_formula(elem: Any, ns_mapping: dict[str, URIRef] | None = None) -> Any:
    for child in elem:
        tag = child.tag
        handler = _FORMULA_HANDLERS.get(tag)
        if handler:
            result = handler(child, ns_mapping)
            if result is not None:
                return result
    return And([])


def _formula_and(elem: Any, ns_mapping: dict | None = None) -> And:
    return _parse_set_operator(elem, And, ns_mapping)


def _formula_or(elem: Any, ns_mapping: dict | None = None) -> Or:
    return _parse_set_operator(elem, Or, ns_mapping)


def _formula_atom(elem: Any, ns_mapping: dict | None = None) -> Uniterm | None:
    return _make_uniterm(elem, ns_mapping)


def _formula_frame(elem: Any, ns_mapping: dict | None = None) -> Uniterm | list:
    obj = _make_term(elem.find(_rif_tag("object")), ns_mapping)
    terms = []
    for slot in elem.findall(_rif_tag("slot")):
        children_s = list(slot)
        if len(children_s) >= 2:
            key = _make_term(children_s[0], ns_mapping)
            val = _make_term(children_s[1], ns_mapping)
            terms.append(Uniterm(key, [obj, val]))
    return terms if len(terms) != 1 else terms[0]


def _formula_member(elem: Any, ns_mapping: dict | None = None) -> Uniterm:
    instance = _make_term(elem.find(_rif_tag("instance")), ns_mapping)
    cls = _make_term(elem.find(_rif_tag("class")), ns_mapping)
    return Uniterm(RDF.type, [instance, cls])


def _formula_subclass(elem: Any, ns_mapping: dict | None = None) -> Uniterm:
    sub = _make_term(elem.find(_rif_tag("sub")), ns_mapping)
    sup = _make_term(elem.find(_rif_tag("super")), ns_mapping)
    return Uniterm(RDFS.subClassOf, [sub, sup])


def _formula_equal(elem: Any, ns_mapping: dict | None = None) -> Uniterm:
    return _parse_equal(elem, ns_mapping)


def _formula_external(elem: Any, ns_mapping: dict | None = None) -> Any:
    return _make_term(elem, ns_mapping)


def _formula_expr(elem: Any, ns_mapping: dict | None = None) -> Uniterm | None:
    return _make_uniterm(elem, ns_mapping)


_FORMULA_HANDLERS = {
    _rif_tag("And"): _formula_and,
    _rif_tag("Or"): _formula_or,
    _rif_tag("Atom"): _formula_atom,
    _rif_tag("Frame"): _formula_frame,
    _rif_tag("Member"): _formula_member,
    _rif_tag("Equal"): _formula_equal,
    _rif_tag("Subclass"): _formula_subclass,
    _rif_tag("External"): _formula_external,
    _rif_tag("Expr"): _formula_expr,
}


def _extract_slot(
    slot: Any, obj: Any, ns_mapping: dict[str, URIRef] | None = None
) -> Uniterm:
    slot_children = list(slot)
    if len(slot_children) >= 2:
        key = _make_term(slot_children[0], ns_mapping)
        val = _make_term(slot_children[1], ns_mapping)
        return Uniterm(key, [obj, val], new_nss=list((ns_mapping or {}).items()))
    return Uniterm(URIRef(""), [obj, obj], new_nss=list((ns_mapping or {}).items()))


def _parse_equal(elem: Any, ns_mapping: dict[str, URIRef] | None = None) -> Uniterm:
    left = _make_term(elem.find(_rif_tag("left")), ns_mapping)
    right = _make_term(elem.find(_rif_tag("right")), ns_mapping)
    if left is None:
        left = URIRef("")
    if right is None:
        right = URIRef("")
    return Uniterm(_EQ_PRED, [left, right])


def _collect_rules(
    parent: Any, ns_mapping: dict[str, URIRef] | None = None
) -> list[Rule]:
    rules: list[Rule] = []
    for child in parent:
        if child.tag == _rif_tag("Group"):
            rules.extend(_collect_rules(child, ns_mapping))
        elif child.tag == _rif_tag("sentence"):
            result = _parse_sentence(child, ns_mapping)
            rules.extend(_ensure_rules(result))
        else:
            result = _parse_sentence(child, ns_mapping)
            rules.extend(_ensure_rules(result))
    return rules


def _ensure_rules(result: Any) -> list[Rule]:
    rules: list[Rule] = []
    if isinstance(result, Rule):
        rules.append(result)
    elif isinstance(result, list):
        for item in result:
            rules.extend(_ensure_rules(item))
    elif isinstance(result, (Uniterm, And, Equal, ExternalFunction)):
        rules.append(Rule(Clause(And([]), result), declare=[]))
    return rules


class RIFXMLParser:
    def __init__(self, ns_mapping: dict[str, URIRef] | None = None) -> None:
        self._ns_mapping = dict(ns_mapping) if ns_mapping else {}

    def parse(self, source: str | Path | bytes) -> Ruleset:
        if isinstance(source, (str, Path)):
            root = etree.parse(str(source)).getroot()
        else:
            root = etree.fromstring(source)
        rules = self._parse_root(root)
        return Ruleset(formulae=rules, ns_mapping=self._ns_mapping)

    def parse_string(self, text: str | bytes) -> Ruleset:
        if isinstance(text, str):
            text = text.encode("utf-8")
        return self.parse(text)

    def _parse_root(self, root: Any) -> list[Rule]:
        tag = root.tag
        if tag == _rif_tag("Document"):
            payload = root.find(_rif_tag("payload"))
            if payload is not None:
                return _collect_rules(payload, self._ns_mapping)
            return _collect_rules(root, self._ns_mapping)
        return _collect_rules(root, self._ns_mapping)


class RIFParser:
    FORMAT_XML = "xml"
    FORMAT_PS = "ps"
    FORMAT_AUTO = "auto"

    def __init__(self, ns_mapping: dict[str, URIRef] | None = None) -> None:
        self._ns_mapping = dict(ns_mapping) if ns_mapping else {}
        self._xml_parser = RIFXMLParser(ns_mapping=ns_mapping)
        self._ps_parser = None

    @property
    def _ps_parser_instance(self):
        if self._ps_parser is None:
            from fuxi.Horn.rif_presentation_parser import RIFPresentationParser

            self._ps_parser = RIFPresentationParser()
        return self._ps_parser

    def parse(self, source: str | bytes, format: str = FORMAT_AUTO) -> Ruleset:
        resolved = self._resolve_format(source, format)
        if resolved == self.FORMAT_XML:
            return self._xml_parser.parse_string(
                source if isinstance(source, (str, bytes)) else source
            )
        if resolved == self.FORMAT_PS:
            text = source.decode("utf-8") if isinstance(source, bytes) else source
            return self._ps_parser_instance.parse(text, ns_mapping=self._ns_mapping)
        msg = "Unable to detect RIF format from input"
        raise ValueError(msg)

    def parse_file(self, path: str | Path, format: str = FORMAT_AUTO) -> Ruleset:
        source = Path(path).read_bytes()
        return self.parse(source, format=format)

    @staticmethod
    def _resolve_format(source: str | bytes, hint: str) -> str:
        if hint != RIFParser.FORMAT_AUTO:
            return hint
        if isinstance(source, bytes):
            sample = source[:1024].decode("utf-8", errors="replace")
        else:
            sample = source[:1024]
        stripped = sample.strip()
        if stripped.startswith("<?xml") or stripped.startswith("<"):
            return RIFParser.FORMAT_XML
        return RIFParser.FORMAT_PS

    @staticmethod
    def parse_xml(
        source: str | Path | bytes, ns_mapping: dict[str, URIRef] | None = None
    ) -> Ruleset:
        parser = RIFXMLParser(ns_mapping=ns_mapping)
        return parser.parse(source)

    @staticmethod
    def parse_ps(text: str, ns_mapping: dict[str, URIRef] | None = None) -> Ruleset:
        from fuxi.Horn.rif_presentation_parser import RIFPresentationParser

        parser = RIFPresentationParser()
        return parser.parse(text, ns_mapping=ns_mapping)


class RIFCoreParser:
    def __init__(
        self,
        location: str | None = None,
        graph: Any = None,
        debug: bool = False,
    ) -> None:
        self.location = location
        if debug:
            logging.basicConfig(level=logging.DEBUG, format="%(message)s")
        self._rules = []
        if location is not None:
            self._rules = self._load_from_location(location)
        elif graph is not None:
            self._rules = self._legacy_from_graph(graph)

    @staticmethod
    def _load_from_location(location: str) -> list[Rule]:
        from urllib import request

        if location.startswith(("http://", "https://")):
            req = request.Request(location)
            with request.urlopen(req) as f:
                content = f.read()
        else:
            content = Path(location).read_bytes()
        return RIFParser.parse_xml(content).formulae

    @staticmethod
    def from_url(url: str, debug: bool = False) -> RIFCoreParser:
        parser = RIFCoreParser.__new__(RIFCoreParser)
        parser.location = url
        parser._rules = parser._load_from_location(url)
        return parser

    def _legacy_from_graph(self, graph: Any) -> list[Rule]:
        rules: list[Rule] = []
        for s, p, o in graph.triples((None, RDF.type, RIF_NS.Implies)):
            impl = s
            body = graph.value(impl, RIF_NS.if_)
            head = graph.value(impl, RIF_NS.then)
            if body is not None and head is not None:
                rules.append(Rule(Clause(And([]), URIRef("")), declare=[]))
        return rules

    def get_ruleset(self) -> list[Rule]:
        return self.getRuleset()

    def getRuleset(self) -> list[Rule]:  # noqa: N802
        return self._rules

    def extract_imp(self, impl: Any) -> Rule:
        return Rule(Clause(And([]), Uniterm(RIF_NS.trivial, [])), declare=[])

    def extract_rule(self, rule: Any) -> Rule:
        return Rule(Clause(And([]), Uniterm(RIF_NS.trivial, [])), declare=[])
