"""
http://aspn.activestate.com/ASPN/Cookbook/Python/Recipe/492216

Iterator algebra implementations of join algorithms: hash join, merge
join, and nested loops join, as well as a variant I dub "bisect join".

Requires Python 2.4.

Author: Jim Baker, jbaker@zyasoft.com

"""

import operator


def identity(x):
    """x -> x

    As a predicate, this function is useless, but it provides a
    useful/correct default.

    >>> identity(('apple', 'banana', 'cherry'))
    ('apple', 'banana', 'cherry')
    """
    return x


def inner(x):
    """
    >>> X = [1, 2, 3, 4, 5]
    >>> list(inner(X))
    [1, 2, 3, 4, 5]
    """
    yield from x

# The original hash_join
# throughout, we assume S is the smaller relation of R and S.
def hash_join(r, s, predicate=identity, join=inner, combine=operator.concat):
    hashed = {}
    for s in s:
        hashed.setdefault(predicate(s), []).append(s)
    for r in r:
        for s in join(hashed.get(predicate(r), ())):
            yield combine(r, s)


def nested_loops_join(
    r,
    s,
    predicate=identity,
    join=inner,
    combine=operator.concat,
    theta=operator.eq
):
    sp = [(predicate(s), s) for s in s]
    for r in r:
        rp = predicate(r)
        for s in join(s for sp, s in sp if theta(rp, sp)):
            yield combine(r, s)


def bisect_join(r, s, predicate=identity, join=inner, combine=operator.concat):
    """
    I have not found discussion of this variant on the sort-merge
    join anywhere.
    """

    from bisect import bisect_left
    length = len(s)
    def consume(sp, si, rp):
        """This needs a better name..."""
        while si < length:
            sp, _s = sp[si]
            if rp == sp:
                yield _s
            else:
                break
            si += 1

    rp = sorted((predicate(r), r) for r in r)
    sp = sorted((predicate(s), s) for s in s)

    for rp, r in rp:
        si = bisect_left(sp, (rp,))
        for s in join(consume(sp, si, rp)):
            yield combine(r, s)


def merge_join(r, s, predicate=identity, join=inner, combine=operator.concat):
    """
    For obvious reasons, we depend on the predicate providing a
    sortable relation.

    Compare this presentation using iterator algebra with the much
    more difficult to follow presentation (IMHO) in
    http://en.wikipedia.org/wiki/Sort-Merge_Join
    """

    from itertools import groupby

    def advancer(xp):
        """A simple wrapper of itertools.groupby, we simply need
        to follow our convention that Xp -> (xp0, x0), (xp1, x1), ...
        """

        for k, g in groupby(xp, key=operator.itemgetter(0)):
            yield k, list(g)

    r_grouped = advancer(sorted((predicate(r), r) for r in r))
    s_grouped = advancer(sorted((predicate(s), s) for s in s))

    # in the join we need to distinguish rp from rk in the unpack, so
    # just use rk, sk
    rk, r_matched = next(r_grouped)
    sk, s_matched = next(s_grouped)

    while r_grouped and s_grouped:
        comparison = (rk > sk) - (rk < sk)
        if comparison == 0:
            # standard Cartesian join here on the matched tuples, as
            # subsetted by the join method
            for rp, r in r_matched:
                for sp, s in join(s_matched):
                    yield combine(r, s)
            rk, r_matched = next(r_grouped)
            sk, s_matched = next(s_grouped)
        elif comparison > 0:
            sk, s_matched = next(s_grouped)
        else:
            rk, r_matched = next(r_grouped)
