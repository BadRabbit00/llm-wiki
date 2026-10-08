import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  Activity,
  ArrowUpRight,
  BookOpen,
  Play,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Square,
} from "lucide-react";
import { invalidate, useAPI, write } from "../api";
import { canWrite, useAuth } from "../auth";
import type { Job } from "../types";
import { DocsAudit } from "../components/DocsAudit";
import {
  Badge,
  Empty,
  ErrorBanner,
  Heading,
  Loading,
  Modal,
  Submit,
  fullDate,
  useAction,
  useToast,
} from "../components/common";

const errorText: Record<string, string> = {
  E_MODEL_OUTPUT:
    "Модель не смогла вернуть корректный ответ. Задачу можно возобновить.",
  E_NO_TEXT_LAYER:
    "В документе не найден текстовый слой. Загрузите версию с распознанным текстом.",
  E_EXTRACT_TIMEOUT: "Извлечение текста не уложилось в отведённое время.",
  E_AGENT_TOKEN: "Рабочий токен агента настроен неверно.",
  E_CONTEXT_BUDGET: "Материал не помещается в контекст модели.",
};
export default function Jobs() {
  const { actor } = useAuth(),
    data = useAPI<{ items: Job[] }>("/jobs", true, canWrite(actor), 5000),
    [params] = useSearchParams(),
    [filter, setFilter] = useState("all"),
    [confirm, setConfirm] = useState(""),
    [audit, setAudit] = useState(false),
    [cancel, setCancel] = useState<string | null>(null),
    action = useAction(),
    toast = useToast();
  const rows = [...(data.data?.items || [])]
    .filter(
      (j) =>
        filter === "all" ||
        (filter === "active"
          ? [
              "running",
              "pending",
              "waiting_chat",
              "paused",
              "needs_outline",
            ].includes(j.status)
          : ["done", "awaiting_review", "cancelled", "failed"].includes(
              j.status,
            )),
    )
    .sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  const act = (id: string, kind: string) =>
    action.run(async () => {
      await write(`/jobs/${id}/${kind}`, {}, "POST", true);
      await invalidate();
      setCancel(null);
      toast(kind === "cancel" ? "Остановка запрошена" : "Задача возобновлена");
    });
  const heal = () =>
    action.run(async () => {
      await write("/jobs/heal", { scope: confirm }, "POST", true);
      setConfirm("");
      await invalidate();
      toast("Проверка знаний запущена");
    });
  if (!canWrite(actor))
    return (
      <Empty
        icon={Activity}
        title="Для задач нужен доступ редактора"
        text="Источники и фоновые задачи доступны участникам, которые могут создавать предложения."
      />
    );
  return (
    <div className="page-enter">
      <Heading
        eyebrow="РАБОТА ПРОДОЛЖАЕТСЯ"
        title="За кадром"
        description="Разбор источников, поиск противоречий и подготовка знаний — всё под наблюдением."
      >
        {actor?.kind === "human" && (
          <button className="button" onClick={() => setAudit(true)}>
            Сверить документацию
          </button>
        )}
        <button className="button" onClick={() => setConfirm("changed")}>
          <Sparkles size={16} />
          Проверить изменения
        </button>
        <button className="button primary" onClick={() => setConfirm("full")}>
          <ShieldCheck size={17} />
          Полная проверка
        </button>
      </Heading>
      <div className="jobs-info">
        <Activity size={19} />
        <span>
          Состояние обновляется каждые 5 секунд. Результаты агента поступают на
          ревью.
        </span>
        <button
          className="icon-button"
          aria-label="Обновить задачи"
          onClick={() => void data.refetch()}
        >
          <RefreshCw size={16} />
        </button>
      </div>
      <div className="tabs">
        {[
          ["all", "Все задачи"],
          ["active", "В работе"],
          ["finished", "Завершённые"],
        ].map(([key, label]) => (
          <button
            key={key}
            className={filter === key ? "active" : ""}
            onClick={() => setFilter(key)}
          >
            {label}
          </button>
        ))}
      </div>
      <ErrorBanner error={data.error || action.error} />
      {data.isPending ? (
        <Loading lines={5} />
      ) : rows.length ? (
        <div className="jobs-list">
          {rows.map((job) => {
            const done = Number(job.progress.chapters_done || 0),
              total = Number(job.progress.chapters_total || 0),
              active = ["pending", "running", "waiting_chat"].includes(
                job.status,
              ),
              selected = params.get("selected") === job.id,
              proposals = [
                job.progress.proposal,
                ...(Array.isArray(job.progress.proposals)
                  ? job.progress.proposals
                  : []),
              ].filter((v): v is string => typeof v === "string");
            return (
              <article
                className={`job-card ${selected ? "highlight" : ""}`}
                key={job.id}
              >
                <div className="job-heading">
                  <span
                    className={`row-symbol ${job.kind === "heal" ? "purple" : "blue"}`}
                  >
                    {job.kind === "heal" ? (
                      <Sparkles size={21} />
                    ) : (
                      <BookOpen size={21} />
                    )}
                  </span>
                  <div>
                    <h3>
                      {job.kind === "docs_audit"
                        ? `Сверка документации: ${String(job.payload.project)}`
                        : job.kind === "heal"
                          ? job.payload.scope === "full"
                            ? "Полная проверка знаний"
                            : "Проверка изменений"
                          : String(
                              job.payload.title ||
                                String(
                                  job.payload.raw_path || "Разбор источника",
                                )
                                  .split("/")
                                  .pop(),
                            )}
                    </h3>
                    <p>{fullDate(job.created_at)}</p>
                  </div>
                  <Badge value={job.status} />
                </div>
                {total > 0 && (
                  <div className="job-progress">
                    <div>
                      <span>Разобрано глав</span>
                      <strong>
                        {done} / {total}
                      </strong>
                    </div>
                    <progress value={done} max={total} />
                  </div>
                )}
                <div className="job-metrics">
                  {job.progress.candidates !== undefined && (
                    <span>
                      <strong>{String(job.progress.candidates)}</strong>{" "}
                      кандидатов на правила
                    </span>
                  )}
                  {job.progress.checked_pairs !== undefined && (
                    <span>
                      <strong>{String(job.progress.checked_pairs)}</strong>{" "}
                      проверенных связей
                    </span>
                  )}
                  {Array.isArray(job.progress.findings) && (
                    <span>
                      <strong>{job.progress.findings.length}</strong> находок
                    </span>
                  )}
                  {job.progress.model_calls !== undefined && (
                    <span>
                      <strong>{String(job.progress.model_calls)}</strong>{" "}
                      запросов к модели
                    </span>
                  )}
                </div>
                {job.error && (
                  <div className="error-banner">
                    <div>
                      {errorText[job.error] ||
                        "Во время обработки произошла ошибка. Проверьте настройки сервиса и попробуйте возобновить задачу."}
                      <small className="error-code">{job.error}</small>
                    </div>
                  </div>
                )}
                {job.status === "needs_outline" && (
                  <div className="callout">
                    Агенту нужно уточнённое оглавление. Укажите главы в карточке
                    источника, затем возобновите задачу.
                  </div>
                )}
                {job.progress.budget_exhausted === true && (
                  <p className="callout">
                    Достигнут бюджет запросов. Проверка сохранена и сможет
                    продолжиться позже.
                  </p>
                )}
                {Array.isArray(job.progress.errors) &&
                  job.progress.errors.length > 0 && (
                    <details className="advanced">
                      <summary>
                        Замечания при разборе · {job.progress.errors.length}
                      </summary>
                      {job.progress.errors.map((error, i) => (
                        <p key={i}>
                          {typeof error === "string"
                            ? error
                            : Object.entries(error as Record<string, unknown>)
                                .map(([k, v]) => `${k}: ${String(v)}`)
                                .join(" · ")}
                        </p>
                      ))}
                    </details>
                  )}
                <div className="job-footer">
                  <code>{job.id.slice(0, 12)}</code>
                  <div className="inline-actions">
                    {typeof job.payload.raw_path === "string" && (
                      <Link
                        className="button small"
                        to={`/sources?path=${encodeURIComponent(job.payload.raw_path)}`}
                      >
                        Источник <ArrowUpRight size={13} />
                      </Link>
                    )}
                    {proposals.map((pid) => (
                      <Link
                        className="button primary small"
                        to={`/proposals/${pid}`}
                        key={pid}
                      >
                        Проверить результат <ArrowUpRight size={14} />
                      </Link>
                    ))}
                    {(job.kind === "docs_audit" ||
                      (job.kind === "heal" && job.status === "done")) && (
                      <Link
                        className="button small"
                        to="/proposals?tab=findings"
                      >
                        Находки <ArrowUpRight size={14} />
                      </Link>
                    )}
                    {active && (
                      <button
                        className="button small"
                        disabled={action.busy}
                        onClick={() => setCancel(job.id)}
                      >
                        <Square size={13} />
                        Остановить
                      </button>
                    )}
                    {[
                      "failed",
                      "cancelled",
                      "paused",
                      "needs_outline",
                    ].includes(job.status) && (
                      <button
                        className="button small"
                        disabled={action.busy}
                        onClick={() => void act(job.id, "resume")}
                      >
                        <Play size={13} />
                        Продолжить
                      </button>
                    )}
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      ) : (
        <Empty
          icon={Activity}
          title="Пока всё спокойно"
          text="Загрузите источник или запустите проверку знаний — прогресс появится здесь."
        />
      )}
      {audit && <DocsAudit onClose={() => setAudit(false)} />}
      {confirm && (
        <Modal title="Запустить проверку знаний" onClose={() => setConfirm("")}>
          <p className="modal-description">
            {confirm === "full"
              ? "Агент проверит всю доступную базу знаний: связи, противоречия и устаревшие правила."
              : "Агент проверит страницы, которые изменились после предыдущего прохода."}
          </p>
          <p className="callout">
            Проверка использует локальную модель. Предложения поступят на ревью;
            правила автоматически не меняются.
          </p>
          <ErrorBanner error={action.error} />
          <div className="modal-footer">
            <Submit busy={action.busy} onClick={() => void heal()}>
              Начать проверку
            </Submit>
          </div>
        </Modal>
      )}
      {cancel && (
        <Modal title="Остановить задачу" onClose={() => setCancel(null)}>
          <p>
            Агент остановится после текущего шага. Сохранённую задачу можно
            будет продолжить.
          </p>
          <ErrorBanner error={action.error} />
          <div className="modal-footer">
            <Submit
              busy={action.busy}
              onClick={() => void act(cancel, "cancel")}
            >
              Остановить
            </Submit>
          </div>
        </Modal>
      )}
    </div>
  );
}
