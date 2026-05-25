import path from "path"
import os from "os"
import { tool } from "@opencode-ai/plugin"
import { which } from "bun"

const TOOLS_DIR = path.join(os.homedir(), ".opencode", "tools")

export default tool({
  description: "Set an arbitrary annotation on an OWL class using InfixOwl",
  args: {
    owlFile: tool.schema.string().describe("The path to the OWL file"),
    baseuri: tool.schema.string().describe(
        "Ontology namespace base URI (used to resolve local names)"),
    classReference: tool.schema.string().describe("Class local name or rdfs:label"),
    byId: tool.schema.boolean().optional().describe("Treat classReference as local name (not label)"),
    uri: tool.schema.string().describe("The annotation property URI"),
    value: tool.schema.string().describe("The annotation value to set"),
  },
  async execute(args, context) {
    const script = path.join(TOOLS_DIR, "set-annotation.py")
    const byId = String(!!args.byId)

    const useUv = which("uv")
    const commands = useUv
      ? ["uv", "run", "--active", script,
         String(args.owlFile), String(args.baseuri),
         String(args.classReference), byId, String(args.uri), String(args.value)]
      : ["python3", script,
         String(args.owlFile), String(args.baseuri),
         String(args.classReference), byId, String(args.uri), String(args.value)]
    const result = await Bun.$`${commands}`.text()
    return result.trim()
  },
})
