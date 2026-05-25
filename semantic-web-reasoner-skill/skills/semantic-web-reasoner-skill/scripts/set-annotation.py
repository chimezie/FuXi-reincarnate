
# /// script
# requires-python = ">=3.11"
# dependencies = ["rdflib", "fuxi"]
# ///
"""
set-annotation.py — Set an annotation on an OWL entity using InfixOwl

Positional arguments:
1. OWL file path
2. Base URI (namespace base URI, ending with # or /)
3. Class/property reference (local name or rdfs:label)
4. "true" if classReference is a local name, "false" if it's an rdfs:label
5. Annotation property URI
6. Annotation value (string)
"""
import sys
from rdflib import Graph, RDFS, Literal, URIRef
from fuxi.Syntax.InfixOWL import Class, IAO_NS, SKOS_NS, OWL_NS


def main():
    owl_file = sys.argv[1]
    baseuri = sys.argv[2]
    class_reference = sys.argv[3]
    by_id = sys.argv[4].lower() == "true" if len(sys.argv) > 4 else False
    annotation_uri = URIRef(sys.argv[5])
    annotation_value = sys.argv[6]

    g = Graph()
    g.parse(owl_file, format="xml")
    g.bind("iao", IAO_NS)
    g.bind("skos", SKOS_NS)

    if by_id:
        entity_iri = URIRef(baseuri + class_reference)
    else:
        matches = list(g.subjects(RDFS.label, Literal(class_reference)))
        if not matches:
            print(f"ERROR: No entity found with rdfs:label '{class_reference}'")
            sys.exit(1)
        entity_iri = matches[0]

    cls = Class(entity_iri, graph=g)
    cls.declare_annotation_property(annotation_uri)
    cls.set_annotation(annotation_uri, annotation_value)

    g.serialize(owl_file, format="xml")
    print(f"OK: Set {annotation_uri} to '{annotation_value}' on {entity_iri}")


if __name__ == "__main__":
    main()
