import { tool } from "@opencode-ai/plugin"
import { which } from "bun"

export default tool({
  description: "Export details about named ontology entities as a table",
  args: {
    owlFile: tool.schema.string().optional().describe("The path to the OWL file"),
    reportFile: tool.schema.string().optional().describe("A file where to write JSON report")
  },
  async execute(args, context) {
    const command = ['robot',
                           'export',
                             '--export', args.reportFile,
                             '--input', args.owlFile,
                            '--header', "IRI|ID|LABEL|SubClass Of|SubClasses|Equivalent Class|SubProperty Of|Type",
                            '--include', "classes properties",
                            '--entity-select', "NAMED"
                            ]

    // Prefer `uv run` if uv is on PATH; fall back to python3
    const useUv = which("uv")
    const commands = useUv
      ? ["uv", "run", "--active", ...command]
      : [...command]
    const result = await Bun.$`${commands}`.text()
    return result.trim()
  }
})
