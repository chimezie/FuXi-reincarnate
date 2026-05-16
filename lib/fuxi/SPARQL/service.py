from collections.abc import Mapping
from itertools import chain
from typing import Any

from rdflib.plugins.sparql.parser import parseQuery
from rdflib.plugins.sparql.sparql import Query
from rdflib.query import Processor, Result
from rdflib.term import Identifier, Variable

from fuxi.Horn.PositiveConditions import build_uniterm_from_tuple
from fuxi.Rete.SidewaysInformationPassing import get_variables
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

    def triples(self, triple, context=None):
        ns_map = {prefix: uri for prefix, uri in self.namespace_manager.namespaces()}
        query_literal = EDBQuery([build_uniterm_from_tuple(triple, ns_map)], self, None)
        mediated_query = query_literal.as_sparql(service_url=self.service_url)
        response = Graph().query(
            mediated_query, init_ns=ns_map
        )
        self.num_queries += 1
        return response

        raise RuntimeError("SPARQLServiceGraph does not support triples()")

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
        """
        Executes a SPARQL query against the remote service, extracting
        the graph pattern, converting them to an EDBQuery for a
        SPARQL service query

        :param query_object: The SPARQL query string or parsed Query object.
        :param processor: The query processor to use, defaults to 'sparql'.
        :param result: The result format, defaults to 'sparql'.
        :param initNs: Initial namespace bindings, defaults to None.
        :param initBindings: Initial variable bindings, defaults to None.
        :param use_store_provided: Whether to use store-provided results,
               defaults to True.
        :param kwargs: Additional keyword arguments for query execution.
        :return: The query result.
        """
        from fuxi.SPARQL.utilities import extract_triples_from_query

        _, parsed_query = parseQuery(query_object)
        _service_url, triples = extract_triples_from_query(parsed_query, initNs)
        uniterms = [build_uniterm_from_tuple(triple, initNs) for triple in triples]
        vars = [
            *set(
                chain(
                    *map(
                        lambda uniterm: get_variables(uniterm, second_order=True),
                        uniterms,
                    )
                )
            )
        ]
        conjunct = EDBQuery(uniterms, self, vars)
        mediated_query = conjunct.as_sparql(service_url=self.service_url)
        response = Graph().query(
            mediated_query, initNs=initNs, initBindings=initBindings
        )
        self.num_queries += 1
        return response

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
