import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type Chat, type MeResponse } from "../api";

export default function Sidebar({
  user,
  activeChatId,
}: {
  user: NonNullable<MeResponse["user"]>;
  activeChatId?: string;
}) {
  const [chats, setChats] = useState<Chat[]>([]);
  const nav = useNavigate();

  async function refresh() {
    const list = await api.listChats();
    setChats(list);
  }
  useEffect(() => {
    refresh();
  }, [activeChatId]);

  async function startNew() {
    const chat = await api.createChat("Nova conversa");
    await refresh();
    nav(`/c/${chat.id}`);
  }

  async function logout() {
    await api.logout();
    window.location.href = "/";
  }

  return (
    <aside className="sidebar">
      <button className="new-chat" onClick={startNew}>
        + Nova conversa
      </button>
      <nav className="chat-list">
        {chats
          .filter((c) => !c.archived_at)
          .map((c) => (
            <Link
              key={c.id}
              className={`chat-item ${c.id === activeChatId ? "active" : ""}`}
              to={`/c/${c.id}`}
              title={c.title}
            >
              {c.title}
            </Link>
          ))}
      </nav>
      <footer className="sidebar-footer">
        <div className="user-pill">
          {user.avatar_url && <img src={user.avatar_url} alt="" />}
          <span>{user.login}</span>
        </div>
        <button className="link" onClick={logout}>
          Sair
        </button>
      </footer>
    </aside>
  );
}
