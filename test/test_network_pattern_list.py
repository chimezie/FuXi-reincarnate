from fuxi.Rete.Network import HashablePatternList
from rdflib import URIRef, Literal


def test_combine_uri_and_literal():
    """Test HashablePatternList with URI and Literal items (issue from real rule usage)."""
    hpl = HashablePatternList(items=[(URIRef("http://example.com/"),), (Literal(" "),)])
    hash(hpl)
