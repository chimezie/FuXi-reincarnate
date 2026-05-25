You can check an ontology for issues by using the `check-ontology` tool. This uses robot and will print a report of any issues.  
You can also provide a path to a file (using the `reportFile` option) where the report will be saved as JSON. There is
also a labels options, which will print the labels of the ontology classes and properties if specified (default is False).

When verbalizing an ontology with `verbalize-ontology-class`, you don't need a configuration file if the ontology
has owl-dsl annotations about how to render it.  It is an invaluable tool for better understanding the vocabulary 
in an ontology via introspection.

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
the `baseuri` argment and used to resolve local names wen used with the `byId` argument and usually ends in '#' or '/' .

For tools that refer to a particular class, the `classReference` argument is either the local part of the class URI
(when used with `byId`) or the label of the class.

The `owl_file` field value is the source OWL file and corresponds to the `owlFile` argument.

For the `find-ontology-class` tool, the `classSearch` argument is a string or regular expression to match the class label.
The `regexSearch` argument is a boolean flag to indicate whether the class label should be treated as a regular expression.

The `class-entailments` tool runs the ELK reasoner and prints class definitions with entailment explanations.
It uses the same `ontologyUri`, `baseuri`, `sqliteFile`, `owlFile`, and `classReference` arguments as other tools.

⚠️ **Caveats**:
- **Import resolution**: Invokes the Java OWL API which fetches all `owl:imports`. If any import URL is unreachable the tool fails. Ensure imports resolve, or temporarily remove `<owl:imports>` from the OWL file.
- **SQLite locking**: Avoid parallel calls against the same `sqliteFile`. Run sequentially.
- **`ontologyUri` vs `baseuri`**: `ontologyUri` should have **no** trailing `#`; `baseuri` **must** end in `#` or `/` to resolve local names.
- **`owlFile` is required**: Even with `sqliteFile` provided, the tool reads the raw OWL file through Java OWL API.
- **`byId`**: When set, `classReference` is treated as a local name (the URI fragment after `baseuri`); otherwise it matches `rdfs:label`.

You can use the `sparql-interlocution` tool to query a remote, independent SPARQL service which uses terms from an
ontology (you can analyze) to ask questions over SPARQL entailment regimes in which an ontology's entailments are in 
effect and taking advantage of FuXi to reason to introspect over the ontology and write more intelligent queries 
to get more intelligent answers to them. Before using this tool, you may want to run `create-ontology` on the given 
ontology, run `ontology-report` on it, and `verbalize-ontology-class` on its classes to get a better understanding of 
the vocabulary via ontology introspection.

### N-Quads handling

When the fact store is in N-Quads format (quad data with named graphs), **do not** parse with `rdflib.Graph().parse(format='nquads')` — it silently loads 0 triples. Use `rdflib.Dataset().parse(format='nquads')` instead, then flatten to a single `Graph` for the entailment pipeline:

```python
from rdflib import Dataset, Graph
ds = Dataset()
ds.parse('data.nq', format='nquads')
flat = Graph()
for ctx in ds.graphs():
    for s, p, o in ctx:
        flat.add((s, p, o))
```

If the N-Quads file has encoding issues, clean it with `riot` (Apache Jena). Note: riot writes output to stderr (Java logging quirk), so redirect streams separately:

```bash
JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64 \
riot --syntax=nquads --output=nquads input.nq \
  2>/dev/null > clean.nq
```

### `ns_map` requirement

The `owl_entailment_regime_graph()` Python function requires a positional `ns_map: dict[str, Identifier]` argument for prefix-to-namespace bindings. This maps namespace prefixes used in the OWL ontology to their URIs so the DLP rule extractor can resolve them. Example:

```python
ns_map = {
    'wen': 'http://example.org/onto#',
    'rdf': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#',
}
```

### PyPI note

The `sparql-interlocution` tool wraps the Python API function `sparql_interlocution(query, top_down_store)`. The Python function takes a SPARQL string and a `TopDownSPARQLEntailingStore` (produced by `owl_entailment_regime_graph`). The tool handles the setup of `SPARQLServiceGraph` + `owl_entailment_regime_graph` for you.

Arguments:

- `sparqlServiceGraph` (required): URL of the SPARQL endpoint to query (e.g. `http://localhost:7000/`).
- `nsBindings` (required): JSON object mapping prefixes to namespace URIs.
- `query` (required): The SPARQL query string to execute.
- `owlFile` (optional): Path to an OWL file for the TBox ontology.
- `rulesFile` (optional): Path to an N3 rules file for custom entailment rules.
- `hybridPredicates` (optional): JSON array of hybrid predicate URIs. When omitted, hybrid predicates are auto-detected if `identify_hybrid_predicates` is True (scans for predicates in both EDB and rule heads).
- `derivedPredicates` (optional): JSON array of derived predicate URIs — answered via backward-chaining over the rule program. **When omitted**, predicates are auto-derived by `derived_predicate_iterator` which scans rule heads in the combined OWL DLP rules + N3 rules + OWL 2 RL semantics. Pass an empty array `[]` to suppress all derivation.

The tool returns JSON results: a list of result rows, or a boolean for ASK queries.
