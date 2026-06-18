import doctest

from rdflib import RDF


def format_doctest_out(obj):
    return obj


@format_doctest_out
def identify_hybrid_predicates(graph, derived_predicates):
    """
    Takes an RDF graph and a list of derived predicates and return
    those predicates that are both EDB (extensional) and IDB (intensional)
    predicates. i.e., derived predicates that appear in the graph

    >>> import rdflib
    >>> g = rdflib.Graph()
    >>> EX = rdflib.Namespace('http://example.com/')
    >>> g.add((rdflib.BNode(),EX.predicate1,rdflib.Literal(1)))
    >>> g.add((rdflib.BNode(),rdflib.RDF.type,EX.Class1))
    >>> g.add((rdflib.BNode(),rdflib.RDF.type,EX.Class2))
    >>> rt = identify_hybrid_predicates(g,[EX.predicate1,EX.Class1,EX.Class3])
    >>> sorted(rt)
    [rdflib.term.URIRef(%(u)s'http://example.com/Class1'), rdflib.term.URIRef(%(u)s'http://example.com/predicate1')]
    """
    derived_predicates = (
        derived_predicates
        if isinstance(derived_predicates, set)
        else set(derived_predicates)
    )
    return derived_predicates.intersection(
        [o if p == RDF.type else p for s, p, o in graph]
    )


if __name__ == "__main__":
    doctest.testmod()
