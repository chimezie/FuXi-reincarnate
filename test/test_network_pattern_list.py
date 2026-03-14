import unittest
import logging

logging.basicConfig(level=logging.DEBUG)

from fuxi.Rete.Network import HashablePatternList
from rdflib import URIRef, Literal


class TestHashablePatternList(unittest.TestCase):
    def setUp(self):
        super(TestHashablePatternList, self).setUp()

        pass

    def tearDown(self):
        super(TestHashablePatternList, self).tearDown()
        pass

    def testCombineUriAndLiteral(self):
        # This is a simplified version of input that happens in real usage with a rule like this:
        # { ?c :p1 ?uri . } => { ?c :p2 (" " ?uri) . } .
        hpl = HashablePatternList(
            items=[(URIRef("http://example.com/"),), (Literal(" "),)]
        )
        hash(hpl)


if __name__ == "__main__":
    unittest.main()
