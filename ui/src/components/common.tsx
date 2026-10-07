import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  AlertCircle,
  ArrowRight,
  Check,
  Copy,
  FileText,
  Loader2,
  Plus,
  X,
  type LucideIcon,
} from "lucide-react";
import { Link } from "react-router-dom";
import MarkdownView from "react-markdown";
import remarkGfm from "remark-gfm";

export const labels: Record<string, string> = {
  draft: "Черновик",
  submitted: "На ревью",
  changes_requested: "Нужны правки",
  accepted: "Принято",
  rejected: "Отклонено",
  abandoned: "Отменено",
  reverted: "Откачено",
  conflict: "Конфликт",
  active: "Действует",
  candidate: "Кандидат",
  deprecated: "В архиве",
  verified: "Проверено",
  outdated: "Устарело",
  must: "Обязательно",
  should: "Рекомендация",
  idea: "Идея",
  manual: "Вручную",
  chat: "Из чата",
  book: "Из книги",
  heal: "Самолечение",
  open: "Открыта",
  dismissed: "Отклонена",
  resolved: "Решена",
  pending: "В очереди",
  running: "В работе",
  done: "Завершено",
  cancelled: "Отменено",
  failed: "Ошибка",
  paused: "Приостановлено",
  needs_outline: "Нужно оглавление",
  awaiting_review: "Ждёт ревью",
  waiting_chat: "Ожидает чат",
  reader: "Читатель",
  writer: "Редактор",
  reviewer: "Ревьюер",
  admin: "Администратор",
  public: "Публично",
  internal: "Внутренний",
  restricted: "Ограниченный",
  human: "Человек",
  agent: "Агент",
  rule: "Правило",
  source: "Источник",
  term: "Термин",
  pattern: "Паттерн",
  decision: "Решение",
  adr: "Решение",
  process: "Процесс",
  system: "Система",
  app: "Приложение",
  playbook: "Инструкция",
  lesson: "Урок",
  role: "Роль",
  data: "Данные",
  create_rule: "Новое правило",
  update_rule: "Изменить правило",
  deprecate_rule: "В архив",
  flag_page: "Проверить страницу",
  duplicate: "Уже есть",
  attach_source: "Добавить источник",
};
export function Badge({
  value,
  children,
}: {
  value?: string;
  children?: ReactNode;
}) {
  return (
    <span className={`badge badge-${value || "neutral"}`}>
      {children || labels[value || ""] || value}
    </span>
  );
}
export function date(value?: string) {
  return value
    ? new Intl.DateTimeFormat("ru", { day: "numeric", month: "short" }).format(
        new Date(value),
      )
    : "—";
}
export function fullDate(value?: string) {
  return value ? new Date(value).toLocaleString("ru") : "—";
}
export function bytes(value = 0) {
  return value > 1024 * 1024
    ? `${(value / 1024 / 1024).toFixed(1)} МБ`
    : `${Math.max(1, Math.round(value / 1024))} КБ`;
}
export function Heading({
  eyebrow,
  title,
  description,
  children,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  children?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      <div className="heading-actions">{children}</div>
    </div>
  );
}
export function Empty({
  icon: Icon = FileText,
  title,
  text,
  children,
}: {
  icon?: LucideIcon;
  title: string;
  text?: string;
  children?: ReactNode;
}) {
  return (
    <div className="empty">
      <div className="empty-icon">
        <Icon size={25} />
      </div>
      <h3>{title}</h3>
      {text && <p>{text}</p>}
      {children}
    </div>
  );
}
export function Loading({ lines = 4 }: { lines?: number }) {
  return (
    <div className="skeleton-group" role="status" aria-label="Загрузка">
      {Array.from({ length: lines }, (_, i) => (
        <div
          className="skeleton"
          key={i}
          style={{ width: `${100 - (i % 3) * 12}%` }}
        />
      ))}
    </div>
  );
}
export function ErrorBanner({
  error,
  retry,
}: {
  error: unknown;
  retry?: () => void;
}) {
  if (!error) return null;
  const e = error as { message?: string; hint?: string };
  return (
    <div className="error-banner" role="alert">
      <AlertCircle size={18} />
      <div>
        <strong>{e.message || "Не удалось загрузить данные"}</strong>
        {e.hint && <p>{e.hint}</p>}
      </div>
      {retry && (
        <button className="button small" onClick={retry}>
          Повторить
        </button>
      )}
    </div>
  );
}
export function Modal({
  title,
  children,
  onClose,
  wide = false,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null),
    close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const el = ref.current!;
    el.showModal();
    const cancel = (e: Event) => {
      e.preventDefault();
      close.current();
    };
    el.addEventListener("cancel", cancel);
    return () => {
      el.removeEventListener("cancel", cancel);
      el.close();
    };
  }, []);
  return (
    <dialog
      className={`modal ${wide ? "wide" : ""}`}
      ref={ref}
      onClick={(e) => {
        if (e.target === ref.current) {
          const box = ref.current!.getBoundingClientRect();
          if (
            e.clientX < box.left ||
            e.clientX > box.right ||
            e.clientY < box.top ||
            e.clientY > box.bottom
          )
            onClose();
        }
      }}
    >
      <div className="modal-title">
        <h2>{title}</h2>
        <button className="icon-button" aria-label="Закрыть" onClick={onClose}>
          <X size={20} />
        </button>
      </div>
      {children}
    </dialog>
  );
}
const Toast = createContext<(text: string) => void>(() => {});
export function ToastProvider({ children }: { children: ReactNode }) {
  const [message, setMessage] = useState("");
  useEffect(() => {
    if (message) {
      const timer = setTimeout(() => setMessage(""), 4500);
      return () => clearTimeout(timer);
    }
  }, [message]);
  return (
    <Toast.Provider value={(text) => setMessage(text)}>
      {children}
      {message && (
        <div className="toast" role="status">
          <Check size={18} />
          {message}
          <button
            aria-label="Скрыть уведомление"
            onClick={() => setMessage("")}
          >
            <X size={16} />
          </button>
        </div>
      )}
    </Toast.Provider>
  );
}
export const useToast = () => useContext(Toast);
export function useAction() {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(null);
  const run = async (action: () => Promise<void>) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  return { busy, error, run, clear: () => setError(null) };
}
export function Submit({
  busy,
  children,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { busy?: boolean }) {
  return (
    <button
      {...props}
      disabled={busy || props.disabled}
      className={props.className || "button primary"}
    >
      {busy && <Loader2 className="spin" size={16} />} {children}
    </button>
  );
}
export function CopyButton({
  text,
  label = "Копировать",
}: {
  text: string;
  label?: string;
}) {
  const toast = useToast(),
    action = useAction();
  return (
    <>
      <button
        className="button small"
        onClick={() =>
          action.run(async () => {
            await navigator.clipboard.writeText(text);
            toast("Скопировано");
          })
        }
      >
        <Copy size={14} />
        {label}
      </button>
      <ErrorBanner error={action.error} />
    </>
  );
}
export function Markdown({ text }: { text: string }) {
  const content = text
    .replace(
      /\[\[([a-z0-9-]+)(?:\|([^\]]+))?\]\]/g,
      (_m, id, title) => `[${title || id}](/pages/${id})`,
    )
    .replace(
      /\[@([a-z0-9-]+)([^\]]*)\]/g,
      (_m, id, tail) => `[${id}${tail}](/pages/${id})`,
    );
  return (
    <div className="prose">
      <MarkdownView
        remarkPlugins={[remarkGfm]}
        skipHtml
        components={{
          a: ({ href, children }) =>
            href?.startsWith("/") ? (
              <Link to={href}>{children}</Link>
            ) : (
              <a href={href} target="_blank" rel="noopener noreferrer">
                {children}
              </a>
            ),
          img: ({ alt }) => (
            <span className="muted">
              [Изображение: {alt || "без описания"}]
            </span>
          ),
        }}
      >
        {content}
      </MarkdownView>
    </div>
  );
}
export function TextList({ values }: { values?: string[] }) {
  return (
    <div className="tag-list">
      {values?.map((value) => (
        <span className="tag" key={value}>
          {value}
        </span>
      ))}
    </div>
  );
}
export function SectionTitle({
  title,
  to,
  count,
}: {
  title: string;
  to?: string;
  count?: number;
}) {
  return (
    <div className="section-title">
      <h2>
        {title}
        {count !== undefined && <span className="count">{count}</span>}
      </h2>
      {to && (
        <Link className="text-link" to={to}>
          Открыть <ArrowRight size={15} />
        </Link>
      )}
    </div>
  );
}
export function CreateLink({
  to,
  children,
}: {
  to: string;
  children: ReactNode;
}) {
  return (
    <Link to={to} className="button primary">
      <Plus size={16} />
      {children}
    </Link>
  );
}
