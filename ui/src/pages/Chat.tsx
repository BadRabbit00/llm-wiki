import { useEffect, useRef, useState } from "react";
import {
  Link,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";
import {
  ArrowUp,
  ArrowUpRight,
  GitBranch,
  MessageSquare,
  Plus,
  ShieldCheck,
  Sparkles,
  Square,
  UserRound,
} from "lucide-react";
import { invalidate, streamMessage, useAPI, write } from "../api";
import { canWrite, useAuth } from "../auth";
import type { List, Plan, Profile, Proposal, Session } from "../types";
import {
  Badge,
  Empty,
  ErrorBanner,
  Loading,
  Markdown,
} from "../components/common";
import { Mark } from "../components/Layout";

interface SessionBrief {
  id: string;
  title?: string;
  updated_at: string;
  bind: { id: string; type: string };
}
export default function Chat() {
  const { id } = useParams(),
    [params] = useSearchParams(),
    navigate = useNavigate(),
    { actor } = useAuth(),
    [text, setText] = useState(""),
    [profile, setProfile] = useState(""),
    [sending, setSending] = useState(false),
    [pendingText, setPendingText] = useState(""),
    [streamError, setStreamError] = useState<unknown>(null),
    [extraPlans, setExtraPlans] = useState<Plan[]>([]),
    [cursor, setCursor] = useState<string | null>(null),
    [older, setOlder] = useState<SessionBrief[]>([]),
    end = useRef<HTMLDivElement>(null),
    input = useRef<HTMLTextAreaElement>(null),
    abort = useRef<AbortController | null>(null);
  const profiles = useAPI<Profile[]>("/profiles"),
    sessions = useAPI<List<SessionBrief>>(
      `/chat/sessions?limit=30${cursor ? "&cursor=" + encodeURIComponent(cursor) : ""}`,
      true,
      canWrite(actor),
    ),
    session = useAPI<Session>(
      `/chat/sessions/${id}`,
      true,
      !!id && canWrite(actor),
    );
  const rows = [...older, ...(sessions.data?.items || [])].filter(
    (s, i, all) => all.findIndex((v) => v.id === s.id) === i,
  );
  useEffect(() => {
    setExtraPlans([]);
    setStreamError(null);
    setText("");
    setPendingText("");
  }, [id]);
  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [session.data?.messages.length, sending, extraPlans.length]);
  useEffect(() => () => abort.current?.abort(), []);
  const send = async (value = text) => {
    if (!value.trim() || sending) return;
    setSending(true);
    setStreamError(null);
    setPendingText(value);
    setText("");
    setExtraPlans([]);
    const controller = new AbortController();
    abort.current = controller;
    try {
      let sessionId = id;
      if (!sessionId) {
        const created = await write<Session>(
          "/chat/sessions",
          {
            profile: profile || undefined,
            bind: {
              type: params.get("type") || "none",
              id: params.get("bind") || "",
            },
          },
          "POST",
          true,
        );
        sessionId = created.id;
        navigate(`/chat/${sessionId}`, { replace: true });
      }
      await streamMessage(
        sessionId,
        value,
        (_event, result) => {
          if (_event === "message") {
            const data = result as { plans?: Plan[] };
            setExtraPlans(data.plans?.slice(1) || []);
          }
        },
        controller.signal,
      );
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError")
        setStreamError(
          new Error(
            "Получение ответа остановлено. Агент мог продолжить работу: обновите диалог перед повторной отправкой.",
          ),
        );
      else setStreamError(error);
    } finally {
      setSending(false);
      setPendingText("");
      abort.current = null;
      await invalidate();
    }
  };
  if (!canWrite(actor))
    return (
      <Empty
        icon={MessageSquare}
        title="Для чата нужен доступ редактора"
        text="Ваш токен позволяет читать вики. Для создания предложений обратитесь к администратору."
      />
    );
  const choose = (question: string, option: string) => {
    setText(`${question}\nОтвет: ${option}`);
    input.current?.focus();
  };
  return (
    <div className="chat-layout page-enter">
      <aside className="chat-history">
        <div className="chat-history-title">
          <h2>Диалоги</h2>
          <button
            className="icon-button"
            title="Новый диалог"
            aria-label="Новый диалог"
            disabled={sending}
            onClick={() => navigate("/chat")}
          >
            <Plus size={19} />
          </button>
        </div>
        <button
          className="button new-chat"
          disabled={sending}
          onClick={() => navigate("/chat")}
        >
          <Plus size={16} />
          Новый разговор
        </button>
        <div className="nav-label">НЕДАВНИЕ</div>
        <ErrorBanner error={sessions.error} />
        {sessions.isPending ? (
          <Loading lines={3} />
        ) : rows.length ? (
          rows.map((s) => (
            <Link
              aria-disabled={sending}
              onClick={(e) => {
                if (sending) e.preventDefault();
              }}
              className={`chat-history-item ${s.id === id ? "active" : ""}`}
              to={`/chat/${s.id}`}
              key={s.id}
            >
              <MessageSquare size={15} />
              <span>{s.title || "Новый разговор"}</span>
            </Link>
          ))
        ) : (
          <p className="muted chat-history-empty">
            Здесь будут ваши разговоры. Каждый — с сохранённым контекстом.
          </p>
        )}
        {sessions.data?.next_cursor && (
          <button
            className="text-link"
            onClick={() => {
              setOlder(rows);
              setCursor(sessions.data!.next_cursor!);
            }}
          >
            Более ранние диалоги
          </button>
        )}
        <div className="chat-history-note">
          <ShieldCheck size={19} />
          <p>
            Агент предлагает.
            <br />
            <strong>Человек решает.</strong>
          </p>
        </div>
      </aside>
      <section className="chat-main">
        <header className="chat-top">
          <div>
            <span className="agent-orb">
              <Sparkles size={17} />
            </span>
            <strong>Агент знаний</strong>
            <span
              className={`badge ${sessions.error ? "badge-failed" : "badge-active"}`}
            >
              {sessions.error
                ? "Нет связи"
                : sessions.isPending
                  ? "Подключение…"
                  : "На связи"}
            </span>
          </div>
          {(session.data?.bind.id || params.get("bind")) && (
            <span className="tag bound-tag">
              <GitBranch size={13} />
              {session.data?.bind.id || params.get("bind")}
            </span>
          )}
        </header>
        <div className="chat-messages">
          {!id || (!session.isPending && !session.data?.messages.length) ? (
            <div className="chat-welcome">
              <Mark />
              <span className="eyebrow">ДАВАЙТЕ РАЗБЕРЁМСЯ ВМЕСТЕ</span>
              <h1>
                Мысль — ваша.
                <br />
                <span className="serif-accent">Связи найдём вместе.</span>
              </h1>
              <p>
                Расскажите о решении, задайте вопрос или предложите правило.
                <br />Я сверю его с вики и подготовлю понятный план.
              </p>
              <div className="chat-suggestions">
                {[
                  "Мы используем FastAPI и только асинхронный код",
                  "Какие правила действуют для Python-сервисов?",
                  "Давай разберём противоречия в наших правилах",
                ].map((s, i) => (
                  <button
                    key={s}
                    onClick={() => {
                      setText(s);
                      input.current?.focus();
                    }}
                  >
                    <span>{["01", "02", "03"][i]}</span>
                    {s}
                    <ArrowUpRight size={16} />
                  </button>
                ))}
              </div>
            </div>
          ) : session.isPending ? (
            <Loading />
          ) : (
            session.data?.messages.map((m, i) => (
              <div className={`message ${m.role}`} key={`${id}-${i}`}>
                <span className={`message-avatar ${m.role}`}>
                  {m.role === "user" ? (
                    <UserRound size={17} />
                  ) : (
                    <Sparkles size={17} />
                  )}
                </span>
                <div className="message-content">
                  <div className="message-byline">
                    {m.role === "user" ? "Вы" : "Агент знаний"}
                    <time>
                      {new Date(m.created_at).toLocaleTimeString("ru", {
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </time>
                  </div>
                  <Markdown text={m.text} />
                  {m.plan && <PlanCard plan={m.plan} answer={choose} />}
                </div>
              </div>
            ))
          )}
          {pendingText &&
            !session.data?.messages.some(
              (m) => m.role === "user" && m.text === pendingText,
            ) && (
              <div className="message user">
                <span className="message-avatar user">
                  <UserRound size={17} />
                </span>
                <div className="message-content">
                  <div className="message-byline">Вы</div>
                  <Markdown text={pendingText} />
                </div>
              </div>
            )}
          {sending && (
            <div className="message assistant">
              <span className="message-avatar assistant">
                <Sparkles size={17} />
              </span>
              <div className="thinking">
                <span />
                <span />
                <span />
                <p>Сверяю с вики и готовлю ответ…</p>
              </div>
            </div>
          )}
          {extraPlans.map((plan, i) => (
            <PlanCard key={i} plan={plan} answer={choose} />
          ))}
          <ErrorBanner error={streamError || session.error} />
          <div ref={end} />
        </div>
        <div className="composer-area">
          <form
            className={`composer ${sending ? "is-working" : ""}`}
            onSubmit={(e) => {
              e.preventDefault();
              void send();
            }}
          >
            <textarea
              ref={input}
              aria-label="Сообщение агенту"
              placeholder="О чём договоримся сегодня?"
              value={text}
              onChange={(e) => setText(e.target.value)}
              disabled={sending}
              maxLength={100000}
              rows={2}
              onKeyDown={(e) => {
                if (
                  e.key === "Enter" &&
                  !e.shiftKey &&
                  !e.nativeEvent.isComposing
                ) {
                  e.preventDefault();
                  void send();
                }
              }}
            />
            <div className="composer-bottom">
              <div className="composer-context">
                <GitBranch size={14} />
                {id ? (
                  <span>{session.data?.profile || "Общий контекст"}</span>
                ) : (
                  <select
                    aria-label="Профиль чата"
                    value={profile}
                    onChange={(e) => setProfile(e.target.value)}
                  >
                    <option value="">Общий контекст</option>
                    {profiles.data?.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.title}
                      </option>
                    ))}
                  </select>
                )}
              </div>
              {sending ? (
                <button
                  type="button"
                  className="send-button"
                  aria-label="Остановить получение ответа"
                  onClick={() => abort.current?.abort()}
                >
                  <Square size={16} />
                </button>
              ) : (
                <button
                  className="send-button"
                  aria-label="Отправить сообщение"
                  disabled={!text.trim()}
                >
                  <ArrowUp size={19} />
                </button>
              )}
            </div>
          </form>
          <p className="composer-disclaimer">
            Проверьте предложения агента перед принятием.{" "}
            <span>Enter — отправить · Shift + Enter — новая строка</span>
          </p>
        </div>
      </section>
    </div>
  );
}
function PlanCard({
  plan,
  answer,
}: {
  plan: Plan;
  answer: (q: string, a: string) => void;
}) {
  const proposal = useAPI<Proposal>(
    `/proposals/${plan.proposal}`,
    false,
    !!plan.proposal,
  );
  const closed = ["accepted", "rejected", "abandoned", "reverted"].includes(
    proposal.data?.status || "",
  );
  if (plan.cancelled)
    return <div className="callout">Предложение отменено</div>;
  return (
    <div className="plan-card">
      <div className="plan-header">
        <span>
          <GitBranch size={16} />
          ПЛАН ИЗМЕНЕНИЙ
        </span>
        <Badge value={proposal.data?.status || "neutral"}>
          {proposal.data ? undefined : "План"}
        </Badge>
      </div>
      <h3>{plan.summary}</h3>
      <div className="plan-items">
        {plan.items?.map((item, i) => (
          <div className="plan-item" key={i}>
            <span className="plan-number">{i + 1}</span>
            <div>
              <Badge value={item.action} />
              <strong>{item.thesis || item.target}</strong>
              {item.reason && <p>{item.reason}</p>}
            </div>
          </div>
        ))}
      </div>
      {plan.assumptions?.length > 0 && (
        <details>
          <summary>Допущения · {plan.assumptions.length}</summary>
          <ul>
            {plan.assumptions.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        </details>
      )}
      {plan.questions?.map((q) => (
        <div className="plan-question" key={q.id}>
          <strong>{q.text}</strong>
          <div>
            {q.options?.map((option) => (
              <button
                className="button small"
                key={option}
                onClick={() => answer(q.text, option)}
              >
                {option}
              </button>
            ))}
          </div>
        </div>
      ))}
      <div className="plan-footer">
        <span>
          <ShieldCheck size={14} />
          {closed
            ? "Решение сохранено в истории"
            : plan.needs_double_confirm
              ? "Потребуется дополнительное подтверждение"
              : "Решение принимается на ревью"}
        </span>
        {plan.proposal && (
          <Link
            className="button primary small"
            to={`/proposals/${plan.proposal}`}
          >
            {closed ? "Открыть решение" : "Проверить и применить"}{" "}
            <ArrowUpRight size={14} />
          </Link>
        )}
      </div>
    </div>
  );
}
