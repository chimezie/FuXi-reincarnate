from collections.abc import Mapping
from typing import Any

from rdflib.plugins.sparql.sparql import Query
from rdflib.query import Processor, Result
from rdflib.term import Identifier

from fuxi.Horn.PositiveConditions import build_uniterm_from_tuple
from fuxi.SPARQL import EDBQuery
from rdflib import Graph


class SPARQLServiceGraph(Graph):
    """
    A query-only graph wrapper for a remote SPARQL service.

    This class mediates SPARQL query evaluation by extracting the basic graph
    pattern (BGP) from a query, compiling it into an ``EDBQuery``, and issuing
    a service query against the configured SPARQL endpoint. It is designed to
    plug into FuXi's SPARQL entailment machinery so you can implement SPARQL 1.1
    entailment regimes over remote services independent of any
    reasoning capabilities of the service.

    ## How It Works
    1. Parse a SPARQL query and extract the BGP.
    2. Convert the BGP into an ``EDBQuery``.
    3. Emit a SPARQL SERVICE query against ``service_url``.
    4. Return the remote endpoint results.

    ## Entailment Regimes
    In the SPARQL 1.1 entailment specification, regimes include:
    - Simple
    - RDF
    - RDFS
    - OWL Direct Semantics
    - OWL RDF-Based Semantics
    - RIF (RIF Core entailment)
    - D Entailment

    FuXi supports rule-based entailment by providing an intensional
    database (IDB)
    of rules and derived predicates. ``SPARQLServiceGraph`` provides the
    extensional database (EDB) access layer for data living behind a
    SPARQL service.

    ## Example
    ```python
from rdflib import Graph, Variable
    from rdflib.plugins.sparql.parser import parseQuery
    from fuxi.SPARQL import TopDownSPARQLEntailingStore
    from fuxi.SPARQL.utilities import extract_triples_from_query

    parsed_query = parseQuery(".. SPARQL query ..")
    _, query_structure = parsed_query
    service_url, _ = extract_triples_from_query(query_structure, [..])

    service_graph = SPARQLServiceGraph(service_url)
    entailing_graph, closure_delta_graph = owl_entailment_regime_graph(
        service_graph,
        ns_map,
        identify_hybrid_predicates=True,
        derived_predicates=None,
        hybrid_predicates=None,
        goals=goals,
        namespace_manager=namespace_manager,
        extra_rulesets=horn_from_n3(StringIO(thing_rule)),
        verbose=debug,
    )

    top_down_store = TopDownSPARQLEntailingStore(
        service_graph.store,
        service_graph,
        idb=program,
        derived_predicates=derived_predicates,
        identify_hybrid_predicates=False,
        hybrid_predicates=[..],
    )

    result = Graph(store=top_down_store).query(parsed_query, [..])
    ```

    ## Notes
    - ``triples()`` is not supported; this graph is intended for query mediation.
    - The remote service is the EDB, while FuXi rules provide the IDB.
    """

    def __init__(self, service_url: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.service_url = service_url
        self.num_queries = 0

    def __repr__(self):
        return f"SPARQLServiceGraph(service_url='{self.service_url}')"

    def _sparql_post(self, query_str: str) -> dict | None:
        """Execute a SPARQL query against the endpoint and return parsed JSON."""
        import requests as req
        prefix_lines = "".join(
            f"PREFIX {p}: <{ns}>\n"
            for p, ns in self.namespace_manager.namespaces()
            if ns != "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
        )
        if not query_str.lstrip().upper().startswith("PREFIX"):
            query_str = prefix_lines + query_str
        try:
            resp = req.post(
                self.service_url,
                data=query_str,
                headers={
                    "Content-Type": "application/sparql-query",
                    "Accept": "application/sparql-results+json",
                },
                timeout=120,
            )
            resp.raise_for_status()
            self.num_queries += 1
            return resp.json()
        except Exception:
            self.num_queries += 1
            return None

    def triples(self, triple, context=None):
        from rdflib import Variable
        ns_map = {prefix: uri for prefix, uri in self.namespace_manager.namespaces()}
        s, p, o = triple
        vars = []
        tp = list(triple)
        if s is None:
            v = Variable("s")
            tp[0] = v
            vars.append(v)
        if o is None:
            v = Variable("o")
            tp[2] = v
            vars.append(v)
        query_literal = EDBQuery([build_uniterm_from_tuple(tuple(tp), ns_map)], self, vars or None)
        mediated_query = query_literal.as_sparql() + " LIMIT 10000"
        results = self._sparql_post(mediated_query)
        if results is None:
            return iter([])
        for binding in results.get("results", {}).get("bindings", []):
            s_val = self._parse_term(binding.get("s"))
            p_val = self._parse_term(binding.get("p"))
            o_val = self._parse_term(binding.get("o"))
            yield (s_val or s, p_val or p, o_val or o)

    def _parse_term(self, term_dict):
        if term_dict is None:
            return None
        from rdflib import BNode, Literal, URIRef
        typ = term_dict.get("type")
        val = term_dict.get("value")
        if typ == "uri":
            return URIRef(val)
        elif typ == "bnode":
            return BNode(val)
        elif typ == "literal":
            dtype = term_dict.get("datatype")
            lang = term_dict.get("xml:lang")
            if lang:
                return Literal(val, lang=lang)
            elif dtype:
                return Literal(val, datatype=URIRef(dtype))
            else:
                return Literal(val)
        return None

    def query(
        self,
        query_object: str | Query,
        processor: str | Processor | None = "sparql",
        result: str | type[Result] | None = "sparql",
        initNs: dict[str, Identifier] | None = None,
        initBindings: Mapping[str, Identifier] | None = None,
        use_store_provided: bool = True,
        **kwargs: Any,
    ) -> Result:
        """Execute SPARQL query by forwarding to the remote endpoint via HTTP."""
        query_str = str(query_object) if not isinstance(query_object, str) else query_object
        data = self._sparql_post(query_str)
        if data is None:
            return _empty_result(query_str)
        return _json_to_result(data, query_str)


class _AskResult:
    """Minimal result wrapper for ASK queries (checking .askAnswer)."""
    def __init__(self, answer: bool):
        self.askAnswer = answer

    def __iter__(self):
        return iter([])


class _SelectResult:
    """Minimal result wrapper for SELECT queries."""
    def __init__(self, vars, bindings):
        self.vars = vars
        self._bindings = bindings

    def __iter__(self):
        for b in self._bindings:
            yield b


def _empty_result(query_str: str):
    if "ASK" in query_str.upper():
        return _AskResult(False)
    return _SelectResult([], [])


def _json_to_result(data: dict, query_str: str):
    import rdflib

    head = data.get("head", {})
    vars = head.get("vars", [])
    results = data.get("results", {})
    bindings = results.get("bindings", [])

    # ASK query
    if "boolean" in data:
        return _AskResult(data["boolean"])

    # SELECT query
    rows = []
    for b in bindings:
        row = {}
        for var in vars:
            term_dict = b.get(var)
            if term_dict is None:
                continue
            typ = term_dict.get("type")
            val = term_dict.get("value")
            if typ == "uri":
                row[var] = rdflib.URIRef(val)
            elif typ == "bnode":
                row[var] = rdflib.BNode(val)
            elif typ == "literal":
                dtype = term_dict.get("datatype")
                lang = term_dict.get("xml:lang")
                if lang:
                    row[var] = rdflib.Literal(val, lang=lang)
                elif dtype:
                    row[var] = rdflib.Literal(val, datatype=rdflib.URIRef(dtype))
                else:
                    row[var] = rdflib.Literal(val)
        rows.append(row)
    return _SelectResult(vars, rows)

class ServiceGraphPatternError(Exception):
    """
    Utility, parse-time exception for help with extracting SPARQL service
    request URLs and their graph pattern for later reference
    """

    def __init__(self, service_url, graph_pattern):
        self.service_url = service_url
        self.graph_pattern = graph_pattern

    def __str__(self):
        return f"BGP: {self.graph_pattern} for service at {self.service_url}"
