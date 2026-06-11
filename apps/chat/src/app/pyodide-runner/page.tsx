import RunnerClient from "./runner-client";

// Hidden Pyodide host. The main app embeds this page in an off-screen
// iframe and talks to it via postMessage. Lives at its own route so we
// can serve a relaxed Content-Security-Policy (blob: workers, WASM eval,
// jsDelivr) scoped to this route only — the rest of the app keeps the
// strict CSP. See `next.config.ts` for the per-source headers and
// `lib/code-runner/call-worker.ts` for the parent-side protocol.

export const dynamic = "force-static";

export default function PyodideRunnerPage() {
  return <RunnerClient />;
}
