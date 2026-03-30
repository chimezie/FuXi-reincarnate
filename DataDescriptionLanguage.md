# Data Description Language (DDL)

DDL is a small RDF vocabulary used by FuXi to declare which predicate symbols are
**derived** (IDB) and which are **base** (EDB). This is important for query mediation as 
FuXi’s top-down entailment and Magic Set rewriting need to know which terms are introduced
by rules and which already exist in a RDF graph or remote SPARQL dataset.

They can be given explicitly, or determined via introspection on the RDF graph of the vocabulary (an ontology)
or a ruleset used in the target graph.

The DDL namespace is:

```
tag:info@metacognition.info,2026:FuXiVocabulary#
```

The examples below use:

```turtle
@prefix ddl: <tag:info@metacognition.info,2026:FuXiVocabulary#> .
```

Note that RDFS / OWL Classes are unary predicates in Description Logic, while OWL Properties are binary predicates.

## Vocabulary

DDL primarily uses [RDF collections](https://www.w3.org/TR/rdf-schema/#ch_collectionvocab) to enumerate classes and 
properties.

- `ddl:DerivedClassList` and `ddl:DerivedPropertyList`
  - RDF collection of URIs considered **derived** predicates.
- `ddl:BaseClassList`
  - RDF collection of URIs considered **base** class predicates.
- `ddl:DerivedPropertyPrefix` and `ddl:BasePropertyPrefix`
  - RDF collection of **namespace prefixes**, identifying OWL properties, whose URI starts with
    the prefix, to treat as derived/base, respectively.
- `ddl:DerivedClassPrefix` and `ddl:BaseClassPrefix`
  - RDF collection of **namespace prefixes**, identifying OWL classes, whose URI starts with
    the prefix, to treat as derived/base, respectively. 
- `ddl:DerivedClassQuery`
  - RDF nodes that have an `rdf:value` property whose value is a SPARQL query, which when evaluated against the 
  - graph defining the semantics of the vocabulary (an ontology, for example), responds with one or more predicate
    URIs.

## How FuXi Interprets DDL
The method below is defined in `fuxi.Rete.Magic`
```python
IdentifyDerivedPredicates(ddlMetaGraph, tBox, ruleset)
```

Is used to extract derived predicates based on a given DDL graph, an RDF ontology graph, and a ruleset, ensuring there 
is a clear partition of derived and base predicates, excluding any predicates that are both derived and base.

## Example Graphs

Each example is a DDL graph unless otherwise noted.

### Derived class/property lists (drugbank)

```turtle
@prefix ddl: <tag:info@metacognition.info,2026:FuXiVocabulary#> .
@prefix drugbank: <tag:info@metacognition.info,2026:FuXiVocabulary#> .

( drugbank:InfluenzaDrug ) a ddl:DerivedClassList .

(
  drugbank:interactionForDrug
  drugbank:interactionForDrug1
  drugbank:interactionForDrug2
) a ddl:DerivedPropertyList .
```

### Derived property prefixes (with OWL properties in the TBox)

DDL graph:

```turtle
@prefix ddl: <tag:info@metacognition.info,2026:FuXiVocabulary#> .
@prefix ex: <http://example.org/terms/> .

( ex: ) a ddl:DerivedPropertyPrefix .
```

Ontology snippet (separate graph passed to `IdentifyDerivedPredicates`):

```turtle
@prefix ex: <http://example.org/terms/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .

ex:hasSymptom a owl:ObjectProperty .
ex:hasDose a owl:DatatypeProperty .
```

`ex:hasSymptom` and `ex:hasDose` are derived property predicates.

### Derived class query

DDL graph:

```turtle
@prefix ddl: <http://code.google.com/p/fuxi/wiki/DataDescriptionLanguage#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .

[
  a ddl:DerivedClassQuery ;
  rdf:value """
    SELECT ?cls WHERE {
      ?cls a owl:Class ;
           rdfs:subClassOf ?restriction .
      ?restriction owl:onProperty ex:hasSymptom .
    }
  """ ;
] .
```
