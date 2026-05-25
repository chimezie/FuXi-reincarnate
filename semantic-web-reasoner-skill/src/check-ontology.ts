import path from "path"
import { tool } from "@opencode-ai/plugin"
import { which } from "bun"

export default tool({
  description: "Run a report on an OWL file for all the issues it has",
  args: {
    owlFile: tool.schema.string().optional().describe("The path to the OWL file"),
    reportFile: tool.schema.string().optional().describe("A file where to write JSON report"),
    imports: tool.schema.boolean().default(false).describe(
        "Load imported ontologies (default: false, strips owl:imports to avoid HTTP failures)"),
    failOn: tool.schema.string().default("NONE").describe(
        "Robot --fail-on level: NONE, ALL, ERROR, WARN, INFO (default: NONE means always succeed)"),
  },
  async execute(args, context) {
    const useUv = which("uv")
    const robotPath = which("robot")

    // Resolve input path relative to the project worktree or CWD
    const resolvePath = (p: string | undefined): string | undefined => {
      if (!p) return p
      const baseDir = context?.worktree || process.cwd()
      return path.isAbsolute(p) ? p : path.resolve(baseDir, p)
    }

    const owlPath = resolvePath(args.owlFile)

    // Strip owl:imports unless --imports is set
    let inputFile = owlPath
    let tempDir: string | null = null

    if (!args.imports && owlPath) {
      const pythonScript = `
import sys, os, tempfile
from rdflib import Graph, Namespace
g = Graph()
g.parse(sys.argv[1], format="xml")
OWL = Namespace("http://www.w3.org/2002/07/owl#")
for s, p, o in list(g.triples((None, OWL.imports, None))):
    g.remove((s, p, o))
outdir = tempfile.mkdtemp()
out = os.path.join(outdir, "stripped.owl")
g.serialize(out, format="xml")
print(outdir)
      `.trim()
      const pythonCmd = useUv
        ? ["uv", "run", "--active", "python", "-c", pythonScript, owlPath]
        : ["python3", "-c", pythonScript, owlPath]
      try {
        const out = (await Bun.$`${pythonCmd}`.text()).trim()
        if (out) {
          tempDir = out
          inputFile = `${out}/stripped.owl`
        }
      } catch (e: any) {
        return `Python stripping failed: ${e.message || e}`
      }
    }

    // robot is a standalone Java tool — use absolute path to avoid Bun $ PATH issues
    const robotBin = robotPath ?? 'robot'
    const command = [
      robotBin, 'report',
      '--fail-on', args.failOn ?? "NONE",
      '--input', inputFile ?? '',
    ]
    if (args.reportFile) {
      command.push('--output', args.reportFile)
    }

    let result: string
    try {
      result = (await Bun.$`${command}`.text()).trim()
    } catch (e: any) {
      return `Robot report failed: ${e.message || e}`
    }

    // Clean up temp directory
    if (tempDir) {
      await Bun.$`rm -rf ${tempDir}`
    }

    return result
  }
})
