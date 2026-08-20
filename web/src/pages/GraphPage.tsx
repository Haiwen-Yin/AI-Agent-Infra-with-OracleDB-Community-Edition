import React, { useEffect, useRef, useState } from "react";
import { Activity, GitBranch, Layers3, Network, PlayCircle, RefreshCw, X } from "lucide-react";

type Lang = "zh" | "en";
type Row = Record<string, any>;
type Props = {
  lang: Lang;
  text: (zh: string, en: string) => string;
  onNotice: (value: string) => void;
};
type VisNetwork = { destroy: () => void; fit: (options?: Row) => void; on: (event: string, handler: (params: Row) => void) => void };

declare global {
  interface Window {
    vis?: {
      DataSet: new (items: Row[]) => any;
      Network: new (container: HTMLElement, data: Row, options: Row) => VisNetwork;
    };
  }
}

let visLoader: Promise<void> | null = null;
function loadVisNetwork(): Promise<void> {
  if (window.vis) return Promise.resolve();
  if (!visLoader) visLoader = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "/static/vis-network.min.js";
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("vis-network could not be loaded"));
    document.head.appendChild(script);
  });
  return visLoader;
}

function RelationshipGraph({ nodes, edges, text, onSelect }: { nodes: Row[]; edges: Row[]; text: Props["text"]; onSelect: (row: Row) => void }) {
  const container = useRef<HTMLDivElement | null>(null);
  const network = useRef<VisNetwork | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let cancelled = false;
    void loadVisNetwork().then(() => {
      if (cancelled || !container.current || !window.vis) return;
      network.current?.destroy();
      const dark = document.documentElement.dataset.theme === "dark";
      const known = new Set(nodes.map((node) => String(node.id)));
      const graphNodes = nodes.map((node) => ({
        ...node,
        id: String(node.id),
        label: String(node.label || node.title || node.id),
        shape: "dot",
        size: Number(node.size || 14),
        color: node.color || { background: "#0f6f82", border: "#0b4d5c" },
        font: { color: dark ? "#e7eff0" : "#182936", size: 12, strokeWidth: 4, strokeColor: dark ? "#172228" : "#f0f2f2" },
      }));
      const graphEdges = edges.filter((edge) => known.has(String(edge.from)) && known.has(String(edge.to))).map((edge, index) => ({
        ...edge, id: edge.id || `relationship-${index}`, from: String(edge.from), to: String(edge.to), arrows: edge.arrows || "to",
        color: edge.color || { color: dark ? "#8ba3a8" : "#647a80" },
        font: { color: dark ? "#d4e1e2" : "#263b45", size: 10, strokeWidth: 4, strokeColor: dark ? "#172228" : "#f0f2f2" },
      }));
      const instance = new window.vis.Network(container.current, { nodes: new window.vis.DataSet(graphNodes), edges: new window.vis.DataSet(graphEdges) }, {
        autoResize: true,
        interaction: { hover: true, navigationButtons: true, keyboard: true },
        physics: { stabilization: { iterations: 120 }, barnesHut: { gravitationalConstant: -2600, springLength: 125 } },
        edges: { smooth: { type: "continuous" } },
      });
      network.current = instance;
      instance.on("click", (params) => {
        const selected = nodes.find((node) => String(node.id) === String(params.nodes?.[0] || ""));
        if (selected) onSelect(selected);
      });
      window.setTimeout(() => instance.fit({ animation: false }), 0);
      setError("");
    }).catch((reason) => setError(reason instanceof Error ? reason.message : String(reason)));
    return () => { cancelled = true; network.current?.destroy(); network.current = null; };
  }, [nodes, edges]);
  if (error) return <div className="empty-state">{error}</div>;
  if (!nodes.length) return <div className="empty-state">{text("暂无实体关系", "No relationships")}</div>;
  return <div ref={container} className="network-canvas relationship-network-canvas" aria-label={text("实体关系图", "Entity relationship graph")} />;
}

async function read(path: string): Promise<Row> {
  const response = await fetch(path, { credentials: "same-origin", headers: { Accept: "application/json" } });
  const expires = response.headers.get("x-session-expires-at");
  if (expires) window.dispatchEvent(new CustomEvent("cx-session-refresh", { detail: expires }));
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    try {
      const payload = await response.json();
      message = String(payload.detail || payload.message || message);
    } catch { /* response has no JSON error body */ }
    throw new Error(message);
  }
  return response.json();
}

const items = (payload: Row, keys: string[]) => {
  for (const key of [...keys, "items", "results"]) if (Array.isArray(payload?.[key])) return payload[key];
  return Array.isArray(payload) ? payload : [];
};
const field = (row: Row, keys: string[]) => {
  for (const key of keys) if (row?.[key] !== undefined && row[key] !== null && row[key] !== "") return row[key];
  return "-";
};

export default function GraphPage({ lang, text, onNotice }: Props) {
  const initial = new URLSearchParams(window.location.search).get("view") || "overview";
  const [view, setView] = useState(["overview", "definitions", "types", "runs", "relationships"].includes(initial) ? initial : "overview");
  const [graphs, setGraphs] = useState<Row[]>([]);
  const [types, setTypes] = useState<Row[]>([]);
  const [runs, setRuns] = useState<Row[]>([]);
  const [relations, setRelations] = useState<Row>({ nodes: [], edges: [] });
  const [detail, setDetail] = useState<Row | null>(null);
  const [loading, setLoading] = useState(true);
  const display = (value: unknown) => String(value ?? "-").replaceAll("_", " ");

  const load = async () => {
    setLoading(true);
    try {
      const [graphPayload, typePayload, runPayload, relationPayload] = await Promise.all([
        read("/api/graphs"), read("/api/graph-types"), read("/api/graph-runs"), read("/api/graph/all"),
      ]);
      setGraphs(items(graphPayload, ["graphs"]));
      setTypes(items(typePayload, ["types"]));
      setRuns(items(runPayload, ["runs"]));
      setRelations(relationPayload);
    } catch (error) {
      onNotice(error instanceof Error ? error.message : text("图数据加载失败", "Graph data could not be loaded"));
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { void load(); }, []);
  const changeView = (next: string) => {
    setView(next);
    const url = new URL(window.location.href);
    url.searchParams.set("view", next);
    window.history.replaceState({}, "", url);
  };
  const tabs: [string, string, React.ComponentType<{ size?: number }>][] = [
    ["overview", text("概览", "Overview"), Activity],
    ["definitions", text("图定义", "Definitions"), Network],
    ["types", text("图类型", "Types"), Layers3],
    ["runs", text("运行记录", "Runs"), PlayCircle],
    ["relationships", text("实体关系", "Entity relationships"), GitBranch],
  ];
  const table = (headers: string[], rows: React.ReactNode[][], empty: string) => (
    <div className="table-wrap"><table><thead><tr>{headers.map((header) => <th key={header}>{header}</th>)}</tr></thead><tbody>
      {rows.length ? rows.map((row, index) => <tr key={index}>{row.map((value, cell) => <td key={cell}>{value}</td>)}</tr>) : <tr><td className="empty-cell" colSpan={headers.length}>{empty}</td></tr>}
    </tbody></table></div>
  );
  const detailButton = (row: Row, value: unknown) => <button className="text-button" onClick={() => setDetail(row)}>{String(value)}</button>;
  return <section>
    <div className="section-heading"><div className="section-heading-main"><h1>{text("图探索", "Graph")}</h1><p>{text("图定义、类型、运行和实体关系分区呈现；数据均来自当前数据库授权范围。", "Definitions, types, runs, and relationships are separated into focused authorized views.")}</p></div><div className="section-heading-actions"><button className="icon-button" onClick={() => void load()}><RefreshCw className={loading ? "spin" : ""} size={15} />{text("刷新", "Refresh")}</button></div></div>
    <div className="view-toggle" role="tablist">{tabs.map(([key, label, Icon]) => <button type="button" role="tab" aria-selected={view === key} className={view === key ? "active" : ""} key={key} onClick={() => changeView(key)}><Icon size={14} /><span>{label}</span></button>)}</div>
    {loading ? <div className="empty-state cx-data-loading" role="status"><span className="cx-loader spinner" /><span>{text("正在读取数据库", "Reading database")}</span></div> : <>
      {view === "overview" && <div className="metric-grid">{[[text("图定义", "Graph definitions"), graphs.length], [text("图类型", "Graph types"), types.length], [text("运行记录", "Runs"), runs.length], [text("实体关系", "Relationships"), (relations.edges || []).length]].map(([label, value]) => <div className="metric" key={String(label)}><span>{label}</span><strong>{value}</strong></div>)}</div>}
      {view === "definitions" && <section className="info-panel"><div className="panel-title"><h2>{text("图定义", "Graph definitions")}</h2></div>{table(["ID", text("名称", "Name"), text("类型", "Type"), text("状态", "Status")], graphs.map((row) => [detailButton(row, field(row, ["graph_id", "definition_id", "id"])), display(field(row, ["name", "title"])), display(field(row, ["kind", "type", "graph_type"])), display(field(row, ["status"]))]), text("暂无图定义", "No Graph definitions"))}</section>}
      {view === "types" && <section className="info-panel"><div className="panel-title"><h2>{text("图类型", "Graph types")}</h2></div>{table([text("类型", "Type"), text("名称", "Name"), text("状态", "Status")], types.map((row) => [display(field(row, ["kind", "type", "graph_type"])), display(field(row, ["name", "title"])), display(field(row, ["status"]))]), text("暂无图类型", "No Graph types"))}</section>}
      {view === "runs" && <section className="info-panel"><div className="panel-title"><h2>{text("运行记录", "Graph runs")}</h2></div>{table(["ID", text("图", "Graph"), text("状态", "Status"), text("更新时间", "Updated")], runs.map((row) => [detailButton(row, field(row, ["run_id", "id"])), String(field(row, ["graph_id", "definition_id"])), display(field(row, ["status"])), String(field(row, ["updated_at", "created_at"]))]), text("暂无运行记录", "No runs"))}</section>}
      {view === "relationships" && <><section className="info-panel"><div className="panel-title"><h2>{text("实体关系图", "Entity relationship graph")}</h2><span>{(relations.nodes || []).length} {text("节点", "nodes")} · {(relations.edges || []).length} {text("关系", "relationships")}</span></div><RelationshipGraph nodes={relations.nodes || []} edges={relations.edges || []} text={text} onSelect={setDetail} /></section><section className="info-panel"><div className="panel-title"><h2>{text("关系明细", "Relationship details")}</h2></div>{table([text("来源", "Source"), text("关系", "Relationship"), text("目标", "Target")], (relations.edges || []).map((row: Row) => [String(field(row, ["from", "source", "source_id"])), display(field(row, ["label", "type", "edge_type"])), String(field(row, ["to", "target", "target_id"]))]), text("暂无实体关系", "No relationships"))}</section></>}
    </>}
    {detail && <div className="detail-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setDetail(null); }}><aside className="detail-drawer" role="dialog" aria-modal="true"><div className="subhead"><h2>{text("图数据详情", "Graph data detail")}</h2><button className="icon-button" onClick={() => setDetail(null)} aria-label={text("关闭", "Close")}><X size={16} /></button></div><pre>{JSON.stringify(detail, null, 2)}</pre></aside></div>}
  </section>;
}
