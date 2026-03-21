# -*- coding: utf-8 -*-
# flake8: noqa
"""
Utility functions for a Boost Graph Library (BGL) DiGraph via the BGL Python Bindings
"""

import itertools
import os
import pickle
from functools import lru_cache, wraps
from rdflib import (
    BNode,
    Namespace,
)
from rdflib.graph import Graph
from rdflib.collection import Collection
from rdflib.namespace import NamespaceManager


def format_doctest_out(doc):
    return doc


try:
    from pydot import Node, Edge, Dot
except:
    import warnings

    warnings.warn("Missing pydot library", ImportWarning)

LOG = Namespace("http://www.w3.org/2000/10/swap/log#")


def _env_flag(name: str) -> bool:
    value = os.environ.get(name, "")
    return value.lower() not in ("", "0", "false", "no")


def xcombine(*seqin):
    """
    http://aspn.activestate.com/ASPN/Cookbook/Python/Recipe/302478
    returns a generator which returns combinations of argument sequences
    for example xcombine((1,2),(3,4)) returns a generator; calling the next()
    method on the generator will return [1,3], [1,4], [2,3], [2,4] and
    StopIteration exception.  This will not create the whole list of
    combinations in memory at once.
    """

    def rloop(seqin, comb):
        """recursive looping function"""
        if seqin:  # any more sequences to process?
            for item in seqin[0]:
                # add next item to current combination
                newcomb = comb + [item]
                # call rloop w/ remaining seqs, newcomb
                for item in rloop(seqin[1:], newcomb):
                    yield item  # seqs and newcomb
        else:  # processing last sequence
            yield comb  # comb finished, add to list

    return rloop(seqin, [])


def permu(xs):
    """
    http://aspn.activestate.com/ASPN/Cookbook/Python/Recipe/496819
    "A recursive function to get permutation of a list"

    >>> print(list(permu([1,2,3])))
    [[1, 2, 3], [1, 3, 2], [2, 1, 3], [2, 3, 1], [3, 1, 2], [3, 2, 1]]

    """
    if len(xs) <= 1:
        yield xs
    else:
        for i in range(len(xs)):
            for p in permu(xs[:i] + xs[i + 1 :]):
                yield [xs[i]] + p


@format_doctest_out
def CollapseDictionary(mapping):
    """
    Takes a dictionary mapping prefixes to URIs
    and removes prefix mappings that begin with _ and
    there is already a map to their value

    >>> from rdflib import URIRef
    >>> a = {'ex': URIRef('http://example.com/')}
    >>> a['_1'] =  a['ex']
    >>> len(a)
    2
    >>> a.values()
    [rdflib.term.URIRef(%(u)s'http://example.com/'), rdflib.term.URIRef(%(u)s'http://example.com/')]
    >>> CollapseDictionary(a)
    {'ex': rdflib.term.URIRef(%(u)s'http://example.com/')}
    >>> a
    {'ex': rdflib.term.URIRef(%(u)s'http://example.com/'), '_1': rdflib.term.URIRef(%(u)s'http://example.com/')}
    """

    def originalPrefixes(item):
        return item.find("_") + 1 == 1

    revDict = {}
    for k, v in list(mapping.items()):
        revDict.setdefault(v, set()).add(k)
    prefixes2Collapse = []
    for k, v in list(revDict.items()):
        origPrefixes = []
        dupePrefixes = []
        # group prefixes for a single URI by whether or not
        # they have a _ prefix
        for rt, items in itertools.groupby(v, originalPrefixes):
            if rt:
                dupePrefixes.extend(items)
            else:
                origPrefixes.extend(items)
        if origPrefixes and len(v) > 1 and len(dupePrefixes):
            # There are allocated prefixes for URIs that were originally
            # given a prefix
            assert len(origPrefixes) == 1
            prefixes2Collapse.extend(dupePrefixes)
    return dict(
        [(k, v) for k, v in list(mapping.items()) if k not in prefixes2Collapse]
    )


class selective_memoize(object):
    """Decorator that caches a function's return value each time it is called.
    If called later with the same arguments, the cached value is returned, and
    not re-evaluated. Slow for mutable types.
    The arguments used for the cache are given to the decorator

    >>> @selective_memoize([0,1])
    ... def addition(l,r,other):
    ...     print("calculating..")
    ...     return l+r
    >>> addition(1,2,3)
    calculating..
    3
    >>> addition(1,2,4)
    3
    >>> @selective_memoize()
    ... def addition(l,r,other):
    ...     print("calculating..")
    ...     return l+r
    >>> addition(1,2,3)
    calculating..
    3
    >>> addition(1,2,4)
    calculating..
    3
    >>> @selective_memoize([0,1],'baz')
    ... def addition(l,r,baz=False, bar=False):
    ...     print("calculating..")
    ...     return l+r
    >>> addition(1,2,baz=True)
    calculating..
    3
    >>> addition(1,2,baz=True,bar = True)
    3
    """

    # Ideas from MemoizeMutable class of Recipe 52201 by Paul Moore and
    # from memoized decorator of
    # http://wiki.python.org/moin/PythonDecoratorLibrary

    def __init__(self, cacheableArgPos=[], cacheableArgKey=[]):
        self.cacheableArgPos = cacheableArgPos
        self.cacheableArgKey = cacheableArgKey

    def __call__(self, func):
        class _KeyedArgs:
            __slots__ = ("key", "args", "kwds")

            def __init__(self, key, args, kwds):
                self.key = key
                self.args = args
                self.kwds = kwds

            def __hash__(self):
                return hash(self.key)

            def __eq__(self, other):
                return isinstance(other, _KeyedArgs) and self.key == other.key

        @lru_cache(maxsize=None)
        def cached(call_args):
            return func(*call_args.args, **call_args.kwds)

        @wraps(func)
        def innerHandler(*args, **kwds):
            if self.cacheableArgPos:
                chosenKeys = []
                for idx, arg in enumerate(args):
                    if idx in self.cacheableArgPos:
                        chosenKeys.append(arg)
                key = tuple(chosenKeys)
            else:
                key = args
            if kwds:
                if self.cacheableArgKey:
                    items = [
                        (k, v)
                        for k, v in list(kwds.items())
                        if k in self.cacheableArgKey
                    ]
                else:
                    items = []
                items.sort()
                key = key + tuple(items)
            try:
                hash(key)
            except TypeError:
                try:
                    key = pickle.dumps(key)
                except pickle.PicklingError:
                    return func(*args, **kwds)
            return cached(_KeyedArgs(key, args, kwds))

        return innerHandler


class InformedLazyGenerator(object):
    def __init__(self, generator, successful):
        self.generator = generator
        self.successful = successful

    def __iter__(self):
        for item in self.generator:
            yield item


def lazyGeneratorPeek(iterable, firstN=1):
    """
    Lazily peeks into an iterable and returns None if it has less than N items
    or returns another generator over *all* content if it isn't

    >>> from rdflib.util import first
    >>> a=(i for i in [1,2,3])
    >>> first(a)
    1
    >>> list(a)
    [2, 3]
    >>> a=(i for i in [1,2,3])
    >>> result = lazyGeneratorPeek(a)
    >>> result  # doctest:+ELLIPSIS
    <fuxi.Rete.Util.InformedLazyGenerator object at ...>
    >>> result = list(result)
    >>> result
    [1, 2, 3]
    >>> lazyGeneratorPeek((i for i in [])) # doctest:+ELLIPSIS
    <fuxi.Rete.Util.InformedLazyGenerator object at ...>
    >>> lazyGeneratorPeek(result,4) # doctest:+ELLIPSIS
    <fuxi.Rete.Util.InformedLazyGenerator object at ...>
    >>> lazyGeneratorPeek(result,3) # doctest:+ELLIPSIS
    <fuxi.Rete.Util.InformedLazyGenerator object at ...>
    """
    cnt = firstN
    header = []
    for item in iterable:
        cnt -= 1
        header.append(item)
        if not cnt:
            # Stop after consuming first N items
            break
    if not cnt:
        # There at least N items
        return InformedLazyGenerator(
            (i for i in itertools.chain(header, iterable)), True
        )
    else:
        return InformedLazyGenerator((i for i in header), False)


class setdict(dict):
    """
    Add set operations to dicts.

    Credit thom neale
    See: http://code.activestate.com/recipes/577471-setdict/
    """

    def __sub__(self, other):
        res = {}
        for k in set(self) - set(other):
            res[k] = self[k]
        return setdict(**res)

    def __and__(self, other):
        res = {}
        for k in set(self) & set(other):
            res[k] = self[k]
        return setdict(**res)

    def __xor__(self, other):
        res = {}
        for k in set(self) ^ set(other):
            try:
                res[k] = self[k]
            except KeyError:
                res[k] = other[k]
        return setdict(**res)

    def __or__(self, other):
        res = {}
        for k in set(self) | set(other):
            try:
                res[k] = self[k]
            except KeyError:
                res[k] = other[k]
        return setdict(**res)


def call_with_filtered_args(args, _callable):
    """
    Filter any nonkeyword elements from args, then call
    the callable with them.
    """
    try:
        argnames = _callable.__code__.co_varnames
    except AttributeError:
        argnames = _callable.__init__.__code__.co_varnames

    args = setdict(**args) & argnames

    return _callable(**args)


def generateTokenSet(graph, debugTriples=[], skipImplies=True):
    """
    Takes an rdflib graph and generates a corresponding Set of ReteTokens
    Note implication statements are excluded from the realm of facts by default
    """
    from fuxi.Rete import ReteToken

    rt = set()
    intern_terms = _env_flag("FUXI_RETE_TERM_INTERN")
    term_cache = {} if intern_terms else None

    def normalizeGraphTerms(term):
        if isinstance(term, Collection):
            return term.uri
        else:
            return term

    def maybe_intern(term):
        if term_cache is None:
            return term
        try:
            return term_cache.setdefault(term, term)
        except TypeError:
            return term

    for s, p, o in graph:
        if not skipImplies or p != LOG.implies:
            # print(s, p, o)
            debug = debugTriples and (s, p, o) in debugTriples
            s = maybe_intern(normalizeGraphTerms(s))
            p = maybe_intern(normalizeGraphTerms(p))
            o = maybe_intern(normalizeGraphTerms(o))
            rt.add(
                ReteToken(
                    (
                        s,
                        p,
                        o,
                    ),
                    debug,
                )
            )
    return rt


def generateBGLNode(dot, node, namespace_manager, identifier):
    from fuxi.Rete import ReteNetwork, BetaNode, BuiltInAlphaNode, AlphaNode
    from .BetaNode import LEFT_MEMORY, RIGHT_MEMORY

    vertex = Node(identifier)

    shape = "circle"
    root = False
    if isinstance(node, ReteNetwork):
        root = True
        peripheries = "3"
    elif isinstance(node, BetaNode) and not node.consequent:
        peripheries = "1"
        if node.fedByBuiltin:
            label = "Built-in pass-thru\\n"
        elif node.aPassThru:
            label = "Pass-thru Beta node\\n"
        elif node.commonVariables:
            label = "Beta node\\n(%s)" % (
                ",".join(["?%s" % i for i in node.commonVariables])
            )
        else:
            label = "Beta node"
        if not node.fedByBuiltin:
            leftLen = (
                node.memories[LEFT_MEMORY] and len(node.memories[LEFT_MEMORY]) or 0
            )
            rightLen = len(node.memories[RIGHT_MEMORY])
            label += "\\n %s in left, %s in right memories" % (leftLen, rightLen)

    elif isinstance(node, BetaNode) and node.consequent:
        # rootMap[vertex] = 'true'
        peripheries = "2"
        stmts = []
        for s, p, o in node.consequent:
            stmts.append(
                " ".join(
                    [
                        str(namespace_manager.normalizeUri(s)),
                        str(namespace_manager.normalizeUri(p)),
                        str(namespace_manager.normalizeUri(o)),
                    ]
                )
            )

        rhsVertex = Node(
            BNode(), label='"' + "\\n".join(stmts) + '"', shape="plaintext"
        )
        edge = Edge(vertex, rhsVertex)
        # edge.color = 'red'
        dot.add_edge(edge)
        dot.add_node(rhsVertex)
        if node.commonVariables:
            inst = node.network.instantiations.get(node, 0)
            label = str(
                "Terminal node\\n(%s)\\n%d instantiations"
                % (",".join(["?%s" % i for i in node.commonVariables]), inst)
            )
        else:
            label = "Terminal node"
        leftLen = node.memories[LEFT_MEMORY] and len(node.memories[LEFT_MEMORY]) or 0
        rightLen = len(node.memories[RIGHT_MEMORY])
        label += "\\n %s in left, %s in right memories" % (leftLen, rightLen)
        inst = node.network.instantiations[node]
        if inst:
            label += "\\n%s instantiations" % inst

    elif isinstance(node, BuiltInAlphaNode):
        peripheries = "1"
        shape = "plaintext"
        # label = '..Builtin Source..'
        label = repr(node.n3builtin)
        canonicalFunc = namespace_manager.normalizeUri(node.n3builtin.uri)
        canonicalArg1 = namespace_manager.normalizeUri(node.n3builtin.argument)
        canonicalArg2 = namespace_manager.normalizeUri(node.n3builtin.result)
        label = "%s(%s,%s)" % (canonicalFunc, canonicalArg1, canonicalArg2)

    elif isinstance(node, AlphaNode):
        peripheries = "1"
        shape = "plaintext"
        # widthMap[vertex] = '50em'
        label = " ".join(
            [
                isinstance(i, BNode)
                and i.n3()
                or str(namespace_manager.normalizeUri(i))
                for i in node.triplePattern
            ]
        )

    vertex.set_shape(shape)
    vertex.set_label('"%s"' % label)
    vertex.set_peripheries(peripheries)
    if root:
        vertex.set_root("true")
    return vertex


def renderNetwork(network, nsMap={}):
    """
    Takes an instance of a compiled ReteNetwork and a namespace mapping (for constructing QNames
    for rule pattern terms) and returns a BGL Digraph instance representing the Rete network
    #(from which GraphViz diagrams can be generated)
    """
    # from fuxi.Rete import BuiltInAlphaNode
    # from BetaNode import LEFT_MEMORY, RIGHT_MEMORY, LEFT_UNLINKING
    dot = Dot(graph_type="digraph")
    namespace_manager = NamespaceManager(Graph())
    for prefix, uri in list(nsMap.items()):
        namespace_manager.bind(prefix, uri, override=False)

    visitedNodes = {}
    edges = []
    idx = 0
    for node in list(network.nodes.values()):
        if node not in visitedNodes:
            idx += 1
            visitedNodes[node] = generateBGLNode(dot, node, namespace_manager, str(idx))
            dot.add_node(visitedNodes[node])
    nodeIdxs = {}
    for node in list(network.nodes.values()):
        for mem in node.descendentMemory:
            if not mem:
                continue
            bNode = mem.successor
        for bNode in node.descendentBetaNodes:
            for idx, otherNode in enumerate([bNode.leftNode, bNode.rightNode]):
                if node == otherNode and (node, otherNode) not in edges:
                    for i in [node, bNode]:
                        if i not in visitedNodes:
                            idx += 1
                            nodeIdxs[i] = idx
                            visitedNodes[i] = generateBGLNode(
                                dot, i, namespace_manager, str(idx)
                            )
                            dot.add_node(visitedNodes[i])
                    edge = Edge(
                        visitedNodes[node],
                        visitedNodes[bNode],
                        label=idx == 0 and "left" or "right",
                    )
                    dot.add_edge(edge)
                    edges.append((node, bNode))

    return dot


def test():
    import doctest

    doctest.testmod()


if __name__ == "__main__":
    test()

# from fuxi.Rete.Util import selective_memoize
# from fuxi.Rete.Util import InformedLazyGenerator
# from fuxi.Rete.Util import setdict

# from fuxi.Rete.Util import xcombine
# from fuxi.Rete.Util import permu
# from fuxi.Rete.Util import CollapseDictionary
# from fuxi.Rete.Util import lazyGeneratorPeek
# from fuxi.Rete.Util import call_with_filtered_args
# from fuxi.Rete.Util import generateTokenSet
# from fuxi.Rete.Util import generateBGLNode
# from fuxi.Rete.Util import renderNetwork
