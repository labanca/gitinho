import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, type ChatMessage } from "../api";

interface DisplayMessage {
  id: string;
  role: ChatMessage["role"];
  content: string;
  tool_calls?: Array<{ name: string; status: string }>;
  exports?: Array<{ id: string; filename: string; rows?: number | null }>;
}

export default function ChatView({ chatId }: { chatId: string }) {
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    void load();
  }, [chatId]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function load() {
    const rows = await api.listMessages(chatId);
    setMessages(
      rows.map((m) => ({
        id: m.id,
        role: m.role,
        content: m.content,
        tool_calls: m.tool_calls,
      })),
    );
  }

  async function send() {
    const content = input.trim();
    if (!content || streaming) return;
    setInput("");
    const userMsg: DisplayMessage = {
      id: `tmp-${Date.now()}`,
      role: "user",
      content,
    };
    setMessages((m) => [...m, userMsg]);

    await api.postMessage(chatId, content);

    const assistant: DisplayMessage = {
      id: `live-${Date.now()}`,
      role: "assistant",
      content: "",
      tool_calls: [],
      exports: [],
    };
    setMessages((m) => [...m, assistant]);
    setStreaming(true);

    const es = new EventSource(`/api/chats/${chatId}/stream`, {
      withCredentials: true,
    } as EventSourceInit);

    es.addEventListener("token", (e) => {
      const { text } = JSON.parse((e as MessageEvent).data);
      setMessages((m) => {
        const copy = [...m];
        const last = copy[copy.length - 1];
        copy[copy.length - 1] = { ...last, content: last.content + text };
        return copy;
      });
    });

    es.addEventListener("tool_call", (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      setMessages((m) => {
        const copy = [...m];
        const last = copy[copy.length - 1];
        copy[copy.length - 1] = {
          ...last,
          tool_calls: [...(last.tool_calls || []), data],
        };
        return copy;
      });
    });

    es.addEventListener("export", (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      setMessages((m) => {
        const copy = [...m];
        const last = copy[copy.length - 1];
        copy[copy.length - 1] = {
          ...last,
          exports: [...(last.exports || []), data],
        };
        return copy;
      });
    });

    es.addEventListener("done", () => {
      es.close();
      setStreaming(false);
      void load();
    });

    es.addEventListener("error", () => {
      es.close();
      setStreaming(false);
    });
  }

  return (
    <main className="main chat-main">
      <div className="messages">
        {messages.length === 0 && (
          <div className="welcome">
            Faça uma pergunta sobre a organização. Por exemplo:
            <ul>
              <li>Quantos PRs abertos temos?</li>
              <li>Qual o último commit do usuário fulano?</li>
              <li>Gere uma planilha com todos os repositórios.</li>
            </ul>
          </div>
        )}
        {messages.map((m) => (
          <MessageBubble key={m.id} message={m} />
        ))}
        <div ref={endRef} />
      </div>
      <form
        className="composer"
        onSubmit={(e) => {
          e.preventDefault();
          void send();
        }}
      >
        <textarea
          rows={2}
          placeholder="Pergunte algo sobre a organização…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void send();
            }
          }}
          disabled={streaming}
        />
        <button type="submit" disabled={streaming || !input.trim()}>
          {streaming ? "Pensando…" : "Enviar"}
        </button>
      </form>
    </main>
  );
}

function MessageBubble({ message }: { message: DisplayMessage }) {
  return (
    <div className={`bubble ${message.role}`}>
      <div className="bubble-role">
        {message.role === "user" ? "Você" : "Gitinho"}
      </div>
      {message.tool_calls && message.tool_calls.length > 0 && (
        <div className="tool-trace">
          {message.tool_calls.map((tc, i) => (
            <span key={i} className={`tool-chip ${tc.status}`}>
              🔧 {tc.name}
            </span>
          ))}
        </div>
      )}
      <div className="bubble-content">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>
          {message.content || (message.role === "assistant" ? "▍" : "")}
        </ReactMarkdown>
      </div>
      {message.exports && message.exports.length > 0 && (
        <div className="exports">
          {message.exports.map((e) => (
            <a
              key={e.id}
              href={api.exportUrl(e.id)}
              className="export-link"
              download
            >
              ⬇ Baixar {e.filename}
              {e.rows != null && ` (${e.rows} linhas)`}
            </a>
          ))}
        </div>
      )}
    </div>
  );
}
