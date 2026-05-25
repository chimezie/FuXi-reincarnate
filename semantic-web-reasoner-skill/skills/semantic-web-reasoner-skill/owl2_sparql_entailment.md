The `sparql_interlocution` method facilitates SPARQL entailment. It takes a SPARQL query string and a `TopDownSPARQLEntailingStore` as arguments, and yields solution dictionaries.

### Local Graph (all-in-memory)

```python
from fuxi.SPARQL.utilities import sparql_interlocution, owl_entailment_regime_graph
from fuxi.types import Variable, RDFTerm
from rdflib import Graph

fact_graph = Graph().parse("ontology.ttl")

entailing_graph, _ = owl_entailment_regime_graph(
    fact_graph,
    # derived_predicates omitted → auto-derived from rule heads
    add_pd_semantics = False,
    add_non_dhl_owl_rules = True,
)
for answer in sparql_interlocution(" .. sparql query ..", entailing_graph.store):
    answer: dict[Variable, RDFTerm]
    user_readable_dict = {f"?{k} -> {v.n3()}" for k, v in answer.items()}
    # Use answers in subsequent query, etc.
```

`identify_hybrid_predicates`, `hybrid_predicates`, and `derived_predicates` are all optional — when omitted, predicates are auto-discovered from rule heads via `derived_predicate_iterator`. For the default `identify_hybrid_predicates=True`, FuXi intersects the auto-derived set against the EDB facts; predicates found in both have their IDB role renamed to `<pred>_derived` internally to avoid name clashes.

### Remote SPARQL endpoint + local TBox (recommended for large datasets)

When the instance data lives behind a remote SPARQL endpoint (e.g., QLever, Virtuoso, Blazegraph), the TBox (OWL schema) should be loaded locally for DLP compilation. The `sparql-interlocution` tool does this automatically when `owlFile` is provided: it uses the local OWL file for description logic programming (classes, properties, domain/range axioms) and the remote endpoint as the EDB for instance queries only.

```python
from fuxi.SPARQL.utilities import sparql_interlocution, owl_entailment_regime_graph
from fuxi.types import Variable, RDFTerm
from fuxi.SPARQL.service import SPARQLServiceGraph 
from rdflib import Graph

# Load the TBox (ontology schema) locally
tbox_graph = Graph()
tbox_graph.parse("imdb.owl")

# Remote SPARQL endpoint serves as EDB (instance data)
fact_graph = SPARQLServiceGraph("http://localhost:7000")
fact_graph.namespace_manager = tbox_graph.namespace_manager

# Parse N3 rules for derived predicates
from io import StringIO
from fuxi.Horn.HornRules import horn_from_n3

n3_rules = list(horn_from_n3(StringIO("""... N3 rules ...""")))
ns_map = {"imdb": "https://www.imdb.com/", "my": "tag:info@..."}

# DLP runs against tbox_graph; EDB queries go to fact_graph
# derived_predicates omitted → FuXi auto-discovers from rule heads
entailing_graph, _ = owl_entailment_regime_graph(
    fact_graph,
    ns_map=ns_map,
    tbox_only_graph=tbox_graph,
    extra_rulesets=n3_rules,
    add_pd_semantics=False,
    add_non_dhl_owl_rules=True,
)
for answer in sparql_interlocution(" .. sparql query ..", entailing_graph.store):
    answer: dict[Variable, RDFTerm]
    user_readable_dict = {f"?{k} -> {v.n3()}" for k, v in answer.items()}
    # Use answers in subsequent query, etc.
```

Key point: `owl_entailment_regime_graph` handles DLP internally — when `tbox_only_graph` is provided, it uses that for OWL→Horn compilation instead of the fact graph. Never pass the SPARQL endpoint graph directly to DLP; compile the TBox locally. The `derived_predicates` parameter is optional in all cases — omit it to let FuXi auto-discover IDB predicates from the combined rule set (DLP + OWL semantics + N3 rules).

### SPARQLServiceGraph (remote SPARQL, no entailment)

You can also use rdflib to query remote SPARQL endpoints directly (no FuXi entailment):

```python
from rdflib import Graph
from rdflib.plugins.stores.sparqlstore import SPARQLStore

endpoint = "https://dbpedia.org/sparql"

store = SPARQLStore(endpoint)
g = Graph(store=store)

for row in g.query(".. SPARQL query .."):
    print(row.label)
```
