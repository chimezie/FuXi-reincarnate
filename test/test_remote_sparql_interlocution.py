# -*- coding: utf-8 -*-
"""
In [13]: for row in g.query("SELECT ?s WHERE { SERVICE <http://localhost:7000> { ?s rdfs:label 'bone foramen' FILTER isIRI(?s) } } LIMIT 3"):
    ...:     print(row.s)
    ...:
http://purl.obolibrary.org/obo/UBERON_0005744

In [7]: for row in g.query("SELECT ?s WHERE { SERVICE <http://localhost:7000> { <http://purl.obolibrary.org/obo/UBERON_0002279> rdfs:subClassOf ?s } } LIMIT 3"):
   ...:     print(row.s)
   ...:
http://purl.obolibrary.org/obo/UBERON_0013685
bn90524
bn113804

$ owl_dsl.reason --ontology-uri "http://purl.obolibrary.org/obo/uberon/uberon-base.owl#" \
                 --ontology-namespace-baseuri http://purl.obolibrary.org/obo/ \
                 --sqlite-file /tmp/ontology.sqlite3  \
                 --configuration-file ontology_configurations/OBO.CNL.yaml \
                 --class-reference "vestibular aqueduct" \
                 -a explain_logical_inferences uberon-base-plus-ro.owl
[main] INFO org.semanticweb.elk.reasoner.Reasoner - ELK reasoner was created
Warning: Could not find label for property http://purl.obolibrary.org/obo/BSPO_0001102
Warning: Could not find label for property http://purl.obolibrary.org/obo/BSPO_0015005
# http://purl.obolibrary.org/obo/UBERON_0002279 (vestibular aqueduct) #
## Textual definition ##
At the hinder part of the medial wall of the vestibule is the orifice of the vestibular aqueduct, which extends to the
posterior surface of the petrous portion of the temporal bone. It transmits a small vein, and contains a tubular
prolongation of the membranous labyrinth, the ductus endolymphaticus, which ends in a cul-de-sac between the layers of
the dura mater within the cranial cavity. [WP,unvetted].

## Logical definition ##
The vestibular aqueduct is defined in Uber-anatomy ontology as a foramen of skull that is a conduit for a vein of
vestibular aqueduct. It is a foramen of skull. It is part of an osseus labyrinth vestibule. It is a conduit for a
vein of vestibular aqueduct
------------------------------------------------------------
[..]
How is every 'vestibular aqueduct' (UBERON_0002279) a 'bone foramen'?

  Every vestibular aqueduct is a foramen of skull that is a conduit for a vein of vestibular aqueduct and vice versa.
    Every foramen of skull is a bone foramen
------------------------------------------------------------
[..]
How is every 'vestibular aqueduct' (UBERON_0002279) a 'anatomical conduit'?

  Every vestibular aqueduct is a foramen of skull that is a conduit for a vein of vestibular aqueduct and vice versa.
    Every foramen of skull is a bone foramen
      Every bone foramen is an anatomical conduit that is part of a bone element and vice versa.
"""

from io import StringIO
from pprint import pprint

from fuxi.DLP import non_DHL_OWL_Semantics
from fuxi.Horn.HornRules import HornFromN3
from fuxi.Rete.RuleStore import SetupRuleStore
from fuxi.SPARQL.service import SPARQLServiceGraph
from fuxi.Syntax.InfixOWL import GraphContext, Class, Property, AnnotationProperty
from rdflib import Graph, Namespace, RDF, Literal
from fuxi.SPARQL.BackwardChainingStore import TopDownSPARQLEntailingStore
from rdflib.plugins.sparql.parser import parseQuery
from fuxi.SPARQL.utilities import extract_triples_from_query
from fuxi.SPARQL.utilities import owl_entailment_regime_graph

NS_BINDINGS = {
    "dc": "http://purl.org/dc/elements/1.1/",
    "obo": "http://purl.obolibrary.org/obo/",
    "owl": "http://www.w3.org/2002/07/owl#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "oboInOwl": "http://www.geneontology.org/formats/oboInOwl#",
    "health": "tag:info@metacognition.info,2026:PatientRecordConcepts#",
    "dnode": "http://www.clevelandclinic.org/heartcenter/ontologies/DataNodes.owl#",
    "ptrec": "tag:info@semanticdb.ccf.org,2007:PatientRecordTerms#",
    "time": "tag:info@semanticdb.ccf.org,2009:TemporalTerms#"
}

QUERY = """
SELECT ?person { 
    SERVICE <http://localhost:7001> { 
        ?person a health:African_American_with_hx_T2DM 
    } 
}"""

HEALTH = Namespace("tag:info@metacognition.info,2026:PatientRecordConcepts#")
PTREC = Namespace("tag:info@semanticdb.ccf.org,2007:PatientRecordTerms#")
OWL_DSL = Namespace("https://github.com/chimezie/OWL_DSL/tree/main/ontology_configurations/")
DNODE = Namespace("http://www.clevelandclinic.org/heartcenter/ontologies/DataNodes.owl#")

def make_sdb_ontology_graph():
    graph = Graph()
    with GraphContext(graph, NS_BINDINGS):
        singular_phrase = AnnotationProperty(OWL_DSL.OWL_DSL_000001)
        black_patient = Class(HEALTH.African_American_Patient, label=Literal("African American Patient"))
        patient = Class(PTREC.Patient, label=Literal("Patient"))
        has_race = Property(PTREC.hasRace, domain=patient, label=Literal("has race"))

        contains = Property(DNODE.contains, label=Literal("contains"))
        contains.set_annotation(singular_phrase, " contains {}")

        has_race.set_annotation(singular_phrase, " is {}")
        patient_record = Class(PTREC.PatientRecord, label=Literal("Patient Record"))
        black_patient.equivalent_class = [patient & has_race.value(PTREC.Race_African_American)]

        black_ptrec = Class(HEALTH.African_American_Patient_Record,
                            label=Literal("African American Patient Record"))
        black_patient.equivalent_class = [patient_record & contains.some(black_patient)]

        has_history_of_disease_status = Property(PTREC.hasHistoryOfDiseaseStatus,
                                                 label=Literal("Has history of disease status"))
        t2dm_hx = Class(PTREC.HistoryOfDiabetes, label=Literal("History of Diabetes"))
        pt_t2dm_hx_record = Class(HEALTH.Patient_record_with_hx_T2DM,
                                  label=Literal("Patient Record with active History of Type II Diabetes"))

        pt_t2dm_hx_record.equivalent_class = [patient_record &
                                              contains.some(t2dm_hx & has_history_of_disease_status.value(True))]

        black_pt_t2dm_hx_record = Class(HEALTH.African_American_Patient_Record_with_hx_T2DM,
                                        label=Literal("African American Patient Record with Type II Diabetes history"))
        black_pt_t2dm_hx_record.equivalent_class = [black_ptrec & pt_t2dm_hx_record]

        history_and_physical_event = Class(PTREC.Event_evaluation_history_and_physical,
                                           label=Literal("History and physical event"))

        pulmonary_hx = Class(PTREC.MedicalDiagnosis_pulmonary_hypertension_primary,
                             label=Literal("Pulmonary hypertension primary DX"))
        vascular_hx = Class(PTREC.MedicalDiagnosis_vascular_systemic_hypertension,
                            label=Literal("Vascular hypertension primary DX"))

        h_and_p_with_htn_dx = Class(HEALTH.H_and_P_with_htn_dx, label=Literal("Historical Htx Dx from H&amp;P event"))
        h_and_p_with_htn_dx.equivalent_class = [history_and_physical_event & contains.some(pulmonary_hx | vascular_hx)]

        black_pt_h_and_p_htx_dx_record = Class(HEALTH.Patient_Record_of_African_American_with_Htn_Dx_from_H_and_P,
                                              label=Literal("Patient record of African American Patient "
                                                            "with Htn H&amp;P event DX"))
        black_pt_h_and_p_htx_dx_record.equivalent_class = [black_ptrec & contains.some(h_and_p_with_htn_dx)]
    return graph

def _test_uberon_sparql_interlocution():
    parsed_query = parseQuery(QUERY)
    _, query_structure = parsed_query
    service_url, _ = extract_triples_from_query(query_structure, NS_BINDINGS)
    fact_graph = SPARQLServiceGraph(service_url)
    for prefix, url in NS_BINDINGS.items():
        fact_graph.bind(prefix, url)
    derived_predicates = [
        HEALTH.African_American_Patient,
        HEALTH.African_American_Patient_Record,
        HEALTH.African_American_with_hx_T2DM,
        HEALTH.H_and_P_with_htn_dx,
        HEALTH.Patient_record_with_htn_dx,
        HEALTH.Patient_record_with_hx_T2DM,
        HEALTH.Patient_record_with_hx_htn,
        HEALTH.Patient_Record_of_African_American_with_Htn_Dx_from_H_and_P,
    ]
    program = []
    ont_graph = make_sdb_ontology_graph()
    rule_store, rule_graph, network = SetupRuleStore(makeNetwork=True)
    program.extend(
        network.setupDescriptionLogicProgramming(
            ont_graph,
            addPDSemantics=False,
            constructNetwork=False,
            derivedPreds=derived_predicates,
        )
    )
    pprint(program)

    # entailing_graph, closure_delta_graph = owl_entailment_regime_graph(
    #     premise_graph,
    #     ns_map,
    #     identify_hybrid_predicates=True,
    #     derived_predicates=None,
    #     hybrid_predicates=None,
    #     goals=goals,
    #     namespace_manager=namespace_manager,
    #     extra_rulesets=HornFromN3(StringIO(thing_rule)),
    #     verbose=debug,
    # )
    #
    #
    # top_down_store = TopDownSPARQLEntailingStore(
    #     fact_graph.store,
    #     fact_graph,
    #     idb=program,
    #     DEBUG=False,
    #     derivedPredicates=derived_predicates,
    #     nsBindings=NS_BINDINGS,
    #     identifyHybridPredicates=False,
    #     hybridPredicates=[
    #         RDF.type,
    #         PTREC.Patient_record,
    #         PTREC.Event_evaluation_history_and_physical,
    #         PTREC.hasHistoryOfDiseaseStatus,
    #         PTREC.Patient,
    #         PTREC.Event_evaluation_history,
    #     ],
    # )
    # target_graph = Graph(store=top_down_store)
    # for prefix, url in {k: v for k, v in NS_BINDINGS.items()}.items():
    #     target_graph.bind(prefix, url)
    # import time
    #
    # start_time = time.perf_counter()
    # res = target_graph.query(parsed_query, initNs=NS_BINDINGS)
    # end_time = time.perf_counter()
    # elapsed_time = end_time - start_time
    # print(f"Query execution time: {elapsed_time:.4f} seconds")
    # result_list = list(res)
    # assert result_list
    # assert top_down_store.edbQueries


if __name__ == "__main__":
    _test_uberon_sparql_interlocution()
