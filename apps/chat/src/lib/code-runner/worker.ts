import {
  CodeRunnerResult,
  CodeWorkerEvent,
  CodeWorkerRequest,
  CodeWorkerResult,
} from "./code-runner.interface";
import { safeJsRun } from "./safe-js-run";

// Python execution moved to `/pyodide-runner` (iframe with scoped CSP);
// see `call-worker.ts`. This worker only handles JavaScript now.
self.onmessage = async (event) => {
  const { code, type, timeout = 300000, id } = event.data as CodeWorkerRequest;
  if (type !== "javascript") {
    const errorResult: CodeRunnerResult = {
      success: false,
      error: `Unsupported type in JS worker: ${type}`,
      logs: [
        {
          type: "error",
          args: [
            {
              type: "data",
              value: `Worker only handles javascript; got ${type}`,
            },
          ],
        },
      ],
    };
    const resultEvent: CodeWorkerResult = { id, type: "result", result: errorResult };
    self.postMessage(resultEvent);
    return;
  }

  const result = await safeJsRun({
    code,
    timeout,
    onLog(entry) {
      const logEvent: CodeWorkerEvent = { id, type: "log", entry };
      self.postMessage(logEvent);
    },
  }).catch((error) => {
    const errorResult: CodeRunnerResult = {
      success: false,
      logs: [
        {
          type: "error",
          args: [{ type: "data", value: error.message }],
        },
      ],
      error: error.message,
    };
    return errorResult;
  });

  const resultEvent: CodeWorkerResult = { id, type: "result", result };
  self.postMessage(resultEvent);
};
