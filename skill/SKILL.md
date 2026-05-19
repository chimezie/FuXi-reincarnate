---
name: fuxi-engineer
compatibility: opencode
description: Use FuXi for various semantic web reasoning needs (RDF, RDFS, OWL, RIF, SPARQL)
---

## Use FuXi for semantic web reasoning (RDF, OWL, SPARQL)

FuXi is a Python bi-directional reasoning engine (forward/bottom-up + backward/top-down) companion to RDFLib.

## What I do

- Try steps of reasoning and generation of proofs
- Add annotations to OWL ontologies
- Summarizing an OWL ontology using InfixOWL API
- Performing theorem proving services
- Make use of QLever for SPARQL interlocution with ontologies and/or rules
- Use robot to validate if an ontology is in the OWL 2 RL profile (and therefore can be used with DLP)
- Use riot to convert between RDF formats

## When to Use This Skill

- When you need to interpret an OWL ontology rule file
- When you need to answer SPARQL queries
- When you need to add annotations to OWL ontology using InfixOWL API

## Basic Principles
The best format for OWL ontologies is OWL/RDF/XML, for compatibility with ontology tools such as protege.  
When verbalizing or serializing OWL for human eyes or reviewing narrative readability, the preferred syntax is
Manchester OWL (OWL/RDF/XML):

```python
from rdflib import Graph
from fuxi.cli.renderers import _render_man_owl as render_man_owl
from fuxi.Syntax.InfixOWL import all_classes, all_properties
ontology_graph = Graph().parse("ontology.owl")

for p in all_properties(ontology_graph):
    print(p.identifier, list(p.label))
    print(repr(p))
for c in all_classes(ontology_graph):
    print(c.__repr__(True))
```

Otherwise, turtle is the preferred format for RDF/XML if it has no rules or N3 if it does.  SPARQL files should be 
managed in separate .rq files.

Some core RDF vocabularies to re-use whenever possible:
- skos ([SKOS Simple Knowledge Organization System Reference](https://www.w3.org/TR/skos-reference/))
- OBO Information Artifact ontology IAO [Information Artifact Ontology](https://obofoundry.org/ontology/iao.html)
- ([Relation Ontology](https://obofoundry.org/ontology/ro.html)) 
- [FOAF Vocabulary Specification](https://xmlns.com/foaf/spec/) 
- dublin core ([DCMI Metadata expressed in RDF Schema Language](https://www.dublincore.org/schemas/rdfs/))
- (https://www.w3.org/TR/rdf-schema/)[RDFS]

If there is a need to query over a large RDF dataset, have decent performance, etc., then use QLever 
(see [QLever Documentation: Quickstart](https://docs.qlever.dev/quickstart/#using-qlever)) and various 
[examples of configuration files](https://github.com/qlever-dev/qlever-control/tree/main/src/qlever/Qleverfiles) to see 
how RDF can be loaded into it and queried efficiently via its [configuration file format](https://docs.qlever.dev/qleverfile/#section-data).

Use named graphs and named graph pattern matching to take advantage of the fact that RDF graphs are 
excellent for logical grouping of common content in the same way that files and directories are useful for grouping
content by common criteria and the naming conventions can be useful in sorting and filtering.  

### Installation

Use uv whenever possible (see https://github.com/uv-python/uv)
```bash
uv pip install fuxi          # or: uv pip install -e ".[dev]"
```

### Using robot

Checking if an ontology is in the OWL 2 RL profile (or give an error otherwise):
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

Output formats: `n3`, `nt`, `xml`, `conflict`, `rif`, `man-owl`, `adornment` (adorned rules), `pml` (proof serialization), `proof-graph-svg/png`, `rete-network-svg/png`, `sip-collection-svg/png`.

Example of running individual OWL test as command-line:

```bash
$ fuxi.owl --method=bfp --dlp --hybrid \
           --ns eg=http://example.net/vocab# \
           --ns your=http://example.net/vocab# \
           --why "ASK { eg:bob your:isBrotherOf eg:joe }" \
           --output proof-graph-svg https://www.w3.org/2002/03owlt/inverseOf/premises001
```
--hybrid should be used for small, given fact graphs but not large SPARQL services.  Use --ns to bind prefixes.
Use --output to specify output formats (such as _'sip-collection-svg'_, for example)

### Combining RDF/XML output from fuxi with other tools
You can convert the serialization of a proof graph to PML RDF/XML to turtle using riot:
```bash
$ fuxi.proof --method=bfp --dlp --hybrid \
             --ns eg=http://example.net/vocab# \
             --ns your=http://example.net/vocab# \
             --why "ASK { eg:bob your:isBrotherOf eg:joe }" \
             --output pml test/OWL/inverseOf/premises001.rdf | \
  JENA_HOME=/opt/apache-jena JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64 PATH="$PATH:$JENA_HOME/bin" riot \
      --syntax=rdfxml \
      --output=turtle -
```

### Programmatic API (canonical pipeline)

```python
from rdflib import Graph, Namespace
from fuxi.Rete.RuleStore import setup_rule_store
from fuxi.cli.shared import _extract_goals, _compute_derived_predicates
from fuxi.SPARQL.utilities import owl_entailment_regime_graph, sparql_interlocution
from fuxi.DLP.DLNormalization import normal_form_reduction

fact_graph = Graph().parse("onto.ttl", format="turtle")
normal_form_reduction(fact_graph)
ns_binds = dict(fact_graph.namespaces())
_, _, network = setup_rule_store(make_network=True)
dlp = list(network.setup_description_logic_programming(
    fact_graph, add_pd_semantics=False, construct_network=False))
goals = _extract_goals("SELECT ?x WHERE { ... }", ns_binds)
derived_preds, _ = _compute_derived_predicates(goals, ns_binds)
entailing_graph, _ = owl_entailment_regime_graph(
    fact_graph, ns_binds, derived_predicates=derived_preds or None,
    goals=goals, extra_rulesets=dlp)
answers = list(sparql_interlocution(query, entailing_graph.store))
```

- ASK provable → `answers[0] is True`; unprovable → `len(answers) == 0`
- SELECT → each answer is a `dict[Variable, URIRef]`

### TopDownSPARQLEntailingStore (direct use)

```python
from fuxi.SPARQL.BackwardChainingStore import TopDownSPARQLEntailingStore, BFP_METHOD

store = TopDownSPARQLEntailingStore(
    fact_graph.store, fact_graph, idb=program,
    ns_bindings=ns_binds, decision_procedure=BFP_METHOD,
    derived_predicates=derived_preds,
)
for answer in sparql_interlocution(query, store):
    print(answer[Variable("x")])
```

### SPARQLServiceGraph (remote SPARQL)

#### Regular (no reasoning)
```python
from rdflib import Graph
from rdflib.plugins.stores.sparqlstore import SPARQLStore

# Define the remote endpoint URL
endpoint = "https://dbpedia.org/sparql"

# Create a graph backed by the remote SPARQL store
store = SPARQLStore(endpoint)
g = Graph(store=store)

# Run a query just like a local graph
query = """
SELECT ?label WHERE {
    <http://dbpedia.org> rdfs:label ?label .
    FILTER (lang(?label) = 'en')
}
"""

for row in g.query(query):
    print(row.label)
```

#### With reasoning (sparql_interlocution and owl_entailment_regime_graph in fuxi.SPARQL.utilities)

```python
from fuxi.SPARQL.utilities import sparql_interlocution, owl_entailment_regime_graph
from fuxi.types import Variable, RDFTerm
from rdflib import Graph

fact_graph = Graph().parse("ontology.ttl")
hybrid_predicates = [
    #
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

### InfixOWL (edit/build/read ontologies)

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

### N3 rules from strings

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

### Using riot and sop to convert between RDF formats

Below is an example of using riot (assumed `JENA_HOME=/opt/apache-jena` and and `JAVA_HOME` and `PATH` set) and 
sop (assumed in ~/qlever$ sophia-cli/sop) to extract NQuad files with given graph names 
```bash
#!/usr/bin/env bash
set -euo pipefail

for f in *.rdf; do
  [ -e "$f" ] || continue        # skip if no matches
  base="${f%.*}"
  nt_out="${base}.nt"
  nquad_out="${base}.nq"
  base_urn=urn:medical-data:patient-record:"$base"
  sparql_base_urn="<$base_urn>"
  echo "Converting $f -> $nt_out"
  JENA_HOME=/opt/apache-jena JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64 PATH="$PATH:$JENA_HOME/bin" riot \
           --base="$base_urn" --quiet --output=NTRIPLES "$f" > "$nt_out"
  echo "Converting $nt_out -> $nquad_out (in $sparql_base_urn)"
  ~/qlever$ sophia-cli/sop parse "$nt_out" ! map -g "$sparql_base_urn" ! canonicalize -o "$nquad_out"
done
```

You can also convert between formats more directly:
```bash
riot --output turtle /path/to/ontology.owl
```

### Testing patterns

Use `@pytest.mark.integration` for CLI tests. Validate N3 output via `Graph().parse(data=stdout, format="n3")` and triple membership. Validate SVG via `stdout.startswith(b"<?xml")`. Use `conftest.py` fixtures `simple_rules_n3`, `horn_ruleset`, `rete_network` for quick in-process tests.
