from __future__ import annotations

from collections.abc import Iterable, Mapping, MutableMapping
from typing import Protocol

from rdflib.term import Identifier

from rdflib import BNode, Literal, URIRef, Variable

RDFTerm = Identifier
RDFNode = URIRef | BNode | Literal | Variable
Triple = tuple[RDFNode, RDFNode, RDFNode]
TriplePattern = tuple[RDFNode | None, RDFNode | None, RDFNode | None]
Bindings = Mapping[Variable, RDFTerm]
MutableBindings = MutableMapping[Variable, RDFTerm]
NamespaceMap = Mapping[str, URIRef]


class GraphLike(Protocol):
    def triples(self, triple: TriplePattern) -> Iterable[Triple]: ...

    def query(self, query_object, **kwargs): ...

    def namespaces(self): ...

    def qname(self, uri: RDFTerm) -> str: ...
