# -*- coding: utf-8 -*-
# flake8: noqa
"""
Implements the behavior associated with the 'join' (Beta) node in a RETE
network:
    - Stores tokens in two memories
    - Tokens in memories are checked for consistent bindings (unification)
      for variables in common *across* both
    - Network 'trigger' is propagated downward

This reference implementation follows,  quite closely, the algorithms presented
in the PhD thesis (1995) of Robert Doorenbos:
    Production Matching for Large Learning Systems (RETE/UL)

A N3 Triple is a working memory element (WME)

The Memories are implemented with consistent binding hashes. Unlinking is not
implemented but null activations are mitigated (somewhat) by the hash / set mechanism.

"""

import copy
import os
import unittest
from pprint import pprint
from .AlphaNode import AlphaNode, BuiltInAlphaNode, ReteToken
from .Node import Node
# from RuleStore import N3Builtin
# from IteratorAlgebra import hash_join
# from Util import xcombine
# from ReteVocabulary import RETE_NS

# from rdflib.graph import QuotedGraph, Graph
# from rdflib.collection import Collection

from rdflib import BNode, Literal, Namespace, RDF, Variable
from rdflib.util import first
from functools import reduce


_XSD_NS = Namespace("http://www.w3.org/2001/XMLSchema#")
OWL_NS = Namespace("http://www.w3.org/2002/07/owl#")
Any = None

LEFT_MEMORY = 1
RIGHT_MEMORY = 2

# Implementn left unlinking?
LEFT_UNLINKING = False

memory_position = {
    LEFT_MEMORY: "left",
    RIGHT_MEMORY: "right",
}


def collect_variables(node):
    """
    Utility function for locating variables common to the patterns in both left and right nodes
    """
    if isinstance(node, BuiltInAlphaNode):
        return set()
    if isinstance(node, AlphaNode):
        return set(
            [
                term
                for term in node.triple_pattern
                if isinstance(term, (Variable, BNode))
            ]
        )
    elif node:
        combined_vars = set()
        combined_vars |= node.left_variables
        combined_vars |= node.right_variables
        return combined_vars
    else:
        return set()


def any(seq, pred=None):
    """Returns True if pred(x) is true for at least one element in the iterable"""
    for elem in filter(pred, seq):
        return True
    return False


def _env_flag(name: str) -> bool:
    value = os.environ.get(name, "")
    return value.lower() not in ("", "0", "false", "no")


class ReteMemory(set):
    def __init__(self, beta_node, position, filter=None):
        super(ReteMemory, self).__init__(())
        self.filter = filter
        self.successor = beta_node
        self.position = position
        self.substitution_dict = {}  # hashed

    def union(self, other):
        """Return the union of two sets as a new set.

        (I.e. all elements that are in either set.)
        """
        result = ReteMemory(self.successor, self.position)
        result.update(other)
        return result

    def __repr__(self):
        return "<%sMemory: %s item(s)>" % (
            self.position == LEFT_MEMORY and "Beta" or "Alpha",
            len(self),
        )

    def add_token(self, token, debug=False):
        common_var_key = []
        if isinstance(token, PartialInstantiation):
            for binding in token.bindings:
                common_var_key = []
                for var in self.successor.common_variables:
                    common_var_key.append(binding.get(var))
                self.substitution_dict.setdefault(tuple(common_var_key), set()).add(
                    token
                )
        else:
            for var in self.successor.common_variables:
                common_var_key.append(token.binding_dict.get(var))
            self.substitution_dict.setdefault(tuple(common_var_key), set()).add(token)
        self.add(token)

    def reset(self):
        self.clear()
        self.substitution_dict = {}

    @classmethod
    def _wrap_methods(cls, names):
        def wrap_method_closure(name):
            def inner(self, *args):
                result = getattr(super(cls, self), name)(*args)
                if isinstance(result, set) and not hasattr(result, "foo"):
                    result = cls(result, foo=self.foo)
                return result

            inner.fn_name = name
            setattr(cls, name, inner)

        for name in names:
            wrap_method_closure(name)


ReteMemory._wrap_methods(
    [
        "__ror__",
        "difference_update",
        "__isub__",
        "symmetric_difference",
        "__rsub__",
        "__and__",
        "__rand__",
        "intersection",
        "difference",
        "__iand__",
        "__ixor__",
        "symmetric_difference_update",
        "__or__",
        "copy",
        "__rxor__",
        "intersection_update",
        "__xor__",
        "__ior__",
        "__sub__",
    ]
)


def project(orig_dict, attributes, inverse=False):
    """
    Dictionary projection: http://jtauber.com/blog/2005/11/17/relational_python:_projection

    >>> a = {'one' : 1, 'two' : 2, 'three' : 3 }
    >>> project(a,['one','two'])
    {'two': 2, 'one': 1}
    >>> project(a,['four'])
    {}
    >>> project(a,['one','two'],True)
    {'three': 3}
    """
    if inverse:
        return dict(
            [item for item in list(orig_dict.items()) if item[0] not in attributes]
        )
    else:
        return dict([item for item in list(orig_dict.items()) if item[0] in attributes])


class PartialInstantiation(object):
    """
    Represents a set of WMEs 'joined' along one or more
    common variables from an ancestral join node 'up' the network

    In the RETE/UL PhD thesis, this is refered to as a token, which contains a set of WME triples.
    This is a bit of a clash with the use of the same word (in the original Forgy paper) to
    describe what is essentially a WME and whether or not it is an addition to the networks memories
    or a removal

    It is implemented (in the RETE/UL thesis) as a linked list of:

    structure token:
        parent: token {points to the higher token, for items 1...i-1}
        wme: WME {gives item i}
    end

    Here it is instead implemented as a set of WME triples associated with a list variables whose
    bindings are consistent

    >>> from rdflib import Variable
    >>> aNode = AlphaNode((Variable('X'),RDF.type,Variable('C')))
    >>> token = ReteToken((URIRef('urn:uuid:Boo'),RDF.type,URIRef('urn:uuid:Foo')))
    >>> token = token.bind_variables(aNode)
    >>> PartialInstantiation([token])
    <PartialInstantiation: set([<ReteToken: X->urn:uuid:Boo, C->urn:uuid:Foo>])>
    >>> for token in PartialInstantiation([token]):
    ...   print(token)
    <ReteToken: X->urn:uuid:Boo, C->urn:uuid:Foo>
    """

    __slots__ = (
        "joined_bindings",
        "inconsistent_vars",
        "debug",
        "tokens",
        "_bindings_cache",
        "_bindings_cache_enabled",
        "hash",
    )

    def __init__(self, tokens=None, debug=False, consistent_bindings=None):
        """
        Note a hash is calculated by
        sorting & concatenating the hashes of its tokens
        """
        self.joined_bindings = consistent_bindings and consistent_bindings or {}
        self.inconsistent_vars = set()
        self.debug = debug
        self.tokens = set()
        self._bindings_cache_enabled = _env_flag("FUXI_RETE_BINDINGS_CACHE")
        self._bindings_cache = None
        if tokens:
            for token in tokens:
                self.add(token, no_post_processing=True)
            self._generate_hash()

    def copy(self):
        token_list = []
        for token in self.tokens:
            wme = copy.deepcopy(token)
            token_list.append(wme)
        return PartialInstantiation(
            token_list, consistent_bindings=self.joined_bindings
        )

    def _generate_hash(self):
        token_hashes = [hash(token) for token in self.tokens]
        token_hashes.sort()
        self.hash = hash(reduce(lambda x, y: x + y, token_hashes))

    def unify(self, left, right):
        """
        Takes two dictionary and collapses it if there are no overlapping 'bindings' or
        'rounds out' both dictionaries so they each have each other's non-overlapping binding
        """
        both_keys = [
            key
            for key in list(left.keys()) + list(right.keys())
            if key not in self.joined_bindings
        ]
        if len(both_keys) == len(set(both_keys)):
            join_dict = left.copy()
            join_dict.update(right)
            return join_dict
        else:
            r_copy = right.copy()
            left.update(
                project(r_copy, [key for key in list(right.keys()) if key not in left])
            )
            l_copy = left.copy()
            right.update(
                project(l_copy, [key for key in list(left.keys()) if key not in right])
            )
            return [left, right]

    def _generate_bindings(self):
        if self._bindings_cache_enabled:
            self._bindings_cache = list(self._iter_bindings())
        else:
            self._bindings_cache = None

    def _iter_bindings(self):
        """
        Generates unique variable substitutions (bindings) for this partial instantiation.
        """

        def product(*args):
            if not args:
                return iter(((),))
            return (
                items + (item,) for items in product(*args[:-1]) for item in args[-1]
            )

        disjunctive_dict = {}
        for token in self.tokens:
            for key, val in list(token.binding_dict.items()):
                disjunctive_dict.setdefault(key, set()).add(val)
        if not disjunctive_dict:
            yield {}
            return
        keys = list(disjunctive_dict)
        for entry in product(
            *tuple([disjunctive_dict[var] for var in disjunctive_dict])
        ):
            yield dict([(keys[idx], val) for idx, val in enumerate(entry)])

    def __hash__(self):
        return self.hash

    def __eq__(self, other):
        return hash(self) == hash(other)

    def add(self, token, no_post_processing=False):
        """
        >>> from rdflib import URIRef, Variable
        >>> aNode = AlphaNode((Variable('S'),Variable('P'),Variable('O')))
        >>> token1 = ReteToken((URIRef('urn:uuid:Boo'),RDF.type,URIRef('urn:uuid:Foo')))
        >>> token2 = ReteToken((URIRef('urn:uuid:Foo'),RDF.type,URIRef('urn:uuid:Boo')))
        >>> inst = PartialInstantiation([token1.bind_variables(aNode),token2.bind_variables(aNode)])
        >>> inst
        <PartialInstantiation: set([<ReteToken: S->urn:uuid:Boo, P->http://www.w3.org/1999/02/22-rdf-syntax-ns#type, O->urn:uuid:Foo>, <ReteToken: S->urn:uuid:Foo, P->http://www.w3.org/1999/02/22-rdf-syntax-ns#type, O->urn:uuid:Boo>])>
        """
        self.tokens.add(token)
        if not no_post_processing:
            self._generate_hash()
            self._generate_bindings()

    def __repr__(self):
        if self.joined_bindings:
            join_msg = " (joined on %s)" % (
                ",".join(["?" + v for v in self.joined_bindings])
            )
        else:
            join_msg = ""
        return "<PartialInstantiation%s: %s>" % (join_msg, self.tokens)

    def __iter__(self):
        for i in self.tokens:
            yield i

    def __len__(self):
        return len(self.tokens)

    def add_consistent_binding(self, new_join_variables):
        # new_join_dict = self.joinedBindings.copy()
        # only a subset of the tokens in this partial instantiation will be 'merged' with
        # the new token - joined on the new join variables
        new_join_dict = dict([(v, None) for v in new_join_variables])
        unmapped_join_vars = set(new_join_dict)
        # new_join_dict.update(dict([(v,None) for v in newJoinVariables]))
        for binding in self.bindings:
            for key, val in new_join_dict.items():
                bound_val = binding.get(key)
                if bound_val is not None:
                    unmapped_join_vars.discard(key)
                    if val is None:
                        new_join_dict[key] = bound_val
        if unmapped_join_vars:
            for unmapped_var in unmapped_join_vars:
                for token in self.tokens:
                    unmapped_var_val = token.get_var_bindings().get(unmapped_var)
                    if unmapped_var_val is not None:
                        assert (
                            new_join_dict[unmapped_var] is None
                            or unmapped_var_val == new_join_dict[unmapped_var]
                        )
                        new_join_dict[unmapped_var] = unmapped_var_val
        self.joined_bindings.update(new_join_dict)
        self._generate_bindings()

    @property
    def bindings(self):
        if self._bindings_cache_enabled:
            if self._bindings_cache is None:
                self._bindings_cache = list(self._iter_bindings())
            return self._bindings_cache
        return self._iter_bindings()

    def new_join(self, right_wme, new_join_variables):
        """
        >>> aNode1 = AlphaNode((Variable('P1'),RDF.type,URIRef('urn:uuid:Prop1')))
        >>> aNode2 = AlphaNode((Variable('P2'),RDF.type,URIRef('urn:uuid:Prop1')))
        >>> aNode3 = AlphaNode((Variable('P1'),Variable('P2'),RDFS.Class))
        >>> token1 = ReteToken((RDFS.domain,RDFS.domain,RDFS.Class))
        >>> token2 = ReteToken((RDFS.domain,RDF.type,URIRef('urn:uuid:Prop1')))
        >>> token3 = ReteToken((RDFS.range,RDF.type,URIRef('urn:uuid:Prop1')))
        >>> token4 = ReteToken((RDFS.range,RDFS.domain,RDFS.Class))
        >>> token5 = ReteToken((RDFS.domain,RDF.type,URIRef('urn:uuid:Prop1'))).bind_variables(aNode2)
        >>> inst = PartialInstantiation([token2.bind_variables(aNode1),token3.bind_variables(aNode2),token5])
        >>> pprint(list(inst.tokens))
        [<ReteToken: P2->http://www.w3.org/2000/01/rdf-schema#range>,
         <ReteToken: P1->http://www.w3.org/2000/01/rdf-schema#domain>,
         <ReteToken: P2->http://www.w3.org/2000/01/rdf-schema#domain>]
        >>> newInst = inst.new_join(token1.bind_variables(aNode3),[Variable('P2')])
        >>> token1
        <ReteToken: P1->http://www.w3.org/2000/01/rdf-schema#domain, P2->http://www.w3.org/2000/01/rdf-schema#domain>
        >>> newInst
        <PartialInstantiation (joined on ?P2): set([<ReteToken: P1->http://www.w3.org/2000/01/rdf-schema#domain, P2->http://www.w3.org/2000/01/rdf-schema#domain>, <ReteToken: P2->http://www.w3.org/2000/01/rdf-schema#range>, <ReteToken: P1->http://www.w3.org/2000/01/rdf-schema#domain>, <ReteToken: P2->http://www.w3.org/2000/01/rdf-schema#domain>])>
        >>> pprint(list(newInst.tokens))
        [<ReteToken: P1->http://www.w3.org/2000/01/rdf-schema#domain, P2->http://www.w3.org/2000/01/rdf-schema#domain>,
         <ReteToken: P2->http://www.w3.org/2000/01/rdf-schema#range>,
         <ReteToken: P1->http://www.w3.org/2000/01/rdf-schema#domain>,
         <ReteToken: P2->http://www.w3.org/2000/01/rdf-schema#domain>]
        """
        new_join_dict = self.joined_bindings.copy()
        if new_join_variables:
            # only a subset of the tokens in this partial instantiation will be 'merged' with
            # the new token - joined on the new join variables
            new_join_dict.update(project(right_wme.binding_dict, new_join_variables))
            new_p_inst = PartialInstantiation([], consistent_bindings=new_join_dict)
            for token in self.tokens:
                common_vars = False
                for new_var in [
                    x
                    for x in new_join_variables
                    if x in token.binding_dict
                    and right_wme.binding_dict[x] == token.binding_dict[x]
                ]:
                    # consistent token
                    common_vars = True
                    new_p_inst.add(token, no_post_processing=True)
                if not common_vars:
                    # there are no common variables, no need to check
                    new_p_inst.add(token, no_post_processing=True)
        else:
            # all of the tokens in this partial instantiation are already bound consistently with
            # respect to the new token
            new_p_inst = PartialInstantiation([], consistent_bindings=new_join_dict)
            for token in self.tokens:
                new_p_inst.add(token, no_post_processing=True)
        new_p_inst.add(right_wme)
        return new_p_inst


class BetaNode(Node):
    """
      Performs a rete network join between partial instantiations in its left memory and tokens in its memories

      "The data structure for a join node, therefore, must contain pointers to its two memory
      nodes (so they can be searched), a specification of any variable binding consistency tests to be
      performed, and a list of the node's children. .. (the beta memory is always its parent)."

      Setup 3 alpha nodes (Triple Patterns):

          aNode1 = ?X rdf:value 1
          aNode2 = ?X rdf:type ?Y
          aNode3 = ?Z <urn:uuid:Prop1> ?W

      >>> aNode1 = AlphaNode((Variable('X'),RDF.value,Literal(2)))
      >>> aNode2 = AlphaNode((Variable('X'),RDF.type,Variable('Y')))
      >>> aNode3 = AlphaNode((Variable('Z'),URIRef('urn:uuid:Prop1'),Variable('W')))


      Rete Network
      ------------

     aNode1
       |
    joinNode1
          \\   aNode2
           \\   /    aNode3
          joinNode2  /
              \\     /
               \\   /
           joinNode3

      joinNode3 is the Terminal node

      >>> joinNode1 = BetaNode(None,aNode1,a_pass_thru=True)
      >>> joinNode1.connect_incoming_nodes(None,aNode1)
      >>> joinNode2 = BetaNode(joinNode1,aNode2)
      >>> joinNode2.connect_incoming_nodes(joinNode1,aNode2)
      >>> joinNode3 = BetaNode(joinNode2,aNode3)
      >>> joinNode3.connect_incoming_nodes(joinNode2,aNode3)

      >>> joinNode1
      <BetaNode (pass-thru): CommonVariables: [?X] (0 in left, 0 in right memories)>
      >>> joinNode2
      <BetaNode : CommonVariables: [?X] (0 in left, 0 in right memories)>

      Setup tokens (RDF triples):

          token1 = <urn:uuid:Boo> rdf:value 2
          token2 = <urn:uuid:Foo> rdf:value 2
          token3 = <urn:uuid:Foo> rdf:type <urn:uuid:Baz>             (fires network)

          token3 is set with a debug 'trace' so its path through the network is printed along the way

          token4 = <urn:uuid:Bash> rdf:type <urn:uuid:Baz>
          token5 = <urn:uuid:Bar> <urn:uuid:Prop1> <urn:uuid:Beezle>  (fires network)
          token6 = <urn:uuid:Bar> <urn:uuid:Prop1> <urn:uuid:Bundle>  (fires network)

      >>> token1 = ReteToken((URIRef('urn:uuid:Boo'),RDF.value,Literal(2)))
      >>> token2 = ReteToken((URIRef('urn:uuid:Foo'),RDF.value,Literal(2)))
      >>> token3 = ReteToken((URIRef('urn:uuid:Foo'),RDF.type,URIRef('urn:uuid:Baz')),debug=True)
      >>> token4 = ReteToken((URIRef('urn:uuid:Bash'),RDF.type,URIRef('urn:uuid:Baz')))
      >>> token5 = ReteToken((URIRef('urn:uuid:Bar'),URIRef('urn:uuid:Prop1'),URIRef('urn:uuid:Beezle')),debug=True)
      >>> token6 = ReteToken((URIRef('urn:uuid:Bar'),URIRef('urn:uuid:Prop1'),URIRef('urn:uuid:Bundle')))
      >>> tokenList = [token1,token2,token3,token4,token5,token6]

      Setup the consequent (RHS) of the rule:
          { ?X rdf:value 1. ?X rdf:type ?Y. ?Z <urn:uuid:Prop1> ?W } => { ?X a <urn:uuid:SelectedVar> }

      a Network 'stub' is setup to capture the conflict set at the time the rule is fired

      >>> joinNode3.consequent.update([(Variable('X'),RDF.type,URIRef('urn:uuid:SelectedVar'))])
      >>> class NetworkStub:
      ...     def __init__(self):
      ...         self.firings = 0
      ...         self.conflictSet = set()
      ...     def fireConsequent(self,tokens,termNode,debug):
      ...         self.firings += 1
      ...         self.conflictSet.add(tokens)
      >>> testHelper = NetworkStub()
      >>> joinNode3.network = testHelper

      Add the tokens sequentially to the top of the network (the alpha nodes).
      token3 triggers a trace through it's path down to the terminal node (joinNode2)

      >>> aNode1.descendent_memory[0]
      <AlphaMemory: 0 item(s)>
      >>> aNode1.descendent_memory[0].position
      2
      >>> aNode1.activate(token1.unbound_copy())
      >>> aNode1.activate(token2.unbound_copy())
      >>> joinNode1.memories[LEFT_MEMORY]
      <BetaMemory: 0 item(s)>
      >>> joinNode2.memories[LEFT_MEMORY]
      <BetaMemory: 2 item(s)>

      # >>> aNode1.activate(token3.unboundCopy())
      # Propagated from <AlphaNode: (u'X', u'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', u'Y'). Feeds 1 beta nodes>
      # (u'urn:uuid:Foo', u'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', u'urn:uuid:Baz')
      # <BetaNode : CommonVariables: [u'X'] (2 in left, 1 in right memories)>.propagate(right,None,<ReteToken: X->urn:uuid:Foo,Y->urn:uuid:Baz>)
      # activating with <PartialInstantiation (joined on ?X): set([<ReteToken: X->urn:uuid:Foo>, <ReteToken: X->urn:uuid:Foo,Y->urn:uuid:Baz>])>

      # Add the remaining 3 tokens (each fires the network)

      # >>> aNode2.activate(token4.unboundCopy())
      # >>> list(joinNode3.memories[LEFT_MEMORY])[0]
      # <PartialInstantiation (joined on ?X): set([<ReteToken: X->urn:uuid:Foo>, <ReteToken: X->urn:uuid:Foo,Y->urn:uuid:Baz>])>
      # >>> aNode3.activate(token5.unboundCopy())
      # Propagated from <AlphaNode: (u'Z', u'urn:uuid:Prop1', u'W'). Feeds 1 beta nodes>
      # (u'urn:uuid:Bar', u'urn:uuid:Prop1', u'urn:uuid:Beezle')
      # <TerminalNode : CommonVariables: [] (1 in left, 1 in right memories)>.propagate(right,None,<ReteToken: Z->urn:uuid:Bar,W->urn:uuid:Beezle>)
      # activating with <PartialInstantiation (joined on ?X): set([<ReteToken: Z->urn:uuid:Bar,W->urn:uuid:Beezle>, <ReteToken: X->urn:uuid:Foo>, <ReteToken: X->urn:uuid:Foo,Y->urn:uuid:Baz>])>

      # >>> aNode3.activate(token6.unboundCopy())
      # >>> joinNode3
      # <TerminalNode : CommonVariables: [] (1 in left, 2 in right memories)>
      # >>> testHelper.firings
      # 2
      # >>> pprint(testHelper.conflictSet)
      # [<PartialInstantiation (joined on ?X): set([<ReteToken: Z->urn:uuid:Bar,W->urn:uuid:Beezle>, <ReteToken: X->urn:uuid:Foo>, <ReteToken: X->urn:uuid:Foo,Y->urn:uuid:Baz>])>, <PartialInstantiation (joined on ?X): set([<ReteToken: Z->urn:uuid:Bar,W->urn:uuid:Bundle>, <ReteToken: X->urn:uuid:Foo>, <ReteToken: X->urn:uuid:Foo,Y->urn:uuid:Baz>])>]
    """

    def __init__(
        self,
        left_node,
        right_node,
        a_pass_thru=False,
        left_variables=None,
        right_variables=None,
        execute_actions=None,
        rete_memory_kind=ReteMemory,
    ):
        self.rete_memory_kind = rete_memory_kind
        self.instanciating_tokens = set()
        self.a_pass_thru = a_pass_thru
        self.name = BNode()
        self.network = None

        # used by terminal nodes only
        self.consequent = set()  # List of tuples in RHS
        self.rules = set()
        self.antecedent = None
        self.head_atoms = set()
        self.left_node = left_node
        # The incoming right input of a BetaNode is always an AlphaNode
        self.right_node = right_node
        self.memories = {}
        self.descendent_memory = []
        self.descendent_beta_nodes = set()
        self.left_unlinked_nodes = set()
        self.unlinked_memory = None
        self.fed_by_builtin = None
        if isinstance(left_node, BuiltInAlphaNode):
            self.fed_by_builtin = LEFT_MEMORY
            assert not isinstance(right_node, BuiltInAlphaNode), (
                "Both %s and %s are builtins feeding a beta node."
                % (left_node, right_node)
            )
            self.memories[RIGHT_MEMORY] = self.rete_memory_kind(
                (self, RIGHT_MEMORY, left_node.n3builtin)
            )
        else:
            self.memories[RIGHT_MEMORY] = self.rete_memory_kind(self, RIGHT_MEMORY)

        assert not (self.fed_by_builtin), (
            "No support for 'built-ins', function symbols, or non-equality tests."
        )
        if isinstance(right_node, BuiltInAlphaNode):
            self.fed_by_builtin = RIGHT_MEMORY
            assert not isinstance(left_node, BuiltInAlphaNode), (
                "Both %s and %s are builtins feeding a beta node."
                % (left_node, right_node)
            )
            self.memories[LEFT_MEMORY] = self.rete_memory_kind(
                self, LEFT_MEMORY, right_node.n3builtin
            )
        else:
            self.memories[LEFT_MEMORY] = self.rete_memory_kind(self, LEFT_MEMORY)
        if a_pass_thru:
            if right_node:
                self.left_variables = (
                    set() if left_variables is None else left_variables
                )
                self.right_variables = (
                    collect_variables(self.right_node)
                    if right_variables is None
                    else right_variables
                )
                self.common_variables = list(self.right_variables)
            else:
                self.left_variables = self.right_variables = set()
                self.common_variables = []
        else:
            self.left_variables = (
                collect_variables(self.left_node)
                if left_variables is None
                else left_variables
            )
            self.right_variables = (
                collect_variables(self.right_node)
                if right_variables is None
                else right_variables
            )
            self.common_variables = [
                left_var
                for left_var in self.left_variables
                if left_var in self.right_variables
            ]
        self.left_index = {}
        self.right_index = {}
        self.execute_actions = execute_actions if execute_actions is not None else {}

    def connect_incoming_nodes(self, left_node, right_node):
        if left_node:
            if self.left_node and LEFT_UNLINKING:
                # candidate for left unlinking
                self.left_unlinked_nodes.add(left_node)
                left_node.unlinked_memory = self.rete_memory_kind(self, LEFT_MEMORY)
                # print("unlinked %s from %s"%(leftNode,self))
            elif self.left_node:
                left_node.update_descendent_memory(self.memories[LEFT_MEMORY])
                left_node.descendent_beta_nodes.add(self)
        right_node.update_descendent_memory(self.memories[RIGHT_MEMORY])
        right_node.descendent_beta_nodes.add(self)

    def clause_representation(self):
        if len(self.rules) > 1:
            return "And(%s) :- %s" % (
                " ".join([repr(atom) for atom in self.head_atoms]),
                self.antecedent,
            )
        elif len(self.rules) > 0:
            return repr(first(self.rules).formula)
        else:
            return ""

    def actions_for_terminal_node(self):
        for rhs_triple in self.consequent:
            override, execute_fn = self.execute_actions.get(rhs_triple, (None, None))
            if execute_fn is not None:
                yield override, execute_fn

    def __repr__(self):
        if self.execute_actions:
            action_str = " with %s actions" % (
                len(list(self.actions_for_terminal_node()))
            )
        else:
            action_str = ""
        if self.consequent and self.fed_by_builtin:
            node_type = "TerminalBuiltin(%s)%s" % (
                self.memories[self._opposite_memory(self.fed_by_builtin)].filter,
                action_str,
            )
        elif self.consequent:
            node_type = "TerminalNode%s (%s)" % (
                action_str,
                self.clause_representation(),
            )
        elif self.fed_by_builtin:
            node_type = "Builtin(%s)" % (
                self.memories[self._opposite_memory(self.fed_by_builtin)].filter
            )
        else:
            node_type = "BetaNode"
        if self.unlinked_memory is not None:
            node_type = "LeftUnlinked-" + node_type
        left_len = self.memories[LEFT_MEMORY] and len(self.memories[LEFT_MEMORY]) or 0
        return "<%s %s: CommonVariables: %s (%s in left, %s in right memories)>" % (
            node_type,
            self.a_pass_thru and "(pass-thru)" or "",
            self.common_variables,
            left_len,
            len(self.memories[RIGHT_MEMORY]),
        )

    def _activate(self, part_inst_or_list, debug=False):
        if debug:
            print("activating with %s" % part_inst_or_list)
        if self.unlinked_memory is not None:
            if debug:
                print("adding %s into unlinked memory" % part_inst_or_list)
            self.unlinked_memory.add_token(part_inst_or_list, debug)
        for memory in self.descendent_memory:
            if debug:
                print("\t## %s memory ##" % memory_position[memory.position])
                print("\t", memory.successor)
                if memory.successor.consequent:
                    print("\t", memory.successor.clause_representation())
            # print(self,partInstOrList)
            memory.add_token(part_inst_or_list, debug)
            if (
                memory.successor.a_pass_thru
                or not memory.successor.check_null_activation(memory.position)
            ):
                if memory.position == LEFT_MEMORY:
                    memory.successor.propagate(
                        memory.position, debug, part_inst_or_list
                    )
                else:
                    # print(partInstOrList)
                    memory.successor.propagate(None, debug, part_inst_or_list)

        if self.consequent:
            self.network.fire_consequent(part_inst_or_list, self, debug)

    def _unroll_tokens(self, iterable):
        for token in iterable:
            if isinstance(token, PartialInstantiation):
                for i in token:
                    yield i
            else:
                yield token

    def _opposite_memory(self, memory_position):
        if memory_position == LEFT_MEMORY:
            return RIGHT_MEMORY
        else:
            return LEFT_MEMORY

    def _check_opposing_memory(self, memory_position):
        return bool(len(self.memories[self._opposite_memory(memory_position)]))

    def check_null_activation(self, source):
        """
        Checks whether this beta node is involved in a NULL activation relative to the source.
        NULL activations are where one of the opposing memories that feed
        this beta node are empty.  Takes into account built-in filters/function.
        source is the position of the 'triggering' memory (i.e., the memory that had a token added)
        """
        opposite_mem = self.memories[self._opposite_memory(source)]
        return not self.fed_by_builtin and not opposite_mem

    def propagate(self, propagation_source, debug=False, partial_inst=None, wme=None):
        """
        .. 'activation' of Beta Node - checks for consistent
        variable bindings between memory of incoming nodes ..
        Beta (join nodes) with no variables in common with both ancestors
        activate automatically upon getting a propagation 'signal'

        """
        if debug and propagation_source:
            print(
                "%s.propagate(%s, %s, %s)"
                % (self, memory_position[propagation_source], partial_inst, wme)
            )
            print("### Left Memory ###")
            pprint(list(self.memories[LEFT_MEMORY]))
            print("###################")
            print("### Right Memory ###")
            pprint(list(self.memories[RIGHT_MEMORY]))
            print("####################")
            print(self.clause_representation())
        if self.a_pass_thru:
            if self.consequent:
                if self.right_node is None:
                    assert partial_inst is not None
                    self._activate(partial_inst, debug)
                else:
                    assert not partial_inst, "%s,%s" % (partial_inst, wme)
                    self._activate(
                        PartialInstantiation(
                            [wme], consistent_bindings=wme.binding_dict.copy()
                        ),
                        debug,
                    )

            elif self.memories[RIGHT_MEMORY]:
                # pass on wme as an unjoined partInst
                # print(self)
                if wme:
                    self._activate(
                        PartialInstantiation(
                            [wme], consistent_bindings=wme.binding_dict.copy()
                        ),
                        debug,
                    )
                elif partial_inst:
                    # print("## Problem ###")
                    # print("%s.propagate(%s,%s,%s)"%(self,memoryPosition[propagationSource],partialInst,wme))
                    self._activate(partial_inst, debug)
        elif not propagation_source:
            # Beta node right activated by another beta node
            # Need to unify on common variable hash, using the bindings
            # provided by the partial instantiation that triggered the
            # activation
            if partial_inst:
                for binding in partial_inst.bindings:
                    # for var in self.common_variables:
                    # if var not in binding:
                    #     import pdb;pdb.set_trace()
                    try:
                        common_vals = tuple(
                            [binding[var] for var in self.common_variables]
                        )
                        l_tokens = self.memories[RIGHT_MEMORY].substitution_dict.get(
                            common_vals, set()
                        )
                        r_tokens = self.memories[LEFT_MEMORY].substitution_dict.get(
                            common_vals, set()
                        )
                        joined_tokens = set(self._unroll_tokens(r_tokens | l_tokens))
                        if joined_tokens:
                            common_dict = dict(
                                [
                                    (
                                        var,
                                        list(common_vals)[
                                            self.common_variables.index(var)
                                        ],
                                    )
                                    for var in self.common_variables
                                ]
                            )
                            new_p = PartialInstantiation(
                                joined_tokens, consistent_bindings=common_dict
                            )
                            self._activate(new_p, debug)
                    except KeyError:
                        print("\tProblem with ", partial_inst)

        elif propagation_source == LEFT_MEMORY:
            # Doesn't check for null left activation! - cost is mitigated by
            # left activation, partialInst passed down
            # procedure join-node-left-activation (node: join-node, t: token)
            #     for each w in node.amem.items do
            #         if perform-join-tests (node.tests, t, w) then
            #             for each child in node.children do left-activation (child, t, w)
            # end
            matches = set()
            if self.fed_by_builtin:
                builtin = self.memories[
                    self._opposite_memory(self.fed_by_builtin)
                ].filter
                new_consistent_bindings = [
                    term
                    for term in [builtin.argument, builtin.result]
                    if isinstance(term, Variable)
                    and term not in partial_inst.joined_bindings
                ]
                partial_inst.add_consistent_binding(new_consistent_bindings)
                for binding in partial_inst.bindings:
                    lhs = builtin.argument
                    rhs = builtin.result
                    lhs = binding.get(lhs) if isinstance(lhs, Variable) else lhs
                    rhs = binding.get(rhs) if isinstance(rhs, Variable) else rhs
                    assert lhs is not None and rhs is not None
                    if builtin.func(lhs, rhs):
                        if debug:
                            print("\t%s + %s => True" % (binding, builtin))
                        matches.add(partial_inst)
                    else:
                        if debug:
                            print("\t%s + %s => False" % (binding, builtin))
            else:
                for binding in partial_inst.bindings:
                    # iterate over the binding combinations
                    # and use the substitutionDict in the right memory to find
                    # matching WME'a
                    if debug:
                        print("\t", binding)

                    substituted_term = []
                    common_dict_kv = []
                    for var in self.common_variables:
                        if var not in binding:
                            continue
                        else:
                            common_dict_kv.append((var, binding[var]))
                            substituted_term.append(binding[var])
                    r_wmes = self.memories[RIGHT_MEMORY].substitution_dict.get(
                        tuple(substituted_term), set()
                    )
                    common_dict = dict(common_dict_kv)
                    if debug:
                        print(
                            common_dict,
                            r_wmes,
                            list(self.memories[RIGHT_MEMORY].substitution_dict.keys()),
                        )
                    for right_wme in r_wmes:
                        if isinstance(right_wme, ReteToken):
                            matches.add(
                                partial_inst.new_join(
                                    right_wme,
                                    [
                                        x
                                        for x in self.common_variables
                                        if x not in partial_inst.joined_bindings
                                    ],
                                )
                            )
                        else:
                            # Joining two Beta/Join nodes!
                            joined_tokens = list(partial_inst.tokens | right_wme.tokens)
                            if self.consequent:
                                for consequent in self.consequent:
                                    cons_vars = [
                                        x for x in consequent if isinstance(x, Variable)
                                    ]
                                    # [i for i in consequent if isinstance(i,Variable)]
                                failed = True
                                for binding in PartialInstantiation(
                                    joined_tokens, consistent_bindings=common_dict
                                ).bindings:
                                    # [key for key in cons_vars if key not in binding]:
                                    if any(cons_vars, lambda x: x not in binding):
                                        continue
                                    else:
                                        failed = False
                                if not failed:
                                    new_p = PartialInstantiation(
                                        joined_tokens, consistent_bindings=common_dict
                                    )
                                    matches.add(new_p)
                            else:
                                new_p = PartialInstantiation(
                                    joined_tokens, consistent_bindings=common_dict
                                )
                                matches.add(new_p)

            for p_inst in matches:
                self._activate(p_inst, debug)
        else:
            # right activation, partialInst & wme passed down
            # procedure join-node-right-activation (node: join-node, w: WME)
            #    for each t in node.parent.items do {"parent" is the beta memory node}
            #        if perform-join-tests (node.tests, t, w) then
            #            for each child in node.children do left-activation (child, t, w)
            # end
            matches = set()
            try:
                l_part_insts = self.memories[LEFT_MEMORY].substitution_dict.get(
                    tuple([wme.binding_dict[var] for var in self.common_variables])
                )
            except:
                raise Exception("%s and %s" % (repr(self), repr(wme.binding_dict)))
            if l_part_insts:
                for partial_inst in l_part_insts:
                    if not isinstance(partial_inst, PartialInstantiation):
                        single_token = PartialInstantiation(
                            [partial_inst],
                            consistent_bindings=partial_inst.binding_dict.copy(),
                        )
                        matches.add(single_token)
                    else:
                        assert isinstance(partial_inst, PartialInstantiation), repr(
                            partial_inst
                        )
                        matches.add(
                            partial_inst.new_join(
                                wme,
                                [
                                    x
                                    for x in self.common_variables
                                    if x not in partial_inst.joined_bindings
                                ],
                            )
                        )
            for p_inst in matches:
                self._activate(p_inst, debug)


TEST_NS = Namespace("http://example.com/text1/")


def populate_token_from_a_node(a_node, bindings):
    # print(aNode, bindings)
    term_list = [
        isinstance(term, Variable) and bindings[term] or term
        for term in a_node.triple_pattern
    ]
    token = ReteToken(tuple(term_list))
    token.bind_variables(a_node)
    return token


class PartialInstantiationTests(unittest.TestCase):
    def testConsistentBinding(self):
        all_bindings = {}
        all_bindings.update(self.joinedBindings)
        all_bindings.update(self.unJoinedBindings)
        a_nodes = [
            self.a_node1,
            self.a_node2,
            self.a_node5,
            self.a_node6,
            self.a_node7,
            self.a_node8,
            self.a_node9,
            self.a_node10,
            self.a_node11,
        ]
        p_token = PartialInstantiation(
            tokens=[
                populate_token_from_a_node(aNode, all_bindings) for aNode in a_nodes
            ],
            consistent_bindings=self.joinedBindings,
        )
        # print(p_token)
        p_token.add_consistent_binding(list(self.unJoinedBindings.keys()))
        # print(p_token.joinedBindings)
        for binding in p_token.bindings:
            for key in self.unJoinedBindings:
                self.failUnless(
                    key in binding, "Missing key %s from %s" % (key, binding)
                )

    def setUp(self):
        self.a_node1 = AlphaNode(
            (Variable("HOSP"), TEST_NS.contains, Variable("HOSP_START_DATE"))
        )
        self.a_node2 = AlphaNode((Variable("HOSP"), RDF.type, TEST_NS.Hospitalization))
        self.a_node5 = AlphaNode(
            (
                Variable("HOSP_START_DATE"),
                TEST_NS.dateTimeMin,
                Variable("ENCOUNTER_START"),
            )
        )
        self.a_node6 = AlphaNode(
            (Variable("HOSP_STOP_DATE"), RDF.type, TEST_NS.EventStopDate)
        )
        self.a_node7 = AlphaNode(
            (
                Variable("HOSP_STOP_DATE"),
                TEST_NS.dateTimeMax,
                Variable("ENCOUNTER_STOP"),
            )
        )
        self.a_node8 = AlphaNode(
            (Variable("EVT_DATE"), RDF.type, TEST_NS.EventStartDate)
        )
        self.a_node9 = AlphaNode(
            (Variable("EVT_DATE"), TEST_NS.dateTimeMin, Variable("EVT_START_MIN"))
        )
        self.a_node10 = AlphaNode(
            (Variable("EVT"), TEST_NS.contains, Variable("EVT_DATE"))
        )
        self.a_node11 = AlphaNode((Variable("EVT"), RDF.type, Variable("EVT_KIND")))

        self.joinedBindings = {
            Variable("HOSP_START_DATE"): BNode(),
            Variable("HOSP_STOP_DATE"): BNode(),
            Variable("HOSP"): BNode(),
        }
        self.unJoinedBindings = {
            Variable("EVT"): BNode(),
            Variable("EVT_DATE"): BNode(),
            Variable("EVT_KIND"): TEST_NS.ICUStay,
        }
        for dtVariable in [
            Variable("ENCOUNTER_START"),
            Variable("ENCOUNTER_STOP"),
            Variable("EVT_START_MIN"),
        ]:
            self.unJoinedBindings[dtVariable] = Literal(
                "2007-02-14T10:00:00", datatype=_XSD_NS.dateTime
            )


def test():
    # import doctest
    # doctest.testmod()
    suite = unittest.makeSuite(PartialInstantiationTests)
    unittest.TextTestRunner(verbosity=5).run(suite)


if __name__ == "__main__":
    test()
