# -*- coding: utf-8 -*-
# flake8: noqa
"""
Utility functions for a Boost Graph Library (BGL) DiGraph via the BGL Python Bindings
"""

import itertools
import os
import pickle
from functools import lru_cache, wraps
from typing import Tuple

from rdflib import (
    BNode,
    Namespace,
)
from rdflib.graph import Graph
from rdflib.collection import Collection
from rdflib.namespace import NamespaceManager
from rdflib.term import Identifier


def format_doctest_out(doc):
    return doc


def _get_graphviz():
    try:
        import graphviz
    except Exception as exc:
        raise ImportError("graphviz is required for RETE network rendering") from exc
    return graphviz


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
def collapse_dictionary(mapping):
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
    >>> collapse_dictionary(a)
    {'ex': rdflib.term.URIRef(%(u)s'http://example.com/')}
    >>> a
    {'ex': rdflib.term.URIRef(%(u)s'http://example.com/'), '_1': rdflib.term.URIRef(%(u)s'http://example.com/')}
    """

    def original_prefixes(item):
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
        for rt, items in itertools.groupby(v, original_prefixes):
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


def lazy_generator_peek(iterable, firstN=1):
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
    >>> result = lazy_generator_peek(a)
    >>> result  # doctest:+ELLIPSIS
    <fuxi.Rete.Util.InformedLazyGenerator object at ...>
    >>> result = list(result)
    >>> result
    [1, 2, 3]
    >>> lazy_generator_peek((i for i in [])) # doctest:+ELLIPSIS
    <fuxi.Rete.Util.InformedLazyGenerator object at ...>
    >>> lazy_generator_peek(result,4) # doctest:+ELLIPSIS
    <fuxi.Rete.Util.InformedLazyGenerator object at ...>
    >>> lazy_generator_peek(result,3) # doctest:+ELLIPSIS
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


def generate_token_set(
    graph: Graph,
    debug_triples: Tuple[Identifier, Identifier, Identifier] = None,
    skip_implies=True,
):
    """
    Takes an rdflib graph and generates a corresponding Set of ReteTokens
    Note implication statements are excluded from the realm of facts by default
    """
    if debug_triples is None:
        debug_triples = []
    from fuxi.Rete import ReteToken

    rt = set()
    intern_terms = _env_flag("FUXI_RETE_TERM_INTERN")
    term_cache = {} if intern_terms else None

    def normalize_graph_terms(term):
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
        if not skip_implies or p != LOG.implies:
            # print(s, p, o)
            debug = debug_triples and (s, p, o) in debug_triples
            s = maybe_intern(normalize_graph_terms(s))
            p = maybe_intern(normalize_graph_terms(p))
            o = maybe_intern(normalize_graph_terms(o))
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


def _rete_label(uri: str) -> str:
    return uri[1:-1] if uri.startswith("<") and uri.endswith(">") else uri


def _add_rete_node(dot, node, namespace_manager, identifier):
    from fuxi.Rete import ReteNetwork, BetaNode, BuiltInAlphaNode, AlphaNode
    from .BetaNode import LEFT_MEMORY, RIGHT_MEMORY

    shape = "circle"
    root = False
    rhs_name = None
    if isinstance(node, ReteNetwork):
        root = True
        peripheries = "3"
        label = "ReteNetwork"
    elif isinstance(node, BetaNode) and not node.consequent:
        peripheries = "1"
        if node.fed_by_builtin:
            label = "Built-in pass-thru"
        elif node.a_pass_thru:
            label = "Pass-thru Beta node"
        elif node.common_variables:
            label = "Beta node\\n(%s)" % (
                ",".join(["?%s" % i for i in node.common_variables])
            )
        else:
            label = "Beta node"
        if not node.fed_by_builtin:
            leftLen = (
                node.memories[LEFT_MEMORY] and len(node.memories[LEFT_MEMORY]) or 0
            )
            rightLen = len(node.memories[RIGHT_MEMORY])
            label += "\\n %s in left, %s in right memories" % (leftLen, rightLen)

    elif isinstance(node, BetaNode) and node.consequent:
        peripheries = "2"
        stmts = []
        for s, p, o in node.consequent:
            stmts.append(
                " ".join(
                    [
                        _rete_label(str(namespace_manager.normalizeUri(s))),
                        _rete_label(str(namespace_manager.normalizeUri(p))),
                        _rete_label(str(namespace_manager.normalizeUri(o))),
                    ]
                )
            )

        rhs_name = str(BNode())
        dot.node(
            rhs_name,
            label="\\n".join(stmts),
            shape="plaintext",
        )
        dot.edge(identifier, rhs_name)
        if node.common_variables:
            inst = node.network.instantiations.get(node, 0)
            label = "Terminal node\\n(%s)\\n%d instantiations" % (
                ",".join(["?%s" % i for i in node.common_variables]),
                inst,
            )
        else:
            label = "Terminal node"
        leftLen = node.memories[LEFT_MEMORY] and len(node.memories[LEFT_MEMORY]) or 0
        rightLen = len(node.memories[RIGHT_MEMORY])
        label += "\\n %s in left, %s in right memories" % (leftLen, rightLen)
        inst = node.network.instantiations.get(node, 0)
        if inst:
            label += "\\n%s instantiations" % inst

    elif isinstance(node, BuiltInAlphaNode):
        peripheries = "1"
        shape = "plaintext"
        canonicalFunc = _rete_label(namespace_manager.normalizeUri(node.n3builtin.uri))
        canonicalArg1 = _rete_label(
            namespace_manager.normalizeUri(node.n3builtin.argument)
        )
        canonicalArg2 = _rete_label(
            namespace_manager.normalizeUri(node.n3builtin.result)
        )
        label = "%s(%s,%s)" % (canonicalFunc, canonicalArg1, canonicalArg2)

    elif isinstance(node, AlphaNode):
        peripheries = "1"
        shape = "plaintext"
        label = " ".join(
            [
                isinstance(i, BNode)
                and i.n3()
                or _rete_label(str(namespace_manager.normalizeUri(i)))
                for i in node.triple_pattern
            ]
        )
    else:
        peripheries = "1"
        label = repr(node)

    node_attrs = dict(
        label=label,
        shape=shape,
        peripheries=peripheries,
    )
    if root:
        node_attrs["root"] = "true"
    dot.node(identifier, **node_attrs)
    return identifier


def render_network(network, ns_map=None, format="png"):
    """
    Takes an instance of a compiled ReteNetwork and a namespace mapping
    (for constructing QNames for rule pattern terms) and returns a
    graphviz.Digraph instance representing the Rete network.
    """
    if ns_map is None:
        ns_map = {}
    graphviz = _get_graphviz()
    dot = graphviz.Digraph("RETE Network", format=format)
    namespace_manager = NamespaceManager(Graph())
    for prefix, uri in list(ns_map.items()):
        namespace_manager.bind(prefix, uri, override=False)

    # Register namespaces from the network's inferred_facts namespace manager
    # (set to the fact graph's namespace manager in the BFP path)
    inferred_nm = getattr(
        getattr(network, "inferred_facts", None), "namespace_manager", None
    )
    if inferred_nm:
        for prefix, uri in inferred_nm.namespaces():
            namespace_manager.bind(prefix, uri, override=False)

    visited_nodes = {}
    edges = []
    idx = 0

    def handle_bnode(idx, node, beta_node, dot):
        for i, other_node in enumerate([beta_node.left_node, beta_node.right_node]):
            if node == other_node and (node, other_node) not in edges:
                for item in [node, beta_node]:
                    if item not in visited_nodes:
                        idx += 1
                        visited_nodes[item] = _add_rete_node(
                            dot, item, namespace_manager, str(idx)
                        )
                dot.edge(
                    visited_nodes[node],
                    visited_nodes[beta_node],
                    label="left" if i == 0 else "right",
                )
                edges.append((node, beta_node))

    for node in list(network.nodes.values()):
        if node not in visited_nodes:
            idx += 1
            visited_nodes[node] = _add_rete_node(dot, node, namespace_manager, str(idx))
    for node in list(network.nodes.values()):
        for mem in node.descendent_memory:
            if not mem:
                continue
            beta_node = mem.successor
        for beta_node in node.descendent_beta_nodes:
            for i, otherNode in enumerate([beta_node.left_node, beta_node.right_node]):
                if node == otherNode and (node, otherNode) not in edges:
                    for item in [node, beta_node]:
                        if item not in visited_nodes:
                            idx += 1
                            visited_nodes[item] = _add_rete_node(
                                dot, item, namespace_manager, str(idx)
                            )
                    dot.edge(
                        visited_nodes[node],
                        visited_nodes[beta_node],
                        label="left" if i == 0 else "right",
                    )
                    edges.append((node, beta_node))

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
