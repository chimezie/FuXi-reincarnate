import path from "path"
import os from "os"
import { tool } from "@opencode-ai/plugin"
import { which } from "bun"

const TOOLS_DIR = path.join(os.homedir(), ".opencode", "tools")

export default tool({
  description: "Find OWL properties by label pattern using `owl_dsl.review`",
  args: {
    ontologyUri: tool.schema.string().describe("Ontology URI (must match the base IRI used when loading, including # if present)"),
    sqliteFile: tool.schema.string().describe("Path to SQLite file with pre-loaded ontology"),
    baseuri: tool.schema.string().optional().describe("Ontology namespace base URI (defaults to ontologyUri)"),
    prefix: tool.schema.string().optional().describe("URI prefix filter"),
    propReferenceLabel: tool.schema.string().optional().describe("Property label regex filter"),
    limit: tool.schema.number().optional().describe("Max results (default 10)"),
    showPropertyDefinitionUsage: tool.schema.boolean().optional().describe("Show property definition usage (default false)"),
    owlFile: tool.schema.string().optional().describe("The path to the OWL file"),
    configurationFile: tool.schema.string().optional().describe("Path to configuration YAML file for NL rendering"),
  },
  async execute(args, context) {
    const configFile = args.configurationFile ?? path.join(TOOLS_DIR, "yijing.CNL.yaml")

    const command = ['owl_dsl.review',
                     '-a', 'find_properties',
                     '--ontology-uri', args.ontologyUri,
                     '--sqlite-file', args.sqliteFile,
                     '--ontology-namespace-baseuri', args.baseuri ?? args.ontologyUri]
    if (args.prefix) {
      command.push('--prefix', args.prefix)
    }
    if (args.propReferenceLabel) {
      command.push('--prop-reference-label', args.propReferenceLabel)
    }
    if (args.configurationFile) {
      command.push('--configuration-file', configFile)
    }
    command.push('--limit', String(args.limit ?? 10))
    if (args.showPropertyDefinitionUsage) {
      command.push('--show-property-definition-usage')
    }
    if (args.owlFile) {
      command.push(args.owlFile)
    }

    const useUv = which("uv")
    const commands = useUv
      ? ["uv", "run", "--active", ...command]
      : [...command]
    const result = await Bun.$`${commands}`.text()
    return result.trim()
  }
})
