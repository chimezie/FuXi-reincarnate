"""
testSeralizationOfEval.py

Created by Chimezie Ogbuji on 2010-08-15.
Copyright (c) 2010 __MyCompanyName__. All rights reserved.
"""

from rdflib import Literal, RDF, Variable

from FuXi.Horn.HornRules import Clause, Rule
from FuXi.Horn.PositiveConditions import Uniterm
from FuXi.LP.BackwardFixpointProcedure import BFP_NS, BFP_RULE


def test_serializing_eval_pred():
    ns_bindings = {"bfp": BFP_NS, "rule": BFP_RULE}
    evaluate_term = Uniterm(
        BFP_NS.evaluate,
        [BFP_RULE[str(1)], Literal(1)],
        newNss=ns_bindings,
    )
    assert repr(evaluate_term) == "bfp:evaluate(rule:1 1)"
    x_var = Variable("X")
    y_var = Variable("Y")
    body_term = Uniterm(RDF.rest, [x_var, y_var], newNss=ns_bindings)
    rule = Rule(Clause(body_term, evaluate_term), declare=[x_var, y_var])
    assert repr(rule) == "Forall ?X ?Y ( bfp:evaluate(rule:1 1) :- rdf:rest(?X ?Y) )"
