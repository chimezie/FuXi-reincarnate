from abc import ABC
from rdflib import Graph, URIRef
from rdflib.term import Identifier
from .Horn.HornRules import Rule, horn_from_n3
from .Rete.Magic import derived_predicate_iterator
from .DLP import NON_DHL_OWL_SEMANTICS
from .Rete.RuleStore import setup_rule_store
from .SPARQL.BackwardChainingStore import TopDownSPARQLEntailingStore

class PredicatePartitioner(ABC):
    """Abstract base class for partitioning EDB/IDB  predicates"""
    def __init__(self,
                 fact_graph: Graph | None = None,
                 rules: list[Rule] | None = None,
                 edb_predicates: list[URIRef] | None = None,
                 derived_predicates: list[URIRef] | None = None,
                 hybrid_predicates: list[URIRef] | None = None,
                 ):
        self.fact_graph = fact_graph
        self.rules = rules if rules is not None else []
        self.edb_predicates = edb_predicates
        self.derived_predicates = derived_predicates
        self.hybrid_predicates = hybrid_predicates

class DescriptionLogicCompiler:
    """Handles the common task of extracting rules from an OWL ontology"""

    def compile_rules(self,
                      ontology_graph: Graph,
                      add_pd_semantics: bool = False,
                      introspect_rules: bool = False):
        _, _, network = setup_rule_store(make_network=True)
        rules = []
        rules.extend(
            network.setup_description_logic_programming(
                ontology_graph,
                add_pd_semantics=add_pd_semantics,
                construct_network=False)
        )
        if introspect_rules:
            for rule in additional_rules(ontology_graph):
                rules.append(rule)
        return rules

class DefaultPredicatePartitioner(PredicatePartitioner):
    """Default predicate partitioner"""
    def __init__(self,
                 fact_graph: Graph | None = None,
                 rules: list[Rule] | None = None,
                 edb_predicates: list[URIRef] | None = None,
                 derived_predicates: list[URIRef] | None = None,
                 hybrid_predicates: list[URIRef] | None = None,
                 identify_hybrid_predicates: bool = False
                 ):
        super().__init__(fact_graph, rules, edb_predicates, derived_predicates, hybrid_predicates)
        if hybrid_predicates is None:
            hybrid_predicates = []
        if derived_predicates is None:
            derived_predicates = list(
                derived_predicate_iterator(self.fact_graph, self.idb)
            )
        if identify_hybrid_predicates:
            hybrid_predicates = identify_hybrid_predicates_fn(
                self.fact_graph, derived_predicates
            )
        else:
            hybrid_predicates = hybrid_predicates if hybrid_predicates is not None else []

        for hybrid_pred in hybrid_predicates:
            if hybrid_pred in derived_predicates:
                derived_predicates.remove(hybrid_pred)
            derived_predicates.append(URIRef(hybrid_pred + "_derived"))

SPARQL_PREDICATE_QUERY = """
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
SELECT DISTINCT ?pred
WHERE {{
    {{ ?subj ?pred ?obj FILTER(?pred != rdf:type) }}
    UNION
    {{ ?subj a     ?pred }}
}}"""

class SPARQLPredicatePartitioner(PredicatePartitioner, DescriptionLogicCompiler):
    def __init__(self,
                 fact_graph: Graph | None = None,
                 rules: list[Rule] | None = None,
                 edb_predicates: list[URIRef] | None = None,
                 derived_predicates: list[URIRef] | None = None,
                 hybrid_predicates: list[URIRef] | None = None,
                 identify_hybrid_predicates: bool = False,
                 tbox_only_graph: Graph | None  = None,
                 add_pd_semantics: bool = False,
                 introspect_rules: bool = False
                 ):
        super().__init__(fact_graph, rules, edb_predicates, derived_predicates, hybrid_predicates)
        if edb_predicates is None:
            self.edb_predicates = [URIRef(row['pred']) for row in fact_graph.query(SPARQL_PREDICATE_QUERY)]
        if hybrid_predicates is None:
            hybrid_predicates = []

        if tbox_only_graph:
            rules = self.compile_rules(tbox_only_graph,
                                       add_pd_semantics=add_pd_semantics,
                                       introspect_rules=introspect_rules)
            if self.rules:
                self.rules.extend(rules)

        if derived_predicates is None:
            self.derived_predicates = list(
                set(derived_predicate_iterator(self.edb_predicates, self.rules, predicates_given=True))
            )
        if identify_hybrid_predicates:
            _derived_predicates = (
                derived_predicates
                if isinstance(self.derived_predicates, set)
                else set(self.derived_predicates)
            )
            self.hybrid_predicates = list(_derived_predicates.intersection(self.edb_predicates))
        else:
            self.hybrid_predicates = hybrid_predicates if hybrid_predicates is not None else []

        for hybrid_pred in self.hybrid_predicates:
            if hybrid_pred in self.derived_predicates:
                self.derived_predicates.remove(hybrid_pred)
            self.derived_predicates.append(URIRef(hybrid_pred + "_derived"))

    def create_entailing_store(self,
                               verbose: bool = False,
                               ns_map: dict[str, Identifier] = None):
        top_down_store = TopDownSPARQLEntailingStore(
            self.fact_graph.store,
            self.fact_graph,
            derived_predicates=self.derived_predicates,
            idb=self.rules,
            debug=verbose,
            ns_bindings=ns_map,
            identify_hybrid_predicates=False,
            hybrid_predicates=self.hybrid_predicates
        )
        return Graph(top_down_store)