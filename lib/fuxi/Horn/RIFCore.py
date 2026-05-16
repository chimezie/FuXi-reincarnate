# -*- coding: utf-8 -*-
# flake8: noqa
"""
RIF Core parser for fuxi.

Parses RIF Core XML (and RIF In RDF) syntaxes into FuXi (converts the former
into the latter).

Supports Frames and atoms with only two positional arguments.  Follows import
trail.
"""

import os
import logging
from urllib import request
from lxml import etree
from rdflib.graph import Graph
from rdflib import Namespace, RDF, Variable, URIRef
from rdflib.util import first
from rdflib.collection import Collection
from fuxi.Horn.PositiveConditions import And, ExternalFunction, Uniterm
from fuxi.Horn.HornRules import Rule, Clause


def _debug(*args, **kw):
    logging.basicConfig(level=logging.DEBUG, format="%(message)s")
    logger = logging.getLogger(__name__)
    logger.debug(*args, **kw)


__all__ = [
    "RIFCoreParser",
    "SmartRedirectHandler",
    "RIF_NS",
    "XSD_NS",
    "mimetypes",
]


class SmartRedirectHandler(request.HTTPRedirectHandler):
    def http_error_301(self, req, fp, code, msg, headers):
        result = request.HTTPRedirectHandler.http_error_301(
            self, req, fp, code, msg, headers
        )
        result.status = code
        return result

    def http_error_302(self, req, fp, code, msg, headers):
        result = request.HTTPRedirectHandler.http_error_302(
            self, req, fp, code, msg, headers
        )
        result.status = code
        return result


RIF_NS = Namespace("http://www.w3.org/2007/rif#")
XSD_NS = Namespace("http://www.w3.org/2001/XMLSchema#")

mimetypes = {
    "application/rdf+xml": "xml",
    "text/n3": "n3",
    "text/turtle": "turtle",
}

# TRANSFORM_URI = iri.absolutize(
#        'rif-core-rdf.xsl',iri.os_path_to_uri(__file__))

__fpath__ = os.path.split(__file__)[0]

if "build/src/" in __fpath__:
    __fpath__ = "".join(__fpath__.split("build/src/"))

TRANSFORM_URI = "file://" + os.path.join(__fpath__, "rif-core-rdf.xsl")


IMPLIES_PARTS = """
SELECT DISTINCT ?impl ?body ?bodyType ?head ?headType {
    ?impl a             rif:Implies;
          rif:if        ?body;
          rif:then      ?head .
    ?body a             ?bodyType .
    ?head a             ?headType .
}
"""

RULE_PARTS = """
SELECT DISTINCT ?rule ?vars ?impl {
    ?rule a             rif:Forall;
          rif:formula   ?impl;
          rif:vars      ?vars
}
"""

FRAME_PARTS = """
SELECT ?frame ?object ?slots {
    ?frame  a           rif:Frame;
            rif:object  ?object;
            rif:slots   ?slots
}
"""

EXTERNAL_PARTS = """
SELECT ?external ?args ?op {
    ?external   a           rif:External;
                rif:content [ a rif:Atom; rif:args ?args; rif:op ?op ]
}
"""

ATOM_PARTS = """
SELECT ?atom ?args ?op {
    ?atom   a        rif:Atom;
            rif:args ?args;
            rif:op ?op
}
"""

rif_namespaces = {"rif": RIF_NS}


class RIFCoreParser(object):
    def __init__(self, location=None, graph=None, debug=False):
        self.location = location
        self.rules = {}
        if graph:
            assert location is None, "Must supply one of graph or location"
            self.graph = graph
            if debug:
                _debug("RIF in RDF graph was provided")
        else:
            assert graph is None, "Must supply one of graph or location"
            if debug:
                _debug("RIF document URL provided %s" % location)
            if self.location.find("http:") + 1:
                req = request.Request(self.location)

                # From:
                # http://www.diveintopython.org/http_web_services/redirects.html
                # points an 'opener' to the address to 'sniff' out final
                # Location header
                opener = request.build_opener(SmartRedirectHandler())
                f = opener.open(req)
                self.content = f.read()
            else:
                self.content = request.urlopen(self.location).read()
                # self.content = open(self.location).read()
            try:
                transform = etree.XSLT(etree.parse(TRANSFORM_URI))
                self.graph = Graph().parse(
                    data=etree.tostring(transform(etree.fromstring(self.content)))
                )
                if debug:
                    _debug("Extracted rules from RIF XML format")
            except ValueError:
                try:
                    self.graph = Graph().parse(data=self.content, format="xml")
                except:
                    self.graph = Graph().parse(data=self.content, format="n3")
                if debug:
                    _debug("Extracted rules from RIF in RDF document")

    def get_ruleset(self):
        """
        >>> parser = RIFCoreParser('http://www.w3.org/2005/rules/test/repository/tc/Frames/Frames-premise.rif')
        >>> for rule in parser.getRuleset(): print(rule)
        Forall ?Customer ( ns1:discount(?Customer 10) :- ns1:status(?Customer "gold"^^<http://www.w3.org/2001/XMLSchema#string>) )
        Forall ?Customer ( ns1:discount(?Customer 5) :- ns1:status(?Customer "silver"^^<http://www.w3.org/2001/XMLSchema#string>) )
        >>> parser = RIFCoreParser('http://www.w3.org/2005/rules/test/repository/tc/Guards_and_subtypes/Guards_and_subtypes-premise.rif')
        >>> for rule in parser.getRuleset(): print(rule)
        """
        self.implications = dict(
            [
                (impl, (body, bodyType, head, headType))
                for impl, body, bodyType, head, headType in self.graph.query(
                    IMPLIES_PARTS, initNs=rif_namespaces
                )
            ]
        )
        self.rules = dict(
            [
                (rule, (vars, impl))
                for rule, vars, impl in self.graph.query(
                    RULE_PARTS, initNs=rif_namespaces
                )
            ]
        )
        self.frames = dict(
            [
                (frame, (obj, slots))
                for frame, obj, slots in self.graph.query(
                    FRAME_PARTS, initNs=rif_namespaces
                )
            ]
        )

        self.atoms = dict(
            [
                (atom, (args, op))
                for atom, args, op in self.graph.query(
                    ATOM_PARTS, initNs=rif_namespaces
                )
            ]
        )

        self.externals = dict(
            [
                (external, (args, op))
                for external, args, op in self.graph.query(
                    EXTERNAL_PARTS, initNs=rif_namespaces
                )
            ]
        )
        rt = []
        for sentenceCollection in self.graph.objects(predicate=RIF_NS.sentences):
            col = Collection(self.graph, sentenceCollection)
            for sentence in col:
                if RIF_NS.Implies in self.graph.objects(sentence, RDF.type):
                    rt.append(self.extract_imp(sentence))
                elif RIF_NS.Forall in self.graph.objects(sentence, RDF.type):
                    rt.append(self.extract_rule(sentence))
        return rt

    def extract_imp(self, impl):
        body, bodyType, head, headType = self.implications[impl]
        head = first(self.extract_predication(head, headType))
        if bodyType == RIF_NS.And:
            raise
        else:
            body = self.extract_predication(body, bodyType)

        body = And([first(body)]) if len(body) == 1 else And(body)
        return Rule(Clause(body, head), declare=[])

    def extract_rule(self, rule):
        vars, impl = self.rules[rule]
        body, bodyType, head, headType = self.implications[impl]
        allVars = map(self.extract_term, Collection(self.graph, vars))
        head = first(self.extract_predication(head, headType))
        if bodyType == RIF_NS.And:
            body = [
                first(
                    self.extract_predication(i, first(self.graph.objects(i, RDF.type)))
                )
                for i in Collection(
                    self.graph, first(self.graph.objects(body, RIF_NS.formulas))
                )
            ]

        else:
            body = self.extract_predication(body, bodyType)

        body = And([first(body)]) if len(body) == 1 else And(body)
        return Rule(
            Clause(body, head), declare=allVars, ns_mapping=dict(self.graph.namespaces())
        )

    def extract_predication(self, predication, pred_type):
        if pred_type == RIF_NS.Frame:
            return self.extract_frame(predication)
        elif pred_type == RIF_NS.Atom:
            return [self.extract_atom(predication)]
        else:
            assert pred_type == RIF_NS.External
            args, op = self.externals[predication]
            args = list(map(self.extract_term, Collection(self.graph, args)))
            op = self.extract_term(op)
            return [ExternalFunction(Uniterm(op, args))]

    def extract_atom(self, atom):
        args, op = self.atoms[atom]
        op = self.extract_term(op)
        args = list(map(self.extract_term, Collection(self.graph, args)))
        if len(args) > 2:
            raise NotImplementedError(
                "FuXi RIF Core parsing only supports subset involving binary/unary Atoms"
            )
        return Uniterm(op, args)

    def extract_frame(self, frame):
        obj, slots = self.frames[frame]
        rt = []
        for slot in Collection(self.graph, slots):
            k = self.extract_term(first(self.graph.objects(slot, RIF_NS.slotkey)))
            v = self.extract_term(first(self.graph.objects(slot, RIF_NS.slotvalue)))
            rt.append(Uniterm(k, [self.extract_term(obj), v]))
        return rt

    def extract_term(self, term):
        if (term, RDF.type, RIF_NS.Var) in self.graph:
            return Variable(first(self.graph.objects(term, RIF_NS.varname)))
        elif (term, RIF_NS.constIRI, None) in self.graph:
            iriLit = first(self.graph.objects(term, RIF_NS.constIRI))
            assert iriLit.datatype == XSD_NS.anyURI
            return URIRef(iriLit)
        else:
            return first(self.graph.objects(term, RIF_NS.value))


def test():
    import doctest

    doctest.testmod()


if __name__ == "__main__":
    # test()
    parser = RIFCoreParser(
        "http://www.w3.org/2005/rules/test/repository/tc/Guards_and_subtypes/Guards_and_subtypes-premise.rif"
    )
    for rule in parser.get_ruleset():
        _debug(rule)

# from fuxi.Horn.RIFCore import RIFCoreParser
# from fuxi.Horn.RIFCore import SmartRedirectHandler
# from fuxi.Horn.RIFCore import RIF_NS
# from fuxi.Horn.RIFCore import XSD_NS
# from fuxi.Horn.RIFCore import mimetypes
