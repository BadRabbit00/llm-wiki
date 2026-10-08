import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  ArrowUpRight,
  CheckCheck,
  FileCheck2,
  Search,
  Sparkles,
} from "lucide-react";
import { invalidate, useAll, write } from "../api";
import { canReview, useAuth } from "../auth";
import { PersonName } from "../components/PersonName";
import type { Finding, Proposal } from "../types";
import {
  Badge,
  Empty,
  ErrorBanner,
  Heading,
  Loading,
  Modal,
  Submit,
  date,
  useAction,
  useToast,
} from "../components/common";

export default function Review() {
  const [params, setParams] = useSearchParams(),
    tab = params.get("tab") || "queue",
    proposals = useAll<Proposal>("/proposals"),
    findings = useAll<Finding>("/findings"),
    [query, setQuery] = useState(""),
    [dismiss, setDismiss] = useState<Finding | null>(null),
    [reason, setReason] = useState(""),
    action = useAction(),
    toast = useToast(),
    { actor } = useAuth();
  const data = [...(proposals.data || [])]
    .filter((p) =>
      tab === "history"
        ? ["accepted", "rejected", "abandoned", "reverted"].includes(p.status)
        : !["accepted", "rejected", "abandoned", "reverted"].includes(p.status),
    )
    .filter((p) =>
      (p.title + " " + p.author).toLowerCase().includes(query.toLowerCase()),
    )
    .sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  const findingRows = (findings.data || []).filter(
    (f) =>
      f.status === "open" &&
      (f.summary + " " + f.kind).toLowerCase().includes(query.toLowerCase()),
  );
  const resolve = () =>
    action.run(async () => {
      await write(`/findings/${dismiss!.id}/dismiss`, { reason });
      await invalidate();
      setDismiss(null);
      setReason("");
      toast("Находка отклонена с комментарием");
    });
  return (
    <div className="page-enter">
      <Heading
        eyebrow="РЕШЕНИЯ ОСТАЮТСЯ ЗА ВАМИ"
        title="Второй взгляд меняет многое"
        description="Проверьте предложения, оцените влияние и решите, что станет знанием команды."
      />
      <div className="tabs">
        <button
          className={tab === "queue" ? "active" : ""}
          onClick={() => setParams({ tab: "queue" })}
        >
          Предложения{" "}
          <span>
            {
              (proposals.data || []).filter((p) =>
                [
                  "submitted",
                  "draft",
                  "changes_requested",
                  "conflict",
                ].includes(p.status),
              ).length
            }
          </span>
        </button>
        <button
          className={tab === "findings" ? "active" : ""}
          onClick={() => setParams({ tab: "findings" })}
        >
          <Sparkles size={15} />
          Находки{" "}
          <span>
            {(findings.data || []).filter((f) => f.status === "open").length}
          </span>
        </button>
        <button
          className={tab === "history" ? "active" : ""}
          onClick={() => setParams({ tab: "history" })}
        >
          История решений
        </button>
      </div>
      <div className="catalog-toolbar">
        <div className="filter-search">
          <Search size={17} />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Найти в очереди…"
            aria-label="Фильтр ревью"
          />
        </div>
        <span className="muted">
          {tab === "findings"
            ? "Агент находит — человек решает"
            : "Все изменения сохраняются в истории"}
        </span>
      </div>
      <ErrorBanner error={proposals.error || findings.error} />
      {(tab === "findings" ? findings.isPending : proposals.isPending) ? (
        <Loading lines={5} />
      ) : tab === "findings" ? (
        findingRows.length ? (
          <div className="finding-list">
            {findingRows.map((f) => (
              <article key={f.id} className="finding-card">
                <div className="finding-title">
                  <span className={`severity-dot ${f.severity}`} />
                  <Badge value={f.severity} />
                  <code>{f.kind}</code>
                  <small>{date(f.created_at)}</small>
                </div>
                <h3>{f.summary}</h3>
                <p>{f.explanation}</p>
                {f.evidence.map((e, i) => (
                  <blockquote key={i}>
                    {e.quote}
                    <Link to={`/pages/${e.page}`}>
                      {e.page}
                      <ArrowUpRight size={12} />
                    </Link>
                  </blockquote>
                ))}
                <div className="finding-actions">
                  <div>
                    {f.pages.map((p) => (
                      <Link className="tag" to={`/pages/${p}`} key={p}>
                        {p}
                      </Link>
                    ))}
                  </div>
                  {f.proposal_pid && (
                    <Link
                      className="button primary small"
                      to={`/proposals/${f.proposal_pid}`}
                    >
                      Проверить исправление <ArrowUpRight size={14} />
                    </Link>
                  )}
                  {canReview(actor) && (
                    <button
                      className="button small"
                      onClick={() => setDismiss(f)}
                    >
                      Отклонить находку
                    </button>
                  )}
                </div>
              </article>
            ))}
          </div>
        ) : (
          <Empty
            icon={CheckCheck}
            title="Открытых находок нет"
            text="Самолечение проверяет связи и противоречия. Его можно запустить в разделе задач."
          />
        )
      ) : data.length ? (
        <div className="proposal-list">
          {data.map((p) => (
            <Link
              className="proposal-card"
              to={`/proposals/${p.pid}`}
              key={p.pid}
            >
              <span
                className={`row-symbol ${p.kind === "heal" ? "purple" : "orange"}`}
              >
                <FileCheck2 size={22} />
              </span>
              <div className="proposal-card-main">
                <div className="proposal-card-heading">
                  <h3>{p.title}</h3>
                  <Badge value={p.status} />
                </div>
                {p.description && <p>{p.description}</p>}
                <div className="proposal-card-meta">
                  <Badge value={p.kind} />
                  <PersonName
                    identity={p.author_identity || p.author}
                    fallback={p.author}
                  />
                  <span>·</span>
                  <span>{date(p.updated_at)}</span>
                  <code>{p.pid.slice(0, 8)}</code>
                </div>
              </div>
              <ArrowUpRight size={19} />
            </Link>
          ))}
        </div>
      ) : (
        <Empty
          icon={FileCheck2}
          title={
            tab === "history" ? "История ещё впереди" : "Всё под контролем"
          }
          text={
            query
              ? "По этому запросу ничего не найдено."
              : "Новых предложений пока нет. Обсудите изменение с агентом или добавьте знание вручную."
          }
        />
      )}{" "}
      {dismiss && (
        <Modal title="Отклонить находку" onClose={() => setDismiss(null)}>
          <p>{dismiss.summary}</p>
          <label className="field">
            Почему исправление не требуется?
            <textarea
              rows={4}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Комментарий сохранится вместе с решением"
            />
          </label>
          <ErrorBanner error={action.error} />
          <div className="modal-footer">
            <Submit
              busy={action.busy}
              disabled={!reason.trim()}
              onClick={() => void resolve()}
            >
              Сохранить решение
            </Submit>
          </div>
        </Modal>
      )}
    </div>
  );
}
