import { tool } from "@opencode-ai/plugin"

export default tool({
  description: "'Compute a number of metrics about your ontology, such as entity and axiom counts, qualitative " +
      "information such as OWL 2 profiles and more complex metrics'",
  args: {
    owlFile: tool.schema.string().optional().describe("The path to the OWL file"),
    reportFile: tool.schema.string().optional().describe("A file where to write JSON report")
  },
  async execute(args, context) {
    const commands = ['robot',
                      'measure',
                      '--format', 'json',
                      '--metrics', 'essential',
                      '--output', args.reportFile,
                      '--input', args.owlFile]
    const result = await Bun.$`${commands}`.text()
    return result.trim()
  }
})
