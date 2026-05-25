import { tool } from "@opencode-ai/plugin"

export default tool({
  description: "Extract a class from an ontology",
  args: {
    owlFile: tool.schema.string().optional().describe("The path to the OWL file"),
    term: tool.schema.string().describe("The term to extract as a full URI or a Q Name"),
    outputOwl: tool.schema.string().optional().default('/tmp/output.owl').describe(
        "A file where to write the resulting OWL (defaults to /tmp/output.owl)")
  },
  async execute(args, context) {
    const commands = ['robot',
                      'extract',
                      '--output', args.outputOwl,
                      '--method', 'STAR',
                      '--term', args.term,
                      '--input', args.owlFile]
    const result = await Bun.$`${commands}`.text()
    return result.trim()
  }
})
