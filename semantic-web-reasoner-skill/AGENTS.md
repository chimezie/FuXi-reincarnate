# Semantic Web Reasoner Skill — Agent Guide

An [OpenCode](https://opencode.ai) skill providing ontology management tools (check, create, verbalize, reason over OWL ontologies).

---

## Build & Check Commands

```bash
# Install dependencies
npm install

# Compile TypeScript → dist/
npm run build          # tsc (zero warnings policy)

# The project uses tsc directly, not a bundler.
# Output: dist/*.js + dist/*.d.ts (for plugin consumers)
```

## Project Structure

```
├── src/                          # TypeScript tool definitions (plugin entry)
│   ├── index.ts                  # Plugin entry — wires all tools
│   ├── check-ontology.ts         # → check-ontology tool (robot report)
│   ├── class-entailments.ts      # → class-entailments tool (ELK reasoning)
│   ├── create-ontology.ts        # → create-ontology tool (owlready2 SQLite)
│   ├── dir-ontology.ts           # → dir-ontology tool (Manchester OWL listing)
│   ├── extract-class.ts          # → extract-class tool (robot extract)
│   ├── find-ontology-class.ts    # → find-ontology-class tool
│   ├── find-ontology-property.ts # → find-ontology-property tool
│   ├── list-ontologies.ts        # → list-ontologies tool
│   ├── ontology-measure-essentials.ts
│   ├── ontology-report.ts
│   ├── set-alt-label.ts          # → set-alt-label tool (InfixOwl)
│   ├── set-annotation.ts         # → set-annotation tool (InfixOwl, generic)
│   ├── set-editorial-note.ts     # → set-editorial-note tool (InfixOwl)
│   ├── set-human-readable-definition.ts  # → set-human-readable-definition (InfixOwl)
│   ├── set-label.ts              # → set-label tool (InfixOwl)
│   ├── sparql-interlocution.ts   # → sparql-interlocution tool (FuXi SPARQL)
│   ├── verbalize-ontology-class.ts
│   └── dir-ontology.py           # Python backend for dir-ontology.ts
├── skills/semantic-web-reasoner-skill/
│   ├── SKILL.md                  # Skill instructions (loaded at runtime)
│   ├── scripts/                  # Python backends referenced by tools
│   │   ├── create-ontology.py
│   │   ├── dir-ontology.py
│   │   ├── list-ontologies.py
│   │   ├── set-annotation.py     # Python backend for annotation tools
│   │   ├── sparql-interlocution.py  # Python backend for sparql-interlocution
│   │   └── index.ts              # (empty, unused)
│   ├── advanced.md
│   ├── owl_engineering_apis.md
│   ├── owl2_sparql_entailment.md
│   ├── semantic-web-architecture.md
│   └── sw-tools.md
├── scripts/                      # Utility scripts
│   └── install.sh                # Build + deploy to .opencode/tools/
├── dist/                         # Compiled output (gitignored)
├── tsconfig.json                 # "module": "preserve", "moduleResolution": "bundler"
└── package.json
```

## How Tools Work

- Every `src/*.ts` (except `index.ts`) exports a single tool definition via `@opencode-ai/plugin`'s `tool()` function.
- Tools use **Bun runtime APIs**: `Bun.$` for shell commands and `import { which } from "bun"` for PATH lookups.
- The plugin entry (`src/index.ts`) imports all tools and registers them in the `tool` hook.
- Python backend scripts live in two places:
  - `src/dir-ontology.py` — richer Manchester OWL rendering (Restrictions, And/Or/Not/OneOf/Inverse)
  - `skills/semantic-web-reasoner-skill/scripts/` — simpler versions and list-ontologies.py
  - Production tools reference scripts at `/home/chimezie/.opencode/tools/` (deployed separately via `scripts/install.sh`)

## Code Style

- **TypeScript**: strict ESM with `.js` extensions in imports (for Bun/tsc compatibility)
- **No comments in code** unless explaining non-obvious behavior. Comments that remain must be purposeful (e.g., `/// script` directives in Python).
- **Use `tool.schema.*`** for argument definitions (zod-based, via `@opencode-ai/plugin`).
- **Resolve paths** relative to `context.worktree` when accepting user-provided file paths.
- **Prefer `uv run --active`** when executing Python scripts; fall back to `python3` if `uv` is not on PATH.
- **Naming**: tool file names = kebab-case tool names (e.g., `check-ontology.ts` → `check-ontology` tool).
- **Error handling**: catch shell command failures and return a user-facing error string, never let Bun exceptions propagate raw.

## Adding a New Tool

1. Create `src/<tool-name>.ts` with a default export using `tool({...})`.
2. Import and register it in `src/index.ts` under the `tool` key.
3. Add documentation in `skills/semantic-web-reasoner-skill/SKILL.md`.
4. Run `npm run build` to verify it compiles.

## Python Script Conventions

- Scripts use PEP 723 inline metadata (`# /// script` header) for dependency declarations.
- They accept positional CLI arguments (no `argparse`) — keep it simple.
- owlready2 is the primary library for ontology interaction.

## Runtime Requirements

- **Bun** (for executing the TypeScript plugin and tool definitions)
- **robot** (Java JAR, for check/extract/measure/report tools)
- **uv** (recommended) + Python 3.11+ with `owl_dsl` and `owlready2`
- The `@opencode-ai/plugin` npm package provides the tool framework and zod schema helpers
