import { tool } from "@opencode-ai/plugin"
import { which } from "bun"

export default tool({
  description: "'Compute a number of metrics about your ontology, such as entity and axiom counts, qualitative " +
      "information such as OWL 2 profiles and more complex metrics'",
  args: {
    owlFile: tool.schema.string().optional().describe("The path to the OWL file"),
    reportFile: tool.schema.string().optional().describe("A file where to write JSON report")
  },
  async execute(args, context) {
    const command = ['robot',
                             'measure',
                             '--format', 'json',
                             '--metrics', 'essential',
                             '--output', args.reportFile,
                             '--input', args.owlFile
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
