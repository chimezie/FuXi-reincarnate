# FuXi + RDFLib Agent Guide

FuXi (pronounced foo-shee) is a FuXi is a highly efficient, Python-based, bi-directional semantic web logical reasoning system. 
It works as a companion to RDFLib, a Python library for working with RDF.

It is being re-written for modern Python 3.9+ and changes are being made to the Fuxi-reincarnate-chimezie git repository.

The details of its original design are in ARCHITECTURE.md.

---

## Build, Lint, and Test Commands

### Modern Python (3.12+) Commands
```bash
# Install dependencies
uv pip install -e ".[dev]"

# Run all tests
uv run pytest test

# Run single test file
uv run pytest test/testOWL2.py

# Run specific test
uv run pytest test/testOWL.py --single-test OWL/TransitiveProperty/premises001 --ground-query

# Lint with ruff (replaces flake8, isort, black)
uv run ruff check .

# Format with ruff
uv run ruff format .

# Generate Sphinx docs
tox -e docs

# Coverage report (HTML in coverage/)
uv run pytest --cov=FuXi --cov-report=html
```

### Legacy Commands (FuXi-reincarnate-chimezie)
```bash
# Install dependencies (legacy)
pip install -r FuXi-reincarnate-chimezie/requirements.py3.txt

# Run all tests (legacy nose-based)
python FuXi-reincarnate-chimezie/setup.py nosetests
```

---

## Code Style Guidelines

### Ruff (Primary Linter & Formatter)

FuXi uses **ruff** as the single tool for linting and formatting. It replaces flake8, isort, black, and pyupgrade. Configuration is in `pyproject.toml` [tool.ruff] section.

```bash
# Lint
uv run ruff check .

# Auto-fix
uv run ruff check --fix .

# Format
uv run ruff format .

# Check formatting without changes
uv run ruff format --check .
```

**Enabled rules** (from pyproject.toml):
- `E`, `W`, `F`: Pyflakes (replaces flake8)
- `I`: isort (import sorting)
- `N`: Naming conventions
- `FA`: Future annotations
- `UP`: Pyupgrade

**Ignored rules**:
- `E501`: Line too long (handled by formatter)
- `E203`: Whitespace before ':'
- `E231`: Missing whitespace after ','

### General Python Conventions
- **Imports**: Organize as standard library → third-party → local imports. Use absolute imports. One import per line for multiple symbols from same module.
```python
import os
from typing import Any

import rdflib
from rdflib import Graph

from fuxi.local_module import something
```
- **Type hints**: Use `typing` module for public APIs and complex type flows. Prefer modern syntax: `dict[str, Any]` over `Dict[str, Any]`.
- **Naming conventions**:
  - Functions/variables: `snake_case` (e.g., `compute_score`, `user_id`)
  - Classes: `PascalCase` (e.g., `RDFGraph`, `LogicEngine`)
  - Constants: `UPPER_SNAKE_CASE` (e.g., `MAX_RETRIES`, `DEFAULT_NS`)
- **Error handling**: Raise specific exceptions (`ValueError`, `TypeError`). Never use bare `except:`. Provide meaningful error messages.
```python
if not isinstance(value, int):
    raise TypeError(f"Expected int, got {type(value).__name__}")
```
- **Logging**: Use `logging.getLogger(__name__)` for all logging. Avoid `print()` statements except in debug scripts.

---

## Testing Best Practices
Use pytest for all new tests.

### RDFLib pytest behavior
- Default flags: `--doctest-modules`, ignores paths: `admin/`, `devtools/`, `docs/`, `site/`
- Internet-dependent tests marked with `@pytest.mark.webtest`
- EARL reports written to `test_reports/*-HEAD.ttl` by default

### FuXi test organization
- Primary test directory: `FuXi-reincarnate-chimezie/test/`
- SPARQL-specific tests: `FuXi-reincarnate-chimezie/test/SPARQL/`
- OWL test suites: `test/testOWL.py` (OWL 1), `test/testOWL2.py` (OWL 2)
- SPARQL entailment harness: `test/SPARQL/test_sparql_entailment.py`

### Running FuXi Tests

See the [Testing section](../README.md#testing) in README.md for detailed examples.

```bash
# Run all tests
uv run pytest test

# Run OWL test suite with specific options
uv run pytest test/testOWL.py --single-test OWL/TransitiveProperty/premises001 --ground-query

# Run with debugging
uv run pytest test/testOWL.py --owl-debug --capture-proofs

# Run SPARQL entailment harness
uv run pytest test/SPARQL/test_sparql_entailment.py

# Run one SPARQL entailment case by manifest ID
uv run pytest test/SPARQL/test_sparql_entailment.py --single-test rdfs04
```

### SPARQL entailment harness architecture notes (agent-facing)

`test/SPARQL/test_sparql_entailment.py` is intentionally structured like the
OWL harnesses:

1. **Manifest collection** (`collect_sparql_entailment_test_cases`):
   - Parses the W3C entailment manifest
   - Filters to approved query-evaluation tests
   - Chooses supported regimes (`ent:RDFS`, `ent:RDF`)
   - Applies explicit `SKIP` reasons via pytest marks

2. **Entailment setup**:
   - Builds a fact graph from test data
   - Adds RDFS axiomatic triples for RDFS-regime runs
   - Extends the entailment rule program with regime-specific extra rules
     (`test/SPARQL/W3C/rdf-rdfs.n3` and RDF helper rules)
   - Constructs an entailing graph via
     `fuxi.SPARQL.utilities.owl_entailment_regime_graph`

3. **Query execution and comparison**:
   - Executes each manifest query against the entailing graph
   - Parses expected `.srx` result sets
   - ASK queries are strict boolean comparisons
   - SELECT-style result sets use subset comparison (expected bindings must be
     present; extra bindings are currently tolerated)

4. **Current boundaries**:
   - BIND-heavy tests (`bind01`-`bind08`) are known failures pending richer
     algebra support in top-down query extraction.
   - Some SPARQL-DL tests require OWL entailment strength beyond current
     RDFS/RDF harness mode and are explicitly skipped.

When editing this harness, prefer small, explicit transformations and keep the
collector, setup, and assertion paths separate (SRP) to reduce debugging
complexity.

---

## FuXi Domain Architecture (Quick Reference)

**Core philosophy**: Bi-directional reasoning (forward/bottom-up + backward/top-down) for Semantic Web data.

| Module | Purpose | Key Classes/Constants |
|--------|---------|----------------------|
| `fuxi.Horn` | Logic programming, RIF-BLD abstraction | Rule classes, safety constants |
| `fuxi.Rete` | RETE-UL network for forward chaining | ReteNetwork, Alpha/Beta nodes |
| `fuxi.DLP` | Description Logic Programs (OWL→rules) | DLProgram, translation utilities |
| `fuxi.LP` | Backwards Fixpoint Procedure (BFP) | Query answering engine |
| `fuxi.SPARQL` | Backward-chaining SPARQL store | Entailment registry |
| `fuxi.SPARQL.service` | SPARQL service graph wrapper | SPARQLServiceGraph, sparql_interlocution |

### Rule Safety Levels (`fuxi.Horn`)
```python
DATALOG_SAFETY_NONE   # No safety checks (fastest, unsafe rules allowed)
DATALOG_SAFETY_STRICT # Strict variable binding requirements
DATALOG_SAFETY_LOOSE  # Relaxed safety with warnings
```

---

## Practical Tips for Agents

1. **Before suggesting changes**: Always run `uv run ruff check .` and `uv run pytest <file>` to verify code quality.

2. **Use the right CLI command for examples/tests**:
   - `fuxi.core` for forward-chaining examples and RETE diagnostics
   - `fuxi.proof` for `--why` query solving and proof/SIP graph output
   - `fuxi.owl` for DLP/ontology and `--output=man-owl` workflows
   - `fuxi` remains a compatibility wrapper

3. **When working on FuXi**: Use pytest for all new tests. Legacy nose-based tests may have `@known_issue` markers in `setup.cfg`.

4. **Import ordering and formatting**: Use `uv run ruff check --fix .` to auto-fix imports and formatting issues.

5. **Type annotations**: Add types to new public APIs and complex internal functions. Legacy code may have minimal typing.

6. **Testing edge cases**: Review existing tests in `test/` for patterns before writing new ones.

7. **SPARQL queries in FuXi**: Use `sparql_interlocution` from `fuxi.SPARQL.service` for querying `TopDownSPARQLEntailingStore`. Check `test/SPARQL/` for query test templates and expected result formats.

8. **Building documentation**: Run `tox -e docs` to build Sphinx documentation locally.
