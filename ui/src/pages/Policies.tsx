import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ArrowUpRight, Download, FileText, ShieldCheck } from "lucide-react";
import { useAPI } from "../api";
import type { Profile } from "../types";
import {
  Badge,
  CopyButton,
  ErrorBanner,
  Heading,
  Loading,
  Markdown,
  TextList,
} from "../components/common";

interface Policy {
  version: string;
  markdown: string;
  used_tokens: number;
  budget_tokens: number;
  over_budget: boolean;
  scopes: string[];
  included: { id: string; level: string; category: string; tokens: number }[];
  omitted: { id: string; reason: string }[];
}
export default function Policies() {
  const profiles = useAPI<Profile[]>("/profiles"),
    [params, setParams] = useSearchParams(),
    profile = params.get("profile") || profiles.data?.[0]?.id || "",
    [budget, setBudget] = useState(2000),
    [enforced, setEnforced] = useState("keep_must"),
    [raw, setRaw] = useState(false);
  useEffect(() => {
    setBudget(
      profiles.data?.find((p) => p.id === profile)?.budget_tokens || 2000,
    );
  }, [profile, profiles.data]);
  const result = useAPI<Policy>(
      `/policies/compile?profile=${encodeURIComponent(profile)}&budget_tokens=${budget}&enforced=${enforced}&explain=true`,
      false,
      !!profile && budget > 0 && budget <= 24000,
    ),
    policy = result.data;
  const exportText = policy
    ? `<!-- wikisvc:begin version=${policy.version} -->\n${policy.markdown.trim()}\n<!-- wikisvc:end -->\n`
    : "";
  const download = () => {
    const url = URL.createObjectURL(
      new Blob([exportText], { type: "text/markdown;charset=utf-8" }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = "AGENTS.md";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  return (
    <div className="page-enter">
      <Heading
        eyebrow="ПРАВИЛЬНЫЙ КОНТЕКСТ"
        title="Одна инструкция. Общее направление."
        description="Соберите действующие правила команды в готовый контекст для агента."
      >
        {policy && (
          <>
            <CopyButton text={exportText} />
            <button className="button primary" onClick={download}>
              <Download size={16} />
              Скачать AGENTS.md
            </button>
          </>
        )}
      </Heading>
      <div className="policy-layout">
        <aside className="policy-controls">
          <div className="meta-card">
            <h3>
              <ShieldCheck size={18} />
              Параметры инструкции
            </h3>
            <label className="field">
              Профиль
              <select
                value={profile}
                onChange={(e) => setParams({ profile: e.target.value })}
              >
                {profiles.data?.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.title}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              Бюджет токенов
              <input
                type="number"
                min="100"
                max="24000"
                step="100"
                value={budget}
                onChange={(e) => setBudget(+e.target.value)}
              />
            </label>
            <label className="field">
              Автоматически проверяемые
              <select
                value={enforced}
                onChange={(e) => setEnforced(e.target.value)}
              >
                <option value="keep_must">Сохранять обязательные</option>
                <option value="none">Скрывать проверяемые</option>
                <option value="all">Включать все</option>
              </select>
            </label>
            <h4>Области применения</h4>
            <TextList
              values={
                policy?.scopes ||
                profiles.data?.find((p) => p.id === profile)?.scopes
              }
            />
          </div>
          {policy && (
            <div className="policy-budget">
              <span>КОНТЕКСТ</span>
              <div>
                <strong>{policy.used_tokens.toLocaleString("ru")}</strong>
                <span>/ {policy.budget_tokens.toLocaleString("ru")}</span>
              </div>
              <progress
                value={Math.min(policy.used_tokens, policy.budget_tokens)}
                max={policy.budget_tokens}
              />
              <p>
                {policy.included.length} правил включено
                {policy.omitted.length
                  ? ` · ${policy.omitted.length} пропущено`
                  : ""}
              </p>
              {policy.over_budget && (
                <p className="callout">
                  Обязательные правила превышают бюджет. Они сохранены
                  полностью.
                </p>
              )}
            </div>
          )}
        </aside>
        <section className="policy-paper">
          <div className="policy-paper-toolbar">
            <span>
              <FileText size={17} />
              AGENTS.md
            </span>
            <div className="segmented">
              <button
                className={!raw ? "selected" : ""}
                onClick={() => setRaw(false)}
              >
                Предпросмотр
              </button>
              <button
                className={raw ? "selected" : ""}
                onClick={() => setRaw(true)}
              >
                Markdown
              </button>
            </div>
            {policy && <code>v{policy.version}</code>}
          </div>
          <ErrorBanner error={result.error || profiles.error} />
          {result.isPending ? (
            <Loading lines={8} />
          ) : raw ? (
            <pre className="policy-raw">{exportText}</pre>
          ) : (
            <Markdown
              text={
                policy?.markdown || "Выберите профиль для сборки инструкции."
              }
            />
          )}
        </section>
      </div>
      {policy && (
        <section className="policy-explain panel">
          <div className="section-title">
            <h2>Что попало в контекст</h2>
            <span className="muted">
              Прозрачная сборка из действующих правил
            </span>
          </div>
          <div className="included-grid">
            {policy.included.map((p) => (
              <Link key={p.id} to={`/pages/${p.id}`}>
                <Badge value={p.level} />
                <code>{p.id}</code>
                <span>{p.tokens} ток.</span>
                <ArrowUpRight size={14} />
              </Link>
            ))}
          </div>
          {!!policy.omitted.length && (
            <details>
              <summary>
                Почему некоторые правила не включены · {policy.omitted.length}
              </summary>
              {policy.omitted.map((p) => (
                <div className="omitted-rule" key={p.id}>
                  <Link to={`/pages/${p.id}`}>{p.id}</Link>
                  <span>
                    {(
                      {
                        budget: "Не поместилось в бюджет",
                        enforced: "Проверяется автоматически",
                        lifecycle: "Не введено в действие",
                        scope: "Другая область",
                        level: "Уровень idea",
                      } as Record<string, string>
                    )[p.reason] || p.reason}
                  </span>
                </div>
              ))}
            </details>
          )}
        </section>
      )}
    </div>
  );
}
