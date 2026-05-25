
# /// script
# requires-python = ">=3.11"
# dependencies = ["rdflib", "fuxi"]
# ///
"""
sparql-interlocution.py — Execute SPARQL queries with OWL entailment via FuXi

Positional arguments:
1. SPARQL endpoint URL
2. nsBindings (JSON: {"prefix": "uri", ...})
3. SPARQL query string
4. Path to OWL file for TBox (ontology), or "--" for none
5. Path to N3 rules file, or "--" for none
6. Hybrid predicates (JSON array of URIs), or "--" for none
7. Derived predicates (JSON array of URIs), or "--" for none
"""
import json
import sys
from io import StringIO
from pathlib import Path

from fuxi.Horn.HornRules import horn_from_n3
from fuxi.SPARQL.service import SPARQLServiceGraph
from fuxi.SPARQL.utilities import owl_entailment_regime_graph, sparql_interlocution
from rdflib import Graph, URIRef


def collect_head_predicates(ruleset):
    """Extract all head predicates from a ruleset (N3 or DLP)."""
    preds = set()
    for rule in ruleset:
        head = rule.formula.head
        if hasattr(head, "op"):
            preds.add(URIRef(str(head.op)))
        if hasattr(head, "formulae"):
            for sub in head.formulae:
                if hasattr(sub, "op"):
                    preds.add(URIRef(str(sub.op)))
    return preds


def main():
    if len(sys.argv) < 4:
        print(__doc__, file=sys.stderr)
        sys.exit(1)

    endpoint_url = sys.argv[1]
    ns_bindings = json.loads(sys.argv[2])
    query = sys.argv[3]
    owl_file = sys.argv[4] if len(sys.argv) > 4 and sys.argv[4] not in ("", "--") else None
    rules_file = sys.argv[5] if len(sys.argv) > 5 and sys.argv[5] not in ("", "--") else None
    hybrid_predicates = []
    if len(sys.argv) > 6 and sys.argv[6] and sys.argv[6] != "--":
        hybrid_predicates = [URIRef(hp) for hp in json.loads(sys.argv[6])]
    derived_predicates = None
    if len(sys.argv) > 7 and sys.argv[7] and sys.argv[7] != "--":
        derived_predicates = [URIRef(dp) for dp in json.loads(sys.argv[7])]

    ns_map = {k: URIRef(v) for k, v in ns_bindings.items()}

    tbox_graph = None
    if owl_file:
        tbox_graph = Graph()
        tbox_graph.parse(owl_file)
        for prefix, uri in ns_bindings.items():
            tbox_graph.bind(prefix, URIRef(uri))

    fact_graph = SPARQLServiceGraph(endpoint_url)
    ns_graph = Graph()
    for prefix, uri in ns_bindings.items():
        ns_graph.bind(prefix, URIRef(uri))
    fact_graph.namespace_manager = ns_graph.namespace_manager

    program = []
    if rules_file:
        n3_rules = list(horn_from_n3(StringIO(Path(rules_file).read_text())))
        for rule in n3_rules:
            rule.ns_mapping.update(ns_bindings)
        program.extend(n3_rules)

    # Merge explicit derived predicates with those from N3 rules (if any).
    derived_preds = set(derived_predicates) if derived_predicates else set()
    if rules_file:
        derived_preds.update(collect_head_predicates(program))


    entailing_graph, _ = owl_entailment_regime_graph(
        fact_graph,
        ns_map=ns_map,
        identify_hybrid_predicates=False,
        hybrid_predicates=hybrid_predicates,
        derived_predicates=list(derived_preds) if derived_preds else None,
        extra_rulesets=program or None,
        tbox_only_graph=tbox_graph,
        add_pd_semantics=False,
        add_non_dhl_owl_rules=True,
        namespace_manager=ns_graph.namespace_manager,
    )

    results = []
    for answer in sparql_interlocution(query, entailing_graph.store):
        if isinstance(answer, bool):
            results.append({"type": "boolean", "value": answer})
        else:
            row = {}
            for var, val in answer.items():
                row[str(var)] = val.n3() if hasattr(val, "n3") else str(val)
            results.append(row)

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
