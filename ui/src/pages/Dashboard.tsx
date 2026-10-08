import { Link } from "react-router-dom";
import {
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  Check,
  FileCheck2,
  GitBranch,
  Library,
  MessageSquare,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { useAll, useAPI } from "../api";
import { PersonName } from "../components/PersonName";
import type { Page, Proposal, Finding } from "../types";
import {
  Badge,
  Empty,
  ErrorBanner,
  Loading,
  SectionTitle,
  date,
} from "../components/common";

export default function Dashboard() {
  const pages = useAll<Page>("/pages"),
    rules = useAll<Page>("/rules?lifecycle=candidate,active,deprecated"),
    proposals = useAll<Proposal>("/proposals"),
    findings = useAPI<{ items: Finding[] }>("/findings?status=open&limit=5");
  const recent = [...(pages.data || [])]
    .sort((a, b) => (b.updated || "").localeCompare(a.updated || ""))
    .slice(0, 5);
  const waiting = (proposals.data || []).filter((p) =>
      ["submitted", "draft", "changes_requested"].includes(p.status),
    ),
    active = (rules.data || []).filter((r) => r.lifecycle === "active"),
    candidates = (rules.data || []).filter((r) => r.lifecycle === "candidate");
  const stats = [
    {
      label: "Страниц в базе",
      value: pages.data?.length,
      detail: "Общая память команды",
      icon: BookOpen,
      to: "/pages",
      tone: "blue",
    },
    {
      label: "Действующих правил",
      value: rules.data ? active.length : undefined,
      detail: "Контекст для ваших агентов",
      icon: ShieldCheck,
      to: "/rules?lifecycle=active",
      tone: "green",
    },
    {
      label: "Ждут решения",
      value: proposals.data ? waiting.length : undefined,
      detail: "Предложения и черновики",
      icon: FileCheck2,
      to: "/proposals",
      tone: "orange",
    },
    {
      label: "Правил-кандидатов",
      value: rules.data ? candidates.length : undefined,
      detail: "Идеи, которым нужен взгляд",
      icon: GitBranch,
      to: "/rules?lifecycle=candidate",
      tone: "purple",
    },
  ];
  return (
    <div className="dashboard page-enter">
      <div className="dashboard-greeting">
        <div>
          <div className="eyebrow">ВАШЕ РАБОЧЕЕ ПРОСТРАНСТВО</div>
          <h1>
            Всё знание. <span className="serif-accent">В одном месте.</span>
          </h1>
          <p>У решений есть история. У команды — общий контекст.</p>
        </div>
        <span className="date-stamp">
          {new Intl.DateTimeFormat("ru", {
            day: "numeric",
            month: "long",
            weekday: "long",
          }).format(new Date())}
        </span>
      </div>
      <section className="hero-panel">
        <div className="hero-copy">
          <div className="hero-label">
            <Sparkles size={14} /> ОТ МЫСЛИ К ПРАВИЛУ
          </div>
          <h2>
            Расскажите, как
            <br />
            работает ваша команда.
          </h2>
          <p>
            Агент найдёт связи, предложит изменения
            <br />и подготовит их к вашему решению.
          </p>
          <Link className="button primary" to="/chat">
            Начать разговор <ArrowUpRight size={17} />
          </Link>
        </div>
        <div className="hero-workflow" aria-hidden="true">
          <div className="workflow-card conversation">
            <div className="workflow-card-icon">
              <MessageSquare size={18} />
            </div>
            <div>
              <span>Вы</span>
              <p>«Новые сервисы пишем на FastAPI»</p>
            </div>
          </div>
          <div className="workflow-line">
            <span />
            <span />
            <span />
            <ArrowDownRight size={18} />
          </div>
          <div className="workflow-card decision">
            <div className="workflow-card-top">
              <span className="tiny-label">ПЛАН ИЗМЕНЕНИЙ</span>
              <span className="badge badge-candidate">На проверку</span>
            </div>
            <h4>Единый стек веб-сервисов</h4>
            <p>Правило · Архитектура · Python</p>
            <div className="workflow-card-footer">
              <span>
                <GitBranch size={13} /> Связи учтены
              </span>
              <span>
                <ShieldCheck size={13} /> Решаете вы
              </span>
            </div>
          </div>
          <span className="hero-annotation">
            Пример: мысль → проверенное знание
          </span>
        </div>
        <div className="hero-orbit" />
      </section>
      <div className="stats-grid">
        {stats.map(({ label, value, detail, icon: Icon, to, tone }) => (
          <Link to={to} className="stat-card" key={label}>
            <div className="stat-top">
              <span>{label}</span>
              <Icon size={18} className={`text-${tone}`} />
            </div>
            <div className="stat-value">
              {value === undefined ? (
                <span className="skeleton-number" />
              ) : (
                value.toLocaleString("ru")
              )}
              <ArrowUpRight size={17} />
            </div>
            <p>{detail}</p>
          </Link>
        ))}
      </div>
      <ErrorBanner error={pages.error || rules.error || proposals.error} />
      <div className="dashboard-columns">
        <section className="panel">
          <SectionTitle
            title="На вашем радаре"
            to="/proposals"
            count={waiting.length}
          />
          {proposals.isPending ? (
            <Loading />
          ) : waiting.length ? (
            <div className="review-rows">
              {waiting.slice(0, 4).map((p) => (
                <Link
                  to={`/proposals/${p.pid}`}
                  className="review-row"
                  key={p.pid}
                >
                  <span className="row-symbol orange">
                    <FileCheck2 size={19} />
                  </span>
                  <div className="row-content">
                    <strong>{p.title}</strong>
                    <small>
                      <PersonName
                        identity={p.author_identity || p.author}
                        fallback={p.author}
                      />{" "}
                      <span>·</span> {date(p.created_at)}
                    </small>
                  </div>
                  <Badge value={p.status} />
                  <ArrowUpRight size={16} />
                </Link>
              ))}
            </div>
          ) : (
            <Empty
              icon={Check}
              title="Можно выдохнуть"
              text="Новых предложений пока нет. Когда агент подготовит изменения, они появятся здесь."
            />
          )}
          <div className="panel-bottom">
            <ShieldCheck size={15} />
            <span>Правила вступают в силу после решения человека.</span>
          </div>
        </section>
        <section className="panel">
          <SectionTitle title="Недавно обновлено" to="/pages" />
          {pages.isPending ? (
            <Loading />
          ) : recent.length ? (
            <div className="recent-rows">
              {recent.map((p) => (
                <Link to={`/pages/${p.id}`} className="recent-row" key={p.id}>
                  <span className="document-mini">
                    <BookOpen size={16} />
                  </span>
                  <div>
                    <strong>{p.title}</strong>
                    <span>
                      <Badge value={p.type} /> <small>{date(p.updated)}</small>
                    </span>
                  </div>
                  <Chevron />
                </Link>
              ))}
            </div>
          ) : (
            <Empty
              icon={BookOpen}
              title="Начните вашу историю"
              text="Загрузите первый источник или обсудите правило в чате."
            />
          )}
        </section>
      </div>
      <div className="section-title quick-heading">
        <h2>Продолжить работу</h2>
        <span className="muted">Знание становится полезнее с каждым шагом</span>
      </div>
      <div className="quick-grid">
        {[
          {
            to: "/sources",
            icon: Library,
            title: "Добавить источник",
            text: "Книга, документ или заметка",
            tone: "blue",
          },
          {
            to: "/graph",
            icon: GitBranch,
            title: "Увидеть связи",
            text: "Как знания влияют друг на друга",
            tone: "purple",
          },
          {
            to: "/policies",
            icon: ShieldCheck,
            title: "Собрать инструкцию",
            text: "Действующие правила для агента",
            tone: "green",
          },
        ].map(({ to, icon: Icon, title, text, tone }) => (
          <Link className="quick-card" to={to} key={to}>
            <span className={`row-symbol ${tone}`}>
              <Icon size={21} />
            </span>
            <div>
              <h3>{title}</h3>
              <p>{text}</p>
            </div>
            <ArrowUpRight size={18} />
          </Link>
        ))}
      </div>
      {!!findings.data?.items.length && (
        <section className="findings-strip">
          <Sparkles size={20} />
          <div>
            <strong>Есть знания, которым нужно внимание</strong>
            <p>{findings.data.items[0].summary}</p>
          </div>
          <Link className="button small" to="/proposals?tab=findings">
            Посмотреть находки <ArrowRight size={14} />
          </Link>
        </section>
      )}
    </div>
  );
}
function Chevron() {
  return <ArrowUpRight size={15} className="muted" />;
}
