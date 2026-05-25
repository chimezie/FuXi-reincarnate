import { tool } from "@opencode-ai/plugin"

export default tool({
  description: "Export details about named ontology entities as a table",
  args: {
    owlFile: tool.schema.string().optional().describe("The path to the OWL file"),
    reportFile: tool.schema.string().optional().describe("A file where to write JSON report")
  },
  async execute(args, context) {
    const commands = ['robot',
                      'export',
                      '--export', args.reportFile,
                      '--input', args.owlFile,
                      '--header', "IRI|ID|LABEL|SubClass Of|SubClasses|Equivalent Class|SubProperty Of|Type",
                      '--include', "classes properties",
                      '--entity-select', "NAMED"]
    const result = await Bun.$`${commands}`.text()
    return result.trim()
  }
})
