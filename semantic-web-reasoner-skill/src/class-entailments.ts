import path from "path"
import os from "os"
import { tool } from "@opencode-ai/plugin"
import { which } from "bun"

const TOOLS_DIR = path.join(os.homedir(), ".opencode", "tools")

export default tool({
  description: "Print logical entailment explanations about class via ELK reasoner with " +
               "`owl_dsl.reason --action explain_logical_inferences` (OWL-DSL).  If used with `byId` argument, then " +
               "`classReference` is the local name " +
               "(the part after the ontology Namespace Base URI or `ontologyNamespaceBaseuri`) " +
               "otherwise it is the rdfs:label",
  args: {
    ontologyUri: tool.schema.string().describe(
        "Ontology URI (must match the base IRI used when loading, including # if present)"),
    sqliteFile: tool.schema.string().describe("Path to SQLite file with pre-loaded ontology"),
    baseuri: tool.schema.string().describe(
        "Ontology namespace base URI (used to resolve local names)"),
    classReference: tool.schema.string().describe("Class local name or rdfs:label"),
    byId: tool.schema.boolean().optional().describe("Treat classReference as local name (not label)"),
    owlFile: tool.schema.string().optional().describe("Path to OWL file (passed as positional arg)"),
    configurationFile: tool.schema.string().optional().describe("Path to configuration YAML file for NL rendering"),
  },
  async execute(args, context) {
    const configFile = args.configurationFile ?? path.join(TOOLS_DIR, "yijing.CNL.yaml")

    const command = ['owl_dsl.reason',
                     '--action', 'explain_logical_inferences',
                     '--ontology-uri', args.ontologyUri,
                     '--sqlite-file', args.sqliteFile,
                     '--ontology-namespace-baseuri', args.baseuri,
                     '--configuration-file', configFile,
                     '--class-reference', args.classReference]
    if (args.byId) {
      command.push('--by-id')
    }
    if (args.owlFile) {
      command.push(args.owlFile)
    }

    const useUv = which("uv")
    const commands = useUv
      ? ["uv", "run", "--active", ...command]
      : [...command]
    try {
      const result = await Bun.$`${commands}`.text()
      return result.trim()
    } catch (e: any) {
      return `class-entailments failed: ${e.message || e}${e.stderr ? '\nstderr: ' + e.stderr.toString() : ''}`
    }
  },
})
