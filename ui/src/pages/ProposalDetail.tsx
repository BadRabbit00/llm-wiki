import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ArrowLeft,
  ArrowUpRight,
  Check,
  GitBranch,
  MessageSquare,
  RotateCcw,
  ShieldCheck,
} from "lucide-react";
import { invalidate, useAPI, write } from "../api";
import { canReview, canWrite, useAuth } from "../auth";
import { PersonName } from "../components/PersonName";
import type { Diff, Impact, Proposal, Promotion } from "../types";
import {
  Badge,
  Empty,
  ErrorBanner,
  Loading,
  Modal,
  Submit,
  date,
  useAction,
  useToast,
} from "../components/common";

const value = (v: unknown) =>
  v === null || v === undefined
    ? "—"
    : typeof v === "object"
      ? JSON.stringify(v)
      : String(v);
export default function ProposalDetail() {
  const { id = "" } = useParams(),
    data = useAPI<Proposal>(`/proposals/${id}`),
    diff = useAPI<Diff>(`/proposals/${id}/diff`),
    impact = useAPI<Impact>(`/proposals/${id}/impact`),
    { actor } = useAuth(),
    [tab, setTab] = useState("diff"),
    [decision, setDecision] = useState(""),
    [reason, setReason] = useState(""),
    [confirmed, setConfirmed] = useState(false),
    [promotions, setPromotions] = useState<Promotion[]>([]),
    action = useAction(),
    toast = useToast();
  const p = data.data,
    open =
      p &&
      ["draft", "submitted", "changes_requested", "conflict"].includes(
        p.status,
      ),
    self =
      p && (p.author_identity || p.author) === (actor?.person || actor?.name),
    review = canReview(actor) && !self && p?.last_editor !== actor?.name,
    double =
      !!p?.notes?.needs_double_confirm ||
      (p?.pages?.length || 0) > 5 ||
      p?.pages?.some((p) => p.level === "must"),
    questions = !!p?.notes?.questions?.length;
  const begin = (kind: string) => {
    action.clear();
    setDecision(kind);
    setReason("");
    setConfirmed(false);
    setPromotions(p?.notes?.accept_body?.promote || []);
  };
  const decide = () =>
    action.run(async () => {
      const payload =
        decision === "accept"
          ? {
              promote: promotions,
              deprecate: p?.notes?.accept_body?.deprecate || [],
            }
          : decision === "request-changes"
            ? { comment: reason }
            : { reason };
      await write(`/proposals/${id}/${decision}`, payload);
      await invalidate();
      setDecision("");
      toast(
        decision === "accept"
          ? "Изменения приняты. Вики обновлена."
          : "Решение сохранено",
      );
    });
  if (data.isPending) return <Loading lines={7} />;
  if (!p) return <ErrorBanner error={data.error} />;
  return (
    <div className="page-enter">
      <Link className="back-link" to="/proposals">
        <ArrowLeft size={15} />
        Очередь ревью
      </Link>
      <div className="document-header">
        <div className="document-labels">
          <Badge value={p.status} />
          <Badge value={p.kind} />
          <code>{p.pid.slice(0, 12)}</code>
        </div>
        <h1>{p.title}</h1>
        <p>
          {p.description ||
            p.notes?.summary ||
            "Предложение изменений в общую базу знаний."}
        </p>
        <div className="proposal-byline">
          <span className="avatar small">
            {p.author.slice(0, 1).toUpperCase()}
          </span>
          <strong>
            <PersonName
              identity={p.author_identity || p.author}
              fallback={p.author}
            />
          </strong>
          <span>· {date(p.created_at)}</span>
        </div>
      </div>
      <div className="review-summary">
        <div>
          <strong>{diff.data?.pages.length ?? "—"}</strong>
          <span>изменённых страниц</span>
        </div>
        <div>
          <strong>{impact.data?.profiles.length ?? "—"}</strong>
          <span>затронутых профилей</span>
        </div>
        <div>
          <strong>{impact.data?.pages.length ?? "—"}</strong>
          <span>связанных страниц</span>
        </div>
        <div className="review-summary-status">
          <ShieldCheck size={21} />
          <span>
            Решение
            <br />
            <strong>принимает человек</strong>
          </span>
        </div>
      </div>
      {p.review_comment && (
        <div className="callout">
          <strong>Комментарий ревьюера</strong>
          <p>{p.review_comment}</p>
        </div>
      )}
      <div className="tabs">
        <button
          className={tab === "diff" ? "active" : ""}
          onClick={() => setTab("diff")}
        >
          Изменения <span>{diff.data?.pages.length || 0}</span>
        </button>
        <button
          className={tab === "impact" ? "active" : ""}
          onClick={() => setTab("impact")}
        >
          <GitBranch size={15} />
          Влияние
        </button>
        <button
          className={tab === "checks" ? "active" : ""}
          onClick={() => setTab("checks")}
        >
          Проверки
        </button>
      </div>
      <ErrorBanner error={diff.error || impact.error || action.error} />
      {tab === "diff" ? (
        diff.isPending ? (
          <Loading />
        ) : (
          diff.data?.pages.map((page) => (
            <section className="diff-file" key={page.id}>
              <div className="diff-file-header">
                <span className={`diff-status ${page.change}`}>
                  {page.change === "added"
                    ? "+"
                    : page.change === "deleted"
                      ? "−"
                      : "~"}
                </span>
                <strong>{page.id}</strong>
                <Badge value={page.change} />
              </div>
              {page.warnings?.map((w, i) => (
                <div className="error-banner" key={i}>
                  {w.message}
                </div>
              ))}
              <div className="metadata-diff">
                {page.frontmatter_diff
                  .filter(
                    (f) =>
                      ![
                        "created",
                        "updated",
                        "verified_at",
                        "verified_by",
                      ].includes(f.field),
                  )
                  .map((f) => (
                    <div key={f.field}>
                      <code>{f.field}</code>
                      <span className="before">{value(f.before)}</span>
                      <span>→</span>
                      <span className="after">{value(f.after)}</span>
                    </div>
                  ))}
              </div>
              {page.sections.map((s) => (
                <div className="diff-section" key={s.heading}>
                  <h4>{s.heading}</h4>
                  <div className="diff-code">
                    {s.unified_diff
                      .split("\n")
                      .filter(
                        (l) => !l.startsWith("---") && !l.startsWith("+++"),
                      )
                      .map((line, i) => (
                        <div
                          key={i}
                          className={
                            line.startsWith("+")
                              ? "addition"
                              : line.startsWith("-")
                                ? "deletion"
                                : line.startsWith("@@")
                                  ? "diff-marker"
                                  : ""
                          }
                        >
                          <span className="line-number">{i + 1}</span>
                          <code>{line || " "}</code>
                        </div>
                      ))}
                  </div>
                </div>
              ))}
            </section>
          ))
        )
      ) : tab === "impact" ? (
        <div className="impact-panel">
          <h3>Профили инструкций</h3>
          <div className="tag-list">
            {impact.data?.profiles.map((profile) => (
              <Link
                className="tag"
                key={profile}
                to={`/policies?profile=${profile}`}
              >
                {profile}
                <ArrowUpRight size={13} />
              </Link>
            ))}
            {!impact.data?.profiles.length && (
              <p className="muted">Профили не затронуты</p>
            )}
          </div>
          <h3>Связанные страницы и действующие правила</h3>
          {[...(impact.data?.pages || []), ...(impact.data?.rules || [])]
            .filter((p, i, rows) => rows.findIndex((r) => r.id === p.id) === i)
            .map((page) => (
              <Link
                className="impact-row"
                to={`/pages/${page.id}`}
                key={page.id}
              >
                <div>
                  <strong>{page.title}</strong>
                  <p>{page.summary}</p>
                </div>
                <Badge value={page.level || page.type} />
                <ArrowUpRight size={16} />
              </Link>
            ))}
        </div>
      ) : (
        <div className="checks-panel">
          {canWrite(actor) && open && (
            <button
              className="button"
              onClick={() =>
                action.run(async () => {
                  await validateProposal(id);
                  await invalidate();
                  toast("Проверки обновлены");
                })
              }
            >
              Перепроверить предложение
            </button>
          )}
          {[
            ...(diff.data?.validation.errors || []),
            ...(diff.data?.validation.warnings || []),
          ].map((issue, i) => (
            <div className="check-issue" key={i}>
              <Badge value={issue.severity} />
              <div>
                <strong>{issue.message}</strong>
                <p>{issue.hint}</p>
                {issue.page && <code>{issue.page}</code>}
              </div>
            </div>
          ))}
          {!diff.data?.validation.errors.length &&
            !diff.data?.validation.warnings.length && (
              <Empty
                icon={Check}
                title="Замечаний нет"
                text="Проверьте смысл изменений и их влияние перед принятием."
              />
            )}
        </div>
      )}
      {open && (
        <div className="review-decision-bar">
          <div>
            <strong>
              {self
                ? "Ваше предложение ждёт другого ревьюера"
                : questions
                  ? "В плане есть вопросы к человеку"
                  : "Всё проверили?"}
            </strong>
            <span>
              {questions
                ? "Уточните план в чате перед принятием."
                : "Решение и изменения останутся в истории."}
            </span>
          </div>
          <div className="decision-buttons">
            {canWrite(actor) && (
              <Link className="button" to={`/chat?bind=${id}&type=proposal`}>
                <MessageSquare size={15} />
                Обсудить
              </Link>
            )}
            {review && (
              <>
                <button
                  className="button"
                  onClick={() => begin("request-changes")}
                >
                  На доработку
                </button>
                <button
                  className="button danger-quiet"
                  onClick={() => begin("reject")}
                >
                  Отклонить
                </button>
                <button
                  className="button primary"
                  disabled={
                    questions ||
                    !!diff.data?.validation.errors.length ||
                    !diff.data
                  }
                  onClick={() => begin("accept")}
                >
                  <Check size={16} />
                  Принять
                </button>
              </>
            )}
            {self && canWrite(actor) && (
              <button
                className="button danger-quiet"
                onClick={() => begin("abandon")}
              >
                Отменить предложение
              </button>
            )}
          </div>
        </div>
      )}
      {p.status === "accepted" && canReview(actor) && (
        <div className="review-decision-bar">
          <span>Изменения уже вошли в базу знаний.</span>
          <button className="button" onClick={() => begin("revert")}>
            <RotateCcw size={15} />
            Откатить принятие
          </button>
        </div>
      )}
      {decision && (
        <Modal
          title={
            decision === "accept"
              ? "Принять изменения"
              : decision === "revert"
                ? "Откатить это предложение"
                : decision === "reject"
                  ? "Отклонить предложение"
                  : decision === "abandon"
                    ? "Отменить предложение"
                    : "Запросить доработку"
          }
          wide={decision === "accept"}
          onClose={() => {
            if (!action.busy) setDecision("");
          }}
        >
          <p className="modal-description">{p.title}</p>
          {decision === "accept" ? (
            <>
              <p className="muted">
                Выберите, какие правила войдут в инструкции. Остальные
                сохранятся кандидатами.
              </p>
              {p.pages
                ?.filter(
                  (page) =>
                    page.type === "rule" && page.lifecycle === "candidate",
                )
                .map((page) => {
                  const promotion = promotions.find((v) => v.id === page.id);
                  return (
                    <div className="promotion-choice" key={page.id}>
                      <label className="check-label">
                        <input
                          type="checkbox"
                          checked={!!promotion}
                          onChange={(e) =>
                            setPromotions((values) =>
                              e.target.checked
                                ? [...values, { id: page.id, level: "should" }]
                                : values.filter((v) => v.id !== page.id),
                            )
                          }
                        />
                        <span>
                          <strong>{page.title}</strong>
                          <small>{page.summary}</small>
                        </span>
                      </label>
                      {promotion && (
                        <div className="promotion-fields">
                          <select
                            aria-label={`Уровень ${page.title}`}
                            value={promotion.level}
                            onChange={(e) =>
                              setPromotions((values) =>
                                values.map((v) =>
                                  v.id === page.id
                                    ? {
                                        ...v,
                                        level: e.target.value as
                                          "must" | "should",
                                      }
                                    : v,
                                ),
                              )
                            }
                          >
                            <option value="should">
                              Рекомендация — should
                            </option>
                            <option value="must">Обязательно — must</option>
                          </select>
                          {promotion.level === "must" && (
                            <input
                              aria-label={`Владелец ${page.title}`}
                              placeholder="Владелец обязательного правила"
                              value={promotion.owner || ""}
                              onChange={(e) =>
                                setPromotions((values) =>
                                  values.map((v) =>
                                    v.id === page.id
                                      ? { ...v, owner: e.target.value }
                                      : v,
                                  ),
                                )
                              }
                            />
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              {!!p.notes?.accept_body?.deprecate.length && (
                <div className="callout">
                  <strong>Будут сняты с действия</strong>
                  {p.notes.accept_body.deprecate.map((d) => (
                    <p key={d.id}>
                      {d.id} — {d.reason}
                    </p>
                  ))}
                </div>
              )}
              {(double || promotions.some((v) => v.level === "must")) && (
                <label className="check-label important-confirm">
                  <input
                    type="checkbox"
                    checked={confirmed}
                    onChange={(e) => setConfirmed(e.target.checked)}
                  />
                  <span>
                    Я проверил влияние на обязательные правила и связанные
                    страницы и подтверждаю эти изменения.
                  </span>
                </label>
              )}
            </>
          ) : ["reject", "request-changes"].includes(decision) ? (
            <label className="field">
              Комментарий ревьюера
              <textarea
                rows={4}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="Объясните, что нужно изменить или почему предложение отклоняется"
              />
            </label>
          ) : (
            <p className="callout">
              {decision === "revert"
                ? "Принятые изменения будут отменены отдельным коммитом. Если страницы менялись позже, сервер остановит откат при конфликте."
                : "Черновик будет закрыт. Содержимое основной вики не изменится."}
            </p>
          )}
          <ErrorBanner error={action.error} />
          <div className="modal-footer">
            <button
              className="button"
              onClick={() => setDecision("")}
              disabled={action.busy}
            >
              Назад
            </button>
            <Submit
              busy={action.busy}
              disabled={
                decision === "accept"
                  ? ((double || promotions.some((v) => v.level === "must")) &&
                      !confirmed) ||
                    promotions.some(
                      (v) => v.level === "must" && !v.owner?.trim(),
                    )
                  : ["reject", "request-changes"].includes(decision) &&
                    !reason.trim()
              }
              onClick={() => void decide()}
            >
              {decision === "accept"
                ? "Принять и обновить вики"
                : "Подтвердить"}
            </Submit>
          </div>
        </Modal>
      )}
    </div>
  );
}
async function validateProposal(id: string) {
  const { api } = await import("../api");
  return api(`/proposals/${id}/validate`);
}
