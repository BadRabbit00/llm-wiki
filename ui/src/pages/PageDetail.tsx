import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ArrowLeft,
  ArrowUpRight,
  GitBranch,
  History as HistoryIcon,
  MessageSquare,
  Pencil,
  ShieldCheck,
  Archive,
  Check,
} from "lucide-react";
import { invalidate, useAPI, write } from "../api";
import { useAuth, canWrite, canReview } from "../auth";
import { PersonName } from "../components/PersonName";
import type { History, Page } from "../types";
import {
  Badge,
  CopyButton,
  ErrorBanner,
  Loading,
  Markdown,
  Modal,
  Submit,
  TextList,
  date,
  fullDate,
  useAction,
  useToast,
} from "../components/common";
import Editor from "../components/Editor";

export default function PageDetail() {
  const { id = "" } = useParams(),
    data = useAPI<Page>(`/pages/${id}?include=neighbors,history`),
    { actor } = useAuth(),
    [edit, setEdit] = useState(false),
    [tab, setTab] = useState("content"),
    [decision, setDecision] = useState(""),
    [level, setLevel] = useState("should"),
    [owner, setOwner] = useState(""),
    [reason, setReason] = useState(""),
    [historical, setHistorical] = useState<History | null>(null),
    action = useAction(),
    toast = useToast();
  const past = useAPI<Page>(
    `/pages/${id}/at/${historical?.commit}`,
    false,
    !!historical,
  );
  const page = data.data,
    rule = page?.type === "rule";
  if (data.isPending) return <Loading lines={8} />;
  if (data.error || !page)
    return <ErrorBanner error={data.error} retry={() => void data.refetch()} />;
  const act = () =>
    action.run(async () => {
      if (decision === "promote")
        await write(`/rules/${id}/promote`, {
          level,
          ...(owner ? { owner } : {}),
        });
      else if (decision === "deprecate")
        await write(`/rules/${id}/deprecate`, { reason });
      else if (decision === "verify") await write(`/pages/${id}/verify`);
      else await write(`/pages/${id}/mark-outdated`, { reason });
      await invalidate();
      setDecision("");
      toast("Решение сохранено");
    });
  return (
    <div className="page-enter">
      <Link className="back-link" to={rule ? "/rules" : "/pages"}>
        <ArrowLeft size={15} />
        {rule ? "Правила команды" : "База знаний"}
      </Link>
      <div className="document-header">
        <div className="document-labels">
          <Badge value={page.type} />
          <Badge value={rule ? page.lifecycle : page.status} />
          {rule && <Badge value={page.level} />}
          <code>{page.id}</code>
        </div>
        <h1>{page.title}</h1>
        <p>{page.summary}</p>
        <div className="document-actions">
          {canWrite(actor) && (
            <>
              <button className="button" onClick={() => setEdit(true)}>
                <Pencil size={15} />
                Предложить правку
              </button>
              <Link
                className="button"
                to={`/chat?bind=${page.id}&type=${rule ? "rule" : "page"}`}
              >
                <MessageSquare size={16} />
                Обсудить с агентом
              </Link>
            </>
          )}
          <CopyButton text={window.location.href} label="Ссылка" />
        </div>
      </div>
      <div className="document-layout">
        <article className="document-paper">
          <div className="tabs paper-tabs">
            <button
              className={tab === "content" ? "active" : ""}
              onClick={() => setTab("content")}
            >
              Содержание
            </button>
            <button
              className={tab === "history" ? "active" : ""}
              onClick={() => setTab("history")}
            >
              <HistoryIcon size={15} />
              История <span>{page.history?.length || 0}</span>
            </button>
          </div>
          {tab === "content" ? (
            <Markdown text={page.body_md || ""} />
          ) : (
            <div className="history-list">
              {page.history?.map((h) => (
                <button key={h.commit} onClick={() => setHistorical(h)}>
                  <span className="history-dot" />
                  <div>
                    <strong>{h.message}</strong>
                    <p>
                      {h.author} · {fullDate(h.date)}
                    </p>
                  </div>
                  <code>{h.commit.slice(0, 7)}</code>
                </button>
              ))}
            </div>
          )}
        </article>
        <aside className="document-aside">
          <div className="meta-card">
            <h3>О странице</h3>
            <dl>
              <dt>Обновлено</dt>
              <dd>{date(page.updated)}</dd>
              <dt>Видимость</dt>
              <dd>
                <Badge value={page.sensitivity} />
              </dd>
              {page.verified_by && (
                <>
                  <dt>Проверил</dt>
                  <dd>
                    <PersonName identity={page.verified_by} />
                  </dd>
                </>
              )}
              {page.owner && (
                <>
                  <dt>Владелец</dt>
                  <dd>{page.owner}</dd>
                </>
              )}
              {page.category && (
                <>
                  <dt>Категория</dt>
                  <dd>{page.category}</dd>
                </>
              )}
            </dl>
            {!!page.applies_to?.length && (
              <>
                <h4>Области применения</h4>
                <TextList values={page.applies_to} />
              </>
            )}
            {!!page.tags?.length && (
              <>
                <h4>Теги</h4>
                <TextList values={page.tags} />
              </>
            )}
            {!!page.enforced_by?.length && (
              <>
                <h4>Проверяется автоматически</h4>
                <TextList values={page.enforced_by} />
              </>
            )}
          </div>
          {canReview(actor) && (
            <div className="meta-card">
              <h3>
                <ShieldCheck size={17} />
                Решение человека
              </h3>
              {rule ? (
                <>
                  {page.lifecycle !== "active" && (
                    <button
                      className="button primary full"
                      onClick={() => setDecision("promote")}
                    >
                      <Check size={16} />
                      Ввести в действие
                    </button>
                  )}
                  {page.lifecycle !== "deprecated" && (
                    <button
                      className="button full"
                      onClick={() => setDecision("deprecate")}
                    >
                      <Archive size={16} />
                      Снять с действия
                    </button>
                  )}
                </>
              ) : (
                <>
                  <button
                    className="button full"
                    onClick={() => setDecision("verify")}
                  >
                    Подтвердить актуальность
                  </button>
                  <button
                    className="button full"
                    onClick={() => setDecision("outdated")}
                  >
                    Отметить устаревшей
                  </button>
                </>
              )}
            </div>
          )}
          <div className="meta-card">
            <h3>
              <GitBranch size={16} />
              Связанные знания
            </h3>
            {page.neighbors?.nodes.filter((p) => p.id !== id).length ? (
              page.neighbors.nodes
                .filter((p) => p.id !== id)
                .slice(0, 12)
                .map((p) => (
                  <Link
                    className="related-link"
                    to={`/pages/${p.id}`}
                    key={p.id}
                  >
                    <span>{p.title}</span>
                    <ArrowUpRight size={14} />
                  </Link>
                ))
            ) : (
              <p className="muted">Связей пока нет</p>
            )}
            <Link className="text-link" to={`/graph?focus=${id}`}>
              Открыть граф <ArrowUpRight size={14} />
            </Link>
          </div>
          {!!page.sources?.length && (
            <div className="meta-card">
              <h3>Источники</h3>
              {page.sources.map((s) => (
                <Link className="related-link" key={s} to={`/pages/${s}`}>
                  {s}
                  <ArrowUpRight size={14} />
                </Link>
              ))}
            </div>
          )}
        </aside>
      </div>
      {edit && <Editor page={page} onClose={() => setEdit(false)} />}{" "}
      {!!decision && (
        <Modal
          title={
            decision === "promote"
              ? "Ввести правило в действие"
              : decision === "deprecate"
                ? "Снять правило с действия"
                : "Изменить актуальность"
          }
          onClose={() => setDecision("")}
        >
          <p className="modal-description">{page.title}</p>
          {decision === "promote" ? (
            <>
              <label className="field">
                Уровень
                <select
                  value={level}
                  onChange={(e) => setLevel(e.target.value)}
                >
                  <option value="should">Рекомендация — should</option>
                  <option value="must">Обязательно — must</option>
                </select>
              </label>
              {level === "must" && (
                <>
                  <label className="field">
                    Владелец обязательного правила
                    <input
                      value={owner}
                      onChange={(e) => setOwner(e.target.value)}
                      placeholder="Команда или ответственный"
                    />
                  </label>
                  <p className="callout">
                    Для must в странице должен быть указан источник решения. При
                    необходимости сначала предложите правку.
                  </p>
                </>
              )}
            </>
          ) : (
            decision !== "verify" && (
              <label className="field">
                Причина
                <textarea
                  rows={3}
                  value={reason}
                  maxLength={200}
                  onChange={(e) => setReason(e.target.value)}
                />
              </label>
            )
          )}
          <ErrorBanner error={action.error} />
          <div className="modal-footer">
            <button className="button" onClick={() => setDecision("")}>
              Отмена
            </button>
            <Submit
              busy={action.busy}
              disabled={
                (decision === "promote" && level === "must" && !owner.trim()) ||
                (["deprecate", "outdated"].includes(decision) && !reason.trim())
              }
              onClick={() => void act()}
            >
              Подтвердить решение
            </Submit>
          </div>
        </Modal>
      )}
      {historical && (
        <Modal
          title={`Версия от ${fullDate(historical.date)}`}
          wide
          onClose={() => setHistorical(null)}
        >
          <p className="muted">
            {historical.author} · {historical.message}
          </p>
          <ErrorBanner error={past.error} />
          {past.isPending ? (
            <Loading />
          ) : (
            <Markdown text={past.data?.body_md || ""} />
          )}
        </Modal>
      )}
    </div>
  );
}
