import { useEffect, useRef, useState } from "react";
import {
  NavLink,
  Outlet,
  Link,
  useLocation,
  useNavigate,
} from "react-router-dom";
import {
  Activity,
  BookOpen,
  ChevronRight,
  FileCheck2,
  FileText,
  LayoutDashboard,
  Library,
  Menu,
  MessageSquare,
  Moon,
  Network,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  Sun,
} from "lucide-react";
import { useAPI } from "../api";
import { useAuth, canReview } from "../auth";
import type { Page } from "../types";
import { Badge, Empty, ErrorBanner, Loading, Modal, labels } from "./common";

export function Mark({ small = false }: { small?: boolean }) {
  return (
    <span className={`brand-mark ${small ? "small" : ""}`}>
      <svg viewBox="0 0 40 40" fill="none" aria-hidden="true">
        <path
          d="m7 13 6 16 7-11 7 11 6-16"
          stroke="currentColor"
          strokeWidth="3.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </span>
  );
}
export const navigation = [
  { to: "/", label: "Обзор", icon: LayoutDashboard, exact: true },
  { to: "/pages", label: "База знаний", icon: BookOpen },
  { to: "/rules", label: "Правила", icon: ShieldCheck },
  { to: "/chat", label: "Чат с агентом", icon: MessageSquare },
  { to: "/proposals", label: "Ревью", icon: FileCheck2 },
  { to: "/sources", label: "Источники", icon: Library },
  { to: "/graph", label: "Граф знаний", icon: Network },
  { to: "/policies", label: "Инструкции", icon: FileText },
  { to: "/jobs", label: "Задачи", icon: Activity },
];
export function SearchDialog({ onClose }: { onClose: () => void }) {
  const [text, setText] = useState(""),
    [query, setQuery] = useState(""),
    [selected, setSelected] = useState(0);
  const navigate = useNavigate();
  useEffect(() => {
    const timeout = setTimeout(() => {
      setQuery(text);
      setSelected(0);
    }, 200);
    return () => clearTimeout(timeout);
  }, [text]);
  const result = useAPI<{ results: Page[] }>(
    `/search?q=${encodeURIComponent(query)}&k=20&expand=true`,
    false,
    !!query.trim(),
  );
  const rows = result.data?.results || [];
  const open = (id: string) => {
    navigate(`/pages/${id}`);
    onClose();
  };
  return (
    <Modal title="Поиск по знаниям" onClose={onClose}>
      <div className="command-input">
        <Search size={22} />
        <input
          autoFocus
          placeholder="Правило, решение, технология…"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setSelected((i) => Math.min(i + 1, rows.length - 1));
            }
            if (e.key === "ArrowUp") {
              e.preventDefault();
              setSelected((i) => Math.max(0, i - 1));
            }
            if (e.key === "Enter" && rows[selected]) open(rows[selected].id);
          }}
        />
      </div>
      <div className="command-results">
        <ErrorBanner error={result.error} />
        {result.isFetching ? (
          <Loading lines={3} />
        ) : rows.length ? (
          rows.map((page, i) => (
            <button
              className={`command-result ${i === selected ? "selected" : ""}`}
              key={page.id}
              onClick={() => open(page.id)}
              onMouseEnter={() => setSelected(i)}
            >
              <FileText size={18} />
              <div>
                <strong>{page.title}</strong>
                <p>{page.summary}</p>
              </div>
              <Badge value={page.type} />
              <ChevronRight size={15} />
            </button>
          ))
        ) : (
          <Empty
            icon={Search}
            title={query ? "Ничего не найдено" : "Что найдём?"}
            text={
              query
                ? "Попробуйте другое слово или более короткий запрос."
                : "Ищите по заголовкам и содержимому страниц."
            }
          />
        )}
      </div>
      <div className="command-footer">
        <span>
          <kbd>↑</kbd>
          <kbd>↓</kbd> выбрать
        </span>
        <span>
          <kbd>↵</kbd> открыть
        </span>
        <span>
          <kbd>esc</kbd> закрыть
        </span>
      </div>
    </Modal>
  );
}
export default function Layout() {
  const { actor } = useAuth(),
    location = useLocation(),
    [search, setSearch] = useState(false),
    [mobile, setMobile] = useState(false);
  const [theme, setTheme] = useState(
    localStorage.getItem("wiki.theme") || "light",
  );
  const inbox = useAPI<{ proposals: number; open_findings: number }>(
    "/inbox",
    false,
    canReview(actor),
    60000,
  );
  const health = useAPI<{ version: string }>("/health", false, true, 30000);
  const main = useRef<HTMLElement>(null);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("wiki.theme", theme);
  }, [theme]);
  useEffect(() => {
    setMobile(false);
    main.current?.scrollTo(0, 0);
  }, [location.pathname]);
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setSearch((v) => !v);
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);
  const current = navigation.find((n) =>
    n.to === "/"
      ? location.pathname === "/"
      : location.pathname.startsWith(n.to),
  );
  return (
    <div className="app-shell">
      <a className="skip-link" href="#content">
        Перейти к содержимому
      </a>
      {mobile && (
        <button
          className="sidebar-overlay"
          aria-label="Закрыть навигацию"
          onClick={() => setMobile(false)}
        />
      )}
      <aside className={`sidebar ${mobile ? "open" : ""}`}>
        <Link className="brand" to="/">
          <Mark />
          <span>
            wiki<span className="brand-dot">.</span>
          </span>
          <small>workspace</small>
        </Link>
        <div className="workspace-label">
          <span className="workspace-avatar">W</span>
          <div>
            <strong>Знания команды</strong>
            <small>Общее пространство</small>
          </div>
        </div>
        <button className="sidebar-search" onClick={() => setSearch(true)}>
          <Search size={16} />
          <span>Найти что-нибудь</span>
          <kbd>⌘ K</kbd>
        </button>
        <div className="nav-label">ПРОСТРАНСТВО</div>
        <nav aria-label="Основная навигация">
          {navigation.map(({ to, label, icon: Icon, exact }, i) => (
            <NavLink
              key={to}
              to={to}
              end={exact}
              className={({ isActive }) =>
                `nav-item ${isActive ? "active" : ""} ${i === 6 ? "nav-divider" : ""}`
              }
            >
              <Icon size={18} />
              <span>{label}</span>
              {to === "/proposals" && !!inbox.data?.proposals && (
                <span className="nav-count">{inbox.data.proposals}</span>
              )}
              {to === "/chat" && <Sparkles size={13} className="nav-spark" />}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="system-status">
            <i className={health.error ? "offline" : ""} />
            <span>{health.error ? "Нет связи с вики" : "Вики на связи"}</span>
            <small>{health.data?.version}</small>
          </div>
          <NavLink to="/settings" className="user-panel">
            <span className="avatar">
              {(actor?.person || actor?.name || "U").slice(0, 1).toUpperCase()}
            </span>
            <div>
              <strong>{actor?.person || actor?.name}</strong>
              <small>{labels[actor?.role || ""]}</small>
            </div>
            <Settings size={17} />
          </NavLink>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <button
            className="icon-button mobile-menu"
            aria-label="Открыть навигацию"
            onClick={() => setMobile(true)}
          >
            <Menu size={21} />
          </button>
          <div className="breadcrumbs">
            <span>Пространство</span>
            <ChevronRight size={13} />
            <strong>{current?.label || "Настройки"}</strong>
          </div>
          <div className="topbar-actions">
            <span className="private-label">
              <ShieldCheck size={14} /> Ваши знания — внутри команды
            </span>
            <button
              className="icon-button"
              aria-label="Поиск"
              onClick={() => setSearch(true)}
            >
              <Search size={19} />
            </button>
            <button
              className="icon-button"
              aria-label={theme === "light" ? "Тёмная тема" : "Светлая тема"}
              onClick={() =>
                setTheme((v) => (v === "light" ? "dark" : "light"))
              }
            >
              {theme === "light" ? <Moon size={18} /> : <Sun size={18} />}
            </button>
          </div>
        </header>
        <main id="content" className="main-content" ref={main}>
          <Outlet />
        </main>
        <footer className="app-footer">
          <span>Знания, которые работают.</span>
          <span>
            <span className="dot" /> Всё важное проходит через человека
          </span>
        </footer>
      </div>
      {search && <SearchDialog onClose={() => setSearch(false)} />}
    </div>
  );
}
