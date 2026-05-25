---
name: fuxi-engineer
compatibility: opencode
description: Use FuXi for various semantic web reasoning needs (RDF, RDFS, OWL, RIF, SPARQL)
---

## Use FuXi for semantic web reasoning (RDF, OWL, SPARQL)

FuXi is a Python bi-directional reasoning engine (forward/bottom-up + backward/top-down) companion to RDFLib.

It is meant for use with Semantic Web applications that use OWL, RDF, RDFS, RIF, N3, and other W3C Semantic Web standards.

## Installation

Use uv whenever possible (see https://github.com/uv-python/uv)
```bash
uv pip install fuxi owl_dsl          # or: uv pip install -e ".[dev]"
```

## Semantic Web names

In Semantic Web applications, things are identified by URIs. These usually share a common prefix, called the 
*base URI* or *base namespace URI*, which usually ends in a '/' or '#', so a heuristic for finding the base URI is 
to include everything up to the final '/' or '#".  

For brevity, the *local name* is often used instead of the full URI.  It is is the part of the URI after the base URI.  
The base URI is usually associated with a short prefix and the name can be provided as a QName (qualified name), 
consisting of the prefix and the local name separated by a colon.

## Tools / Commands

The following OWL tools are available to the agent for ontology management functions

| Tool                       | Purpose                                                                    | Arguments                                                                     |
|----------------------------|----------------------------------------------------------------------------|-------------------------------------------------------------------------------|
| `list-ontologies`          | List OWL ontologies saved as owlready 2 SQLite files                       | `workingDir?`                                                                 |
| `verbalize-ontology-class` | Verbalize an OWL class into Controlled Natural Language owlready2 ontology | `ontologyUri`, `sqliteFile`, `baseuri`, `classReference`, `byId?`             |
| `find-ontology-property`   | Find OWL properties by label and URL pattern                               | `ontologyUri`, `sqliteFile`, `baseuri`, `classReference`, `byId?`, `owlFile?` |
| `create-ontology`          | Create owlready2 SQLite ontology and archive provenance for later use      | `ontologyUri`, `baseuri`, `owlFile`, `workingDir?`                            |
| `find-ontology-class`      | Find OWL class by label pattern (string or REGEX)                          | `sqliteFile` + `classSearch`, `regexSearch?`                                  |
| `dir-ontology`             | List the terms in an ontology as Manchester OWL                            | `sqliteFile`                                                                  |
| `check-ontology`           | Run a report on all issues with the ontology                               | `owlFile`, `reportFile?`, `labels?`                                           |
| `extract-class`            | Extract a class from an ontology                                           | `owlFile`, `term`, `outputOwl?`                                               |
| `ontology-report`          | Export details about ontology entities as a table                          | `owlFile`, `reportFile`                                                     |

You can check an ontology for issues by using the `check-ontology` tool. This uses robot and will print a report of any issues.  
You can also provide a path to a file (using the `reportFile` option) where the report will be saved as JSON. There is
also a labels options, which will print the labels of the ontology classes and properties if specified (default is False).

You can extract a class from an ontology using the `extract-class` tool. The `term` argument is the QName of the class
to extract and the `outputOwl` argument is the path to the output file where the extracted class will be saved 
(defaults to /tmp/output.owl).

You can also export the ontology entities as a table using the `ontology-report` tool, which has an `reportFile` option
to specify the path to the output JSON file.  

To work with an ontology using the other tools, you need to create it first, using `create-ontology`, which will determine the
SQLite file path (if not specified), using a name convention of the same ontology file name but with a `.sqlite` extension.

Once created, you can search it or verbalize its classes using the same arguments you used to create it for the 
corresponding tools. 

You should also use `list-ontologies`
to see the list of ontologies that are available for use in case one of them defines the base URI in an ontology you are reviewing.

`workingDir` is the directory where the SQLite files for ontologies are saved along with an index describing how it was made
in a file called `ontology_db.json` in the same directory with zero or more structures like this:

```json
{
   'datetime': '%Y-%m-%d-%H-%M-%S',
   'sqlite_file': '/path/to/sqlite/file.db',
   'owl_file': '/path/to/owl/file.owl',
   'ontology_base_uri': ' .. common BASE URI for ontology terms ..',
   'ontology_uri': ' ..ontology URI ..',
}
```
The `sqlite_file` field value is the path to the SQLite file and corresponds to the `sqliteFile` argument to the OWL tools.

The `ontology_uri` field value is the URI of the ontology and the same as the `ontologyUri` argument.  When 
creating the ontology, any trailing '#' should be removed and used for later reference to the stored ontology.  

The `ontology_base_uri` field value is the common prefix for all URIs of terms defined in the ontology.  It corresponds to
the `baseuri` argment and used to resolve local names wen used with the `byId` argument.

For tools that refer to a particular class, the `classReference` argument is either the local part of the class URI
(when used with `byId`) or the label of the class.

The `owl_file` field value is the source OWL file and corresponds to the `owlFile` argument.

For the `find-ontology-class` tool, the `classSearch` argument is a string or regular expression to match the class label.
The `regexSearch` argument is a boolean flag to indicate whether the class label should be treated as a regular expression.

### Using robot

Checking if an ontology is in the [OWL 2 RL profile](https://www.w3.org/2007/OWL/wiki/Primer#OWL_2_Profiles) (or give an error otherwise):
```bash
robot validate-profile --profile RL  --input  /path/to/ontology.owl
```

Or that it is in OWL 2 DL:
```bash
robot validate-profile --profile DL  --input  /path/to/ontology.owl 
OWL 2 DL Profile Report: [Ontology and imports closure in profile]
```

### CLI subcommands

| Command | Purpose |
|---------|---------|
| `fuxi.core facts.n3` | Forward chaining, RETE diagnostics |
| `fuxi.proof --why='Q' facts.n3` | BFP query answering, proof/SIP graphs |
| `fuxi.owl --dlp onto.ttl` | OWL→DLP, ontology reasoning |

Common flags: `--rules PATH`, `--output FORMAT`, `--ns PREFIX=URI`, `--why "SPARQL"`, `--method {naive,bfp}`.

Output formats: `ttl`, `n3`, `nt`, `xml`, `conflict`, `rif`, `man-owl`, `adornment` (adorned rules), `pml` (proof serialization), `proof-graph-svg/png`, `rete-network-svg/png`, `sip-collection-svg/png`.

## Basic Principles

The best format for OWL ontologies is OWL/RDF/XML for compatibility with ontology tools such as protege.  
When verbalizing or serializing OWL for human eyes or reviewing narrative readability, the preferred syntax is
to verbalize its classes with the `verbalize-ontology-class` tool or using Manchester OWL.

For non ontology-files, turtle is the preferred format if it doesn't have rules or N3 if it does or human-readable RIF Core BLD 
if a generic 'rif' format is specified.  SPARQL files should be managed in separate .rq files.

Some core RDF vocabularies to re-use whenever possible:
- skos ([SKOS Simple Knowledge Organization System Reference](https://www.w3.org/TR/skos-reference/))
- OBO Information Artifact ontology IAO [Information Artifact Ontology](https://obofoundry.org/ontology/iao.html)
- ([Relation Ontology](https://obofoundry.org/ontology/ro.html)) 
- [FOAF Vocabulary Specification](https://xmlns.com/foaf/spec/) 
- dublin core ([DCMI Metadata expressed in RDF Schema Language](https://www.dublincore.org/schemas/rdfs/))
- (https://www.w3.org/TR/rdf-schema/)[RDFS]

### InfixOWL (edit/build/read ontologies)

When creating a new ontology, extending, or adding annotations to an existing ontology, use the API:

```python
from fuxi.Syntax.InfixOWL import GraphContext, Class, Property, AnnotationProperty
from rdflib import Graph, Namespace, Literal

g = Graph()
NS = {"ex": "http://example.org/"}
with GraphContext(g, NS):
    person = Class(NS.ex.Person, label="Person")
    has_child = Property(NS.ex.hasChild, domain=[person])
    parent = Class(NS.ex.Parent)
    parent.equivalent_class = [person & has_child.some(person)]
```

To add annotation to an ontology:

```python
from fuxi.Syntax.InfixOWL import Class, Property, GraphContext
from rdflib import Graph, Namespace, Literal
g = Graph()

IMDB = Namespace("https://www.imdb.com/")
MY_NS = Namespace("tag:info@metacognition.info,2026:FuXiSPARQLExample#")
OWL_DSL = Namespace("https://github.com/chimezie/OWL_DSL/tree/main/ontology_configurations/")

with GraphContext(g, {"my": MY_NS, "owl_dsl": OWL_DSL, "imdb": IMDB}):
    movie = Class(IMDB.Movie, label=Literal("Movie"))
    person = Class(MY_NS.Person, label=Literal("Person"))
    singular_annotation = OWL_DSL.OWL_DSL_000001 #singular predicate string template
    film_director = Property(MY_NS.film_director, domain=[movie], range=[person])
    film_director.set_annotation(singular_annotation, "directed by {}")

print(g.serialize(format="ttl"))
```

### Combining RDF output from fuxi with other tools

If you run `fuxi.core` on a file with an OWL TBox (with class definitions) and ABox (instance assertions) along with
`--dlp` it will calculate and serialize just the inferred facts:

```bash
$ fuxi.core --method=bfp --dlp --hybrid \
            --ns eg=http://example.net/vocab# \
            --ns your=http://example.net/vocab# \
            --output xml ../FuXi-reincarnate/FuXi-reincarnate-chimezie/test/OWL/inverseOf/premises001.rdf  
<?xml version="1.0" encoding="utf-8"?>
<rdf:RDF
   xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
   xmlns:your="http://example.net/yourVocab#"
>
  <rdf:Description rdf:about="http://example.net/vocab#bob">
    <your:isBrotherOf rdf:resource="http://example.net/vocab#joe"/>
  </rdf:Description>
</rdf:RDF>
```

You can pipe this to riot to convert it to turtle:

```bash
$ fuxi.core --method=bfp --dlp --hybrid \
            --ns eg=http://example.net/vocab# \
            --ns your=http://example.net/vocab# \
            --output xml https://www.w3.org/2002/03owlt/inverseOf/premises001 \
| JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64/ riot --syntax=rdfxml --formatted=ttl -
PREFIX rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX your: <http://example.net/yourVocab#>

<http://example.net/vocab#bob>
        your:isBrotherOf  <http://example.net/vocab#joe> .
```

If you add the `--closure` flag, then the original RDF graph plus the inferred facts can be serialized:

## Advanced Usage

### OWL 2 RL SPARQL entailment

The `owl_entailment_regime_graph` method can be used to interact with an OWL graph 
(especially one in the OWL 2 RL profile) and perform SPARQL queries over it using terms from the ontologies' 
vocabulary with their logical entailments in mind (see https://www.w3.org/TR/sparql11-entailment/#OWL2RLDS). 
Some information about the vocabulary and its instances in the graph may be needed (which predicates are derived, 
some additional rules may be provided, and goals).  Note that, if used with an enterprise-class SPARQL service such
as Virtuoso or Qlever, the ontology can be handled separately (DLP transformations, etc.) and used with a runtime
, idempotent query over large RDF datasets without incurring a major resource utilization penalty

```python
from fuxi.SPARQL.utilities import sparql_interlocution, owl_entailment_regime_graph
from fuxi.types import Variable, RDFTerm
from rdflib import Graph

fact_graph = Graph().parse("ontology.ttl")
hybrid_predicates = [
    #hybrid predicates
]
rules = [
    #rules
]

#[.. snip ..]
entailing_graph, _ = owl_entailment_regime_graph(
    fact_graph,
    identify_hybrid_predicates = True,
    hybrid_predicates = hybrid_predicates,
    extra_rulesets = rules, #parsed using horn_from_n3
    add_pd_semantics = False,
    add_non_dhl_owl_rules = True,
)
for answer in sparql_interlocution(" .. sparql query ..", entailing_graph.store):
    answer: dict[Variable, RDFTerm]
    user_readable_dict = {f"?{k} -> {v.n3()}" for k, v in answer.items()}
    #Use answers in subsequent query, etc.
```

The `sparql_interlocution` method is what facilitates SPARQL entailment and takes a SPARQL query

### SPARQLServiceGraph (remote SPARQL)

You can also use rdflib and FuXi to query remote SPARQL endpoints.

```python
from rdflib import Graph
from rdflib.plugins.stores.sparqlstore import SPARQLStore

endpoint = "https://dbpedia.org/sparql"

store = SPARQLStore(endpoint)
g = Graph(store=store)

for row in g.query(".. SPARQL query .."):
    print(row.label)
```

#### Remote SPARQL Entailment Regime

To perform SPARQL entailment over a remote SPARQL endpoint, you simply need to instanciate a `SPARQLServiceGraph`
and pass it to the `owl_entailment_regime_graph` method and use the store of the graph to run queries with `sparql_interlocution`.

The main distinction is passing False to `identify_hybrid_predicates` and explicity providing the hybrid and derived predicates.

Otherwise, you can still pass additional rules, etc.

```python
from fuxi.SPARQL.service import SPARQLServiceGraph
from fuxi.SPARQL.utilities import sparql_interlocution, owl_entailment_regime_graph

remote_graph = SPARQLServiceGraph("http://localhost:7000")

hybrid_predicates = [..]
derived_predicates = [..]
entailing_graph, _ = owl_entailment_regime_graph(
    remote_graph,
    identify_hybrid_predicates = False,
    hybrid_predicates = hybrid_predicates,
    derived_predicates=derived_predicates
)

for answer in sparql_interlocution(" .. sparql query ..", entailing_graph.store):
    #Entailed answers
```

### Parsing N3 rules from strings

You can parse rules from N3 strings via `horn_from_n3`

```python
from io import StringIO
from fuxi.Horn.HornRules import horn_from_n3

program = list(horn_from_n3(StringIO("""\
@prefix ex: <http://example.org/> .
{ ?s ex:parentOf ?o } => { ?s ex:relatedTo ?o } .
""")))
for rule in program:
    rule.nsMapping.update(ns_binds)
```
