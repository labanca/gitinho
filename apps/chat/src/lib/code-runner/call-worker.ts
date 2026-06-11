"use client";
import { createDebounce, generateUUID } from "lib/utils";
import {
  CodeRunnerOptions,
  CodeRunnerResult,
  CodeWorkerRequest,
  CodeWorkerResponse,
} from "./code-runner.interface";

export function callCodeRunWorker(
  type: "javascript" | "python",
  option: CodeRunnerOptions,
): Promise<CodeRunnerResult> {
  if (type === "python") return runPythonInIframe(option);
  return runJavascriptInWorker(option);
}

// Pyodide needs blob: workers and WASM eval, both blocked by the main
// app's strict CSP. We host it inside `/pyodide-runner`, which has a
// scoped relaxed CSP (see `next.config.ts`). The iframe is same-origin,
// so session cookies travel with it and the user's Python can still
// call `/api/gh-proxy/...`.
//
// The iframe is a singleton per page so Python globals persist between
// code cells (matches notebook-style expectations from the chat agent).
// First call boots Pyodide (~3s), subsequent calls reuse the same
// interpreter. On timeout we tear down the iframe — we can't trust the
// runaway code stopped, so the next call rebuilds from scratch.

let iframeSingleton: HTMLIFrameElement | null = null;
let readyPromise: Promise<HTMLIFrameElement> | null = null;

function ensureIframe(): Promise<HTMLIFrameElement> {
  if (
    iframeSingleton &&
    iframeSingleton.parentNode &&
    iframeSingleton.contentWindow
  ) {
    return readyPromise!;
  }
  // Stale handle (hot reload, removed from DOM, etc.) — rebuild.
  destroyIframe();

  const origin = window.location.origin;
  const iframe = document.createElement("iframe");
  iframe.src = "/pyodide-runner";
  iframe.style.display = "none";
  iframe.setAttribute("aria-hidden", "true");
  iframe.title = "pyodide-runner";

  iframeSingleton = iframe;
  readyPromise = new Promise<HTMLIFrameElement>((resolve) => {
    const onReady = (event: MessageEvent) => {
      if (event.origin !== origin) return;
      if (event.source !== iframe.contentWindow) return;
      if (
        !event.data ||
        typeof event.data !== "object" ||
        (event.data as { type?: string }).type !== "ready"
      )
        return;
      window.removeEventListener("message", onReady);
      resolve(iframe);
    };
    window.addEventListener("message", onReady);
    document.body.appendChild(iframe);
  });
  return readyPromise;
}

function destroyIframe() {
  if (iframeSingleton?.parentNode) iframeSingleton.remove();
  iframeSingleton = null;
  readyPromise = null;
}

function runPythonInIframe(
  option: CodeRunnerOptions,
): Promise<CodeRunnerResult> {
  return new Promise((resolve) => {
    const id = generateUUID();
    const origin = window.location.origin;

    let settled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let iframeRef: HTMLIFrameElement | null = null;

    const cleanup = () => {
      window.removeEventListener("message", onMessage);
      if (timer) clearTimeout(timer);
    };

    const settle = (result: CodeRunnerResult, killIframe = false) => {
      if (settled) return;
      settled = true;
      resolve(result);
      cleanup();
      if (killIframe) destroyIframe();
    };

    function onMessage(event: MessageEvent) {
      if (event.origin !== origin) return;
      if (!iframeRef) return;
      if (event.source !== iframeRef.contentWindow) return;
      const data = event.data as
        | { type: "ready" }
        | { type: "log"; id: string; log: CodeRunnerResult["logs"][number] }
        | { type: "result"; id: string; result: CodeRunnerResult }
        | undefined;
      if (!data || typeof data !== "object") return;
      if (!("id" in data) || data.id !== id) return;
      if (data.type === "log") {
        option.onLog?.(data.log);
      } else if (data.type === "result") {
        settle(data.result);
      }
    }

    window.addEventListener("message", onMessage);

    ensureIframe()
      .then((iframe) => {
        if (settled) return;
        iframeRef = iframe;
        iframe.contentWindow?.postMessage(
          { type: "run", id, code: option.code, timeout: option.timeout },
          origin,
        );
      })
      .catch((err) => {
        settle({
          success: false,
          logs: [
            {
              type: "error",
              args: [
                {
                  type: "data",
                  value: err instanceof Error ? err.message : String(err),
                },
              ],
            },
          ],
          error: err instanceof Error ? err.message : String(err),
        });
      });

    timer = setTimeout(() => {
      settle(
        {
          success: false,
          logs: [
            {
              type: "error",
              args: [
                {
                  type: "data",
                  value: JSON.stringify({ type: "error", message: "Timeout" }),
                },
              ],
            },
          ],
          error: "Timeout",
        },
        true,
      );
    }, option.timeout || 40000);
  });
}

function runJavascriptInWorker(
  option: CodeRunnerOptions,
): Promise<CodeRunnerResult> {
  let tk: NodeJS.Timeout;
  const terminateDebounce = createDebounce();
  const terminate = () => {
    terminateDebounce(() => {
      worker.terminate();
    }, 5000);
  };
  let isWorking = true;
  const worker = new Worker(new URL("./worker.ts", import.meta.url));
  const promise = new Promise<CodeRunnerResult>((resolve) => {
    const id = generateUUID();
    const request: CodeWorkerRequest = {
      id,
      type: "javascript",
      code: option.code,
      timeout: option.timeout,
    };
    setTimeout(() => {
      worker.postMessage(request);
    }, 1000); // for boot-up effect
    worker.onmessage = (event) => {
      const response = event.data as CodeWorkerResponse;
      if (response.id !== id) return;
      if (response.type === "log") {
        option.onLog?.(response.entry);
        if (!isWorking) terminate();
      } else {
        resolve(response.result as CodeRunnerResult);
        clearTimeout(tk);
        terminate();
      }
    };
  });

  const race = Promise.race([
    promise,
    new Promise<CodeRunnerResult>((timeout) => {
      tk = setTimeout(() => {
        const errorResult: CodeRunnerResult = {
          success: false,
          logs: [
            {
              type: "error",
              args: [
                {
                  type: "data",
                  value: JSON.stringify({
                    type: "error",
                    message: "Timeout",
                  }),
                },
              ],
            },
          ],
          error: "Timeout",
        };
        timeout(errorResult);
        terminate();
      }, option.timeout || 40000);
    }),
  ]);

  return race.finally(() => {
    isWorking = false;
  });
}
