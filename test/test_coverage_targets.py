from io import StringIO

import pytest
from rdflib.graph import Dataset, QuotedGraph, ReadOnlyGraphAggregate

from fuxi.Horn.HornRules import (
    Clause,
    Rule,
    extract_variables,
    horn_from_dl,
    horn_from_n3,
    network_from_n3,
    normalize_body,
)
from fuxi.Horn.PositiveConditions import And, Uniterm
from fuxi.Rete import ReteToken
from fuxi.Rete.AlphaNode import AlphaNode, BuiltInAlphaNode
from fuxi.Rete.BetaNode import PartialInstantiation
from fuxi.Rete.Network import HashablePatternList, ReteNetwork
from fuxi.Rete.Network import any_match as rete_any
from fuxi.Rete.RuleStore import (
    LOG,
    Formula,
    N3Builtin,
    N3RuleStore,
    setup_rule_store,
)
from fuxi.Rete.RuleStore import (
    Rule as StoreRule,
)
from rdflib import RDF, BNode, Graph, Literal, Namespace, Variable

EX = Namespace("http://example.org/")


def _simple_rule_body():
    return And([Uniterm(EX.p, [Variable("s"), Variable("o")])])


def _empty_head():
    return And([])


def test_hashable_pattern_list_hash_rejects_unknown_item():
    pattern_list = HashablePatternList([object()])
    with pytest.raises(NotImplementedError):
        hash(pattern_list)


def test_hashable_pattern_list_helpers_and_any():
    builtin = N3Builtin(EX.p, lambda *_args, **_kwargs: True, Variable("s"), EX.o)
    patterns = HashablePatternList([builtin])
    assert hash(patterns)

    other = HashablePatternList([(EX.a, EX.p, EX.b)])
    combined = patterns + other
    assert repr(combined)
    patterns.extend(other)
    patterns.append((EX.c, EX.p, EX.d))
    assert len(patterns) == 3

    assert rete_any([1, 2, 3], pred=lambda item: item == 2) is True
    assert rete_any([1, 2, 3], pred=lambda item: item == 9) is False


def test_network_build_network_from_clause_empty_head_warns():
    rule_store, _, network = setup_rule_store(make_network=True)
    rule = Rule(Clause(_simple_rule_body(), _empty_head()))
    with pytest.warns(SyntaxWarning, match="Integrity constraints"):
        result = network.build_network_from_clause(rule)
    assert result is None


def test_network_build_filter_network_from_clause_empty_head_asserts():
    rule_store, _, network = setup_rule_store(make_network=True)
    rule = Rule(Clause(_simple_rule_body(), _empty_head()))
    with pytest.raises(AssertionError, match="Filters must conclude"):
        network.build_filter_network_from_clause(rule)


def test_network_build_filter_network_from_clause_non_empty():
    rule_store, _, network = setup_rule_store(make_network=True)
    rule = Rule(Clause(_simple_rule_body(), Uniterm(EX.r, [EX.a, EX.b])))
    terminal = network.build_filter_network_from_clause(rule)
    assert terminal in network.terminal_nodes


def test_network_find_patterns_prefers_existing_beta_patterns():
    rule_store, _, network = setup_rule_store(make_network=True)
    pattern_one = (EX.s, EX.p, EX.o)
    pattern_two = (EX.s, EX.q, EX.o)
    beta_pattern = HashablePatternList([pattern_one])
    network.nodes[beta_pattern] = "beta"
    pattern_list = HashablePatternList([pattern_one, pattern_two])
    result = network._find_patterns(pattern_list)
    assert result[0] == beta_pattern
    assert result[1] == HashablePatternList([pattern_two])


def test_network_create_alpha_node_handles_builtin():
    rule_store, _, network = setup_rule_store(make_network=True)

    def _always_true(_subject, _object):
        return lambda *_args, **_kwargs: True

    builtin = N3Builtin(EX.p, _always_true, Variable("x"), Variable("y"))
    node = network.create_alpha_node(builtin)
    assert isinstance(node, BuiltInAlphaNode)


def test_rule_store_variable_reference_check_raises():
    store = N3RuleStore()
    missing = Variable("missing")
    with pytest.raises(Exception, match="Builtin refers to variables"):
        store._check_variable_references(set(), [missing], EX.p)


def test_rule_store_list_unroll_extends_facts():
    store = N3RuleStore()
    graph = Graph(store)
    list_node = BNode()
    store.add((list_node, RDF.first, Literal(1)), graph)
    store.add((list_node, RDF.rest, RDF.nil), graph)
    store.add((EX.subject, EX.hasList, list_node), graph)
    store._finalize()
    assert (list_node, RDF.first, Literal(1)) in store.facts
    assert (list_node, RDF.rest, RDF.nil) in store.facts


def test_rule_store_add_builds_rules_facts_and_formulae():
    store = N3RuleStore()
    graph = Graph(store)
    quoted = QuotedGraph(store, identifier=BNode())
    store.add((EX.a, EX.p, EX.b), graph)
    store.add((EX.a, LOG.implies, EX.b), graph)
    store.add((EX.a, EX.p, Variable("x")), quoted)
    assert store.facts
    assert store.rules
    assert quoted.identifier in store.formulae


def test_rule_store_add_builtin_in_quoted_graph():
    store = N3RuleStore()
    quoted = QuotedGraph(store, identifier=BNode())
    builtin_predicate = next(iter(store.filters.keys()))
    store.add((EX.a, builtin_predicate, EX.b), quoted)
    assert quoted.identifier in store.formulae
    assert store.formulae[quoted.identifier]


def test_rule_store_helpers_cover_repr_and_len():
    builtin = N3Builtin(EX.p, lambda *_args, **_kwargs: True, Variable("s"), EX.o)
    assert builtin.to_rdf_tuple() == (Variable("s"), EX.p, EX.o)
    assert "<" in builtin.render("a", "b")
    assert list(iter(builtin))
    assert "?s" in repr(builtin)

    formula = Formula(EX.formula)
    formula.append((EX.a, EX.p, EX.b))
    formula.extend([(EX.a, EX.q, EX.c)])
    assert len(formula) == 2
    assert formula[0] == (EX.a, EX.p, EX.b)
    assert "{" in repr(formula)

    store_rule = StoreRule(formula, formula)
    assert "=>" in repr(store_rule)

    store = N3RuleStore()
    assert repr(store) == ""
    assert len(store) == 0


def test_rule_store_optimize_rules_reports_similar_patterns(capsys):
    store = N3RuleStore()
    formula = Formula(EX.formula)
    formula.append((Variable("s"), EX.p, Variable("o")))
    formula.append((Variable("x"), EX.p, Variable("y")))
    store.rules.append((formula, formula))
    store.optimize_rules()
    output = capsys.readouterr().out
    assert "Similar Patterns" in output


def test_network_init_with_initial_working_memory(capsys):
    store = N3RuleStore()
    token = ReteToken((EX.a, EX.p, EX.b))
    ReteNetwork(store, initial_working_memory={token}, dont_finalize=True, ns_map={})
    output = capsys.readouterr().out
    assert "Time to calculate closure" in output


def test_network_from_n3_dataset_and_graph_paths():
    rules = """
    @prefix ex: <http://example.org/> .
    { ex:a ex:p ?o } => { ex:a ex:q ?o } .
    """
    dataset = Dataset(default_union=True)
    dataset.parse(data=rules, format="n3")
    network_from_dataset = network_from_n3(dataset)
    assert len(network_from_dataset.rules) > 0

    graph = Graph().parse(data=rules, format="n3")
    network_from_graph = network_from_n3(graph)
    assert network_from_graph.rules == set()


def test_horn_from_n3_dataset_builds_ruleset():
    rules = """
    @prefix ex: <http://example.org/> .
    { ex:a ex:p ?o } => { ex:a ex:q ?o } .
    """
    dataset = Dataset(default_union=True)
    dataset.parse(data=rules, format="n3")
    ruleset = horn_from_n3(dataset)
    assert len(list(ruleset)) == 1


def test_horn_from_dl_returns_ruleset():
    owl_graph = Graph()
    rules = horn_from_dl(owl_graph)
    assert rules is not None


def test_rule_is_safe_and_second_order_paths():
    clause_safe = Clause(
        And(
            [
                Uniterm(EX.p, [Variable("s"), Variable("o")]),
                Uniterm(EX.q, [Variable("o"), Variable("z")]),
            ]
        ),
        Uniterm(EX.r, [Variable("s"), Variable("z")]),
    )
    rule_safe = Rule(clause_safe, [Variable("s"), Variable("o"), Variable("z")])
    assert rule_safe.is_safe() is True

    clause_unsafe = Clause(
        And([Uniterm(EX.p, [Variable("s"), Variable("o")])]),
        Uniterm(EX.r, [Variable("missing"), Variable("o")]),
    )
    rule_unsafe = Rule(clause_unsafe, [Variable("s"), Variable("o")])
    assert rule_unsafe.is_safe() is False

    second_order = Rule(
        Clause(
            And([Uniterm(Variable("pred"), [Variable("s"), Variable("o")])]),
            Uniterm(EX.r, [Variable("s"), Variable("o")]),
        )
    )
    assert second_order.is_second_order() is True


def test_normalize_body_moves_builtins_to_end():
    builtin = N3Builtin(EX.p, lambda *_args, **_kwargs: True, Variable("s"), EX.o)
    rule = Rule(
        Clause(
            And([builtin, Uniterm(EX.q, [Variable("s"), EX.o])]),
            Uniterm(EX.r, [Variable("s"), EX.o]),
        )
    )
    normalized = normalize_body(rule)
    assert list(normalized.formula.body)[-1] == builtin


def test_extract_variables_from_uniterm_and_bnode():
    uniterm = Uniterm(EX.p, [Variable("s"), Variable("o")])
    vars_from_uniterm = list(extract_variables(uniterm, existential=False))
    assert Variable("s") in vars_from_uniterm
    assert Variable("o") in vars_from_uniterm
    assert list(extract_variables(BNode(), existential=True))


def test_network_misc_helpers():
    rules = """
    @prefix ex: <http://example.org/> .
    { ex:a ex:p ?o } => { ex:a ex:q ?o } .
    """
    ruleset = horn_from_n3(StringIO(rules))
    rule_store, _, network = setup_rule_store(make_network=True)
    for rule in ruleset:
        network.build_network_from_clause(rule)

    network.get_ns_bindings(Graph().namespace_manager)
    network._reset_instantiation_stats()
    for term_node in network.terminal_nodes:
        if term_node.rules:
            term_node.rule = next(iter(term_node.rules))
    network.check_duplicate_rules()

    for term_node in network.terminal_nodes:
        term_node.execute_actions = {}
    network.register_rete_action(
        (EX.a, EX.q, Variable("o")), False, lambda *_args, **_kwargs: None
    )

    network.report_conflict_set()
    network.report_size(token_size_threshold=0)
    assert isinstance(
        network.closure_graph(Graph(), read_only=True), ReadOnlyGraphAggregate
    )
    assert isinstance(network.closure_graph(Graph(), read_only=False), Dataset)


def test_network_fire_consequent_infers_fact():
    rules = """
    @prefix ex: <http://example.org/> .
    { ex:a ex:p ?o } => { ex:a ex:q ?o } .
    """
    ruleset = horn_from_n3(StringIO(rules))
    rule_store, _, network = setup_rule_store(make_network=True)
    for rule in ruleset:
        network.build_network_from_clause(rule)

    term_node = next(iter(network.terminal_nodes))
    alpha_node = AlphaNode((Variable("s"), EX.p, Variable("o")))
    token = ReteToken((EX.a, EX.p, EX.b))
    bound_token = token.bind_variables(alpha_node)
    tokens = PartialInstantiation([bound_token])
    network.fire_consequent(tokens, term_node)
    assert (EX.a, EX.q, EX.b) in network.inferred_facts


def test_network_fire_consequent_override_executes_action():
    rules = """
    @prefix ex: <http://example.org/> .
    { ex:a ex:p ?o } => { ex:a ex:q ?o } .
    """
    ruleset = horn_from_n3(StringIO(rules))
    rule_store, _, network = setup_rule_store(make_network=True)
    for rule in ruleset:
        network.build_network_from_clause(rule)

    term_node = next(iter(network.terminal_nodes))
    called = {"count": 0}

    def _exec_action(_node, _triple, _tokens, _binding, _debug):
        called["count"] += 1

    term_node.execute_actions = {(EX.a, EX.q, Variable("o")): (True, _exec_action)}

    alpha_node = AlphaNode((Variable("s"), EX.p, Variable("o")))
    token = ReteToken((EX.a, EX.p, EX.b))
    bound_token = token.bind_variables(alpha_node)
    tokens = PartialInstantiation([bound_token])
    network.fire_consequent(tokens, term_node)
    assert called["count"] == 1


def test_network_fire_consequent_debug_paths_and_goal():
    rules = """
    @prefix ex: <http://example.org/> .
    { ex:a ex:p ?o } => { ex:a ex:q ?o } .
    """
    ruleset = horn_from_n3(StringIO(rules))
    rule_store, _, network = setup_rule_store(make_network=True)
    for rule in ruleset:
        network.build_network_from_clause(rule)

    term_node = next(iter(network.terminal_nodes))
    term_node.filter = True
    term_node.execute_actions = {}

    alpha_node = AlphaNode((Variable("s"), EX.p, Variable("o")))
    token = ReteToken((EX.a, EX.p, EX.b))
    bound_token = token.bind_variables(alpha_node)
    tokens = PartialInstantiation([bound_token])
    tokens._bindings_cache_enabled = True
    tokens._bindings_cache = []

    network.goal = (EX.a, EX.q, EX.b)
    with pytest.raises(Exception):
        network.fire_consequent(tokens, term_node, debug=True)

    network.goal = None
    network.fire_consequent(tokens, term_node, debug=True)

    called = {"count": 0}

    def _exec_action(_node, _triple, _tokens, _binding, _debug):
        called["count"] += 1

    term_node.execute_actions = {(EX.a, EX.q, Variable("o")): (None, _exec_action)}
    network.fire_consequent(tokens, term_node, debug=True)
    assert called["count"] >= 1

    unbound_rule = Rule(
        Clause(_simple_rule_body(), Uniterm(EX.q, [EX.a, Variable("x")]))
    )
    term_node.rules = {unbound_rule}
    term_node.consequent = {(EX.a, EX.q, Variable("x"))}
    term_node.execute_actions = {(EX.a, EX.q, Variable("x")): (None, _exec_action)}
    network.fire_consequent(tokens, term_node, debug=True)
    assert called["count"] >= 1


def test_network_parse_n3_logic_and_repr_clear_reset():
    rules = """
    @prefix ex: <http://example.org/> .
    { ex:a ex:p ?o } => { ex:a ex:q ?o } .
    """
    rule_store, _, network = setup_rule_store(make_network=True)
    network.parse_n3_logic(StringIO(rules))
    assert network.rules
    assert "Network" in repr(network)

    network.clear()
    assert not network.nodes
    assert not network.terminal_nodes
    assert not network.working_memory

    network.parse_n3_logic(StringIO(rules))
    new_graph = Graph()
    network.reset(new_graph)
    assert network.inferred_facts is new_graph


def test_network_closure_graph_store_fallback_and_defaults():
    rule_store, _, network = setup_rule_store(make_network=True)
    empty_graph = Graph()
    ro_graph = network.closure_graph(empty_graph, read_only=True, store=None)
    assert isinstance(ro_graph, ReadOnlyGraphAggregate)


def test_network_parse_and_setup_default_rules_and_stratified_model():
    rule_store, _, network = setup_rule_store(make_network=True)
    rules = """
    @prefix ex: <http://example.org/> .
    { ex:a ex:p ?o } => { ex:a ex:q ?o } .
    """
    network.parse_n3_logic(StringIO(rules))
    network.universal_truths.append((EX.a, EX.p, EX.b))
    network._setup_default_rules()

    network.neg_rules = set()
    assert network.calculate_stratified_model(Graph()) is None


def test_network_attach_beta_nodes_empty_lhs_path():
    rule_store, _, network = setup_rule_store(make_network=True)
    with pytest.raises(AssertionError):
        network.attach_beta_nodes(iter([]))
