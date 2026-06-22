from collections.abc import Mapping
from typing import TYPE_CHECKING

from pyparsing import ParseResults
from rdflib.graph import Graph
from rdflib.namespace import NamespaceManager
from rdflib.plugins.sparql.parser import parseQuery
from rdflib.plugins.sparql.parserutils import CompValue
from rdflib.plugins.sparql.processor import SPARQLResult
from rdflib.query import Result
from rdflib.term import Identifier, Literal

from fuxi.DLP import SKOLEMIZED_CLASS_NS
from fuxi.Rete.Magic import MAGIC
from fuxi.types import Triple
from rdflib import RDF, RDFS, BNode, Namespace, URIRef, Variable

BFP_NS = Namespace("http://dx.doi.org/10.1016/0169-023X(90)90017-8#")
BFP_RULE = Namespace("http://code.google.com/p/python-dlp/wiki/BFPSpecializedRule#")
PML = Namespace("http://inferenceweb.stanford.edu/2004/07/iw.owl#")
PML_PROV = Namespace("http://inferenceweb.stanford.edu/2006/06/pml-provenance.owl#")

namespaces_bindings = {
    "rdf": RDF,
    "bfp": BFP_NS,
    "rule": BFP_RULE,
    "rdfs": RDFS,
    "skolem": SKOLEMIZED_CLASS_NS,
    "pml": PML,
    "pml-prov": PML_PROV,
    "magic": MAGIC,
}

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
    tbox_only_graph: Graph = None,
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

    from fuxi.DLP.ConditionalAxioms import additional_rules
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
    rules = []
    rules.extend(
        network.setup_description_logic_programming(
            graph if tbox_only_graph is None else tbox_only_graph,
            add_pd_semantics=add_pd_semantics,
            construct_network=False,
        )
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
        hybrid_predicates=hybrid_predicates,
    )
    return Graph(top_down_store), closure_delta_graph


def sparql_query_from_result(result: Result) -> SPARQLResult:
    ask_answer = getattr(result, "askAnswer", None)
    if ask_answer is None:
        ask_answer = getattr(result, "ask_answer", None)
    if ask_answer is None and result.type == "SELECT":
        ask_answer = not bool(result.bindings)
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
        for component in extract_list_from_comp_values(query_structure, "part"):
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
            for item in extract_list_from_comp_values(query_structure, "triples"):
                if isinstance(item, list) and len(item) == 3:
                    triples.append(
                        tuple(
                            map(
                                lambda i: extract_triples_from_triple_part(i, ns_binds),
                                item,
                            )
                        )
                    )
                else:
                    for i in item:
                        extract_triples_from_triple_part(i, ns_binds)
                    triples.extend(
                        [
                            tuple(
                                extract_triples_from_triple_part(part, ns_binds)
                                for part in item[i : i + 3]
                            )
                            for i in range(0, len(item), 3)
                        ]
                    )
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
            raise NotImplementedError("Multiple SERVICE patterns are not supported")
        service_url = query_structure.term
        child_service_url, _ = extract_triples_from_query(
            query_structure.graph, ns_binds, triples
        )
        if child_service_url is not None:
            raise NotImplementedError("Multiple SERVICE patterns are not supported")
    else:
        raise Exception(f"Unknown type: {type(query_structure)}")
    return service_url, triples


def check(triple_1: tuple[Identifier], triple_2: list(tuple[Identifier])):
    """
    Matches a ground triple against a list of ungrounded triples,
    to identify which it can unify to.

    :param triple_1: A goal solved during BFP as a ground triple
    :param triple_2: A list of ungrounded triples solved during BFP
    :return: A ``(uniterm, matching_uniterm)`` tuple
    """
    from fuxi.Horn.PositiveConditions import build_uniterm_from_tuple
    from fuxi.Rete.SidewaysInformationPassing import get_op

    uniterm1 = build_uniterm_from_tuple(triple_1)
    for i in triple_2:
        uniterm2 = build_uniterm_from_tuple(i)
        arg_cmp = [
            tuple(
                (arg1 == arg2, isinstance(arg2, Variable))
                for arg1, arg2 in zip(uniterm1.arg, i.arg)
            )
            for i in uniterm2
        ]
        if get_op(uniterm1) == get_op(uniterm2) and all(
            same_arg or other_is_var for same_arg, other_is_var in arg_cmp
        ):
            # Same predicate and at least one match or variable placeholder
            return uniterm1, uniterm2


def reify_rdf_statement(graph: Graph, triple: Triple) -> BNode:
    """
    Reify an RDF statement into a blank node.
    """
    proof_stmt = BNode()
    graph.add((proof_stmt, RDF.type, RDF.Statement))
    graph.add((proof_stmt, RDF.subject, triple[0]))
    graph.add((proof_stmt, RDF.predicate, triple[1]))
    graph.add((proof_stmt, RDF.object, triple[2]))
    return proof_stmt


def sparql_interlocution_basic_graph_pattern(
    query: str,
    top_down_store: "TopDownSPARQLEntailingStore",
    generate_proofs: bool = False,
    ns_bindings: dict[str, Namespace] | None = None,
) -> SPARQLResult | tuple[SPARQLResult, dict[Triple, tuple]]:
    """
    Evaluate a SELECT BGP over a SPARQL Entailment regime that *joins* base
    (EDB) and derived (IDB) predicates, returning a ``SPARQLResult``.

    If generate_proofs is True, also returns truth maintainance information
    from the interlocutor.

    This function *augments* -- it does not replace -- the standard rdflib
    ``Graph.query`` entry point that dispatches to
    ``TopDownSPARQLEntailingStore.query`` -> ``solve_triple_pattern``.

    ``solve_triple_pattern`` partitions the BGP into an EDB group and an IDB
    group, evaluates the EDB group as a *single* SPARQL query, then evaluates
    each IDB pattern *independently* via the BFP and accumulates every binding
    into one flat list.  It deliberately does **not** thread bindings between
    patterns

    This function instead drives ``batch_unify`` -> ``conjunctive_sip_strategy``,
    the nested-loop SIP join that threads each pattern's bindings forward into
    the remaining patterns.  It is therefore the correct path for *mixed* BGPs
    that must join IDB and EDB results, while still returning the same
    ``SPARQLResult`` shape as ``query()`` so callers can use it interchangeably.

    Scope and return contract
    -------------------------
    * Only SELECT queries are supported; ASK/CONSTRUCT/DESCRIBE raise
      ``NotImplementedError`` (use ``Graph.query`` for ASK).
    * Only fully-bound solutions are returned: a candidate is kept only if every
      variable appearing in the BGP is bound (closed-world projection), matching
      the historical ``sparql_interlocution`` semantics.
    * When ``generate_proofs`` is ``False`` (default) a bare ``SPARQLResult`` is
      returned -- a drop-in replacement for ``Graph.query`` output.
    * When ``generate_proofs`` is ``True`` a ``(SPARQLResult, proofs)`` tuple is
      returned.  ``proofs`` maps each proved *ground* goal triple to the
      a 4 item tuple:
       - truth maintainance graph (the SIP collection and PML graph for the solution)
       - the ordered list of adorned rules referenced / compiled by the meta-interpreter
       - The meta interpetation network
       - An RDF graph of inferred statements from the network

      Note that for hybrid predicates the ground goal uses the ``_derived`` suffixed
      predicate the adornment machinery assigns to the IDB role.

    :param query: A SPARQL SELECT query string.
    :param top_down_store: A ``TopDownSPARQLEntailingStore`` configured with the
        rule program (IDB) and the fact graph (EDB).
    :param generate_proofs: When ``True`` also capture and return PML proofs for
        the derived goals solved while answering the query.
    :param ns_bindings: Additional namespace prefix bindings for the query.
    :returns: A ``SPARQLResult`` (``generate_proofs=False``) or a
        ``(SPARQLResult, dict[Triple, tuple])`` tuple (``generate_proofs=True``).

    :raises NotImplementedError: If ``query`` is not a SELECT query.

    Example:
        >>> # SELECT BGP that joins a derived predicate with a base predicate
        >>> result = sparql_interlocution_basic_graph_pattern(
        ...     query, top_down_store
        ... )  # doctest: +SKIP
        >>> for row in result:  # doctest: +SKIP
        ...     city = row["city"]
        >>> # Capture proofs alongside the answers
        >>> result, proofs = sparql_interlocution_basic_graph_pattern(
        ...     query, top_down_store, generate_proofs=True
        ... )  # doctest: +SKIP
    """
    # NOTE: ``extract_triples_from_query`` lives in this same module; this import
    # is retained for explicitness but is effectively a no-op (module is already
    # resolved in ``sys.modules`` by the time this function runs).
    from fuxi.SPARQL.utilities import extract_triples_from_query

    # 1. Parse and gate on form. We only handle SELECT here; ASK has a dedicated
    #    short-circuiting path in ``solve_triple_pattern`` reached via query().
    _, parsed_query = parseQuery(query)
    if parsed_query.name != "SelectQuery":
        raise NotImplementedError("ASK/CONSTRUCT/DESCRIBE not supported")

    # 2. Flatten the WHERE clause into the BGP triple patterns to solve.
    _, triples = extract_triples_from_query(parsed_query, top_down_store.ns_bindings)

    # 3. Collect every variable occurring anywhere in the BGP. These double as
    #    both the "must be bound" closed-world filter (step 5) and the SELECT
    #    projection columns (step 6).
    variables: list[Variable] = []
    for triple in triples:
        for part in triple:
            if isinstance(part, Variable):
                variables.append(part)
    projected_vars: list[Variable] = list(dict.fromkeys(variables))

    # 4. ``batch_unify`` expects quad patterns (triple + graph slot); the trailing
    #    ``None`` means "any/default graph".
    quads = [triple + tuple([None]) for triple in triples]

    # 5. Drive the conjunctive SIP join. Each yielded answer is a
    #    ``dict[Variable, Identifier]``; keep only fully-bound solutions so the
    #    result set contains no partial rows.
    select_bindings: list[Mapping[Variable, Identifier]] = []
    for answer in top_down_store.batch_unify(quads):
        if isinstance(answer, Mapping) and set(variables).issubset(answer.keys()):
            select_bindings.append(answer)

    # 6. Package the joined bindings as an rdflib SELECT ``Result`` -> ``SPARQLResult``
    #    (the same shape ``query()`` returns), projecting onto the BGP variables.
    result = Result("SELECT")
    result.vars = projected_vars
    result.bindings = [
        {var: b[var] for var in projected_vars if var in b} for b in select_bindings
    ]
    sparql_result = sparql_query_from_result(result)

    if not generate_proofs:
        return sparql_result

    # 7. Proof capture:
    from fuxi.Rete.Proof import generate_proof

    proofs: dict[Triple, tuple] = {}
    for network, goal_pattern in top_down_store.query_networks:
        for binding in select_bindings:
            ground = tuple(
                binding.get(t, t) if isinstance(t, Variable) else t
                for t in goal_pattern
            )
            if ground in network.inferred_facts:
                proofs[ground] = generate_proof(network, ground, top_down_store)
    proof_info = {}

    ns_binds = namespaces_bindings
    if ns_bindings:
        ns_binds.update(ns_bindings)

    # We build a truth maintainance graph comprising:
    # - A reification of each statement derived via entailment
    # - The (RDF) SIP representation of each SIP collection used to derive
    #   the entailment
    # - A serialization of the PML proof of each derived entailment,
    #   referencing the derived, reified statement
    # - A rendering of each adorned rule used by the BFP and referenced by
    #   the meta programs
    for proof_goal, (blder, pf) in proofs.items():
        proof_goal_uniterm, uniterm = check(
            proof_goal, list(top_down_store.goal_rule_sip_info)
        )
        (
            goal_lit,
            adorned_program,
            sip_collections,
            inferred_facts,
            meta_interp_network,
        ) = top_down_store.goal_rule_sip_info[uniterm.to_rdf_tuple()]
        truth_maintainance_graph = Graph()
        for prefix, uri in ns_binds.items():
            truth_maintainance_graph.namespace_manager.bind(prefix, uri)
        stmt_bnode = reify_rdf_statement(truth_maintainance_graph, proof_goal)

        truth_maintainance_graph += sip_collections
        blder.serialize(
            pf,
            truth_maintainance_graph,
            ns_mapping=ns_bindings,
            top_goal_statement=stmt_bnode,
        )
        for idx, rule in enumerate(adorned_program):
            truth_maintainance_graph.add(
                (
                    BFP_RULE[str(idx + 1)],
                    RDFS.label,
                    Literal(repr(rule).replace('"', "'")),
                )
            )
        proof_info[proof_goal] = (
            truth_maintainance_graph,
            adorned_program,
            meta_interp_network,
            inferred_facts,
        )
    return (sparql_result, proof_info)
