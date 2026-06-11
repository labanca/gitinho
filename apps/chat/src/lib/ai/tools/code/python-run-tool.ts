import { JSONSchema7 } from "json-schema";
import { tool as createTool } from "ai";
import { jsonSchemaToZod } from "lib/json-schema-to-zod";

export const pythonExecutionSchema: JSONSchema7 = {
  type: "object",
  properties: {
    code: {
      type: "string",
      description: `Execute Python code in the user's browser via Pyodide. State persists between calls in the same chat session.\n\nNetwork: use pyodide.http.pyfetch and the chat's /api/gh-proxy (allowlist: /repos/<org>/... and /orgs/<org>/...). NEVER call api.github.com or raw.githubusercontent.com directly — both are blocked by CSP.\n\nExample:\nfrom pyodide.http import pyfetch\nimport json\nresp = await pyfetch("/api/gh-proxy/orgs/splor-mg/repos?per_page=100")\nrepos = json.loads(await resp.string())\n\nRendering tables: for any listing > ~50 rows, call display_table(title, columns, rows, description=None) — it prints a special marker that the UI renders as the same interactive table component as createTable (search, sort, CSV/XLSX export) without making the model re-emit each row as tool args.\n\nExample:\ndisplay_table("Repos", [{"key":"name","label":"Nome","type":"string"}], [{"name":"x"}, {"name":"y"}])`,
    },
  },
  required: ["code"],
};

export const pythonExecutionTool = createTool({
  description:
    "Execute Python code in the user's browser via Pyodide. Use pyfetch + /api/gh-proxy for GitHub data. For listings > 50 rows, use display_table() instead of createTable to avoid generating every row as tool args.",
  inputSchema: jsonSchemaToZod(pythonExecutionSchema),
});
