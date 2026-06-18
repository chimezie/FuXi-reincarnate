from __future__ import annotations

from rdflib.term import Identifier

# -*- coding: utf-8 -*-
# flake8: noqa
"""
The language of positive RIF conditions determines what can appear as a body (the
if-part) of a rule supported by the basic RIF logic. As explained in Section
Overview, RIF's Basic Logic Dialect corresponds to definite Horn rules, and the
bodies of such rules are conjunctions of atomic formulas without negation.
"""

import itertools
from functools import reduce
from typing import Any, TYPE_CHECKING
from fuxi.types import Triple
from rdflib import (
    Variable,
)  # for doctests

from rdflib import BNode, Literal, Namespace, RDF, URIRef

# from rdflib.collection import Collection
from rdflib.graph import Graph
from rdflib.namespace import NamespaceManager, RDFS

if TYPE_CHECKING:
    from typing import Iterable, Iterator, Mapping


_XSD_NS = Namespace("http://www.w3.org/2001/XMLSchema#")
from rdflib.util import first

from fuxi.types import MutableBindings, RDFNode, RDFTerm, Triple

OWL = Namespace("http://www.w3.org/2002/07/owl#")


def format_doctest_out(obj: Any) -> Any:
    return obj


def build_uniTerm(triple: Triple, new_nss: "Iterable[tuple[str, URIRef]] | None" = None) -> "Uniterm":
    if isinstance(triple, tuple):
        (s, p, o) = triple
    else:
        raise Exception("Expecting a triple, got [%s]" % triple)
    return Uniterm(p, [s, o], new_nss=new_nss)


def get_uterm(term: "Condition") -> "Uniterm":
    if isinstance(term, Uniterm):
        return term
    elif isinstance(term, Exists):
        return term.formula
    else:
        raise Exception("Unknown term: %s" % term)


class QNameManager(object):
    def __init__(self, ns_dict: "Mapping[str, URIRef] | None" = None) -> None:
        self.ns_dict: dict[str, URIRef] = dict(ns_dict) if ns_dict else {}
        self.ns_manager: NamespaceManager = NamespaceManager(Graph())
        self.ns_manager.bind("owl", "http://www.w3.org/2002/07/owl#")
        self.ns_manager.bind("math", "http://www.w3.org/2000/10/swap/math#")
        for prefix, uri in self.ns_dict.items():
            self.ns_manager.bind(prefix, uri)

    def bind(self, prefix: str, namespace: URIRef) -> None:
        self.ns_manager.bind(prefix, namespace)


class SetOperator(object):
    formulae: list[Condition]
    naf: bool

    def repr(self, operator: str) -> str:
        nafPrefix = self.naf and "not " or ""
        if len(self.formulae) == 1:
            return nafPrefix + repr(self.formulae[0])
        else:
            return "%s%s( %s )" % (
                nafPrefix,
                operator,
                " ".join([repr(i) for i in self.formulae]),
            )

    def remove(self, item: Condition) -> None:
        self.formulae.remove(item)

    def __len__(self) -> int:
        return len(self.formulae)


class Condition(object):
    """
    CONDITION   ::= CONJUNCTION | DISJUNCTION | EXISTENTIAL | ATOMIC
    """

    formulae: list[Condition]

    def is_safe_for_variable(self, var: Variable) -> bool:
        """
        A variable, v is safe in a condition formula if and only if ..
        """
        return False

    def binds(self, var: Variable) -> bool:
        return False

    def n3(self) -> str:
        return repr(self)

    def __iter__(self) -> "Iterator[Condition]":
        for f in self.formulae:
            yield f


class And(QNameManager, SetOperator, Condition):
    """
    CONJUNCTION ::= 'And' '(' CONDITION* ')'

    >>> And([Uniterm(RDF.type,[RDFS.comment,RDF.Property]),
    ...      Uniterm(RDF.type,[OWL.Class,RDFS.Class])])
    And( rdf:Property(rdfs:comment) rdfs:Class(owl:Class) )
    """

    def __init__(self, formulae=None, naf=False):
        self.naf = naf
        self.formulae = formulae and formulae or []
        QNameManager.__init__(self)

    @property
    def variables(self) -> "Iterator[Variable]":
        """
        Yield every RDF :class:`~rdflib.Variable` found in the ``.arg`` lists
        of the :class:`Uniterm` instances that are direct terms of this
        conjunction.

        Only the top-level formulae are inspected; nested :class:`And`,
        :class:`Or`, or :class:`Exists` sub-conditions are *not* recursed into
        (see :attr:`has_class_membership` for a recursive traversal example).

        >>> x = Variable('X')
        >>> y = Variable('Y')
        >>> lit1 = Uniterm(RDF.type, [x, RDFS.Class])
        >>> lit2 = Uniterm(RDF.Property, [y, RDFS.Class])
        >>> conj = And([lit1, lit2])
        >>> sorted((v.n3() for v in conj.variables))
        ['?X', '?Y']
        >>> # Ground uniterms (no variables) yield nothing
        >>> list(And([Uniterm(RDF.type, [RDFS.comment, RDF.Property])]).variables)
        []
        """
        for term in self.formulae:
            if isinstance(term, Uniterm):
                for arg in term.arg:
                    if isinstance(arg, Variable):
                        yield arg

    @property
    def has_class_membership(self) -> bool:
        """
        Return ``True`` if any :class:`Uniterm` anywhere in this conjunction's
        term tree has ``.op == RDF.type`` (a class-membership assertion of the
        form ``rdf:type(individual, Class)``), ``False`` otherwise.

        Such uniterms correspond to OWL 2 *class assertions* — described
        objects — and are distinct from binary property uniterms whose ``.op``
        is an arbitrary predicate URI.

        The check descends recursively through every nested :class:`And`,
        :class:`Or`, and :class:`Exists` encountered along the way.

        >>> x = Variable('X')
        >>> type_lit  = Uniterm(RDF.type,     [x, RDFS.Class])
        >>> prop_lit  = Uniterm(RDF.Property, [x, RDFS.Class])
        >>> And([type_lit]).has_class_membership
        True
        >>> And([prop_lit]).has_class_membership
        False
        >>> # rdf:type buried inside an Exists is still detected
        >>> And([Exists(formula=And([type_lit]), declare=[x])]).has_class_membership
        True
        >>> # Or-branch containing an rdf:type uniterm is also detected
        >>> And([Or([prop_lit, type_lit])]).has_class_membership
        True
        """

        def _check(term: "Condition") -> bool:
            # Base case: a leaf Uniterm — test the predicate symbol directly.
            if isinstance(term, Uniterm):
                return term.op == RDF.type

            # Exists wraps exactly one formula; descend into it.
            if isinstance(term, Exists):
                return _check(term.formula)

            # And / Or both expose sub-conditions via .formulae; short-circuit
            # as soon as the first positive result is found.
            if isinstance(term, (And, Or)):
                return any(_check(f) for f in term.formulae)

            return False

        return any(_check(term) for term in self.formulae)

    def binds(self, var):
        """
        A variable, v, is bound in a conjunction formula, f = And(c1...cn), n ≥ 1,
        if and only if, either

        - v is bound in at least one of the conjuncts;

        For now we don't support equality predicates, so we only check the
        first condition

        >>> x=Variable('X')
        >>> y=Variable('Y')
        >>> lit1 = Uniterm(RDF.type,[x,RDFS.Class])
        >>> lit2 = Uniterm(RDF.Property,[y,RDFS.Class])
        >>> conj = And([lit1,lit2])
        >>> conj.binds(Variable('Y'))
        True
        >>> conj.binds(Variable('Z'))
        False
        """
        return first(filter(lambda conj: conj.binds(var), self.formulae)) is not None

    def is_safe_for_variable(self, var):
        """
        A variable, v is safe in a condition formula if and only if ..

        f is a conjunction, f = And(c1...cn), n ≥ 1, and v is safe in at least
        one conjunct in f

        Since we currently don't support equality predicates, we only check
        the first condition

        >>> x=Variable('X')
        >>> y=Variable('Y')
        >>> lit1 = Uniterm(RDF.type,[x,RDFS.Class])
        >>> lit2 = Uniterm(RDF.Property,[y,RDFS.Class])
        >>> conj = And([lit1,lit2])
        >>> conj.is_safe_for_variable(y)
        True

        """
        return (
            first(filter(lambda conj: conj.is_safe_for_variable(var), self.formulae))
            is not None
        )

    @format_doctest_out
    def n3(self):
        """
        >>> And([Uniterm(RDF.type,[RDFS.comment,RDF.Property]),
        ...      Uniterm(RDF.type,[OWL.Class,RDFS.Class])]).n3()
        'rdfs:comment a rdf:Property .\\n owl:Class a rdfs:Class'

        """
        return " .\n ".join([i.n3() for i in self])

    def __repr__(self):
        return self.repr("And")


class Or(QNameManager, SetOperator, Condition):
    """
    DISJUNCTION ::= 'Or' '(' CONDITION* ')'

    >>> Or([Uniterm(RDF.type,[RDFS.comment,RDF.Property]),
    ...      Uniterm(RDF.type,[OWL.Class,RDFS.Class])])
    Or( rdf:Property(rdfs:comment) rdfs:Class(owl:Class) )
    """

    def __init__(self, formulae=None, naf=False):
        self.naf = naf
        self.formulae = formulae and formulae or []
        QNameManager.__init__(self)

    def binds(self, var):
        """
        A variable, v, is bound in a disjunction formula, if and only if v is
        bound in every disjunct where it occurs

        >>> x=Variable('X')
        >>> y=Variable('Y')
        >>> lit1 = Uniterm(RDF.type,[x,RDFS.Class])
        >>> lit2 = Uniterm(RDF.Property,[y,RDFS.Class])
        >>> conj = And([lit1,lit2])
        >>> disj = Or([conj,lit2])
        >>> disj.binds(y)
        True
        >>> disj.binds(Variable('Z'))
        False
        >>> lit = Uniterm(RDF.type,[OWL.Class,RDFS.Class])
        >>> disj= Or([lit,lit])
        >>> disj.binds(x)
        False
        """
        unboundConjs = list(
            itertools.takewhile(lambda conj: conj.binds(var), self.formulae)
        )
        return len(unboundConjs) == len(self.formulae)

    def is_safe_for_variable(self, var):
        """
        A variable, v is safe in a condition formula if and only if ..

        f is a disjunction, and v is safe in every disjunct;
        """
        unboundConjs = list(
            itertools.takewhile(lambda conj: conj.is_safe_for_variable(var), self.formulae)
        )
        return len(unboundConjs) == len(self.formulae)

    def __repr__(self):
        return self.repr("Or")


class Exists(Condition):
    """
    EXISTENTIAL ::= 'Exists' Var+ '(' CONDITION ')'
    >>> Exists(formula=Or([Uniterm(RDF.type,[RDFS.comment,RDF.Property]),
    ...                    Uniterm(RDF.type,[OWL.Class,RDFS.Class])]),
    ...        declare=[Variable('X'),Variable('Y')])
    Exists ?X ?Y ( Or( rdf:Property(rdfs:comment) rdfs:Class(owl:Class) ) )
    """

    def __init__(self, formula=None, declare=None):
        self.formula = formula
        self.declare = declare and declare or []

    def binds(self, var):
        """
        A variable, v, is bound in an existential formula,
        Exists v1,...,vn (f'), n ≥ 1, if and only if v is bound in f'

        >>> ex=Exists(formula=And([Uniterm(RDF.type,[RDFS.comment,RDF.Property]),
        ...                    Uniterm(RDF.type,[Variable('X'),RDFS.Class])]),
        ...        declare=[Variable('X')])
        >>> ex.binds(Variable('X'))
        True
        """
        return self.formula.binds(var)

    def is_safe_for_variable(self, var):
        """
        A variable, v is safe in a condition formula if and only if ..

        f is an existential formula, f = Exists v1,...,vn (f'), n ≥ 1, and
        v is safe in f' .
        """
        return self.formula.is_safe_for_variable(var)

    def __iter__(self):
        for term in self.formula:
            yield term

    def n3(self):
        """ """
        return self.formula.n3()
        # return u"@forSome %s %s"%(','.join(self.declare),self.formula.n3())

    def __repr__(self):
        return "Exists %s ( %r )" % (
            " ".join([var.n3() for var in self.declare]),
            self.formula,
        )


class Atomic(Condition):
    """
    ATOMIC ::= Uniterm | Equal | Member | Subclass (| Frame)
    """

    def binds(self, var):
        """
        A variable, v, is bound in an atomic formula, a, if and only if

        - a is neither an equality nor an external predicate, and v occurs as an
          argument in a;
        - or v is bound in the conjunction formula f = And(a).

        Default is False

        """
        return False

    def __iter__(self):
        yield self


class Equal(QNameManager, Atomic):
    """
    Equal ::= TERM '=' TERM
    TERM ::= Const | Var | Uniterm | 'External' '(' Expr ')'

    >>> Equal(RDFS.Resource,OWL.Thing)
    rdfs:Resource =  owl:Thing
    """

    def __init__(self, lhs=None, rhs=None):
        self.lhs = lhs
        self.rhs = rhs
        QNameManager.__init__(self)

    def __repr__(self):
        left = self.ns_manager.qname(self.lhs)
        right = self.ns_manager.qname(self.rhs)
        return "%s =  %s" % (left, right)


def build_uniterm_from_tuple(triple: Triple,
                             new_nss: Mapping[str, Identifier] = None):
    from rdflib import Variable
    (s, p, o) = triple
    s = Variable("s") if s is None else s
    o = Variable("o") if o is None else o
    return Uniterm(p, [s, o], new_nss)


class Uniterm(QNameManager, Atomic):
    """
    Uniterm ::= Const '(' TERM* ')'
    TERM ::= Const | Var | Uniterm

    We restrict to binary predicates (RDF triples)

    >>> Uniterm(RDF.type,[RDFS.comment,RDF.Property])
    rdf:Property(rdfs:comment)
    """

    def __init__(self, op, arg=None, new_nss=None, naf=False):
        self.naf = naf
        self.op = op
        self.arg = arg and arg or []
        QNameManager.__init__(self)
        if new_nss is not None:
            new_nss = list(new_nss.items()) if isinstance(new_nss, dict) else new_nss
            for k, v in new_nss:
                self.ns_manager.bind(k, v)
        self._hash = hash(
            reduce(
                lambda x, y: str(x) + str(y),
                len(self.arg) == 2 and self.to_rdf_tuple() or [self.op] + self.arg,
            )
        )

    def unify_with(self, other_lit):
        """
        Given another Uniterm, ``otherLit``, that is assumed to be ground and
        structurally compatible with ``self`` (same arity and same constant
        predicate where applicable), return a dict mapping each
        :class:`~rdflib.Variable` occurring in ``self`` to the corresponding
        term at the same position in ``otherLit``.

        Non-variable terms in ``self`` are not included in the result, even
        when they differ from the corresponding term in ``otherLit`` (no
        unification / consistency check is performed here — the caller is
        expected to guarantee that ``otherLit`` is ground and matches).

        >>> x = Variable('X')
        >>> y = Variable('Y')
        >>> # Binary predicate: both args are variables in A, ground in B
        >>> a = Uniterm(RDF.type, [x, RDFS.Class])
        >>> b = Uniterm(RDF.type, [RDFS.comment, RDFS.Class])
        >>> bindings = a.getBindingsFromGround(b)
        >>> bindings[x] == RDFS.comment
        True
        >>> len(bindings)
        1

        >>> # Second-order: the predicate symbol itself is a variable
        >>> a2 = Uniterm(x, [y, RDFS.Class])
        >>> b2 = Uniterm(RDF.type, [RDFS.comment, RDFS.Class])
        >>> m = a2.getBindingsFromGround(b2)
        >>> m[x] == RDF.type and m[y] == RDFS.comment
        True
        """
        bindings = {}
        for selfTerm, otherTerm in zip(
                [self.op] + self.arg, [other_lit.op] + other_lit.arg
        ):
            if isinstance(selfTerm, Variable):
                bindings[selfTerm] = otherTerm
        return bindings

    @property
    def variables(self) -> "Iterator[Variable]":
        """
        Yield every RDF :class:`~rdflib.Variable` found in this uniterm.

        Variables are drawn from both the predicate symbol (``.op``) and the
        argument list (``.arg``), so second-order uniterms are included.

        >>> x = Variable('X')
        >>> y = Variable('Y')
        >>> [v.n3() for v in Uniterm(RDF.type, [x, RDFS.Class]).variables]
        ['?X']
        >>> [v.n3() for v in Uniterm(x, [y, RDFS.Class]).variables]
        ['?X', '?Y']
        >>> list(Uniterm(RDF.type, [RDFS.comment, RDF.Property]).variables)
        []
        """
        for term in [self.op] + self.arg:
            if isinstance(term, Variable):
                yield term

    def binds(self, var):
        """
        A variable, v, is bound in an atomic formula, a, if and only if

        - a is neither an equality nor an external predicate, and v occurs as an
          argument in a;
        - or v is bound in the conjunction formula f = And(a).

        Default is False

        >>> x = Variable('X')
        >>> lit = Uniterm(RDF.type,[RDFS.comment,x])
        >>> lit.binds(Variable('Z'))
        False
        >>> lit.binds(x)
        False
        >>> Uniterm(RDF.type,[x,RDFS.Class]).binds(x)
        True

        """
        if self.op == RDF.type:
            arg0, arg1 = self.arg
            return var == arg0
        else:
            return var in self.arg

    def is_safe_for_variable(self, var):
        """
        A variable, v is safe in a condition formula if and only if ..

        f is an atomic formula and f is not an equality formula in which both
        terms are variables, and v occurs in f;
        """
        return self.binds(var)

    def rename_variables(self, var_mapping):
        if self.op == RDF.type:
            self.arg[0] = var_mapping.get(self.arg[0], self.arg[0])
        else:
            self.arg[0] = var_mapping.get(self.arg[0], self.arg[0])
            self.arg[1] = var_mapping.get(self.arg[1], self.arg[1])
        # Recalculate the hash after modification
        self._hash = hash(
            reduce(
                lambda x, y: str(x) + str(y),
                len(self.arg) == 2 and self.to_rdf_tuple() or [self.op] + self.arg,
            )
        )

    @format_doctest_out
    def _get_terms(self):
        """
        Class attribute that returns all the terms of the literal as a lists
        >>> x = Variable('X')
        >>> lit = Uniterm(RDF.type,[RDFS.comment,x])
        >>> list(map(str, lit.terms))
        ['http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'http://www.w3.org/2000/01/rdf-schema#comment', 'X']
        """
        return [self.op] + self.arg

    terms = property(_get_terms)

    def get_var_mapping(self, other_lit, reverse=False):
        """
        Takes another Uniterm and in every case where the corresponding term
        for both literals are different variables, we map from the variable
        for *this* uniterm to the corresponding variable of the other.
        The mapping will go in the other direction if the reverse
        keyword is True

        >>> x = Variable('X')
        >>> y = Variable('Y')
        >>> lit1 = Uniterm(RDF.type,[RDFS.comment,x])
        >>> lit2 = Uniterm(RDF.type,[RDFS.comment,y])
        >>> lit1.get_var_mapping(lit2)[x] == y
        True
        >>> lit1.get_var_mapping(lit2,True)[y] == x
        True
        """
        map = {}
        if (
            isinstance(self.op, Variable)
            and isinstance(other_lit.op, Variable)
            and self.op != other_lit.op
        ):
            if reverse:
                map[other_lit.op] = self.op
            else:
                map[self.op] = other_lit.op
        if (
            isinstance(self.arg[0], Variable)
            and isinstance(other_lit.arg[0], Variable)
            and self.arg[0] != other_lit.arg[0]
        ):
            if reverse:
                map[other_lit.arg[0]] = self.arg[0]
            else:
                map[self.arg[0]] = other_lit.arg[0]
        if (
            isinstance(self.arg[1], Variable)
            and isinstance(other_lit.arg[1], Variable)
            and self.arg[1] != other_lit.arg[1]
        ):
            if reverse:
                map[other_lit.arg[1]] = self.arg[1]
            else:
                map[self.arg[1]] = other_lit.arg[1]
        return map

    def applicable_mapping(self, mapping):
        """
        Can the given mapping (presumably from variables to terms) be applied?
        """
        return bool(set(mapping).intersection([self.op] + self.arg))

    def ground(self, varMapping):
        applied_keys = set([self.op] + self.arg).intersection(list(varMapping.keys()))
        self.op = varMapping.get(self.op, self.op)
        self.arg[0] = varMapping.get(self.arg[0], self.arg[0])
        self.arg[1] = varMapping.get(self.arg[1], self.arg[1])
        # Recalculate the hash after modification
        self._hash = hash(
            reduce(
                lambda x, y: str(x) + str(y),
                len(self.arg) == 2 and self.to_rdf_tuple() or [self.op] + self.arg,
            )
        )
        return applied_keys

    def is_ground(self):
        for term in [self.op] + self.arg:
            if isinstance(term, Variable):
                return False
        return True

    def __hash__(self):
        return self._hash

    def __eq__(self, other):
        return hash(self) == hash(other)

    def render_term_as_n3(self, term):
        if term == RDF.type:
            return "a"
        elif isinstance(term, (BNode, Literal, Variable)):
            return term.n3()
        else:
            return self.ns_manager.qname(term)

    @format_doctest_out
    def n3(self):
        """
        Serialize as N3 (using available namespace managers)

        >>> Uniterm(RDF.type,[RDFS.comment,RDF.Property]).n3()
        'rdfs:comment a rdf:Property'

        """
        return " ".join(
            [self.render_term_as_n3(term) for term in [self.arg[0], self.op, self.arg[1]]]
        )

    def to_rdf_tuple(self):
        subject, _object = self.arg
        return (subject, self.op, _object)

    def collapse_name(self, val):
        try:
            rt = self.ns_manager.qname(val)
            if len(rt.split(":")[0]) > 1 and rt[0] == "_":
                return ":" + rt.split(":")[-1]
            else:
                return rt

        except:
            for prefix, uri in self.ns_manager.namespaces():
                if val.startswith(uri):
                    return "%s:%s" % (prefix, val.split(uri)[-1])
            return val

    def normalize_term(self, term):
        if isinstance(term, Literal):
            if term.datatype == _XSD_NS.integer:
                return str(term)
            else:
                return term.n3()
        else:
            return isinstance(term, Variable) and term.n3() or self.collapse_name(term)

    def get_arity(self):
        return 1 if self.op == RDF.type else 2

    arity = property(get_arity)

    def set_operator(self, new_op):
        if self.op == RDF.type:
            self.arg[-1] = new_op
        else:
            self.op = new_op

    def is_second_order(self):
        if self.op == RDF.type:
            return isinstance(self.arg[-1], Variable)
        else:
            return isinstance(self.op, Variable)

    def __repr__(self):
        neg_prefix = self.naf and "not " or ""
        if self.op == RDF.type:
            arg0, arg1 = self.arg
            return "%s%s(%s)" % (
                neg_prefix,
                self.normalize_term(arg1),
                self.normalize_term(arg0),
            )
        else:
            return "%s%s(%s)" % (
                neg_prefix,
                self.normalize_term(self.op),
                " ".join([self.normalize_term(i) for i in self.arg]),
            )


class PredicateExtentFactory(object):
    """
    Creates an object which when indexed returns
    a Uniterm with the 'registered' symbol and
    two-tuple argument

    >>> from rdflib import Namespace, URIRef
    >>> EX_NS = Namespace('http://example.com/')
    >>> ns = {'ex':EX_NS}
    >>> somePredFactory = PredicateExtentFactory(EX_NS.somePredicate,newNss=ns)
    >>> somePredFactory[(EX_NS.individual1,EX_NS.individual2)]
    ex:somePredicate(ex:individual1 ex:individual2)
    >>> somePred2Factory = PredicateExtentFactory(EX_NS.somePredicate,binary=False,newNss=ns)
    >>> somePred2Factory[EX_NS.individual1]
    ex:somePredicate(ex:individual1)

    """

    def __init__(self, predicateSymbol, binary=True, newNss=None):
        self.predicateSymbol = predicateSymbol
        self.binary = binary
        self.newNss = newNss

    def term(self, name):
        from fuxi.Syntax.InfixOWL import Class

        return Class(URIRef(self + name))

    def __getitem__(self, args):
        if self.binary:
            arg1, arg2 = args
            return Uniterm(self.predicateSymbol, [arg1, arg2], new_nss=self.newNss)
        else:
            return Uniterm(RDF.type, [args, self.predicateSymbol], new_nss=self.newNss)


class ExternalFunction(Uniterm):
    """
    An External(ATOMIC) is a call to an externally defined predicate, equality,
    membership, subclassing, or frame. Likewise, External(Expr) is a call to an
    externally defined function.
    >>> ExternalFunction(Uniterm(URIRef('http://www.w3.org/2000/10/swap/math#greaterThan'),[Variable('VAL'),Literal(2)]))
    math:greaterThan(?VAL 2)
    """

    def __init__(self, builtin, new_nss=None):
        from fuxi.Rete.RuleStore import N3Builtin

        self.builtin = builtin
        if isinstance(builtin, N3Builtin):
            Uniterm.__init__(self, builtin.uri, [builtin.argument, builtin.result])
        else:
            Uniterm.__init__(self, builtin.op, builtin.arg)
        QNameManager.__init__(self)
        if new_nss is not None:
            new_nss = isinstance(new_nss, dict) and list(new_nss.items()) or new_nss
            for k, v in new_nss:
                self.ns_manager.bind(k, v)


def test():
    import doctest

    doctest.testmod()


if __name__ == "__main__":
    test()

def format_doctest_out(obj):
    return obj
