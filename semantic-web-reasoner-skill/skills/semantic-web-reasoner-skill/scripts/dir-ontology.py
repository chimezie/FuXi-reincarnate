
# /// script
# requires-python = ">=3.11"
# dependencies = ["owlready2"]
# ///
"""
dir-ontology.py — List the terms in an ontology as Manchester OWL

Positional arguments:
- SQLite file (sqlite_file): Path to SQLite file to store ontology
"""
import sys

from owlready2 import (
    AnnotationProperty,
    DataProperty,
    ObjectProperty,
    ThingClass,
    default_world,
    get_ontology,
)

default_world.set_backend(filename=sys.argv[1])

onto = None
for iri in default_world.ontologies:
    if iri != 'http://anonymous/':
        onto = get_ontology(iri)
        break

if onto is None:
    print("No ontology found in SQLite file")
    sys.exit(1)

print(f"Ontology: {onto.base_iri}\n")

for cls in onto.classes():
    print(f"Class: {cls.name}")
    if cls.label:
        print(f"  Label: {', '.join(cls.label)}")
    for sup in cls.is_a:
        if isinstance(sup, ThingClass):
            print(f"  SubClassOf: {sup.name}")
    print()

for prop in onto.properties():
    print(f"Property: {prop.name}")
    if hasattr(prop, 'label') and prop.label:
        print(f"  Label: {', '.join(prop.label)}")
    ptype = "ObjectProperty" if isinstance(prop, ObjectProperty) else \
            "DataProperty" if isinstance(prop, DataProperty) else \
            "AnnotationProperty" if isinstance(prop, AnnotationProperty) else "Property"
    print(f"  Type: {ptype}")
    print()
