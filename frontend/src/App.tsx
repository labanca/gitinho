import { useEffect, useState } from "react";
import { Navigate, Route, Routes, useNavigate, useParams } from "react-router-dom";
import { api, type MeResponse } from "./api";
import Sidebar from "./components/Sidebar";
import ChatView from "./components/ChatView";
import LoginScreen from "./components/LoginScreen";

export default function App() {
  const [me, setMe] = useState<MeResponse | null>(null);

  useEffect(() => {
    api.me().then(setMe);
  }, []);

  if (me === null) {
    return <div className="loading">Carregando…</div>;
  }
  if (!me.authenticated) {
    return <LoginScreen />;
  }

  return (
    <div className="app">
      <Routes>
        <Route path="/" element={<Home user={me.user!} />} />
        <Route path="/c/:chatId" element={<ChatRoute user={me.user!} />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </div>
  );
}

function Home({ user }: { user: NonNullable<MeResponse["user"]> }) {
  const nav = useNavigate();
  async function startNew() {
    const chat = await api.createChat("Nova conversa");
    nav(`/c/${chat.id}`);
  }
  return (
    <div className="layout">
      <Sidebar user={user} />
      <main className="main empty">
        <div className="empty-inner">
          <h1>Gitinho</h1>
          <p>
            Agente conversacional para sua organização do GitHub. Selecione uma
            conversa ou inicie uma nova.
          </p>
          <button className="btn-primary" onClick={startNew}>
            Iniciar conversa
          </button>
        </div>
      </main>
    </div>
  );
}

function ChatRoute({ user }: { user: NonNullable<MeResponse["user"]> }) {
  const { chatId } = useParams();
  if (!chatId) return <Navigate to="/" replace />;
  return (
    <div className="layout">
      <Sidebar user={user} activeChatId={chatId} />
      <ChatView chatId={chatId} />
    </div>
  );
}
