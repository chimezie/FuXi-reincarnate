import { tool } from "@opencode-ai/plugin"
import { which } from "bun"

export default tool({
  description: "Extract a class from an ontology",
  args: {
    owlFile: tool.schema.string().optional().describe("The path to the OWL file"),
    term: tool.schema.string().describe("The term to extract as a full URI or a Q Name"),
    outputOwl: tool.schema.string().optional().default('/tmp/output.owl').describe(
        "A file where to write the resulting OWL (defaults to /tmp/output.owl)")
  },
  async execute(args, context) {
    const command = ['robot',
                           'extract',
                           '--output', args.outputOwl,
                           '--method', 'STAR',
                           '--term', args.term,
                           '--input', args.owlFile]

    // Prefer `uv run` if uv is on PATH; fall back to python3
    const useUv = which("uv")
    const commands = useUv
      ? ["uv", "run", "--active", ...command]
      : [...command]
    const result = await Bun.$`${commands}`.text()
    return result.trim()
  }
})
