from __future__ import annotations

import logging
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
from rdflib import Literal, Namespace, URIRef, Variable

logger = logging.getLogger(__name__)

_RIF_XML_NS = "http://www.w3.org/2007/rif#"
_XSD_NS = "http://www.w3.org/2001/XMLSchema#"

_RIF = Namespace(_RIF_XML_NS)
_XSD = Namespace(_XSD_NS)

_EQ_PRED = URIRef("http://www.w3.org/2007/rif#Equal")
_NIL = URIRef("http://www.w3.org/2007/rif#nil")


def _ns(tag: str) -> str:
    return f"{{{_RIF_XML_NS}}}{tag}"


def _build_const(value: Any, parent: etree.Element) -> etree.Element:
    if isinstance(value, URIRef):
        const = etree.SubElement(parent, _ns("Const"), type=f"{_RIF_XML_NS}iri")
        const.text = str(value)
        return const
    if isinstance(value, Literal):
        dt = value.datatype
        const = etree.SubElement(parent, _ns("Const"), type=str(dt) if dt else "")
        const.text = str(value)
        return const
    if isinstance(value, Variable):
        var = etree.SubElement(parent, _ns("Var"))
        var.text = str(value)
        return var
    raise ValueError(f"Unknown term type: {type(value)}: {value}")


def _build_term(value: Any, parent: etree.Element) -> etree.Element:
    if isinstance(value, (URIRef, Literal, Variable)):
        return _build_const(value, parent)
    if isinstance(value, Uniterm):
        return _build_uniterm(value, parent)
    if isinstance(value, ExternalFunction):
        return _build_external(value, parent)
    if isinstance(value, list):
        return _build_list(value, parent)
    raise ValueError(f"Unknown term type: {type(value)}: {value}")


def _build_uniterm(ut: Uniterm, parent: etree.Element) -> etree.Element:
    atom = etree.SubElement(parent, _ns("Atom"))
    op = etree.SubElement(atom, _ns("op"))
    _build_const(ut.op, op)
    for arg in ut.arg:
        arg_elem = etree.SubElement(atom, _ns("arg"))
        _build_term(arg, arg_elem)
    return atom


def _build_external(ext: ExternalFunction, parent: etree.Element) -> etree.Element:
    external = etree.SubElement(parent, _ns("External"))
    content = etree.SubElement(external, _ns("content"))
    if hasattr(ext, "builtin") and ext.builtin is not None:
        _build_uniterm(ext.builtin, content)
    else:
        _build_uniterm(ext, content)
    return external


def _build_list(items: list, parent: etree.Element) -> etree.Element:
    list_elem = etree.SubElement(parent, _ns("List"))
    for item in items:
        item_elem = etree.SubElement(list_elem, _ns("arg"))
        _build_term(item, item_elem)
    return list_elem


def _build_frame(obj: Any, slots: list[tuple], parent: etree.Element) -> etree.Element:
    frame = etree.SubElement(parent, _ns("Frame"))
    obj_elem = etree.SubElement(frame, _ns("object"))
    _build_term(obj, obj_elem)
    for key, val in slots:
        slot = etree.SubElement(frame, _ns("slot"), ordered="yes")
        _build_term(key, slot)
        _build_term(val, slot)
    return frame


def _build_equal(lhs: Any, rhs: Any, parent: etree.Element) -> etree.Element:
    equal = etree.SubElement(parent, _ns("Equal"))
    left = etree.SubElement(equal, _ns("left"))
    _build_term(lhs, left)
    right = etree.SubElement(equal, _ns("right"))
    _build_term(rhs, right)
    return equal


def _build_condition(cond: Any, parent: etree.Element) -> None:
    handler = _BUILD_COND_HANDLERS.get(type(cond))
    if handler:
        handler(cond, parent)
    else:
        logger.warning("Unknown condition type: %s", type(cond))


def _build_and(cond: And, parent: etree.Element) -> None:
    and_elem = etree.SubElement(parent, _ns("And"))
    for formula in cond.formulae:
        formula_wrap = etree.SubElement(and_elem, _ns("formula"))
        _build_condition(formula, formula_wrap)


def _build_or(cond: Or, parent: etree.Element) -> None:
    or_elem = etree.SubElement(parent, _ns("Or"))
    for formula in cond.formulae:
        formula_wrap = etree.SubElement(or_elem, _ns("formula"))
        _build_condition(formula, formula_wrap)


def _build_exists(cond: Exists, parent: etree.Element) -> None:
    exists_elem = etree.SubElement(parent, _ns("Exists"))
    for var in cond.declare:
        declare = etree.SubElement(exists_elem, _ns("declare"))
        _build_term(var, declare)
    formula_wrap = etree.SubElement(exists_elem, _ns("formula"))
    _build_condition(cond.formula, formula_wrap)


def _build_external_cond(cond: ExternalFunction, parent: etree.Element) -> None:
    _build_external(cond, parent)


def _build_uniterm_cond(cond: Uniterm, parent: etree.Element) -> None:
    _build_uniterm(cond, parent)


def _build_equal_cond(cond: Equal, parent: etree.Element) -> None:
    _build_equal(cond.lhs, cond.rhs, parent)


_BUILD_COND_HANDLERS = {
    Uniterm: _build_uniterm_cond,
    ExternalFunction: _build_external_cond,
    And: _build_and,
    Or: _build_or,
    Exists: _build_exists,
    Equal: _build_equal_cond,
}


def _build_rule(rule: Rule, parent: etree.Element) -> None:
    sentence = etree.SubElement(parent, _ns("sentence"))

    if rule.declare:
        forall = etree.SubElement(sentence, _ns("Forall"))
        for var in rule.declare:
            declare = etree.SubElement(forall, _ns("declare"))
            var_elem = etree.SubElement(declare, _ns("Var"))
            var_elem.text = str(var)
        formula_wrap = etree.SubElement(forall, _ns("formula"))
        _build_rule_formula(rule.formula, formula_wrap)
    else:
        _build_rule_formula(rule.formula, sentence)


def _build_rule_formula(clause: Clause, parent: etree.Element) -> None:
    implies = etree.SubElement(parent, _ns("Implies"))
    if_elem = etree.SubElement(implies, _ns("if"))
    then_elem = etree.SubElement(implies, _ns("then"))

    _build_condition(clause.body, if_elem)
    _build_condition(clause.head, then_elem)


def _build_ruleset(ruleset: Ruleset) -> etree.Element:
    doc = etree.Element(_ns("Document"))
    payload = etree.SubElement(doc, _ns("payload"))
    group = etree.SubElement(payload, _ns("Group"))

    for rule in ruleset.formulae:
        if isinstance(rule, Rule):
            _build_rule(rule, group)
        else:
            logger.warning("Skipping non-Rule formula: %s", type(rule))

    return doc


def serialize_xml(ruleset: Ruleset, pretty_print: bool = True) -> bytes:
    doc = _build_ruleset(ruleset)
    return etree.tostring(
        doc, pretty_print=pretty_print, xml_declaration=True, encoding="UTF-8"
    )


def serialize_xml_to_file(
    ruleset: Ruleset, path: str, pretty_print: bool = True
) -> None:
    data = serialize_xml(ruleset, pretty_print=pretty_print)
    with open(path, "wb") as f:
        f.write(data)
