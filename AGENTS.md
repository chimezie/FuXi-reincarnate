# FuXi + RDFLib Agent Guide

FuXi (pronounced foo-shee) is a FuXi is a highly efficient, Python-based, bi-directional semantic web logical reasoning system. 
It works as a companion to RDFLib, a Python library for working with RDF.

It is being re-written for modern Python 3.9+ and changes are being made to the Fuxi-reincarnate-chimezie git repository.

The details of its original design are in ARCHITECTURE.md.

---

## Build, Lint, and Test Commands

### FuXi (nose-based legacy system)
```bash
# Install dependencies
pip install -r FuXi-reincarnate-chimezie/requirements.py3.txt

# Run all tests
python FuXi-reincarnate-chimezie/setup.py nosetests

# Run single test file
nosetests FuXi-reincarnate-chimezie/test/test_issue_041.py

# Run specific test by name
python FuXi-reincarnate-chimezie/setup.py nosetests --tests=FuXi-reincarnate-chimezie/test/test_issue_041:TestFoo.test_bar

# Lint with flake8
tox -e flake  # Uses: flake8 --exclude=tools,examples --max-line-length=350

# Coverage report (HTML in FuXi-reincarnate-chimezie/coverage/)
tox -e cover

# Generate Sphinx docs
tox -e docs
cd FuXi-reincarnate-chimezie/docs && make html
```

---

## Code Style Guidelines

### General Python Conventions
- **Formatting**: Follow Black/PEP 8; never reformat unrelated code when editing.
- **Imports**: Organize as standard library → third-party → local imports. Use absolute imports. One import per line for multiple symbols from same module.
```python
import os
from typing import Dict, List

import rdflib
from rdflib import Graph

from .local_module import something
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

### RDFLib-Specific Rules (from `rdflib/pyproject.toml`)
- **Black configuration**: Line length 88, target Python 3.9, version 24.10.0+
- **Ruff ruleset**: Target py39; enabled codes: `E`, `W`, `F`, `I`, `N`, `FA`, `UP*`
- **Ignored codes**: `E501` (line too long), `E203` (whitespace before ':'), `E231` (missing whitespace after ',')
- **isort profile**: Uses Black profile, line length 88, paths: `rdflib`, `test`, `devtools`, `examples`
- **mypy strictness**: `check_untyped_defs = true` for all `rdflib.*`, `warn_unused_ignores = true`

### FuXi-Specific Considerations
- Test framework is nose-based (legacy). Check `setup.cfg` for test exclusions marked with `known_issue`.
- Python 2 compatibility code exists in `FuXi-reincarnate-chimezie/setup.py`; minimize changes to legacy modules.
- **Black configuration**: Line length 88, target Python 3.9, version 24.10.0+
- **Ruff ruleset**: Target py39; enabled codes: `E`, `W`, `F`, `I`, `N`, `FA`, `UP*`
- **isort profile**: Uses Black profile, line length 88, paths: `rdflib`, `test`, `devtools`, `examples`
- **mypy strictness**: `check_untyped_defs = true` for all `rdflib.*`, `warn_unused_ignores = true`

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

### Running FuXi Tests

See the [Testing section](../README.md#testing) in README.md for detailed examples.

```bash
# Run all tests
uv run pytest test

# Run OWL test suite with specific options
uv run pytest test/testOWL.py --single-test OWL/TransitiveProperty/premises001 --ground-query

# Run with debugging
uv run pytest test/testOWL.py --owl-debug --capture-proofs
```

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

### Rule Safety Levels (`fuxi.Horn`)
```python
DATALOG_SAFETY_NONE   # No safety checks (fastest, unsafe rules allowed)
DATALOG_SAFETY_STRICT # Strict variable binding requirements
DATALOG_SAFETY_LOOSE  # Relaxed safety with warnings
```

---

## Practical Tips for Agents

1. **When modifying RDFLib code**: Always run `poetry run ruff check .` and `poetry run pytest <file>` before suggesting changes.

2. **When working on FuXi**: Use nose test discovery; add markers like `@known_issue` for expected failures in `setup.cfg`.

3. **Import ordering**: Use `isort` with Black profile to auto-sort imports consistently across the codebase.

4. **Type annotations**: Add types to new public APIs and complex internal functions. Legacy code may have minimal typing.

5. **Testing edge cases**: RDFLib handles many RDF/OWL edge cases; review existing tests for patterns before writing new ones.

6. **SPARQL queries in FuXi**: Check `FuXi-reincarnate-chimezie/test/SPARQL/` for query test templates and expected result formats.
