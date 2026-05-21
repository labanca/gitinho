/** API helpers shared across the UI. */

function csrfToken(): string {
  const m = document.cookie.match(/(?:^|; )gitinho_csrf=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : "";
}

async function request<T>(
  url: string,
  init: RequestInit = {},
): Promise<T> {
  const method = (init.method || "GET").toUpperCase();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init.headers as Record<string, string> | undefined),
  };
  if (["POST", "PUT", "PATCH", "DELETE"].includes(method)) {
    headers["X-CSRF-Token"] = csrfToken();
  }
  const resp = await fetch(url, {
    credentials: "include",
    ...init,
    headers,
  });
  if (!resp.ok) {
    throw new Error(`${method} ${url} failed: ${resp.status}`);
  }
  if (resp.status === 204) return undefined as unknown as T;
  return (await resp.json()) as T;
}

export interface MeResponse {
  authenticated: boolean;
  user?: { id: string; login: string; avatar_url: string | null };
}

export interface Chat {
  id: string;
  title: string;
  org: string;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "tool" | "system";
  content: string;
  tool_calls: Array<{ name: string; status: string }>;
  created_at: string;
}

export const api = {
  me: () => request<MeResponse>("/auth/me").catch(() => ({ authenticated: false })),
  listChats: () => request<Chat[]>("/api/chats"),
  createChat: (title: string) =>
    request<Chat>("/api/chats", {
      method: "POST",
      body: JSON.stringify({ title }),
    }),
  patchChat: (id: string, body: { title?: string; archived?: boolean }) =>
    request<Chat>(`/api/chats/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  listMessages: (chatId: string) =>
    request<ChatMessage[]>(`/api/chats/${chatId}/messages`),
  postMessage: (chatId: string, content: string) =>
    request<{ id: string }>(`/api/chats/${chatId}/messages`, {
      method: "POST",
      body: JSON.stringify({ content }),
    }),
  exportUrl: (id: string) => `/api/exports/${id}`,
  logout: () =>
    request<{ ok: true }>("/auth/logout", { method: "POST" }),
};
