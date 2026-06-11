"use client";

import { useEffect } from "react";
import { safePythonRun } from "lib/code-runner/safe-python-run";
import type { CodeRunnerResult, LogEntry } from "lib/code-runner/code-runner.interface";

type RunMessage = {
  type: "run";
  id: string;
  code: string;
  timeout?: number;
};

type LogMessage = { type: "log"; id: string; log: LogEntry };
type ResultMessage = { type: "result"; id: string; result: CodeRunnerResult };
type ReadyMessage = { type: "ready" };

type OutboundMessage = LogMessage | ResultMessage | ReadyMessage;

function isRunMessage(value: unknown): value is RunMessage {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return (
    v.type === "run" &&
    typeof v.id === "string" &&
    typeof v.code === "string" &&
    (v.timeout === undefined || typeof v.timeout === "number")
  );
}

export default function RunnerClient() {
  useEffect(() => {
    if (typeof window === "undefined") return;
    // If somebody opens /pyodide-runner directly (no parent), do nothing.
    if (window.parent === window) return;

    const origin = window.location.origin;
    const parent = window.parent;

    const post = (msg: OutboundMessage) => parent.postMessage(msg, origin);

    post({ type: "ready" });

    const onMessage = async (event: MessageEvent) => {
      if (event.origin !== origin) return;
      if (event.source !== parent) return;
      if (!isRunMessage(event.data)) return;

      const { id, code, timeout } = event.data;
      try {
        const result = await safePythonRun({
          code,
          timeout,
          onLog: (log) => post({ type: "log", id, log }),
        });
        post({ type: "result", id, result });
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        post({
          type: "result",
          id,
          result: {
            success: false,
            error: message,
            logs: [],
            solution: "Pyodide runner threw an unexpected error.",
          } as CodeRunnerResult,
        });
      }
    };

    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, []);

  return null;
}
