"use client";

import { useState } from "react";
import { callCodeRunWorker } from "lib/code-runner/call-worker";
import type {
  CodeRunnerResult,
  LogEntry,
} from "lib/code-runner/code-runner.interface";

type StepStatus = "pending" | "running" | "passed" | "failed";

type Step = {
  id: string;
  name: string;
  description: string;
  buildCode: (org: string) => string;
  status: StepStatus;
  result?: CodeRunnerResult;
  durationMs?: number;
};

const STEPS: Omit<Step, "status">[] = [
  {
    id: "load",
    name: "Pyodide load + basic exec",
    description:
      "Carrega o iframe /pyodide-runner sob o CSP escopado e executa Python básico. Falha aqui = CSP do runner ainda bloqueia algo (script-src, worker-src ou wasm-unsafe-eval).",
    buildCode: () => `
import sys
print(f"Python {sys.version.split()[0]} pronto")
print(f"1 + 1 = {1 + 1}")
"hello"
`.trim(),
  },
  {
    id: "proxy",
    name: "pyfetch → /api/gh-proxy",
    description:
      "Chama /api/gh-proxy/orgs/<org> de dentro do iframe via pyfetch. Falha aqui = cookie de sessão não chegou no iframe, ou o proxy/GitHub App está mal configurado.",
    buildCode: (org) => `
from pyodide.http import pyfetch
import json
resp = await pyfetch("/api/gh-proxy/orgs/${org}")
print(f"status: {resp.status}")
body = await resp.string()
if not (200 <= resp.status < 300):
    raise RuntimeError(f"proxy retornou {resp.status}: {body[:300]}")
data = json.loads(body)
login = data.get('login')
public_repos = data.get('public_repos')
print(f"login: {login}")
print(f"public_repos: {public_repos}")
`.trim(),
  },
  {
    id: "no-direct-github",
    name: "CSP bloqueia api.github.com direto",
    description:
      "Defesa em profundidade: o user code não consegue bypassar o proxy. O fetch direto deve estourar exception (CSP do runner não inclui api.github.com em connect-src). Step passa se a exception veio.",
    buildCode: (org) => `
from pyodide.http import pyfetch
try:
    resp = await pyfetch("https://api.github.com/orgs/${org}")
    raise RuntimeError(f"CSP NAO bloqueou: status {resp.status}")
except RuntimeError:
    raise
except Exception as exc:
    name = type(exc).__name__
    msg = str(exc)[:200]
    print(f"bloqueado como esperado: {name}: {msg}")
`.trim(),
  },
];

export default function PyodideSmokeTest({ org }: { org: string }) {
  const [steps, setSteps] = useState<Step[]>(() =>
    STEPS.map((s) => ({ ...s, status: "pending" as const })),
  );
  const [running, setRunning] = useState(false);

  const patch = (id: string, change: Partial<Step>) =>
    setSteps((prev) =>
      prev.map((s) => (s.id === id ? { ...s, ...change } : s)),
    );

  async function runOne(step: Step): Promise<boolean> {
    patch(step.id, { status: "running", result: undefined, durationMs: undefined });
    const start = Date.now();
    const result = await callCodeRunWorker("python", {
      code: step.buildCode(org),
      timeout: 90_000,
    });
    const durationMs = Date.now() - start;
    patch(step.id, {
      status: result.success ? "passed" : "failed",
      result,
      durationMs,
    });
    return result.success;
  }

  async function runAll() {
    if (running) return;
    setRunning(true);
    setSteps((prev) =>
      prev.map((s) => ({
        ...s,
        status: "pending",
        result: undefined,
        durationMs: undefined,
      })),
    );
    try {
      for (const step of steps) {
        const ok = await runOne(step);
        if (!ok) break;
      }
    } finally {
      setRunning(false);
    }
  }

  const allPassed = steps.every((s) => s.status === "passed");
  const anyFailed = steps.some((s) => s.status === "failed");

  return (
    <main
      style={{
        maxWidth: 920,
        margin: "32px auto",
        padding: 24,
        fontFamily: "ui-sans-serif, system-ui, sans-serif",
        color: "#111",
        background: "#fff",
      }}
    >
      <header style={{ marginBottom: 24 }}>
        <h1 style={{ margin: 0, fontSize: 24 }}>Pyodide smoke test</h1>
        <p style={{ color: "#555", marginTop: 4 }}>
          Org alvo: <code>{org}</code>. Cada execução cria um iframe limpo —
          esperado ~30s na primeira etapa (carga do Pyodide) e poucos segundos
          nas seguintes.
        </p>
      </header>

      <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
        <button
          onClick={runAll}
          disabled={running}
          style={{
            padding: "10px 18px",
            fontSize: 14,
            fontWeight: 600,
            border: "1px solid #111",
            borderRadius: 6,
            background: running ? "#eee" : "#111",
            color: running ? "#666" : "#fff",
            cursor: running ? "not-allowed" : "pointer",
          }}
        >
          {running ? "Rodando…" : "Rodar tudo"}
        </button>
        {!running && allPassed && (
          <span style={{ color: "#0a7a30", fontWeight: 600 }}>
            ✅ Tudo verde — Pyodide + proxy operando.
          </span>
        )}
        {!running && anyFailed && (
          <span style={{ color: "#b91c1c", fontWeight: 600 }}>
            ❌ Alguma etapa falhou — veja detalhes abaixo.
          </span>
        )}
      </div>

      <ol
        style={{
          listStyle: "none",
          padding: 0,
          marginTop: 24,
          display: "flex",
          flexDirection: "column",
          gap: 16,
        }}
      >
        {steps.map((step, idx) => (
          <li key={step.id}>
            <StepCard step={step} index={idx + 1} />
          </li>
        ))}
      </ol>
    </main>
  );
}

function statusIcon(status: StepStatus): string {
  switch (status) {
    case "passed":
      return "✅";
    case "failed":
      return "❌";
    case "running":
      return "⏳";
    default:
      return "·";
  }
}

function StepCard({ step, index }: { step: Step; index: number }) {
  const borderColor =
    step.status === "passed"
      ? "#0a7a30"
      : step.status === "failed"
        ? "#b91c1c"
        : step.status === "running"
          ? "#1d4ed8"
          : "#d4d4d4";
  return (
    <div
      style={{
        border: `1px solid ${borderColor}`,
        borderRadius: 8,
        padding: 16,
        background: "#fafafa",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          gap: 16,
          alignItems: "baseline",
        }}
      >
        <h3 style={{ margin: 0, fontSize: 16 }}>
          {statusIcon(step.status)} {index}. {step.name}
        </h3>
        {step.durationMs != null && (
          <span style={{ fontSize: 12, color: "#666" }}>
            {(step.durationMs / 1000).toFixed(1)}s
          </span>
        )}
      </div>
      <p style={{ color: "#555", marginTop: 6, marginBottom: 0, fontSize: 13 }}>
        {step.description}
      </p>
      {step.result && <ResultBox result={step.result} />}
    </div>
  );
}

function ResultBox({ result }: { result: CodeRunnerResult }) {
  return (
    <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 8 }}>
      {result.error && (
        <pre
          style={{
            background: "#fee2e2",
            color: "#7f1d1d",
            padding: 10,
            borderRadius: 4,
            overflowX: "auto",
            fontSize: 12,
            margin: 0,
          }}
        >
          {result.error}
        </pre>
      )}
      {result.logs.length > 0 && (
        <pre
          style={{
            background: "#f4f4f5",
            color: "#27272a",
            padding: 10,
            borderRadius: 4,
            overflowX: "auto",
            fontSize: 12,
            margin: 0,
            whiteSpace: "pre-wrap",
          }}
        >
          {result.logs.map(logToText).join("")}
        </pre>
      )}
    </div>
  );
}

function logToText(log: LogEntry): string {
  const text = log.args
    .map((a) => (a.type === "data" ? String(a.value) : "[image]"))
    .join(" ");
  const prefix = log.type === "error" ? "stderr: " : "";
  return `${prefix}${text}\n`;
}
