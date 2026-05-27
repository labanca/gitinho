"use client";
import { appStore } from "@/app/store";
import useSWR, { SWRConfiguration } from "swr";
import { handleErrorWithToast } from "ui/shared-toast";
import { fetcher, objectFlow } from "lib/utils";
import { AllowedMCPServer, MCPServerInfo } from "app-types/mcp";

export function useMcpList(options?: SWRConfiguration) {
  return useSWR<MCPServerInfo[]>("/api/mcp/list", fetcher, {
    revalidateOnFocus: false,
    errorRetryCount: 0,
    focusThrottleInterval: 1000 * 60 * 5,
    fallbackData: [],
    onError: handleErrorWithToast,
    onSuccess: (data) => {
      const ids = data.map((v) => v.id);
      appStore.setState((prev) => {
        // First-time default: if the user has never touched the toggle
        // (allowedMcpServers === undefined), enable every tool of every
        // server. Once defined — even as `{}` — we respect the user's choices
        // and only prune stale server ids.
        const allowedMcpServers: Record<string, AllowedMCPServer> =
          prev.allowedMcpServers === undefined && data.length > 0
            ? data.reduce(
                (acc, server) => {
                  acc[server.id] = {
                    tools: server.toolInfo.map((t) => t.name),
                  };
                  return acc;
                },
                {} as Record<string, AllowedMCPServer>,
              )
            : objectFlow(prev.allowedMcpServers || {}).filter((_, key) =>
                ids.includes(key),
              );
        return { mcpList: data, allowedMcpServers };
      });
    },
    ...options,
  });
}
