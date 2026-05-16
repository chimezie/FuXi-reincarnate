from typing import TYPE_CHECKING

from pyparsing import ParseResults
from rdflib.graph import Graph
from rdflib.namespace import NamespaceManager
from rdflib.plugins.sparql.parser import parseQuery
from rdflib.plugins.sparql.parserutils import CompValue
from rdflib.plugins.sparql.processor import SPARQLResult
from rdflib.query import Result
from rdflib.term import Identifier, Literal, Variable

from fuxi.types import Triple
from rdflib import RDF, URIRef

if TYPE_CHECKING:
    from fuxi.Horn.HornRules import Ruleset
    from fuxi.SPARQL.BackwardChainingStore import TopDownSPARQLEntailingStore


def owl_entailment_regime_graph(
    graph: Graph,
    ns_map: dict[str, Identifier],
    reasoning_method: int = -1,
    identify_hybrid_predicates: bool = True,
    hybrid_predicates: list[URIRef] = None,
    derived_predicates: list[Identifier] = None,
    goals: list[Triple] = None,
    extra_rulesets: list["Ruleset"] | None = None,
    verbose: bool = False,
    namespace_manager: NamespaceManager = None,
    add_pd_semantics: bool = False,
    add_non_dhl_owl_rules: bool = True,
    tbox_only_graph: Graph = None
):
    """
    Build a goal-directed OWL entailment graph for SPARQL interlocution.

    This helper wires together the DLP rules extracted from OWL/RDF, the RETE-UL
    decision network, and the TopDownSPARQLEntailingStore so that SPARQL queries
    are mediated rather than fully materialized. The returned graph answers queries
    by issuing only the necessary subqueries against the base RDF graph and combining
    bindings according to the ruleset. Derived triples are not inserted into the
    original graph; they are computed on-demand as part of query evaluation.

    Execution flow (conceptual):
    1. Parse the user query into triple patterns (goals).
    2. Rewrite goals into a rule-oriented form (derived vs base predicates).
    3. Derived predicates are resolved via rules; base predicates trigger SPARQL
       queries against the fact graph.
    4. Bindings propagate across rule bodies until a fixpoint is reached.
    5. Answers are returned without mutating the source graph.

    :param graph: Fact graph that provides base (EDB) predicates and the store to query.
    :type graph: Graph
    :param ns_map: Prefix-to-namespace bindings used by the SPARQL entailment store
        for QName rendering and query mediation.
    :type ns_map: dict[str, Identifier]
    :param reasoning_method: Reasoning method for the TopDownSPARQLEntailingStore. Use
        ``-1`` to default to ``BFP_METHOD`` (Backward Fixpoint Procedure).
    :type reasoning_method: int, optional
    :param identify_hybrid_predicates: When True, scans the fact graph to detect
        predicates that are both derived (IDB) and base (EDB) for SIP optimization.
    :type identify_hybrid_predicates: bool, optional
    :param hybrid_predicates: Explicit list of hybrid predicates (in both IDB and EDB).
        Use when you want to avoid graph scanning or be explicit about overlap.
    :type hybrid_predicates: List[URIRef], optional
    :param derived_predicates: Derived predicate URIs (IDB). When provided, these
        guide SIP and rule rewriting without scanning the fact graph. If ``goals``
        is also provided, the derived predicates inferred from goals are appended.
    :type derived_predicates: List[Identifier], optional
    :param goals: Goal triples (SPARQL BGPs) used to infer derived predicates. For
        each goal tuple ``(s, p, o)``, the derived predicate is ``o`` when
        ``p == RDF.type``; otherwise it is ``p``. When provided without
        ``derived_predicates``, the goal-derived predicates are used as the IDB
        predicate set.
    :type goals: List[Triple], optional
    :param extra_rulesets: Additional Ruleset instances to append to the OWL/DLP
        rules before building the SPARQL entailment store.
    :type extra_rulesets: List[Ruleset], optional
    :param verbose: Enables debug output from the entailment store.
    :type verbose: bool, optional
    :param namespace_manager: Namespace manager for the closure delta graph, used to
        serialize inferred triples if you choose to inspect the delta graph directly.
    :type namespace_manager: NamespaceManager, optional
    :param add_non_dhl_owl_rules: Enables additional OWL rules beyond those used in
        the Description Logic Horn (DLH) fragment.
    :type add_non_dhl_owl_rules: bool, optional
    :param tbox_only_graph: If provided, only the TBox (ontology) part of
           the graph will be used for entailment.
    :type tbox_only_graph: Graph, optional

    :return: Tuple of (entailment graph, closure delta graph).
    :rtype: Tuple[Graph, Graph]
    :type tbox_only_graph

    Example (goal-directed mediation):
    >>> from rdflib import Graph, Namespace
    >>> ex = Namespace("http://example.org/")
    >>> fact_graph = Graph()
    >>> _ = fact_graph.add((ex.alice, ex.parentOf, ex.bob))
    >>> ns_map = {"ex": ex}
    >>> entail_graph, _ = owl_entailment_regime_graph(fact_graph, ns_map)
    >>> # Queries against entail_graph are mediated and may use derived predicates.
    >>> list(entail_graph.triples((ex.alice, ex.parentOf, None)))
    [(rdflib.term.URIRef('http://example.org/alice'),
      rdflib.term.URIRef('http://example.org/parentOf'),
      rdflib.term.URIRef('http://example.org/bob'))]
    """
    from io import StringIO

    from fuxi.DLP import NON_DHL_OWL_SEMANTICS
    from fuxi.DLP.ConditionalAxioms import additional_rules
    from fuxi.Horn.HornRules import horn_from_n3
    from fuxi.Rete.RuleStore import setup_rule_store
    from fuxi.SPARQL.BackwardChainingStore import (
        TopDownSPARQLEntailingStore,
    )

    if hybrid_predicates is None:
        hybrid_predicates = []
    if derived_predicates is None:
        derived_predicates = None
    goal_derived_predicates: set[Identifier] = set()
    if goals:
        goal_derived_predicates = {
            (obj if pred == RDF.type else pred) for _subj, pred, obj in goals
        }
    if goal_derived_predicates:
        if derived_predicates:
            derived_predicates = list(
                dict.fromkeys([*derived_predicates, *goal_derived_predicates])
            )
        elif derived_predicates is not None:
            derived_predicates = list(dict.fromkeys(goal_derived_predicates))
    _, _, network = setup_rule_store(make_network=True)
    closure_delta_graph = Graph()
    closure_delta_graph.namespace_manager = namespace_manager
    network.inferred_facts = closure_delta_graph
    if add_non_dhl_owl_rules:
        rules = list(horn_from_n3(StringIO(NON_DHL_OWL_SEMANTICS)))
    else:
        rules = []
    rules.extend(
        network.setup_description_logic_programming(
            graph if tbox_only_graph is None else tbox_only_graph,
            add_pd_semantics=add_pd_semantics,
            construct_network=False)
    )
    if not tbox_only_graph:
        for rule in additional_rules(graph):
            rules.append(rule)
    if extra_rulesets:
        rules.extend(extra_rulesets)
    top_down_store = TopDownSPARQLEntailingStore(
        graph.store,
        graph,
        derived_predicates=derived_predicates,
        idb=rules,
        debug=verbose,
        ns_bindings=ns_map,
        identify_hybrid_predicates=identify_hybrid_predicates,
        hybrid_predicates=hybrid_predicates
    )
    return Graph(top_down_store), closure_delta_graph


def sparql_query_from_result(result: Result) -> SPARQLResult:
    ask_answer = getattr(result, "askAnswer", None)
    if ask_answer is None:
        ask_answer = getattr(result, "ask_answer", None)
    if ask_answer is None and result.type == "SELECT":
        ask_answer = bool(result.bindings)
    mapping = {
        "type_": result.type,
        "vars_": result.vars,
        "bindings": result.bindings,
        "askAnswer": ask_answer,
        "graph": result.graph,
    }
    return SPARQLResult(mapping)


def extract_list_from_comp_values(
    query_structure: CompValue, field: str
) -> list[ParseResults | CompValue | list[CompValue]]:
    items = query_structure[field]
    assert isinstance(items, list)
    for component in items:
        if isinstance(component, ParseResults):
            yield list(component)
        elif isinstance(component, CompValue):
            yield component
        else:
            raise Exception(f"Unknown type: {type(component)}")


def extract_triples_from_triple_part(
    triple_part: CompValue, ns_binds: dict[str, URIRef]
) -> tuple[URIRef, URIRef, URIRef]:
    if isinstance(triple_part, Identifier):
        return triple_part
    elif triple_part.name == "pname":
        return URIRef(ns_binds[triple_part.prefix] + triple_part.localname)
    elif triple_part.name == "PathAlternative":
        return extract_triples_from_triple_part(
            triple_part.part[0].part[0].part, ns_binds
        )
    elif triple_part.name == "literal":
        literal = triple_part.string
        datatype = triple_part.datatype
        if datatype is not None:
            return Literal(literal.value, datatype=datatype)
        return literal
    else:
        raise Exception(f"Unknown type: {type(triple_part)}")


def extract_triples_from_query(
    query_structure: CompValue, ns_binds: dict[str, URIRef], triples: list | None = None
) -> tuple[URIRef | None, list[Triple]]:
    triples = triples if triples is not None else []
    service_url = None
    if query_structure.name == "AskQuery":
        component = query_structure.where
        assert isinstance(component, CompValue)
        service_url, _ = extract_triples_from_query(component, ns_binds, triples)
    elif query_structure.name == "GroupGraphPatternSub":
        for component in extract_list_from_comp_values(query_structure,
                                                       "part"):
            child_service_url, _ = extract_triples_from_query(
                component, ns_binds, triples
            )
            if service_url is None and child_service_url is not None:
                service_url = child_service_url
    elif query_structure.name in "TriplesBlock":
        if isinstance(query_structure.triples, list) and all(

                isinstance(item, list) and len(item) == 3
                for item in query_structure.triples

        ):
            triples.extend(query_structure.triples)
        else:
            for item in extract_list_from_comp_values(query_structure,
                                                      "triples"):
                if isinstance(item, list) and len(item) == 3:
                    triples.append(
                        tuple(
                            map(
                                lambda i: extract_triples_from_triple_part(
                                    i,
                                    ns_binds
                                ),
                                item,
                            )
                        )
                    )
                else:
                    for i in item:
                        extract_triples_from_triple_part(i, ns_binds)
                    triples.extend([
                        tuple(
                            extract_triples_from_triple_part(part, ns_binds)
                            for part in item[i: i + 3]
                        )
                        for i in range(0, len(item), 3)
                    ])
    elif query_structure.name == "BGP":
        triples.extend(query_structure.triples)
    elif query_structure.name == "SelectQuery":
        service_url, _ = extract_triples_from_query(
            query_structure.p
            if query_structure.p is not None
            else query_structure.where,
            ns_binds,
            triples,
        )
    elif query_structure.name == "Project":
        service_url, _ = extract_triples_from_query(
            query_structure.p, ns_binds, triples
        )
    elif query_structure.name == "ServiceGraphPattern":
        if service_url is not None:
            raise NotImplementedError(
                "Multiple SERVICE patterns are not supported")
        service_url = query_structure.term
        child_service_url, _ = extract_triples_from_query(
            query_structure.graph, ns_binds, triples
        )
        if child_service_url is not None:
            raise NotImplementedError(
                "Multiple SERVICE patterns are not supported")
    else:
        raise Exception(f"Unknown type: {type(query_structure)}")
    return service_url, triples


def sparql_interlocution(query: str, top_down_store: "TopDownSPARQLEntailingStore"):
    """
    Execute a SPARQL query against a TopDownSPARQLEntailingStore and yield solutions.

    It parses the query, extracts the basic graph pattern, converts
    triples to quads (with None as the fourth element), and uses the store's batch_unify
    to retrieve matching solutions.

    Only solutions where all query variables are bound are yielded.

    :param query: A SPARQL query string.
    :param top_down_store: A TopDownSPARQLEntailingStore instance configured with
        the rule program and EDB.
    :yields: Dictionaries mapping Variable objects to their bound values for each
        matching solution.

    Example:
        >>> for answer in sparql_interlocution(query, top_down_store):
        ...     movie = answer[Variable('movie')]
    """
    from fuxi.SPARQL.utilities import extract_triples_from_query

    _, parsed_query = parseQuery(query)
    _, triples = extract_triples_from_query(parsed_query, top_down_store.ns_bindings)
    variables: set[Variable] = set()
    for triple in triples:
        for part in triple:
            if isinstance(part, Variable):
                variables.add(part)
    quads = [triple + tuple([None]) for triple in triples]
    try:
        for answer in top_down_store.batch_unify(quads):
            if not variables.difference(answer):
                yield answer
    except (StopIteration, RuntimeError):
        pass
