---
name: semantic-web-reasoner-skill
compatibility: opencode
description: For various semantic web architecture design patterns
---

## Use FuXi for semantic web reasoning (RDF, OWL, SPARQL)

FuXi is a Python bi-directional reasoning engine (forward + backward chaining) for RDF/OWL/SPARQL with CLI tools for ontology management and query answering.

## Installation

Use uv whenever possible (see https://github.com/uv-python/uv)
```bash
uv pip install fuxi owl_dsl          # or: uv pip install -e ".[dev]"
```

## Tools / Commands

The following OWL tools are available to the agent for ontology management functions

Available tools: `check-ontology`, `class-entailments`, `create-ontology`, `dir-ontology`, `extract-class`, `find-ontology-class`, `find-ontology-property`, `list-ontologies`, `ontology-measure-essentials`, `ontology-report`, `set-label`, `set-alt-label`, `set-editorial-note`, `set-human-readable-definition`, `set-annotation`, `sparql-interlocution`. See [sw-tools.md](sw-tools.md) for argument details.

For more on the principles of Semantic Web architecture, see [semantic-web-architecture.md](semantic-web-architecture.md)

### Using `class-entailments` (ELK reasoner)

Explains why a class is subsumed by its parents — useful for ontology QA. See [sw-tools.md](sw-tools.md) for full reference and caveats (import resolution, SQLite locking, URI conventions).

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

`fuxi.core` (forward chaining), `fuxi.proof` (BFP queries), `fuxi.owl` (OWL→DLP)

Common flags: `--rules PATH`, `--output FORMAT`, `--ns PREFIX=URI`, `--why "SPARQL"`, `--method {naive,bfp}`.

Output formats: `ttl`, `n3`, `nt`, `xml`, `conflict`, `rif`, `man-owl`, `adornment` (adorned rules), `pml` (proof serialization), `proof-graph-svg/png`, `rete-network-svg/png`, `sip-collection-svg/png`.

## Workflow: from ontology analysis to entailed queries

The `sparql-interlocution` tool combines a local OWL TBox (DLP), optional N3 rules, and a remote SPARQL endpoint (EDB).

1. **Analyze the ontology** — use `verbalize-ontology-class`, `dir-ontology`, `find-ontology-class` to understand its vocabulary.
2. **Prepare data** — parse N-Quads with `rdflib.Dataset()` (not `Graph()`). Flatten to a single `Graph` for entailment.
3. **Discover EDB predicates** — query `SELECT DISTINCT ?pred WHERE { ?s ?pred ?o } LIMIT 50` on the endpoint.
4. **Write N3 bridge rules** — derive semantic predicates from EDB predicates (see [advanced.md](advanced.md)).
5. **Query** — pass endpoint, bindings, query, OWL file, and rules. Derived predicates are **auto-discovered** from rule heads (DLP + N3 + OWL semantics) by FuXi's `derived_predicate_iterator`.
6. **Override (optional)** — restrict the derived set by passing it explicitly.

### Remote SPARQL Endpoints as a Graph

Use `SPARQLServiceGraph` directly or with `owl_entailment_regime_graph` and `sparql_interlocution`. `owl_entailment_regime_graph()` requires a positional `ns_map: dict[str, Identifier]` argument.

### Auto-Discovery of Derived Predicates

When omitted, FuXi's `TopDownSPARQLEntailingStore` auto-discovers derived predicates by scanning rule heads (DLP rules, OWL 2 RL semantics, N3 rules). Override manually when restricting the derived set.

For more advanced topics see [sw-tools.md](sw-tools.md), [advanced.md](advanced.md), and [owl2_sparql_entailment.md](owl2_sparql_entailment.md)

## Notes
