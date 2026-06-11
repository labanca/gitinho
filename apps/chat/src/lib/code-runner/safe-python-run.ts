"use client";

import { safe } from "ts-safe";
import {
  CodeRunnerOptions,
  CodeRunnerResult,
  LogEntry,
} from "./code-runner.interface";

// Add security validations similar to JS

function validateCodeSafety(code: string): string | null {
  if (code.includes("os.system")) return "Forbidden: os.system";
  return null;
}

// Output handlers from reference
export const OUTPUT_HANDLERS = {
  matplotlib: `
    import io
    import base64
    from matplotlib import pyplot as plt

    plt.clf()
    plt.close('all')
    plt.switch_backend('agg')

    def setup_matplotlib_output():
        def custom_show():
            if plt.gcf().get_size_inches().prod() * plt.gcf().dpi ** 2 > 25_000_000:
                print("Warning: Plot size too large, reducing quality")
                plt.gcf().set_dpi(100)

            png_buf = io.BytesIO()
            plt.savefig(png_buf, format='png')
            png_buf.seek(0)
            png_base64 = base64.b64encode(png_buf.read()).decode('utf-8')
            print(f'data:image/png;base64,{png_base64}')
            png_buf.close()

            plt.clf()
            plt.close('all')

        plt.show = custom_show
  `,
  // Always installed. \`display_table\` lets Python emit an interactive
  // table without sending the rows through the LLM as \`createTable\`
  // args — same payload, but the model only generates the call to
  // pythonExecution, not 583 rows of JSON. Matches the matplotlib
  // magic-prefix pattern (\`data:image/png;base64,...\`).
  basic: `
import json as _gitinho_json

def display_table(title, columns, rows, description=None):
    """Render an interactive table (search/sort/export to CSV/XLSX) in the chat UI.

    Args:
        title: string shown above the table.
        columns: list of dicts like {"key": "name", "label": "Name", "type": "string"}.
                 Valid types: "string", "number", "date", "boolean".
        rows: list of dicts whose keys match column "key" values.
        description: optional subtitle.

    Use this INSTEAD of returning data to the model and asking it to
    call createTable, especially for lists > 50 rows. The model only
    has to generate the call to pythonExecution; the rows never go
    through the model's output token budget.
    """
    payload = _gitinho_json.dumps({
        "title": title,
        "description": description,
        "columns": columns,
        "data": rows,
    })
    print(f"[[gitinho:table]]{payload}[[/gitinho:table]]")
    print(f"Rendered interactive table '{title}' with {len(rows)} rows.")
  `,
};

async function ensurePyodideLoaded(): Promise<any> {
  if ((globalThis as any).loadPyodide) {
    return (globalThis as any).loadPyodide;
  }

  const isWorker = typeof (globalThis as any).importScripts !== "undefined";

  if (isWorker) {
    try {
      (globalThis as any).importScripts(
        "https://cdn.jsdelivr.net/pyodide/v0.23.4/full/pyodide.js",
      );
      return (globalThis as any).loadPyodide;
    } catch {
      throw new Error("Failed to load Pyodide script in worker");
    }
  } else {
    const existingScript = document.querySelector<HTMLScriptElement>(
      'script[src="https://cdn.jsdelivr.net/pyodide/v0.23.4/full/pyodide.js"]',
    );

    if (existingScript) {
      if ((globalThis as any).loadPyodide) {
        return (globalThis as any).loadPyodide;
      }
      await new Promise<void>((resolve, reject) => {
        existingScript.addEventListener("load", () => resolve(), {
          once: true,
        });
        existingScript.addEventListener(
          "error",
          () => reject(new Error("Failed to load Pyodide script")),
          { once: true },
        );
      });
    } else {
      await new Promise<void>((resolve, reject) => {
        const script = document.createElement("script");
        script.src = "https://cdn.jsdelivr.net/pyodide/v0.23.4/full/pyodide.js";
        script.async = true;
        script.onload = () => resolve();
        script.onerror = () =>
          reject(new Error("Failed to load Pyodide script"));
        document.head.appendChild(script);
      });
    }
  }

  return (globalThis as any).loadPyodide;
}

function detectRequiredHandlers(code: string): string[] {
  const handlers: string[] = ["basic"];
  if (code.includes("matplotlib") || code.includes("plt.")) {
    handlers.push("matplotlib");
  }
  return handlers;
}

// Cache the Pyodide instance per iframe. Globals defined in one
// `runPythonAsync` call survive into the next, which is what users
// expect from a notebook-style flow ("results = ..." then later
// "for r in results: ..."). The iframe itself is also reused across
// runs by the parent (see call-worker.ts) so this cache persists for
// the chat session's lifetime.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let pyodidePromise: Promise<any> | null = null;

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function getPyodide(): Promise<any> {
  if (!pyodidePromise) {
    pyodidePromise = (async () => {
      const loadPyodide = await ensurePyodideLoaded();
      return loadPyodide({
        indexURL: "https://cdn.jsdelivr.net/pyodide/v0.23.4/full/",
      });
    })();
  }
  return pyodidePromise;
}

export async function safePythonRun({
  code,
  timeout = 30000,
  onLog,
}: CodeRunnerOptions): Promise<CodeRunnerResult> {
  return safe(async () => {
    const startTime = Date.now();
    const logs: LogEntry[] = [];

    const securityError = validateCodeSafety(code);
    if (securityError) throw new Error(securityError);

    const pyodide = await getPyodide();

    // Set up stdout capture
    pyodide.setStdout({
      batched: (output: string) => {
        const trimmed = output.replace(/\n+$/, "");
        const tableMatch = trimmed.match(
          /^\[\[gitinho:table\]\]([\s\S]+)\[\[\/gitinho:table\]\]$/,
        );
        if (tableMatch) {
          try {
            const value = JSON.parse(tableMatch[1]);
            const entry: LogEntry = {
              type: "log",
              args: [{ type: "table", value }],
            };
            logs.push(entry);
            onLog?.(entry);
            return;
          } catch {
            // JSON malformed — fall through, treat as plain stdout so
            // the user sees the garbled prefix and can debug.
          }
        }
        const type = output.startsWith("data:image/png;base64")
          ? "image"
          : "data";
        logs.push({ type: "log", args: [{ type, value: output }] });
        onLog?.({ type: "log", args: [{ type, value: output }] });
      },
    });
    pyodide.setStderr({
      batched: (output: string) => {
        logs.push({ type: "error", args: [{ type: "data", value: output }] });
        onLog?.({ type: "error", args: [{ type: "data", value: output }] });
      },
    });

    // Load packages and handlers
    await pyodide.loadPackagesFromImports(code);
    const requiredHandlers = detectRequiredHandlers(code);
    for (const handler of requiredHandlers) {
      await pyodide.runPythonAsync(
        OUTPUT_HANDLERS[handler as keyof typeof OUTPUT_HANDLERS],
      );
      if (handler === "matplotlib") {
        await pyodide.runPythonAsync("setup_matplotlib_output()");
      }
    }

    // Execute code with timeout
    const execution = pyodide.runPythonAsync(code);
    const timer = new Promise((_, reject) =>
      setTimeout(() => reject(new Error("Timeout")), timeout),
    );
    const returnValue = await Promise.race([execution, timer]);

    return {
      success: true,
      logs,
      executionTimeMs: Date.now() - startTime,
      result: returnValue,
    } as CodeRunnerResult;
  })
    .ifFail((err) => ({
      success: false,
      error: err.message,
      logs: [],
      solution: "Python execution failed. Check syntax, imports, or timeout.",
    }))
    .unwrap();
}
