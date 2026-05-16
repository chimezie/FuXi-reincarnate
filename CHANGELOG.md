# Changelog

All notable changes to FuXi are documented in this file.

The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
### Changed
### Deprecated
### Removed
### Fixed
### Security

---

## [2.0.0] — 2026-05-15

> First tagged release of the modernized **FuXi-reincarnate** fork.
> Major rewrite: Python 3.13+, `snake_case` public API, split CLI,
> pytest, ruff, uv. See the [Migration from 1.4](#migration-from-14)
> section below.

### Added

- New `fuxi.types` module exposing `Triple`, `RDFTerm`, `Bindings`,
  `GraphLike` for downstream typing.
- `fuxi.SPARQL.utilities.owl_entailment_regime_graph(...)` for mediated
  entailment regime graph construction.
- `fuxi.SPARQL.service.SPARQLServiceGraph` — SPARQL service-graph
  wrapper for federated queries against a top-down entailment store.
- `fuxi.SPARQL.utilities.sparql_interlocution(...)` convenience helper.
- `Uniterm.unify_with(...)` method for variable-to-term binding
  extraction.
- SPARQL 1.1 entailment test harness covering RDFS and RDF regimes.
- Three focused CLI subcommands: `fuxi.core`, `fuxi.proof`, `fuxi.owl`.
- GitHub Actions CI and tag-based PyPI publishing workflow.
- `AGENTS.md` and `ARCHITECTURE.md` developer documentation.

### Changed

- **Python**: minimum supported version is now **3.13**.
- **Build**: project now uses **uv** as canonical environment manager
  and **ruff** as the single linter/formatter (replaces flake8, isort,
  black, pyupgrade).
- **Public API**: pervasive `CamelCase → snake_case` rename across
  `fuxi.Horn`, `fuxi.Rete`, `fuxi.SPARQL`, `fuxi.Syntax.InfixOWL`.
  See the [Migration from 1.4](#migration-from-14) for the full table.
- **CLI**: the legacy `fuxi` command remains as a compatibility router
  that delegates to `fuxi.core` / `fuxi.proof` / `fuxi.owl` based on
  flags.
- `TopDownSPARQLEntailingStore` constructor kwargs renamed:
  `DEBUG → debug`, `nsBindings → ns_bindings`,
  `identifyHybridPredicates → identify_hybrid_predicates`;
  `decisionProcedure` removed.
- `sparql_interlocution` moved from `fuxi.SPARQL.service` to
  `fuxi.SPARQL.utilities`.
- `_extract_goals` moved from `fuxi.Rete.CommandLine` to
  `fuxi.cli.shared`.
- Internal immutable mappings: `ImmutableDict → frozendict` for true
  immutability semantics.
- Proof and SIP rendering: `pydot → graphviz`.
- Test suite migrated from unittest/nose to **pytest** with fixtures.
- Bare `except:` blocks replaced with typed exception handling.
- String formatting upgraded to f-strings throughout.

### Deprecated

- The legacy `fuxi` console-script entry point. It may be removed in a
  future major release. New code should invoke `fuxi.core`,
  `fuxi.proof`, or `fuxi.owl` directly.

### Removed

- Python 2 / Python ≤3.12 support.
- `pydot` dependency (replaced by `graphviz`).
- `ImmutableDict` internal type (replaced by `frozendict`).
- `TopDownSPARQLEntailingStore` `decisionProcedure` kwarg.
- `RDFTuplesToSPARQL` (use `EDBQuery.as_sparql`).
- Legacy example scripts using deprecated APIs: `example1.py`,
  `example3.py`, `example4.py`, `example6.py`, `example7.py`.
- Legacy unittest runners: `test/suite.py`, `test/OWLsuite.py`,
  `test/SPARQL/test.py`.

### Fixed

- RDFS/ASK inference gaps in SPARQL 1.1 entailment harness.
- Two proof-capture regressions in OWL `differentFrom` test.
- OpenQuery proof regression.
- Inferred token handling: `addWME` invocation re-ordered after
  instantiation count update.
- Backward-chaining action propagation tracking and grounded query
  handling.
- Stale `_extract_goals` import path in `test/test_cli_sparql_parse.py`.
- `TopDownSPARQLEntailingStore` forward-reference hoisted into
  `TYPE_CHECKING` in `fuxi.SPARQL.utilities`.

### Known issues

- SPARQL 1.1 `bind01`–`bind08` BIND-heavy entailment tests fail
  pending richer algebra support in top-down query extraction
  (documented in `AGENTS.md`).
- `owl:sameAs` transitivity has a known correctness gap
  (`test/test_sameAs.py:46`).
- BFP variable leakage tracked in issue #8.

---

## Migration from 1.4

### CLI mapping

| Legacy invocation              | New invocation                    | Notes                                      |
|-------------------------------|-----------------------------------|--------------------------------------------|
| `fuxi facts.n3`               | `fuxi.core facts.n3`              | Forward chaining + RETE diagnostics        |
| `fuxi --why='Q' facts.n3`     | `fuxi.proof --why='Q' facts.n3`   | BFP query answering; `--why` required      |
| `fuxi --why='Q' --output=proof-graph facts.n3` | `fuxi.proof --why='Q' --output=proof-graph facts.n3` | Proof graph rendering via graphviz |
| `fuxi --why='Q' --output=sip-collection facts.n3` | `fuxi.proof --why='Q' --output=sip-collection facts.n3` | SIP graph rendering |
| `fuxi --dlp --output=man-owl onto.ttl` | `fuxi.owl --dlp --output=man-owl onto.ttl` | Manchester OWL rendering |
| `fuxi --class=C --property=P onto.ttl` | `fuxi.owl --class=C --property=P onto.ttl` | OWL inspection / DLP extraction |

The legacy `fuxi` entry point still works as a thin router in
`fuxi.Rete.CommandLine`. It is provided for backward compatibility and
may be removed in a future major release.

### Key CamelCase → snake_case renames

| Old name                  | New name                     |
|---------------------------|------------------------------|
| `SetupRuleStore`          | `setup_rule_store`           |
| `HornFromN3`              | `horn_from_n3`              |
| `MagicSetTransformation`  | `magic_set_transformation`   |
| `AdornLiteral`            | `adorn_literal`              |
| `BuildUnitermFromTuple`   | `build_uniterm_from_tuple`   |
| `generateTokenSet`        | `generate_token_set`        |
| `GenerateProof`           | `generate_proof`            |
| `PrettyPrintRule`         | `pretty_print_rule`         |
| `non_DHL_OWL_Semantics`   | `NON_DHL_OWL_SEMANTICS`     |
| `inferredFacts`           | `inferred_facts`            |
| `terminalNodes`           | `terminal_nodes`            |
| `queryNetworks`           | `query_networks`            |
| `edbQueries`              | `edb_queries`               |
| `feedFactsToAdd`          | `feed_facts_to_add`         |
| `buildNetworkFromClause`  | `build_network_from_clause` |
| `setupDescriptionLogicProgramming` | `setup_description_logic_programming` |
| `asSPARQL`                | `as_sparql`                 |
| `reportConflictSet`       | `report_conflict_set`       |
| `toRDFTuple`              | `to_rdf_tuple`              |
| `setOperator`             | `set_operator`              |
| `nsMap` (kwarg)           | `ns_map`                    |
| `RDFTuplesToSPARQL`       | `EDBQuery.as_sparql`        |

### Quick sed migration (review diffs before applying!)

```bash
find your_project -name '*.py' -type f -print0 | xargs -0 sed -i \
  -e 's/\bSetupRuleStore\b/setup_rule_store/g' \
  -e 's/\bHornFromN3\b/horn_from_n3/g' \
  -e 's/\bMagicSetTransformation\b/magic_set_transformation/g' \
  -e 's/\bAdornLiteral\b/adorn_literal/g' \
  -e 's/\bBuildUnitermFromTuple\b/build_uniterm_from_tuple/g' \
  -e 's/\bgenerateTokenSet\b/generate_token_set/g' \
  -e 's/\bGenerateProof\b/generate_proof/g' \
  -e 's/\bPrettyPrintRule\b/pretty_print_rule/g' \
  -e 's/\bnon_DHL_OWL_Semantics\b/NON_DHL_OWL_SEMANTICS/g' \
  -e 's/\binferredFacts\b/inferred_facts/g' \
  -e 's/\bterminalNodes\b/terminal_nodes/g' \
  -e 's/\bfeedFactsToAdd\b/feed_facts_to_add/g' \
  -e 's/\bbuildNetworkFromClause\b/build_network_from_clause/g' \
  -e 's/\basSPARQL\b/as_sparql/g' \
  -e 's/\bnsMap\b/ns_map/g' \
  -e 's/\bnsBindings\b/ns_bindings/g'
```

---

[Unreleased]: https://github.com/chimezie/FuXi-reincarnate/compare/v2.0.0...HEAD
[2.0.0]: https://github.com/chimezie/FuXi-reincarnate/releases/tag/v2.0.0
