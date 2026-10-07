import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  ArrowUpRight,
  BookOpen,
  FileText,
  LayoutGrid,
  List,
  Plus,
  Search,
  ShieldCheck,
} from "lucide-react";
import { useAll, useAPI } from "../api";
import { useAuth, canWrite } from "../auth";
import type { Page, Schema } from "../types";
import {
  Badge,
  Empty,
  ErrorBanner,
  Heading,
  Loading,
  TextList,
  date,
} from "../components/common";
import Editor from "../components/Editor";

export default function Knowledge({ rules = false }: { rules?: boolean }) {
  const data = useAll<Page>(
      rules
        ? "/rules?lifecycle=candidate,active,deprecated"
        : "/pages?lifecycle=candidate,active,deprecated",
    ),
    schema = useAPI<Schema>("/schema"),
    { actor } = useAuth(),
    [query, setQuery] = useState(""),
    [filter, setFilter] = useSearchParams(),
    [view, setView] = useState("list"),
    [create, setCreate] = useState(false);
  const selected = filter.get(rules ? "lifecycle" : "type") || "all";
  const rows = (data.data || []).filter(
    (p) =>
      (selected === "all" || (rules ? p.lifecycle : p.type) === selected) &&
      [p.title, p.summary, p.id, ...(p.applies_to || [])]
        .join(" ")
        .toLocaleLowerCase()
        .includes(query.toLocaleLowerCase()),
  );
  const counts = (value: string) =>
    data.data?.filter(
      (p) => value === "all" || (rules ? p.lifecycle : p.type) === value,
    ).length || 0;
  const tabs = rules
    ? [
        ["all", "Все правила"],
        ["active", "Действующие"],
        ["candidate", "Кандидаты"],
        ["deprecated", "Архив"],
      ]
    : [
        ["all", "Все страницы"],
        ["rule", "Правила"],
        ["source", "Источники"],
        ["pattern", "Паттерны"],
        ["adr", "Решения"],
      ];
  return (
    <div className="page-enter">
      <Heading
        eyebrow={rules ? "ПРИНЦИПЫ КОМАНДЫ" : "КОЛЛЕКТИВНАЯ ПАМЯТЬ"}
        title={rules ? "Правила, на которые можно опереться" : "База знаний"}
        description={
          rules
            ? "От договорённости до инструкции для каждого агента."
            : "Решения, процессы и опыт, которые остаются с командой."
        }
      >
        {canWrite(actor) && (
          <button className="button primary" onClick={() => setCreate(true)}>
            <Plus size={17} />
            {rules ? "Добавить правило" : "Создать страницу"}
          </button>
        )}
      </Heading>
      <div className="catalog-controls">
        <div className="tabs">
          {tabs.map(([value, label]) => (
            <button
              key={value}
              className={selected === value ? "active" : ""}
              onClick={() =>
                setFilter({ [rules ? "lifecycle" : "type"]: value })
              }
            >
              {label}
              <span>{counts(value)}</span>
            </button>
          ))}
        </div>
        <div className="catalog-toolbar">
          <div className="filter-search">
            <Search size={17} />
            <input
              aria-label="Фильтр страниц"
              placeholder="Название, тезис или область…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            {query && <button onClick={() => setQuery("")}>Сбросить</button>}
          </div>
          {!rules && (
            <select
              aria-label="Тип страницы"
              value={selected}
              onChange={(e) => setFilter({ type: e.target.value })}
            >
              <option value="all">Все типы</option>
              {Object.values(schema.data?.page_types || {}).map((t) => (
                <option key={t.type} value={t.type}>
                  {t.title_ru}
                </option>
              ))}
            </select>
          )}
          <div className="segmented icon-segment">
            <button
              className={view === "list" ? "selected" : ""}
              aria-label="Список"
              onClick={() => setView("list")}
            >
              <List size={17} />
            </button>
            <button
              className={view === "grid" ? "selected" : ""}
              aria-label="Карточки"
              onClick={() => setView("grid")}
            >
              <LayoutGrid size={17} />
            </button>
          </div>
        </div>
      </div>
      <ErrorBanner error={data.error} retry={() => void data.refetch()} />
      {data.isPending ? (
        <Loading lines={7} />
      ) : !rows.length ? (
        <Empty
          icon={rules ? ShieldCheck : BookOpen}
          title={
            query
              ? "Ничего не нашлось"
              : rules
                ? "Правила начинаются с разговора"
                : "Здесь будет память команды"
          }
          text={
            query
              ? "Попробуйте другой запрос или снимите фильтры."
              : "Добавьте первое знание вручную или расскажите агенту, как вы работаете."
          }
        >
          {canWrite(actor) && (
            <Link className="button" to="/chat">
              Обсудить с агентом <ArrowUpRight size={16} />
            </Link>
          )}
        </Empty>
      ) : (
        <div className={view === "grid" ? "knowledge-grid" : "knowledge-table"}>
          {view === "list" && (
            <div className="table-heading">
              <span>Название и содержание</span>
              <span>{rules ? "Уровень / статус" : "Тип / статус"}</span>
              <span>{rules ? "Области" : "Обновлено"}</span>
              <span />
            </div>
          )}
          {rows.map((page) => (
            <Link
              to={`/pages/${page.id}`}
              className="knowledge-row"
              key={page.id}
            >
              <div className="knowledge-title">
                <span
                  className={`row-symbol ${page.type === "rule" ? "green" : "blue"}`}
                >
                  {page.type === "rule" ? (
                    <ShieldCheck size={19} />
                  ) : (
                    <FileText size={19} />
                  )}
                </span>
                <div>
                  <strong>{page.title}</strong>
                  <p>{page.summary}</p>
                  {view === "grid" && <code>{page.id}</code>}
                </div>
              </div>
              <div className="knowledge-badges">
                <Badge value={rules ? page.level : page.type} />
                <Badge value={rules ? page.lifecycle : page.status} />
              </div>
              <div className="knowledge-meta">
                {rules ? (
                  <TextList values={page.applies_to?.slice(0, 2)} />
                ) : (
                  date(page.updated)
                )}
              </div>
              <ArrowUpRight className="row-arrow" size={16} />
            </Link>
          ))}
        </div>
      )}
      <div className="result-footer">
        <span>
          {rows.length} из {data.data?.length || 0}{" "}
          {rules ? "правил" : "страниц"}
        </span>
        <span>Изменения проходят через предложения и ревью</span>
      </div>
      {create && (
        <Editor
          defaultType={rules ? "rule" : "term"}
          onClose={() => setCreate(false)}
        />
      )}
    </div>
  );
}
