# encoding: utf-8
# flake8: noqa
"""
Helper Functions for reducing DL axioms into a normal forms
"""

from rdflib.graph import Graph
from rdflib import Namespace, RDFS, BNode
from rdflib.collection import Collection
from rdflib.util import first
import unittest

from fuxi.Syntax.InfixOWL import BooleanClass
from fuxi.Syntax.InfixOWL import cast_class
from fuxi.Syntax.InfixOWL import Class
from fuxi.Syntax.InfixOWL import ClassNamespaceFactory
from fuxi.Syntax.InfixOWL import EnumeratedClass
from fuxi.Syntax.InfixOWL import Individual
from fuxi.Syntax.InfixOWL import OWL_NS
from fuxi.Syntax.InfixOWL import Property
from fuxi.Syntax.InfixOWL import Restriction
from fuxi.Syntax.InfixOWL import only
from fuxi.Syntax.InfixOWL import some
from fuxi.Syntax.InfixOWL import value
from functools import reduce


class NominalRangeTransformer(object):
    NOMINAL_QUERY = """\
SELECT ?RESTRICTION ?INTERMEDIATE_CLASS ?NOMINAL ?PROP
   { ?RESTRICTION owl:onProperty ?PROP;
                  owl:someValuesFrom ?INTERMEDIATE_CLASS .
     ?INTERMEDIATE_CLASS owl:oneOf ?NOMINAL .  }"""

    def transform(self, graph):
        """
        Transforms a 'pure' nominal range into a disjunction of value restrictions
        """
        Individual.factoryGraph = graph
        for restriction, intermediateCl, nominal, prop in graph.query(
            self.NOMINAL_QUERY, initNs={"owl": OWL_NS}
        ):
            nominal_collection = Collection(graph, nominal)
            # purge restriction
            restr = Class(restriction)
            parent_sets = [i for i in restr.sub_class_of]
            restr.clear_out_degree()
            new_conjunct = BooleanClass(
                restriction,
                OWL_NS.unionOf,
                [Property(prop) | value | val for val in nominal_collection],
                graph,
            )
            new_conjunct.sub_class_of = parent_sets

            # purge nominalization placeholder
            i_class = BooleanClass(intermediateCl)
            i_class.clear()
            i_class.delete()


class UniversalNominalRangeTransformer(object):
    NOMINAL_QUERY = """\
SELECT ?RESTRICTION ?INTERMEDIATE_CLASS ?NOMINAL ?PROP ?PARTITION
   { ?RESTRICTION owl:onProperty ?PROP;
                  owl:allValuesFrom ?INTERMEDIATE_CLASS .
     ?INTERMEDIATE_CLASS owl:oneOf ?NOMINAL .
     ?PROP rdfs:range [ owl:oneOf ?PARTITION ] .
   } """

    def transform(self, graph):
        """
        Transforms a universal restriction on a 'pure' nominal range into a
        conjunction of value restriction (using set theory and demorgan's laws)
        """
        Individual.factoryGraph = graph
        for restriction, intermediateCl, nominal, prop, partition in graph.query(
            self.NOMINAL_QUERY, initNs={"owl": OWL_NS, "rdfs": str(RDFS)}
        ):
            exceptions = EnumeratedClass()
            partition = Collection(graph, partition)
            nominal_collection = Collection(graph, nominal)
            for i in partition:
                if i not in nominal_collection:
                    exceptions._rdfList.append(i)
                    # exceptions+=i
            exists = Class(complement_of=(Property(prop) | some | exceptions))
            for s, p, o in graph.triples((None, None, restriction)):
                graph.add((s, p, exists.identifier))
            Individual(restriction).delete()

            # purge nominalization placeholder
            i_class = BooleanClass(intermediateCl)
            i_class.clear()
            i_class.delete()


class GeneralUniversalTransformer(object):
    def transform(self, graph):
        """
        Transforms a universal restriction to a negated existential restriction
        """
        Individual.factoryGraph = graph
        for restr, p, o in graph.triples((None, OWL_NS.allValuesFrom, None)):
            graph.remove((restr, p, o))
            inner_compl = Class(complement_of=o)
            graph.add((restr, OWL_NS.someValuesFrom, inner_compl.identifier))
            outer_compl = Class()
            for _s, _p, _o in graph.triples((None, None, restr)):
                graph.add((_s, _p, outer_compl.identifier))
                graph.remove((_s, _p, _o))
            outer_compl.complement_of = restr


class DoubleNegativeTransformer(object):
    UNIVERSAL_QUERY = """\
SELECT ?COMPL1 ?COMPL2 ?COMPL3
   { ?COMPL1 owl:complementOf ?COMPL2 .
     ?COMPL2 owl:complementOf ?COMPL3
     FILTER( isBlank(?COMPL1) && isBlank(?COMPL2) )
   } """

    def transform(self, graph):
        Individual.factoryGraph = graph
        for compl1, compl2, compl3 in graph.query(
            self.UNIVERSAL_QUERY, initNs={"owl": OWL_NS, "rdfs": RDFS}
        ):
            Individual(compl1).replace(compl3)
            Individual(compl2).delete()


class DemorganTransformer(object):
    def transform(self, graph):
        """
        Uses demorgan's laws to reduce negated disjunctions to a conjunction of
        negated formulae
        """
        Individual.factoryGraph = graph
        for disjunct_id in graph.subjects(predicate=OWL_NS.unionOf):
            if (None, OWL_NS.complementOf, disjunct_id) in graph and isinstance(
                disjunct_id, BNode
            ):
                # not (     A1 or      A2  or .. or      An )
                #                 =
                #    ( not A1 and not A2 and .. and not An )
                disjunct = BooleanClass(disjunct_id, operator=OWL_NS.unionOf)
                items = list(disjunct)
                new_conjunct = BooleanClass(members=[~Class(item) for item in items])
                for negation in graph.subjects(
                    predicate=OWL_NS.complementOf, object=disjunct_id
                ):
                    Class(negation).replace(new_conjunct)
                    if not isinstance(negation, BNode):
                        new_conjunct.identifier = negation
                disjunct.clear()
                disjunct.delete()
            elif ((disjunct_id, OWL_NS.unionOf, None) in graph) and not [
                item
                for item in BooleanClass(disjunct_id, operator=OWL_NS.unionOf)
                if not Class(item).complement_of
            ]:
                # ( not A1 or  not A2  or .. or  not An )
                #                 =
                # not ( A1 and A2 and .. and An )
                disjunct = BooleanClass(disjunct_id, operator=OWL_NS.unionOf)
                items = [Class(item).complement_of for item in disjunct]
                for negation in disjunct:
                    Class(negation).delete()
                negated_conjunct = ~BooleanClass(members=items)
                disjunct.clear()
                disjunct.replace(negated_conjunct)


class ConjunctionFlattener(object):
    def transform(self, graph):
        """
        Flattens conjunctions
        ( A1 and ( B1 and B2 ) and A2 )
                         =
        ( A1 and B1 and B2 and A2 )

        """
        Individual.factoryGraph = graph
        for conjunctId in graph.subjects(predicate=OWL_NS.intersectionOf):
            conjunct = BooleanClass(conjunctId)
            nested_conjuncts = [
                BooleanClass(i)
                for i in conjunct
                if (i, OWL_NS.intersectionOf, None) in graph
            ]
            if nested_conjuncts:

                def collapse_conjunct_terms(left, right):
                    list(left) + list(right)

                if len(nested_conjuncts) == 1:
                    new_top_level_items = list(nested_conjuncts[0])
                else:
                    new_top_level_items = reduce(
                        collapse_conjunct_terms, nested_conjuncts
                    )
                for nc in nested_conjuncts:
                    nc.clear()
                    del conjunct[conjunct.index(nc.identifier)]
                    nc.delete()
                for newItem in new_top_level_items:
                    conjunct.append(newItem)


def normal_form_reduction(ont_graph):
    UniversalNominalRangeTransformer().transform(ont_graph)
    GeneralUniversalTransformer().transform(ont_graph)
    DoubleNegativeTransformer().transform(ont_graph)
    NominalRangeTransformer().transform(ont_graph)
    DemorganTransformer().transform(ont_graph)
    DoubleNegativeTransformer().transform(ont_graph)
    ConjunctionFlattener().transform(ont_graph)


EX_NS = Namespace("http://example.com/")
EX = ClassNamespaceFactory(EX_NS)


class ReductionTestA(unittest.TestCase):
    def setUp(self):
        self.ont_graph = Graph()
        self.ont_graph.bind("ex", EX_NS)
        self.ont_graph.bind("owl", OWL_NS)
        Individual.factoryGraph = self.ont_graph
        partition = EnumeratedClass(
            EX_NS.part,
            members=[EX_NS.individual1, EX_NS.individual2, EX_NS.individual3],
        )
        sub_partition = EnumeratedClass(EX_NS.partition, members=[EX_NS.individual1])
        partition_prop = Property(EX_NS.propFoo, range=partition)
        self.foo = EX.foo
        self.foo.sub_class_of = [partition_prop | only | sub_partition]

    def testUnivInversion(self):
        UniversalNominalRangeTransformer().transform(self.ont_graph)
        self.failUnlessEqual(
            len(list(self.foo.sub_class_of)),
            1,
            "There should still be one subsumed restriction",
        )
        sub_c = cast_class(first(self.foo.sub_class_of))
        self.failUnless(not isinstance(sub_c, Restriction), "subclass of a restriction")
        self.failUnless(sub_c.complement_of is not None, "Should be a complement.")
        inner_c = cast_class(sub_c.complement_of)
        self.failUnless(
            isinstance(inner_c, Restriction),
            "complement of a restriction, not %r" % inner_c,
        )
        self.failUnlessEqual(
            inner_c.on_property, EX_NS.propFoo, "restriction on propFoo"
        )
        self.failUnless(
            inner_c.some_values_from,
            "converted to an existential restriction not %r" % inner_c,
        )
        inverted_c = cast_class(inner_c.some_values_from)
        self.failUnless(
            isinstance(inverted_c, EnumeratedClass),
            "existential restriction on enumerated class",
        )
        self.assertEqual(
            len(inverted_c),
            2,
            "existencial restriction on enumerated class of length 2",
        )
        self.assertEqual(
            repr(inverted_c),
            "{ ex:individual2 ex:individual3 }",
            "The negated partition should exclude individual1",
        )
        NominalRangeTransformer().transform(self.ont_graph)
        DemorganTransformer().transform(self.ont_graph)

        sub_c = cast_class(first(self.foo.sub_class_of))
        self.assertEqual(
            repr(sub_c),
            "( ( not ( ex:propFoo value ex:individual2 ) ) and ( not ( ex:propFoo value ex:individual3 ) ) )",
        )


class ReductionTestB(unittest.TestCase):
    def setUp(self):
        self.ont_graph = Graph()
        self.ont_graph.bind("ex", EX_NS)
        self.ont_graph.bind("owl", OWL_NS)
        Individual.factoryGraph = self.ont_graph
        disjunct = (~EX.alpha) | (~EX.omega)
        self.foo = EX.foo
        disjunct += self.foo

    def testHiddenDemorgan(self):
        normal_form_reduction(self.ont_graph)
        self.failUnless(
            first(self.foo.sub_class_of).complement_of,
            "should be the negation of a boolean class",
        )
        inner_c = cast_class(first(self.foo.sub_class_of).complement_of)
        self.failUnless(
            isinstance(inner_c, BooleanClass)
            and inner_c._operator == OWL_NS.intersectionOf,
            "should be the negation of a conjunct",
        )
        self.assertEqual(repr(inner_c), "( ex:alpha and ex:omega )")


class FlatteningTest(unittest.TestCase):
    def setUp(self):
        self.ont_graph = Graph()
        self.ont_graph.bind("ex", EX_NS)
        self.ont_graph.bind("owl", OWL_NS)
        Individual.factoryGraph = self.ont_graph
        nested_conjunct = EX.omega & EX.gamma
        self.topLevelConjunct = EX.alpha & nested_conjunct

    def testFlattening(self):
        self.assertEquals(
            repr(self.topLevelConjunct), "ex:alpha THAT ( ex:omega AND ex:gamma )"
        )
        ConjunctionFlattener().transform(self.ont_graph)
        self.assertEquals(
            repr(self.topLevelConjunct), "( ex:alpha AND ex:omega AND ex:gamma )"
        )


class UniversalComplementXFormTest(unittest.TestCase):
    def setUp(self):
        self.ont_graph = Graph()
        self.ont_graph.bind("ex", EX_NS)
        self.ont_graph.bind("owl", OWL_NS)
        Individual.factoryGraph = self.ont_graph

    def testUniversalInversion(self):
        test_class1 = EX.omega & (Property(EX_NS.someProp) | only | ~EX.gamma)
        test_class1.identifier = EX_NS.Foo
        self.assertEquals(
            repr(test_class1), "ex:omega THAT ( ex:someProp ONLY ( NOT ex:gamma ) )"
        )
        normal_form_reduction(self.ont_graph)
        self.assertEquals(
            repr(test_class1), "ex:omega THAT ( NOT ( ex:someProp SOME ex:gamma ) )"
        )


if __name__ == "__main__":
    unittest.main()
