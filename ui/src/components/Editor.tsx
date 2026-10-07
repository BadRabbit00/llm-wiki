import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { invalidate, useAPI, write } from "../api";
import type { Page, Proposal, Schema } from "../types";
import {
  ErrorBanner,
  Loading,
  Markdown,
  Modal,
  Submit,
  useAction,
  useToast,
} from "./common";

const protectedFields = new Set([
  "level",
  "lifecycle",
  "priority",
  "owner",
  "deprecated_reason",
  "verified_by",
  "verified_at",
]);
const extraLabels: Record<string, string> = {
  category: "Категория",
  applies_to: "Области применения",
  origin: "Происхождение",
  enforced_by: "Автоматическая проверка",
  parent: "Родительская страница",
  raw_path: "Путь источника",
  raw_sha256: "SHA-256 источника",
  system: "Система",
};
const list = (value: string) =>
  value
    .split(",")
    .map((v) => v.trim())
    .filter(Boolean);
export default function Editor({
  page,
  onClose,
  defaultType = "rule",
}: {
  page?: Page;
  onClose: () => void;
  defaultType?: string;
}) {
  const schema = useAPI<Schema>("/schema"),
    [type, setType] = useState(page?.type || defaultType),
    [id, setId] = useState(page?.id || ""),
    [title, setTitle] = useState(page?.title || ""),
    [summary, setSummary] = useState(page?.summary || ""),
    [body, setBody] = useState(page?.body_md || ""),
    [sources, setSources] = useState(page?.sources?.join(", ") || ""),
    [aliases, setAliases] = useState(page?.aliases?.join(", ") || ""),
    [tags, setTags] = useState(page?.tags?.join(", ") || ""),
    [sensitivity, setSensitivity] = useState(page?.sensitivity || "internal"),
    [extras, setExtras] = useState<Record<string, string>>({}),
    [preview, setPreview] = useState(false),
    [pid, setPid] = useState("");
  const action = useAction(),
    navigate = useNavigate(),
    toast = useToast(),
    definition = schema.data?.page_types[type];
  useEffect(() => {
    if (definition) {
      if (!page) {
        setId(`${definition.prefix}-`);
        setBody(
          definition.required_sections.map((s) => `## ${s}\n\n`).join("\n"),
        );
      }
      setExtras(
        Object.fromEntries(
          Object.entries(definition.extra_fields)
            .filter(([key]) => !protectedFields.has(key))
            .map(([key, field]) => {
              const value =
                page?.extra?.[key] ??
                (page as unknown as Record<string, unknown>)?.[key] ??
                field.default ??
                (key === "applies_to"
                  ? ["*"]
                  : key === "origin"
                    ? "team"
                    : (field.enum?.[0] ?? ""));
              return [
                key,
                Array.isArray(value) ? value.join(", ") : String(value),
              ];
            }),
        ),
      );
    }
  }, [definition, page]);
  const save = () =>
    action.run(async () => {
      const metadata: Record<string, unknown> = {
        ...page?.extra,
        id,
        type,
        title,
        summary,
        sensitivity,
        sources: list(sources),
        aliases: list(aliases),
        tags: list(tags),
        relations: page?.relations || {},
      };
      Object.entries(extras).forEach(([key, value]) => {
        const field = definition?.extra_fields[key];
        if (value || field?.required)
          metadata[key] =
            field?.type === "list"
              ? list(value)
              : field?.type === "int"
                ? Number(value)
                : value;
        else delete metadata[key];
      });
      let proposalId = pid;
      if (!proposalId) {
        const created = await write<Proposal>("/proposals", {
          title: `${page ? "Изменить" : "Добавить"}: ${title}`,
          kind: "manual",
        });
        proposalId = created.pid;
        setPid(proposalId);
      }
      await write(
        `/proposals/${proposalId}/pages/${id}`,
        {
          frontmatter: metadata,
          body_md: body,
          ...(page ? { base_version: page.version } : {}),
        },
        "PUT",
      );
      await write(`/proposals/${proposalId}/submit`);
      await invalidate();
      toast("Предложение отправлено на ревью");
      onClose();
      navigate(`/proposals/${proposalId}`);
    });
  return (
    <Modal
      title={page ? "Предложить изменение" : "Новое знание"}
      onClose={onClose}
      wide
    >
      {schema.isPending ? (
        <Loading />
      ) : (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void save();
          }}
        >
          <div className="editor-meta">
            <label className="field">
              Тип
              <select
                value={type}
                disabled={!!page || !!pid}
                onChange={(e) => setType(e.target.value)}
              >
                {Object.values(schema.data?.page_types || {}).map((d) => (
                  <option key={d.type} value={d.type}>
                    {d.title_ru}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              Идентификатор
              <input
                value={id}
                disabled={!!page || !!pid}
                pattern="[a-z][a-z0-9-]+"
                onChange={(e) => setId(e.target.value)}
                required
              />
            </label>
          </div>
          <label className="field">
            Заголовок
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              minLength={3}
              maxLength={120}
              required
              placeholder="Коротко и по делу"
            />
          </label>
          <label className="field">
            Краткий тезис{" "}
            <span className="field-note">
              {summary.length}/{type === "rule" ? 160 : 200}
            </span>
            <textarea
              value={summary}
              onChange={(e) => setSummary(e.target.value)}
              minLength={20}
              maxLength={type === "rule" ? 160 : 200}
              rows={2}
              required
              placeholder="Одна самодостаточная мысль, которую стоит запомнить"
            />
          </label>
          <div className="editor-meta">
            {Object.entries(definition?.extra_fields || {})
              .filter(([key]) => !protectedFields.has(key))
              .map(([key, field]) => (
                <label className="field" key={key}>
                  {extraLabels[key] || key}
                  {field.type === "list" && (
                    <span className="field-note">через запятую</span>
                  )}
                  {field.enum?.length ? (
                    <select
                      value={extras[key] || ""}
                      onChange={(e) =>
                        setExtras({ ...extras, [key]: e.target.value })
                      }
                    >
                      {field.enum.map((v) => (
                        <option key={v}>{v}</option>
                      ))}
                    </select>
                  ) : (
                    <input
                      value={extras[key] || ""}
                      onChange={(e) =>
                        setExtras({ ...extras, [key]: e.target.value })
                      }
                      type={field.type === "int" ? "number" : "text"}
                      required={field.required}
                    />
                  )}
                </label>
              ))}
          </div>
          <div className="editor-toolbar">
            <strong>Содержание</strong>
            <div className="segmented">
              <button
                type="button"
                className={!preview ? "selected" : ""}
                onClick={() => setPreview(false)}
              >
                Markdown
              </button>
              <button
                type="button"
                className={preview ? "selected" : ""}
                onClick={() => setPreview(true)}
              >
                Предпросмотр
              </button>
            </div>
          </div>
          {preview ? (
            <div className="editor-preview">
              <Markdown text={body} />
            </div>
          ) : (
            <textarea
              className="markdown-editor"
              aria-label="Содержание страницы"
              value={body}
              onChange={(e) => setBody(e.target.value)}
              rows={14}
              required
            />
          )}
          <details className="advanced">
            <summary>Источники и метаданные</summary>
            <div className="editor-meta">
              <label className="field">
                Источники <span className="field-note">ID через запятую</span>
                <input
                  value={sources}
                  onChange={(e) => setSources(e.target.value)}
                />
              </label>
              <label className="field">
                Псевдонимы
                <input
                  value={aliases}
                  onChange={(e) => setAliases(e.target.value)}
                />
              </label>
              <label className="field">
                Теги
                <input
                  value={tags}
                  onChange={(e) => setTags(e.target.value)}
                  list="known-tags"
                />
                <datalist id="known-tags">
                  {schema.data?.tags.map((t) => (
                    <option key={t}>{t}</option>
                  ))}
                </datalist>
              </label>
              <label className="field">
                Видимость
                <select
                  value={sensitivity}
                  onChange={(e) => setSensitivity(e.target.value)}
                >
                  <option value="public">Публично</option>
                  <option value="internal">Внутренний</option>
                  <option value="restricted">Ограниченный</option>
                </select>
              </label>
            </div>
          </details>
          <ErrorBanner error={action.error || schema.error} />
          <div className="modal-footer">
            <span className="muted">
              Изменения появятся в вики после ревью.
            </span>
            <Submit busy={action.busy}>Отправить на ревью</Submit>
          </div>
        </form>
      )}
    </Modal>
  );
}
