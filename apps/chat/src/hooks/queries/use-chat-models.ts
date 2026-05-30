import { appStore } from "@/app/store";
import { fetcher } from "lib/utils";
import useSWR, { SWRConfiguration } from "swr";

export const useChatModels = (options?: SWRConfiguration) => {
  return useSWR<
    {
      provider: string;
      hasAPIKey: boolean;
      models: {
        name: string;
        isToolCallUnsupported: boolean;
        isImageInputUnsupported: boolean;
        supportedFileMimeTypes: string[];
      }[];
    }[]
  >("/api/chat/models", fetcher, {
    dedupingInterval: 60_000 * 5,
    revalidateOnFocus: false,
    fallbackData: [],
    onSuccess: (data) => {
      const status = appStore.getState();
      if (status.chatModel) return;
      // Prefer Claude Sonnet 4.6 (via Anthropic / Foundry passthrough) when
      // available — it's the right baseline for tool orchestration. Falls
      // back to "first usable model from first provider" only if Sonnet
      // 4.6 isn't reachable (no ANTHROPIC_API_KEY, model not registered).
      // Mirrors fallbackModel in lib/ai/models.ts.
      const anthropic = data.find(
        (p) => p.provider === "anthropic" && p.hasAPIKey,
      );
      const sonnet46 = anthropic?.models.find((m) => m.name === "sonnet-4.6");
      if (sonnet46) {
        appStore.setState({
          chatModel: { provider: "anthropic", model: sonnet46.name },
        });
        return;
      }
      const firstProvider = data[0].provider;
      const model = data[0].models[0].name;
      appStore.setState({ chatModel: { provider: firstProvider, model } });
    },
    ...options,
  });
};
