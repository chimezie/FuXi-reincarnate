# -*- coding: utf-8 -*-
# flake8: noqa
from functools import lru_cache, reduce

from rdflib.graph import Graph
from rdflib import BNode, Namespace, Variable

from .Node import Node

OWL_NS = Namespace("http://www.w3.org/2002/07/owl#")

SUBJECT = 0
PREDICATE = 1
OBJECT = 2

VARIABLE = 0
VALUE = 1

TERMS = [SUBJECT, PREDICATE, OBJECT]


def normalize_term(term):
    """
    Graph Identifiers are used
    """
    if isinstance(term, Graph):
        return term.identifier
    else:
        return term


def format_doctest_out(obj):
    return obj


class ReteToken:
    """
    A ReteToken, an RDF triple in a Rete network.  Once it passes an alpha
    node test, if will have unification substitutions per variable
    """

    __slots__ = (
        "debug",
        "subject",
        "predicate",
        "object_",
        "binding_dict",
        "_term_concat",
        "hash",
        "inferred",
        "pattern",
    )

    def __init__(self, triple, debug=False):
        (subject, predicate, object) = triple
        self.debug = debug
        self.subject = (None, normalize_term(subject))
        self.predicate = (None, normalize_term(predicate))
        self.object_ = (None, normalize_term(object))
        self.binding_dict = {}
        self._term_concat = self.concatenate_terms(
            tuple(term[VALUE] for term in [self.subject, self.predicate, self.object_])
        )
        self.hash = hash(self._term_concat)
        self.inferred = False

    def __hash__(self):
        """

        >>> token1 = ReteToken((RDFS.domain, RDFS.domain, RDFS.Class))
        >>> token2 = ReteToken((RDFS.domain, RDFS.domain, RDFS.Class))
        >>> token1 == token2
        True
        >>> token1 in set([token2])
        True
        """
        return self.hash

    @staticmethod
    @lru_cache(maxsize=4096)
    def concatenate_terms(values):
        return reduce(lambda x, y: str(x) + str(y), values)

    def __eq__(self, other):
        return hash(self) == hash(other)

    @format_doctest_out
    def alpha_network_hash(self, term_hash):
        """
        We store pointers to all the system's alpha memories in a hash table, indexed
        according to the particular values being tested. Executing the alpha network then becomes a
        simple matter of doing eight hash table lookups:

        >>> aNode1 = AlphaNode((Variable('Z'), RDF.type, Variable('A')))
        >>> aNode2 = AlphaNode((Variable('X'), RDF.type, Variable('C')))
        >>> token = ReteToken((URIRef('urn:uuid:Boo'), RDF.type, URIRef('urn:uuid:Foo')))
        >>> token.alpha_network_hash(aNode1.alpha_network_hash())
        %(u)s'http://www.w3.org/1999/02/22-rdf-syntax-ns#type'

        """
        triple = list(self.as_tuple())
        term_hash = list(term_hash)
        return "".join([triple[idx] for idx in TERMS if term_hash[idx] == "1"])

    def unbound_copy(self, no_subsequent_debug=False):
        if no_subsequent_debug:
            return ReteToken(
                (self.subject[VALUE], self.predicate[VALUE], self.object_[VALUE])
            )
        else:
            return ReteToken(
                (self.subject[VALUE], self.predicate[VALUE], self.object_[VALUE]),
                self.debug,
            )

    def __repr__(self):
        return "<ReteToken: %s>" % (
            ", ".join(
                ["%s->%s" % (var, val) for var, val in self.get_var_bindings(False)]
            )
        )

    def get_var_bindings(self, as_dict=True):
        _vars = []
        for var, val in [self.subject, self.predicate, self.object_]:
            if isinstance(var, (Variable)):
                _vars.append((var, val))
        return dict(_vars) if as_dict else _vars

    def get_uniterm(self):
        from fuxi.Horn.PositiveConditions import build_uniterm_from_tuple

        return build_uniterm_from_tuple(
            tuple([val for var, val in [self.subject, self.predicate, self.object_]])
        )

    def as_tuple(self):
        return (self.subject[VALUE], self.predicate[VALUE], self.object_[VALUE])

    def bind_variables(self, thing):
        """
        This function, called when a token passes a node test, associates
        token terms with variables in the node test
        """
        if isinstance(thing, BuiltInAlphaNode):
            self.pattern = list(thing.n3builtin)
            self.subject = (thing.n3builtin.argument, self.subject[VALUE])
            self.predicate = (thing.n3builtin.uri, self.predicate[VALUE])
            self.object_ = (thing.n3builtin.result, self.object_[VALUE])
            assert not self.binding_dict, self.binding_dict
            bind_hash_items = []
            for var, val in [self.subject, self.predicate, self.object_]:
                if (
                    var
                    and isinstance(var, (Variable, BNode))
                    and var not in self.binding_dict
                ):
                    self.binding_dict[var] = val
                    bind_hash_items.append(var + val)
                else:
                    bind_hash_items.append(val)
            # self.bindingDict := { var1 -> val1, var2 -> val2, ..  }
            self.hash = hash(reduce(lambda x, y: x + y, bind_hash_items))
            return self
        elif isinstance(thing, AlphaNode):
            self.pattern = thing.triple_pattern
            self.subject = (thing.triple_pattern[SUBJECT], self.subject[VALUE])
            self.predicate = (thing.triple_pattern[PREDICATE], self.predicate[VALUE])
            self.object_ = (thing.triple_pattern[OBJECT], self.object_[VALUE])
            assert not self.binding_dict, self.binding_dict
            bind_hash_items = []
            for var, val in [self.subject, self.predicate, self.object_]:
                if (
                    var
                    and isinstance(var, (Variable, BNode))
                    and var not in self.binding_dict
                ):
                    self.binding_dict[var] = val
                    bind_hash_items.append(var + val)
                else:
                    bind_hash_items.append(val)
            # self.bindingDict := { var1 -> val1, var2 -> val2, ..  }
            self.hash = hash(reduce(lambda x, y: x + y, bind_hash_items))
            return self
        elif isinstance(thing, dict):
            rev_dict = dict([(v, k) for k, v in list(thing.items())])
            # create mapping from variable to value if in range of mapping
            self.subject = (
                rev_dict.get(self.subject[VALUE], self.subject[VALUE]),
                self.subject[VALUE],
            )
            self.predicate = (
                rev_dict.get(self.predicate[VALUE], self.predicate[VALUE]),
                self.predicate[VALUE],
            )
            self.object_ = (
                rev_dict.get(self.object_[VALUE], self.object_[VALUE]),
                self.object_[VALUE],
            )


def default_intra_element_test(a_rete_token, triple_pattern):
    """
    'Standard' Charles Forgy intra element token pattern test.
    """
    token_terms = [
        a_rete_token.subject[VALUE],
        a_rete_token.predicate[VALUE],
        a_rete_token.object_[VALUE],
    ]
    var_bindings = {}
    for idx in [SUBJECT, PREDICATE, OBJECT]:
        token_term = token_terms[idx]
        pattern_term = triple_pattern[idx]
        if not isinstance(pattern_term, (Variable, BNode)) and token_term != pattern_term:
            return False
        elif pattern_term in var_bindings and var_bindings[pattern_term] != token_term:
            return False
        elif pattern_term not in var_bindings:
            var_bindings[pattern_term] = token_term
    return True


class AlphaNode(Node):
    """
    Basic Triple Pattern Pattern check
    """

    def __init__(self, triple_pattern_or_func, filters=None):
        filters = filters and filters or {}
        self.relinked = False
        self.name = BNode()
        self.triple_pattern = triple_pattern_or_func
        self.descendent_memory = []
        self.descendent_beta_nodes = set()
        self.builtin = bool(filters.get(self.triple_pattern[PREDICATE]))
        self.universal_truths = []

    @format_doctest_out
    def alpha_network_hash(self, ground_term_hash=False, skolem_terms=None):
        """
        Thus, given a WME w, to determine which alpha memories w should be added to, we need only check whether
        any of these eight possibilities is actually present in the system.  (Some might not be present, since
        there might not be any alpha memory corresponding to that particular combination of tests and 's.)

        0 - Variable
        1 - Ground term

        >>> aNode1 = AlphaNode((Variable('P'), RDF.type, OWL_NS.InverseFunctionalProperty))
        >>> aNode2 = AlphaNode((Variable('X'), Variable('P'), Variable('Z')))
        >>> aNode1.alpha_network_hash()
        ('0', '1', '1')
        >>> aNode2.alpha_network_hash()
        ('0', '0', '0')
        >>> aNode1.alpha_network_hash(ground_term_hash=True)
        %(u)s'http://www.w3.org/1999/02/22-rdf-syntax-ns#typehttp://www.w3.org/2002/07/owl#InverseFunctionalProperty'
        """
        if skolem_terms is None:
            skolem_terms = []
        if ground_term_hash:
            return "".join(
                [
                    term
                    for term in self.triple_pattern
                    if not isinstance(term, (BNode, Variable))
                       or isinstance(term, BNode)
                       and term in skolem_terms
                ]
            )
        else:
            return tuple(
                [
                    isinstance(term, (BNode, Variable)) and "0" or "1"
                    for term in self.triple_pattern
                ]
            )

    def check_default_rule(self, default_rules):
        """
        Check to see if the inter element test associated with this Alpha node may match
        the given 'default' conflict set.  If so, update universalTruths with the
        default conflict set token list which if matched, means the intra element test automatically
        passes
        """
        pass

    def __repr__(self):
        return "<AlphaNode: %s. Feeds %s beta nodes>" % (
            repr(self.triple_pattern),
            len(self.descendent_beta_nodes),
        )

    def activate(self, a_rete_token):
        from .BetaNode import (
            PartialInstantiation,
            LEFT_MEMORY,
            RIGHT_MEMORY,
            LEFT_UNLINKING,
        )

        a_rete_token.bind_variables(self)
        for memory in self.descendent_memory:
            single_token = PartialInstantiation(
                [a_rete_token], consistent_bindings=a_rete_token.binding_dict.copy()
            )
            if memory.position == LEFT_MEMORY:
                memory.add_token(single_token)
            else:
                memory.add_token(a_rete_token)
            if (
                memory.successor.left_unlinked_nodes
                and len(memory) == 1
                and LEFT_UNLINKING
            ):
                for node in memory.successor.left_unlinked_nodes:
                    if node.unlinked_memory is None:
                        assert len(node.descendent_memory) == 1, "%s %s %s" % (
                            node,
                            node.descendent_memory,
                            memory.successor,
                        )
                        disconnected_memory = list(node.descendent_memory)[0]

                    else:
                        disconnected_memory = node.unlinked_memory
                        node.descendent_memory.append(disconnected_memory)
                        node.unlinked_memory = None
                    memory.successor.memories[LEFT_MEMORY] = disconnected_memory
                    node.descendent_beta_nodes.add(memory.successor)
                    # print(memory.successor.memories[LEFT_MEMORY])
                    memory.successor.propagate(
                        RIGHT_MEMORY, a_rete_token.debug, wme=a_rete_token
                    )
                memory.successor.left_unlinked_nodes = set()

            if a_rete_token.debug:
                print("Added %s to %s" % (a_rete_token, memory.successor))

            if memory.successor.a_pass_thru or not memory.successor.check_null_activation(
                memory.position
            ):
                if a_rete_token.debug:
                    print("Propagated from %s" % (self))
                    print(a_rete_token.as_tuple())
                if memory.position == LEFT_MEMORY:
                    memory.successor.propagate(
                        memory.position, a_rete_token.debug, single_token
                    )
                else:
                    memory.successor.propagate(
                        memory.position, a_rete_token.debug, wme=a_rete_token
                    )
            else:
                if a_rete_token.debug:
                    print(
                        "skipped null right activation of %s from %s"
                        % (memory.successor, self)
                    )

class BuiltInAlphaNode(AlphaNode):
    """
    An Alpha Node for Builtins which doesn't participate in intraElement tests
    """

    def __init__(self, n3_builtin):
        self.name = BNode()
        self.n3builtin = n3_builtin
        self.descendent_memory = []
        self.descendent_beta_nodes = set()
        self.universal_truths = []

    def __iter__(self):
        yield self.n3builtin.argument
        yield self.n3builtin.result

    def alpha_network_hash(self, ground_term_hash=False):
        if ground_term_hash:
            return "".join(
                [
                    term
                    for term in self.n3builtin
                    if not isinstance(term, (BNode, Variable))
                ]
            )
        else:
            return tuple(
                [
                    isinstance(term, (BNode, Variable)) and "0" or "1"
                    for term in self.n3builtin
                ]
            )

    def __repr__(self):
        return "<BuiltInAlphaNode %s(%s), %s : Feeds %s beta nodes>" % (
            self.n3builtin.func,
            self.n3builtin.argument,
            self.n3builtin.result,
            len(self.descendent_beta_nodes),
        )

    def intra_element_test(self, a_rete_token):
        pass


def test():
    import doctest

    doctest.testmod()


if __name__ == "__main__":
    test()
