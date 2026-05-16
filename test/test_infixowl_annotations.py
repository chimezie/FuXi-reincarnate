from fuxi.Syntax.InfixOWL import (
    IAO_NS,
    OWL_NS,
    SKOS_NS,
    Class,
    GraphContext,
    Property,
    declare_common_annotations_fn,
)
from rdflib import RDF, RDFS, Graph, Literal, Namespace


def test_infixowl_annotations_add_set_get():
    g = Graph()
    ex = Namespace("http://example.org/")
    iao = Namespace("http://purl.obolibrary.org/obo/IAO_")

    parent = Class(ex.Parent, graph=g)
    parent.add_annotation(iao["0000115"], "Definition one")
    parent.add_annotation(iao["0000115"], Literal("Definition two"))

    values = set(parent.get_annotations(iao["0000115"]))
    assert Literal("Definition one") in values
    assert Literal("Definition two") in values

    parent.set_annotation(iao["0000115"], "Only one")
    values = parent.get_annotations(iao["0000115"])
    assert len(values) == 1
    assert values[0] == Literal("Only one")


def test_infixowl_declare_annotation_property():
    g = Graph()
    ex = Namespace("http://example.org/")

    parent = Class(ex.Parent, graph=g)
    parent.declare_annotation_property(IAO_NS["0000115"])

    assert (IAO_NS["0000115"], RDF.type, OWL_NS.AnnotationProperty) in g


def test_add_label_and_set_label_with_languages():
    g = Graph()
    ex = Namespace("http://example.org/")
    parent = Class(ex.Parent, graph=g)

    parent.add_label("Parent", lang="en")
    parent.add_label("Parent", lang="en")
    parent.add_label("Parent", lang="fr")

    labels = parent.get_annotations(RDFS.label)
    assert Literal("Parent", lang="en") in labels
    assert Literal("Parent", lang="fr") in labels
    assert labels.count(Literal("Parent", lang="en")) == 1

    parent.set_label("Parent (EN)", lang="en")
    labels = parent.get_annotations(RDFS.label)
    assert Literal("Parent (EN)", lang="en") in labels
    assert Literal("Parent", lang="fr") in labels


def test_label_coerces_string_to_literal():
    g = Graph()
    ex = Namespace("http://example.org/")

    parent = Class(ex.Parent, graph=g, label="Parent")
    has_child = Class(ex.HasChild, graph=g)
    prop = Property(ex.hasChild, graph=g, label="has child")

    assert Literal("Parent") in parent.get_annotations(RDFS.label)
    assert Literal("has child") in prop.get_annotations(RDFS.label)
    assert Literal("HasChild") not in has_child.get_annotations(RDFS.label)


def test_add_definition_and_set_definition_with_languages():
    g = Graph()
    ex = Namespace("http://example.org/")
    parent = Class(ex.Parent, graph=g)

    parent.add_definition("Definition", lang="en")
    parent.add_definition("Definition", lang="en")
    parent.add_definition("Definition", lang="fr")

    definitions = parent.get_annotations(IAO_NS["0000115"])
    assert Literal("Definition", lang="en") in definitions
    assert Literal("Definition", lang="fr") in definitions
    assert definitions.count(Literal("Definition", lang="en")) == 1

    parent.set_definition("Definition (EN)", lang="en")
    definitions = parent.get_annotations(IAO_NS["0000115"])
    assert Literal("Definition (EN)", lang="en") in definitions
    assert Literal("Definition", lang="fr") in definitions


def test_declare_common_annotations_helper():
    g = Graph()
    declare_common_annotations_fn(g, include=("rdfs", "skos", "iao"))

    assert (RDFS.label, RDF.type, OWL_NS.AnnotationProperty) in g
    assert (RDFS.comment, RDF.type, OWL_NS.AnnotationProperty) in g
    assert (SKOS_NS.prefLabel, RDF.type, OWL_NS.AnnotationProperty) in g
    assert (SKOS_NS.altLabel, RDF.type, OWL_NS.AnnotationProperty) in g
    assert (SKOS_NS.definition, RDF.type, OWL_NS.AnnotationProperty) in g
    assert (IAO_NS["0000115"], RDF.type, OWL_NS.AnnotationProperty) in g


def test_graph_context_declares_common_annotations():
    g = Graph()
    ex = Namespace("http://example.org/")
    with GraphContext(
        g,
        {"ex": ex},
        declare_common_annotations=True,
        common_annotation_sets=("rdfs", "iao"),
    ):
        pass

    assert (RDFS.label, RDF.type, OWL_NS.AnnotationProperty) in g
    assert (IAO_NS["0000115"], RDF.type, OWL_NS.AnnotationProperty) in g
