import { tool } from "@opencode-ai/plugin"
import { which } from "bun"

export default tool({
  description: "Verbalize an OWL class into Controlled Natural Language using `owl_dsl.review -a render_class`",
  args: {
    ontologyUri: tool.schema.string().describe("Ontology URI (must match the base IRI used when loading, including # if present)"),
    sqliteFile: tool.schema.string().describe("Path to SQLite file with pre-loaded ontology"),
    baseuri: tool.schema.string().describe(
        "Ontology namespace base URI (used to resolve local names)"),
    classReference: tool.schema.string().describe("Class local name or rdfs:label"),
    byId: tool.schema.boolean().optional().describe("Treat classReference as local name (not label)")
  },
  async execute(args, context) {
    const command = [
      'owl_dsl.review',
      '-a',
      'render_class',
      '--ontology-uri',
      args.ontologyUri,
      '--sqlite-file',
      args.sqliteFile,
      '--ontology-namespace-baseuri',
      args.baseuri,
      '--class-reference',
      args.classReference,
    ]
    if (args.byId) {
      command.push('--by-id')
    }
    const useUv = which("uv")
    const runner = useUv
      ? ["uv", "run", "--active", ...command]
      : [...command]
    const result = await Bun.$`${runner}`.text()
    return result.trim()
  },
})
