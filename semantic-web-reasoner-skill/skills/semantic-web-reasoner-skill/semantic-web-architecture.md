
## Basic Principles

### Semantic Web names and their use with "agents" as originally meant in the Semantic Web

In Semantic Web applications, things are identified by URIs. These usually share a common prefix, called the 
*base URI* or *base namespace URI*, which usually ends in a '/' or '#', so a heuristic for finding the base URI is 
to include everything up to the final '/' or '#".  

For brevity, the *local name* is often used instead of the full URI.  It is the part of the URI after the base URI.  
The base URI is usually associated with a short prefix, and the name can be provided as a QName (qualified name)
or Curie, consisting of the prefix and the local name separated by a colon.

The best format for OWL ontologies is OWL/RDF/XML for compatibility with ontology tools such as protege.  
When verbalizing or serializing OWL for human eyes or reviewing narrative readability, the preferred syntax is
to verbalize its classes with the `verbalize-ontology-class` tool or using Manchester OWL with `fuxi.core`.

For non-ontology files, turtle is the preferred format if it doesn't have rules or N3 if it does or human-readable RIF Core BLD 
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

for programmatic access to the ontology, see [owl_engineering_apis.md](owl_engineering_apis.md)
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

For more on OWL 2 RL SPARQL entailment, remote entailment, and parsing N3 rules from strings, see [advanced.md](advanced.md)
