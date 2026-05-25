### OWL 2 RL SPARQL entailment

The `owl_entailment_regime_graph` method can be used to interact with an OWL graph 
(especially one in the OWL 2 RL profile) and perform SPARQL queries over it using terms from the ontologies' 
vocabulary with their logical entailments in mind (see https://www.w3.org/TR/sparql11-entailment/#OWL2RLDS). 
Some information about the vocabulary and its instances in the graph may be needed (which predicates are derived, 
some additional rules may be provided, and goals).  Note that, if used with an enterprise-class SPARQL service such
as Virtuoso or Qlever, the ontology can be handled separately (DLP transformations, etc.) and used with a runtime, 
idempotent query over large RDF datasets without incurring a major resource utilization penalty

Virtuoso has [a Agent Skills repo](https://github.com/OpenLinkSoftware/ai-agent-skills)

See [owl2_sparql_entailment.md](owl2_sparql_entailment.md) for more details.

#### Remote SPARQL Entailment Regime

To perform SPARQL entailment over a remote SPARQL endpoint, you simply need to instanciate a `SPARQLServiceGraph`
and pass it to the `owl_entailment_regime_graph` method and use the store of the graph to run queries with `sparql_interlocution`.

The main distinction is passing False to `identify_hybrid_predicates` and, when needed, explicity providing the hybrid and derived predicates.

Otherwise, you can still pass additional rules, etc.

**Auto-derivation (recommended)**: Omit `derived_predicates` and `hybrid_predicates` — FuXi's `TopDownSPARQLEntailingStore` auto-discovers derived predicates from rule heads:

```python
from fuxi.SPARQL.service import SPARQLServiceGraph
from fuxi.SPARQL.utilities import sparql_interlocution, owl_entailment_regime_graph

remote_graph = SPARQLServiceGraph("http://localhost:7000")

entailing_graph, _ = owl_entailment_regime_graph(
    remote_graph,
    ns_map={"ex": EX},
    extra_rulesets=program,
    # derived_predicates and hybrid_predicates omitted → auto-derived
)

for answer in sparql_interlocution(" .. sparql query ..", entailing_graph.store):
    #Entailed answers
```

**Manual override** (when you need to restrict the set):

```python
entailing_graph, _ = owl_entailment_regime_graph(
    remote_graph,
    ns_map={"ex": EX},
    derived_predicates=[EX.Movie, EX.film_director],
    extra_rulesets=program,
)
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

## Understanding Derived vs. Base Predicates

When using FuXi with a remote SPARQL endpoint, every predicate falls into one of two categories:

### Base predicates (EDB)
Data that lives in the remote SPARQL endpoint and can be queried directly. Examples: `imdb:type`, `imdb:principal`, `imdb:role`, `imdb:person`, `imdb:title`. These are never derived by rules.

### Derived predicates (IDB)
Predicates that the reasoner must prove via backward-chaining through rules (DLP Horn clauses + N3 rules). Examples: `ex:film_director`, `ex:acted_in`, `ex:Movie`, `ex:Person`.

**Critical rule**: Only predicates that appear in the HEAD of some rule should be in `derived_predicates`. Predicates NOT in this list are treated as EDB — the reasoner queries them directly against the SPARQL endpoint.

### Auto-Discovery (recommended)

FuXi can auto-discover derived predicates for you. When `derived_predicates` is omitted from `owl_entailment_regime_graph()`, the `TopDownSPARQLEntailingStore` calls `derived_predicate_iterator()` which scans all rule heads in the combined rule program (DLP rules + non-DHL OWL semantics + your N3 rules):

```python
entry_point = "fuxi/Rete/Magic.py"
# TopDownSPARQLEntailingStore.__init__:
if derived_predicates is None:
    self.derived_predicates = list(
        derived_predicate_iterator(self.edb, self.idb)
    )
```

Simply omit the parameter:

```python
entailing_graph, _ = owl_entailment_regime_graph(
    fact_graph,
    ns_map=ns_map,
    extra_rulesets=program,    # your N3 rules
    # derived_predicates not passed → auto-derived
)
```

To inspect what was auto-derived:

```python
from fuxi.Rete.Magic import derived_predicate_iterator

auto_preds = list(derived_predicate_iterator(fact_graph, program))
print("Auto-derived predicates:", auto_preds)
```

### Manual override (when auto-discovery is not desired)

1. Run DLP compilation: `fuxi.owl --dlp onto.owl` and inspect the generated Horn rules
2. Look at the HEAD of each N3 rule you wrote
3. Collect all predicates from rule heads (both DLP and N3)
4. Apply `lloyd_topor_transformation` to split conjunctive heads into individual Horn clauses

### Common mistake: data predicates as derived

If you include a data-level predicate like `imdb:person` in `derived_predicates`, the reasoner will try to prove it via backward-chaining against its rules. Since no rule has `imdb:person` in its head, the proof fails and you get empty results — even though the data exists in QLever. When relying on auto-discovery, this mistake cannot happen because data predicates don't appear in any rule head.

## Writing N3 Rules for Data→Ontology Bridging

When your OWL ontology defines semantic predicates (e.g., `ex:film_director`, `ex:acted_in`) but the raw data in your SPARQL endpoint uses different predicates (e.g., `imdb:principal`, `imdb:role`), you need N3 rules that bridge the gap.

### Pattern: triple join with data filtering

```n3
@prefix ex:    <http://example.org#> .
@prefix imdb:  <https://www.imdb.com/> .

# A movie is anything with imdb:type "movie"
{ ?m imdb:type "movie" } => { ?m a ex:Movie } .

# A person is anything with imdb:person ?p
{ ?s imdb:person ?p } => { ?p a ex:Person } .

# film_director: principal with role "director"
{ ?movie imdb:principal ?p . ?p imdb:role "director" ; imdb:person ?d }
  => { ?movie ex:film_director ?d } .

# acted_in: principal with role "actor" or "actress"
{ ?movie imdb:principal ?p . ?p imdb:role ?role ; imdb:person ?a }
  => { ?a ex:acted_in ?movie } .
```

### Pattern: joining two derived predicates

```n3
# worked_together: two people who acted in the same movie
{ ?a ex:acted_in ?movie . ?b ex:acted_in ?movie . FILTER(?a != ?b) }
  => { ?a ex:worked_together ?b } .
```

### Pattern: inverse with restriction

```n3
@prefix owl:   <http://www.w3.org/2002/07/owl#> .

# has_directed_actress: film_director where the principal role was "actress"
{ ?movie ex:film_director ?d . ?movie imdb:principal ?p .
  ?p imdb:role "actress" ; imdb:person ?a }
  => { ?d ex:has_directed_actress ?a } .
```

### Pattern: class membership via role

```n3
# has_actor: ?movie has actor ?a (regardless of director)
{ ?movie imdb:principal ?p . ?p imdb:role "actor" ; imdb:person ?a }
  => { ?movie ex:has_actor ?a } .
```

### Important note about RDF lists and n3

Some predicates like `imdb:genre` may use RDF lists (`rdf:first`/`rdf:rest`). FuXi's BFP can handle these, but the N3 rules need to match the actual triple structure. Use `DESCRIBE ?s` on a sample to see the actual RDF structure before writing rules.

## Debugging Empty Results

If a query returns empty results when you expected data, follow these steps:

### 1. Test the SPARQL endpoint directly

Verify the endpoint is running and has data:

```sparql
SELECT * WHERE { ?s ?p ?o } LIMIT 5
```

### 2. Check that base predicates exist

Query the endpoint for the predicates your N3 rules depend on:

```sparql
SELECT DISTINCT ?role WHERE { ?p imdb:role ?role } LIMIT 20
```

### 3. Enable verbose mode

FuXi's BFP supports SIP graphs and proof output. To see why a proof fails, use the `.why()` method on the closure graph.

### 4. Verify derived predicates list

The most common cause of empty results: a predicate that should be EDB is accidentally in `derived_predicates`, or vice versa.

If using auto-discovery, inspect what was derived:

```python
from fuxi.Rete.Magic import derived_predicate_iterator
auto = list(derived_predicate_iterator(edb, program))
print("Auto-derived:", auto)
# If imdb:person appears here, your N3 rules are deriving a data predicate
```

If using manual override, double-check:

- Data-level predicates (e.g., `imdb:person`, `imdb:role`, `imdb:type`) → should be EDB (NOT in `derived_predicates`)
- Ontology-level predicates (e.g., `ex:film_director`, `ex:Movie`) → should be in `derived_predicates`

### 5. Test with a minimal query

Start with the simplest possible query and build up:

```sparql
# Does the ontology recognize any Movie instances?
SELECT ?m WHERE { ?m a ex:Movie } LIMIT 10
```

If this fails, the N3 rule for `Movie` classification may be wrong, or the `imdb:type` predicate may not exist in the endpoint.

### 6. Check namespace consistency

Ensure the URIs in your `nsBindings`, `derivedPredicates`, and N3 rules all use the same namespaces. A mismatch between `tag:info@...` in one place and `http://example.org#` in another will cause empty results.
