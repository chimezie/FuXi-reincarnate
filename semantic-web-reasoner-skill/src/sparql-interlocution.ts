import path from "path"
import os from "os"
import { tool } from "@opencode-ai/plugin"
import { which } from "bun"

const TOOLS_DIR = path.join(os.homedir(), ".opencode", "tools")

export default tool({
  description: "Execute SPARQL queries over a remote endpoint with OWL entailment via FuXi sparql_interlocution",
  args: {
    sparqlServiceGraph: tool.schema.string().describe("URL of the SPARQL endpoint"),
    nsBindings: tool.schema.string().describe(
        "JSON object mapping prefixes to namespace URIs, e.g. " +
        `'{"rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#", "rdfs": "http://www.w3.org/2000/01/rdf-schema#"}'`),
    query: tool.schema.string().describe("SPARQL query string"),
    owlFile: tool.schema.string().optional().describe(
        "Path to an OWL file for the TBox (loaded locally for DLP; SPARQL endpoint serves as EDB only)"),
    rulesFile: tool.schema.string().optional().describe(
        "Path to an N3 rules file for custom entailment rules"),
    hybridPredicates: tool.schema.string().optional().describe(
        "JSON array of hybrid predicate URIs, e.g. '[\"http://example.org/#prop\"]'"),
    derivedPredicates: tool.schema.string().optional().describe(
        "JSON array of derived predicate URIs, e.g. '[\"https://www.imdb.com/Movie\"]'. " +
        "These are the predicates the reasoner will try to prove via backward chaining. " +
        "Predicates NOT in this list will be queried directly against the SPARQL endpoint."),
  },
  async execute(args, context) {
    const script = path.join(TOOLS_DIR, "sparql-interlocution.py")

    const argsList = [
      String(args.sparqlServiceGraph),
      String(args.nsBindings),
      String(args.query),
      args.owlFile ?? "--",
      args.rulesFile ?? "--",
      args.hybridPredicates ?? "--",
      args.derivedPredicates ?? "--",
    ]

    const useUv = which("uv")
    const commands = useUv
      ? ["uv", "run", "--active", script, ...argsList]
      : ["python3", script, ...argsList]
    const result = await Bun.$`${commands}`.text()
    return result.trim()
  },
})
