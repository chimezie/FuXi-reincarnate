import path from "path"
import os from "os"
import { tool } from "@opencode-ai/plugin"
import { which } from "bun"

const TOOLS_DIR = path.join(os.homedir(), ".opencode", "tools")

export default tool({
  description: "Create OWL_DSL / owlready2 SQLite ontology and archive provenance for later use by " +
      "verbalize-ontology-class, find-ontology-property, find-ontology-class, verbalize-ontology-entailments, " +
      "and summarize-ontology using create-ontology.py",
  args: {
    ontologyUri: tool.schema.string().describe(
        "Ontology URI (must match the base IRI used when loading, including # if present)"),
    //sqliteFile: tool.schema.string().optional().describe("Path to SQLite file with pre-loaded ontology"),
    baseuri: tool.schema.string().describe(
        "Ontology namespace base URI (used to resolve local names)"),
    owlFile: tool.schema.string().describe(
        "The path to the OWL file to load into the SQL file for use with owlready 2"),
    workingDir: tool.schema.string().optional().describe(
        "The working directory where ontology SQLite files and archives will be kept"),
  },
  async execute(args, context) {
    const script = path.join(TOOLS_DIR, "create-ontology.py")

    // Prefer `uv run` if uv is on PATH; fall back to python3
    const useUv = which("uv")
    const working_dir = args.workingDir ? args.workingDir : "/tmp"
    const commands = useUv
      ? ["uv", "run", "--active", script,
          String(args.ontologyUri),
          String(args.baseuri),
          //String(args.sqliteFile),
          String(args.owlFile), working_dir]
      : ["python3", script,
          String(args.ontologyUri),
          String(args.baseuri),
          //String(args.sqliteFile),
          String(args.owlFile), working_dir]
    const result = await Bun.$`${commands}`.text()
    return result.trim()
  },
})
