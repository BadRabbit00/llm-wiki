import { useMemo, useRef, useState } from "react";
import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  type SimulationNodeDatum,
} from "d3-force";
import { Link, useSearchParams } from "react-router-dom";
import {
  ArrowUpRight,
  Maximize2,
  Minus,
  Network,
  Plus,
  Search,
  X,
} from "lucide-react";
import { useAPI } from "../api";
import type { Graph as GraphData, Page } from "../types";
import {
  Badge,
  Empty,
  ErrorBanner,
  Heading,
  Loading,
} from "../components/common";

interface Node extends SimulationNodeDatum {
  id: string;
  page: Page;
  x: number;
  y: number;
}
const palette: Record<string, string> = {
  rule: "#719777",
  source: "#c09059",
  pattern: "#9380b8",
  system: "#6694b4",
  app: "#6694b4",
  scope: "#b7b4aa",
  term: "#ba7d83",
  adr: "#d36b44",
  decision: "#d36b44",
};
export default function Graph() {
  const [params] = useSearchParams(),
    focus = params.get("focus"),
    [scopes, setScopes] = useState(false),
    [type, setType] = useState(""),
    [query, setQuery] = useState(""),
    [selected, setSelected] = useState<string | null>(focus),
    [zoom, setZoom] = useState(1),
    [pan, setPan] = useState({ x: 0, y: 0 }),
    drag = useRef<{ x: number; y: number; px: number; py: number } | null>(
      null,
    );
  const data = useAPI<GraphData>(
    focus
      ? `/graph/neighbors/${focus}?depth=2`
      : `/graph/export?include_scopes=${scopes}${type ? "&type=" + type : ""}`,
  );
  const layout = useMemo(() => {
    const nodes = (data.data?.nodes || [])
      .slice(0, 350)
      .map((page, i): Node => ({
        id: page.id,
        page,
        x: 550 + Math.cos(i * 2.399) * Math.sqrt(i) * 19,
        y: 310 + Math.sin(i * 2.399) * Math.sqrt(i) * 19,
      }));
    const ids = new Set(nodes.map((n) => n.id));
    const edges = (data.data?.edges || []).filter(
      (e) => ids.has(e.src) && ids.has(e.dst),
    );
    const links = edges.map((e) => ({ ...e, source: e.src, target: e.dst }));
    const simulation = forceSimulation(nodes)
      .force("charge", forceManyBody().strength(-180))
      .force(
        "link",
        forceLink<Node, (typeof links)[number]>(links)
          .id((n) => n.id)
          .distance(95),
      )
      .force("center", forceCenter(550, 310))
      .force("collide", forceCollide(33))
      .stop();
    simulation.tick(170);
    return { nodes, edges };
  }, [data.data]);
  const index = new Map(layout.nodes.map((n) => [n.id, n])),
    current = index.get(selected || ""),
    connected = new Set(
      layout.edges
        .filter((e) => e.src === selected || e.dst === selected)
        .flatMap((e) => [e.src, e.dst]),
    );
  const shown = (node: Node) =>
    !query ||
    [node.page.title, node.id]
      .join(" ")
      .toLowerCase()
      .includes(query.toLowerCase());
  const reset = () => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
  };
  return (
    <div className="page-enter">
      <Heading
        eyebrow="БОЛЬШЕ ЧЕМ СПИСОК СТРАНИЦ"
        title="У каждого знания есть связи"
        description="Исследуйте контекст: от источника до правила и от решения до системы."
      >
        {focus && (
          <Link className="button" to="/graph">
            Вся база знаний
          </Link>
        )}
      </Heading>
      <div className="graph-toolbar">
        <div className="filter-search">
          <Search size={17} />
          <input
            placeholder="Найти узел…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Поиск в графе"
          />
        </div>
        {!focus && (
          <>
            <select
              aria-label="Тип узлов"
              value={type}
              onChange={(e) => setType(e.target.value)}
            >
              <option value="">Все типы</option>
              <option value="rule">Правила</option>
              <option value="source">Источники</option>
              <option value="pattern">Паттерны</option>
              <option value="system">Системы</option>
            </select>
            <label className="check-label">
              <input
                type="checkbox"
                checked={scopes}
                onChange={(e) => setScopes(e.target.checked)}
              />
              Области применения
            </label>
          </>
        )}
      </div>
      <ErrorBanner error={data.error} />
      <div className="graph-canvas">
        {data.isPending ? (
          <Loading />
        ) : !layout.nodes.length ? (
          <Empty
            icon={Network}
            title="Связи ещё появятся"
            text="Добавьте страницы, источники и правила. Их отношения станут видны на графе."
          />
        ) : (
          <svg
            viewBox={`${-pan.x} ${-pan.y} ${1100 / zoom} ${620 / zoom}`}
            role="img"
            aria-label="Интерактивный граф знаний"
            onPointerDown={(e) => {
              if ((e.target as Element).closest("[data-node]")) return;
              drag.current = {
                x: e.clientX,
                y: e.clientY,
                px: pan.x,
                py: pan.y,
              };
              e.currentTarget.setPointerCapture(e.pointerId);
            }}
            onPointerMove={(e) => {
              if (drag.current) {
                const scale =
                  1100 / zoom / e.currentTarget.getBoundingClientRect().width;
                setPan({
                  x: drag.current.px + (e.clientX - drag.current.x) * scale,
                  y: drag.current.py + (e.clientY - drag.current.y) * scale,
                });
              }
            }}
            onPointerUp={() => (drag.current = null)}
            onPointerCancel={() => (drag.current = null)}
          >
            <g>
              {layout.edges.map((edge, i) => {
                const a = index.get(edge.src)!,
                  b = index.get(edge.dst)!;
                return (
                  <line
                    key={i}
                    x1={a.x}
                    y1={a.y}
                    x2={b.x}
                    y2={b.y}
                    stroke={
                      edge.src === selected || edge.dst === selected
                        ? "#d46b48"
                        : "var(--graph-edge)"
                    }
                    strokeWidth={
                      edge.src === selected || edge.dst === selected ? 2 : 1
                    }
                    opacity={selected && !connected.has(edge.src) ? 0.25 : 0.8}
                  />
                );
              })}
            </g>
            <g>
              {layout.nodes.map((node) => (
                <g
                  key={node.id}
                  data-node={node.id}
                  className="graph-node"
                  transform={`translate(${node.x},${node.y})`}
                  role="button"
                  tabIndex={0}
                  aria-label={node.page.title}
                  onClick={() => setSelected(node.id)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      setSelected(node.id);
                    }
                  }}
                  opacity={
                    shown(node) &&
                    (!selected ||
                      connected.has(node.id) ||
                      node.id === selected)
                      ? 1
                      : 0.22
                  }
                >
                  <circle
                    r={node.id === selected ? 23 : 18}
                    fill={palette[node.page.type] || "#93a4a0"}
                    stroke={
                      node.id === selected
                        ? "var(--accent)"
                        : "var(--graph-surface)"
                    }
                    strokeWidth={node.id === selected ? 4 : 5}
                  />
                  <text
                    y="4"
                    textAnchor="middle"
                    fill="white"
                    fontSize="11"
                    fontWeight="700"
                  >
                    {node.page.type === "scope"
                      ? "#"
                      : node.page.title.slice(0, 1).toUpperCase()}
                  </text>
                  <text y="37" textAnchor="middle" className="graph-node-label">
                    {node.page.title.length > 25
                      ? node.page.title.slice(0, 24) + "…"
                      : node.page.title}
                  </text>
                  <title>{node.page.title}</title>
                </g>
              ))}
            </g>
          </svg>
        )}
        <div className="graph-legend">
          {[
            ["rule", "Правила"],
            ["source", "Источники"],
            ["pattern", "Паттерны"],
            ["system", "Системы"],
          ].map(([key, label]) => (
            <span key={key}>
              <i style={{ background: palette[key] }} />
              {label}
            </span>
          ))}
        </div>
        <div className="graph-zoom">
          <button
            aria-label="Увеличить граф"
            onClick={() => setZoom(Math.min(zoom * 1.25, 4))}
          >
            <Plus size={17} />
          </button>
          <span>{Math.round(zoom * 100)}%</span>
          <button
            aria-label="Уменьшить граф"
            onClick={() => setZoom(Math.max(zoom / 1.25, 0.35))}
          >
            <Minus size={17} />
          </button>
          <button aria-label="Сбросить масштаб" onClick={reset}>
            <Maximize2 size={16} />
          </button>
        </div>
        {current && (
          <div className="graph-inspector">
            <button
              className="icon-button inspector-close"
              aria-label="Снять выделение"
              onClick={() => setSelected(null)}
            >
              <X size={17} />
            </button>
            <Badge value={current.page.type} />
            <h3>{current.page.title}</h3>
            <p>{current.page.summary}</p>
            <small>
              {
                layout.edges.filter(
                  (e) => e.src === selected || e.dst === selected,
                ).length
              }{" "}
              связей
            </small>
            {current.page.type !== "scope" && (
              <Link
                className="button primary small"
                to={`/pages/${current.id}`}
              >
                Открыть страницу <ArrowUpRight size={14} />
              </Link>
            )}
            <div>
              {layout.edges
                .filter((e) => e.src === selected || e.dst === selected)
                .slice(0, 5)
                .map((e, i) => (
                  <button
                    className="graph-relation"
                    key={i}
                    onClick={() =>
                      setSelected(e.src === selected ? e.dst : e.src)
                    }
                  >
                    <code>{e.rel}</code>
                    <span>
                      {
                        index.get(e.src === selected ? e.dst : e.src)?.page
                          .title
                      }
                    </span>
                  </button>
                ))}
            </div>
          </div>
        )}
      </div>
      <div className="result-footer">
        <span>
          {layout.nodes.length} узлов · {layout.edges.length} связей
          {(data.data?.nodes.length || 0) > 350
            ? " · Показаны первые 350 узлов. Выберите тип или откройте окружение страницы."
            : ""}
        </span>
        <span>
          Нажмите на узел, чтобы увидеть контекст · Перетаскивайте фон
        </span>
      </div>
    </div>
  );
}
