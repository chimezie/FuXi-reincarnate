import path from "path"
import os from "os"
import { tool } from "@opencode-ai/plugin"
import { which } from "bun"

const TOOLS_DIR = path.join(os.homedir(), ".opencode", "tools")

export default tool({
  description: "List the terms in an ontology as Manchester OWL",
  args: {
    sqliteFile: tool.schema.string().describe("Path to SQLite file with pre-loaded ontology"),
  },
  async execute(args, context) {
    const script = path.join(TOOLS_DIR, "dir-ontology.py")

    // Prefer `uv run` if uv is on PATH; fall back to python3
    const useUv = which("uv")
    const commands = useUv
      ? ["uv", "run", "--active", script, String(args.sqliteFile)]
      : ["python3", script, String(args.sqliteFile)]
    const result = await Bun.$`${commands}`.text()
    return result.trim()
  },
})
