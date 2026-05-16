# -*- coding: utf-8 -*-
# flake8: noqa
import sys
import unittest

from fuxi.Syntax.InfixOWL import BooleanClass
from fuxi.Syntax.InfixOWL import Class
from fuxi.Syntax.InfixOWL import Individual
from fuxi.Syntax.InfixOWL import cast_class
from fuxi.Syntax.InfixOWL import class_or_identifier
from fuxi.Syntax.InfixOWL import OWL_NS
from rdflib.graph import Graph
from rdflib.namespace import NamespaceManager
from rdflib import RDF, Namespace
from rdflib.util import first

DATALOG_SAFETY_NONE = 0
DATALOG_SAFETY_STRICT = 1
DATALOG_SAFETY_LOOSE = 2

safety_name_map = {
    "none": DATALOG_SAFETY_NONE,
    "strict": DATALOG_SAFETY_STRICT,
    "loose": DATALOG_SAFETY_LOOSE,
}


def sub_sumption_expansion(owl_class):
    owl_class = cast_class(owl_class)
    if isinstance(owl_class, BooleanClass) and owl_class._operator == OWL_NS.unionOf:
        for member in owl_class:
            expanded = False
            for innerMember in sub_sumption_expansion(Class(member)):
                expanded = True
                yield innerMember
            if not expanded:
                yield member
    else:
        for member in owl_class.sub_sumptee_ids():
            expanded = False
            for innerMember in sub_sumption_expansion(Class(member)):
                expanded = True
                yield innerMember
            if not expanded:
                yield member


def complement_expansion(owl_class, debug=False):
    """
    For binary conjunctions of a positive conjunction concept and a negative atomic concept
    """
    owl_class = cast_class(owl_class.identifier, owl_class.graph)
    if (
        isinstance(owl_class, BooleanClass)
        and len(owl_class) == 2
        and owl_class._operator == OWL_NS.intersectionOf
    ):
        old_repr = owl_class.__repr__()
        # A boolean-constructed class
        negative_classes = set()
        other_classes = set()
        for member in owl_class:
            member = Class(member)
            if member.complement_of:
                # A negative class, expand it and add to bucket of classes to
                # 'remove'
                for expanded_class in sub_sumption_expansion(member.complement_of):
                    negative_classes.add(expanded_class)
            else:
                # A positive class, expand it and add to bucket of base classes
                expanded = False
                for expanded_class in sub_sumption_expansion(member):
                    expanded = True
                    other_classes.add(expanded_class)
                if not expanded:
                    other_classes.add(member.identifier)

        if negative_classes:
            # Delete the old list of operands for the boolean class
            old_list = owl_class._rdfList
            old_list.clear()

            # Recreate the list of operands, exluding the expanded negative
            # classes
            for allowed_classes in other_classes.difference(negative_classes):
                old_list.append(class_or_identifier(allowed_classes))
            owl_class.change_operator(OWL_NS.unionOf)
            if debug:
                print("Incoming boolean class: ", old_repr)
                print("Expanded boolean class: ", owl_class.__repr__())
            return owl_class
        else:
            if debug:
                print("There were no negative classes.")


class ComplementExpansionTestSuite(unittest.TestCase):
    def setUp(self):
        self.testGraph = Graph()
        Individual.factoryGraph = self.testGraph

    def testExpand(self):
        EX = Namespace("http://example.com/")
        namespace_manager = NamespaceManager(Graph())
        namespace_manager.bind("ex", EX, override=False)
        self.testGraph.namespace_manager = namespace_manager

        man = Class(EX.Man)
        boy = Class(EX.Boy)
        woman = Class(EX.Woman)
        girl = Class(EX.Girl)
        male = Class(EX.Male)
        female = Class(EX.Female)
        human = Class(EX.Human)
        animal = Class(EX.Animal)
        cat = Class(EX.Cat)
        dog = Class(EX.Dog)
        animal = Class(EX.Animal)

        animal = cat | dog | human
        human += man
        human += boy
        human += woman
        human += girl
        male += man
        male += boy
        female += woman
        female += girl

        testClass = human & ~female
        self.assertEquals(repr(testClass), "ex:Human THAT ( NOT ex:Female )")
        newtestClass = complement_expansion(testClass, debug=True)
        self.assertTrue(
            repr(newtestClass) in ["( ex:Boy or ex:Man )", "( ex:Man or ex:Boy )"],
            repr(newtestClass),
        )

        testClass2 = animal & ~(male | female)
        self.assertEquals(
            repr(testClass2),
            "( ( ex:Cat or ex:Dog or ex:Human ) and ( not ( ex:Male or ex:Female ) ) )",
        )
        newtestClass2 = complement_expansion(testClass2, debug=True)
        testClass2Repr = repr(newtestClass2)
        self.assertTrue(
            testClass2Repr in ["( ex:Cat or ex:Dog )", "( ex:Dog or ex:Cat )"],
            testClass2Repr,
        )


from fuxi.Horn.RIFCore import RIFParser, RIFXMLParser, RIFCoreParser, RIF_NS, XSD_NS
from fuxi.Horn.rif_presentation_parser import RIFPresentationParser
from fuxi.Horn.rif_presentation_serializer import RIFPresentationSerializer
from fuxi.Horn.rif_validator import RIFValidator, RIFValidationError
from fuxi.Horn.rif_xml_serializer import serialize_xml, serialize_xml_to_file

if __name__ == "__main__":
    unittest.main()
    sys.exit(1)
