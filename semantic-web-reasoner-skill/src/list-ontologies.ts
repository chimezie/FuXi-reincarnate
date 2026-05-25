import path from "path"
import os from "os"
import { tool } from "@opencode-ai/plugin"
import { which } from "bun"

const TOOLS_DIR = path.join(os.homedir(), ".opencode", "tools")

export default tool({
  description: "List all OWL ontologies saved as owlready 2 SQLite files using the `ontology_db.json` owlready 2 / sqlite" +
               " naming convention in /tmp",
  args: {
    workingDir: tool.schema.string().optional().describe("Working directory (working_dir): Path to working directory (/tmp/ by default)"),
  },
  async execute(args, context) {
    const script = path.join(TOOLS_DIR, "list-ontologies.py")

    // Prefer `uv run` if uv is on PATH; fall back to python3
    const useUv = which("uv")
    const working_dir = args.workingDir ? args.workingDir : "/tmp"
    const commands = useUv
      ? ["uv", "run", "--active", script, String(working_dir)]
      : ["python3", script, String(working_dir)]
    const result = await Bun.$`${commands}`.text()
    return result.trim()
  },
})
