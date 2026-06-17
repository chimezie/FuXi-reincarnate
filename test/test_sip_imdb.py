"""
{'?name -> "Frances McDormand"',
 '?person -> <https://www.imdb.com/nm0000531>',
 '?title -> "Blood Simple"'}

"""
import pytest
from fuxi.SPARQL.utilities import sparql_interlocution
from rdflib import Namespace, RDFS, URIRef, Graph, Variable, Literal, XSD
from io import StringIO
IMDB = Namespace("https://www.imdb.com/")
OWL_NS = Namespace("http://www.w3.org/2002/07/owl#")

NS_BINDINGS = {
    "rdfs": RDFS,
    "owl": OWL_NS,
    "imdb": URIRef(IMDB),
}

FACTS = """
@prefix imdb: <https://www.imdb.com/> . 
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

imdb:tt0086979 imdb:id "tt0086979" ; 
               imdb:type "movie" ; 
               imdb:title "Blood Simple" .
               
imdb:tt0086979 imdb:principal [ imdb:role "actor" ; imdb:person imdb:nm0315288 ];
               imdb:principal [ imdb:role "actress" ; imdb:person imdb:nm0000531 ];
               imdb:principal [ imdb:role "actor" ; imdb:person imdb:nm0000445 ];
               imdb:principal [ imdb:role "actor" ; imdb:person imdb:nm0001826 ];
               imdb:principal [ imdb:role "actor" ; imdb:person imdb:nm0931638 ];
               imdb:principal [ imdb:role "actress" ; imdb:person imdb:nm0627029 ];
               imdb:principal [ imdb:role "actress" ; imdb:person imdb:nm0310490 ];
               imdb:principal [ imdb:role "actor" ; imdb:person imdb:nm0112295 ];
               imdb:principal [ imdb:role "actor" ; imdb:person imdb:nm0545810 ];
               imdb:principal [ imdb:role "actor" ; imdb:person imdb:nm0187125 ];
               imdb:principal [ imdb:role "director" ; imdb:person imdb:nm0001054 ];
               imdb:principal [ imdb:role "writer" ; imdb:person imdb:nm0001054 ];
               imdb:principal [ imdb:role "writer" ; imdb:person imdb:nm0001053 ];
               imdb:principal [ imdb:role "producer" ; imdb:person imdb:nm0001053 ];
               imdb:principal [ imdb:role "composer" ; imdb:person imdb:nm0001980 ];
               imdb:principal [ imdb:role "cinematographer" ; imdb:person imdb:nm0001756 ];
               imdb:principal [ imdb:role "editor" ; imdb:person imdb:nm0001053 ];
               imdb:principal [ imdb:role "editor" ; imdb:person imdb:nm0001054 ];
               imdb:principal [ imdb:role "editor" ; imdb:person imdb:nm0927366 ];
               imdb:principal [ imdb:role "casting_director" ; imdb:person imdb:nm0400715 ];
               imdb:principal [ imdb:role "casting_director" ; imdb:person imdb:nm0608912 ];
               imdb:principal [ imdb:role "production_designer" ; imdb:person imdb:nm0615788 ] .
"""

RULES ="""
@prefix imdb: <https://www.imdb.com/> .
@prefix log: <http://www.w3.org/2000/10/swap/log#>.

{ ?movie      imdb:principal ?principal1, ?principal2 .
  ?principal1 imdb:role      "director";
              imdb:person    ?director .
  ?principal2 imdb:role      "actress";
              imdb:person    ?actress .
  ?movie      a              imdb:Movie .
  } => { ?director imdb:has_directed_actress_in_movie ?actress } .

{ ?X imdb:type "movie" } => { ?X a imdb:Movie } .
"""

DERIVED_PREDICATES = [
    URIRef('https://www.imdb.com/has_directed_actress_in_movie'),
    URIRef('https://www.imdb.com/Movie')
]

QUERY = """
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX imdb: <https://www.imdb.com/>

SELECT ?director WHERE {
   ?director    imdb:has_directed_actress_in_movie  imdb:nm0000531 
}"""

def test_sip():
    from fuxi.DLP import NON_DHL_OWL_SEMANTICS
    from fuxi.DLP.ConditionalAxioms import additional_rules
    from fuxi.Horn.HornRules import horn_from_n3
    from fuxi.Rete.RuleStore import setup_rule_store
    from fuxi.SPARQL.BackwardChainingStore import (
        TopDownSPARQLEntailingStore,
    )

    _, _, network = setup_rule_store(make_network=True)
    rules = list(horn_from_n3(StringIO(RULES)))
    graph = Graph().parse(StringIO(FACTS), format="n3")
    top_down_store = TopDownSPARQLEntailingStore(
        graph.store,
        graph,
        derived_predicates=DERIVED_PREDICATES,
        idb=rules,
        debug=True,
        ns_bindings=NS_BINDINGS
    )
    entailing_graph = Graph(top_down_store)

    for answer in sparql_interlocution(QUERY, top_down_store):
        print("\tInner Answer: ")
        print("\t", {f"?{k} -> {v.n3()}" for k, v in answer.items()})


def test_sip_graph_arcs_for_derived_body_literal():
    """
    Regression test for SIP graph construction.

    ``build_natural_sip`` must populate the SIP graph with ``MAGIC.SipArc``
    triples so that each body literal of a rule has at least one incoming
    arc describing which variables are passed sideways into it. Without
    those arcs, ``incoming_sip_arcs`` returns nothing and ``adorn_rule``
    falls back to an all-free adornment for every derived body literal,
    defeating Sideways Information Passing.

    For the IMDB rule whose body ends in ``?movie a imdb:Movie``, the arc
    entering ``imdb:Movie`` must carry ``?movie`` — that variable is bound
    by the earlier ``imdb:principal(?movie ?principal2)`` literal and the
    binding must reach ``Movie`` for the lookup to be constrained.
    """
    from fuxi.Horn.HornRules import horn_from_n3
    from fuxi.Rete.Magic import AdornedUniTerm
    from fuxi.Rete.SidewaysInformationPassing import (
        MAGIC,
        build_natural_sip,
        get_occurrence_id,
        get_op,
        incoming_sip_arcs,
        iter_condition,
        sip_representation,
    )
    from rdflib import RDF
    from rdflib.collection import Collection
    from rdflib.util import first

    rules = list(horn_from_n3(StringIO(RULES)))
    target_rule = first(
        r for r in rules
        if get_op(r.formula.head) == IMDB.has_directed_actress_in_movie
    )
    assert target_rule is not None, "Could not find has_directed_actress_in_movie rule"

    adorned_head = AdornedUniTerm(target_rule.formula.head, ["f", "b"])

    sip = build_natural_sip(
        target_rule.formula,
        [IMDB.has_directed_actress_in_movie, IMDB.Movie],
        adorned_head,
        ignore_unbound_d_preds=True,
    )

    arc_triples = list(sip.triples((None, RDF.type, MAGIC.SipArc)))
    assert arc_triples, (
        "build_natural_sip produced no MAGIC.SipArc triples — the SIP "
        "graph has no arcs at all, so no bindings can be passed sideways."
    )

    arc_descriptions = list(sip_representation(sip))
    assert arc_descriptions, (
        "sip_representation returned no arcs even though MAGIC.SipArc "
        "triples exist — the arc structure is malformed."
    )

    movie_lit = first(
        lit for lit in iter_condition(sip.sipOrder)
        if get_op(lit) == IMDB.Movie
    )
    assert movie_lit is not None, "Movie literal missing from SIP body order"

    incoming = list(incoming_sip_arcs(sip, get_occurrence_id(movie_lit)))
    assert incoming, (
        f"No incoming arc into {IMDB.Movie} — ?movie binding will be lost "
        "and the Movie literal will get an all-free adornment."
    )

    movie_var = Variable("movie")
    found_movie_binding = False
    for _N, bindings_col in incoming:
        bindings = (
            list(bindings_col)
            if not isinstance(bindings_col, Collection)
            else list(bindings_col)
        )
        if movie_var in bindings:
            found_movie_binding = True
            break

    assert found_movie_binding, (
        f"Arc entering imdb:Movie should carry {movie_var.n3()} in its "
        "bindings (?movie is bound by preceding principal/person literals) "
        f"but bindings observed were: "
        f"{[list(b) for _, b in incoming_sip_arcs(sip, get_occurrence_id(movie_lit))]}"
    )


if __name__ == "__main__":
    test_sip()
