import React, { useEffect, useState } from "react";
import { Eye, Pencil, Plus, RefreshCw, Trash2, X } from "lucide-react";
import { catalogId, readCatalog } from "./CatalogPicker";
import RecordDetails from "./RecordDetails";
export default function ToolsCatalog({ text }: { text: (zh: string, en: string) => string }) {
  const [rows, setRows] = useState<Record<string, any>[]>([]);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Record<string, any> | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [namespace, setNamespace] = useState("default");
  const [url, setUrl] = useState("");
  const [spec, setSpec] = useState("");
  const [importing, setImporting] = useState(false);
  const [mode, setMode] = useState<"json" | "url">("json");
  const [notice, setNotice] = useState("");
  const [editing, setEditing] = useState<Record<string, any> | null>(null);
  const [retiring, setRetiring] = useState<Record<string, any> | null>(null);
  const [busyId, setBusyId] = useState("");
  const importHeaders = () => {
    const headers = new Headers({ "Content-Type": "application/json" });
    const csrf = localStorage.getItem("cxDashboardCsrf");
    if (csrf) headers.set("X-CSRF-Token", csrf);
    return headers;
  };
  const load = async () => { setLoading(true); setError(""); try { setRows(await readCatalog("tools")); } catch { setError(text("工具目录加载失败", "Tool catalog unavailable")); } finally { setLoading(false); } };
  useEffect(() => { void load(); }, []);
  const importSpec = async (event: React.FormEvent) => { event.preventDefault(); setImporting(true); setError(""); setNotice(""); try { const parsed = JSON.parse(spec); if (!parsed || typeof parsed !== "object" || !parsed.paths) throw new Error(text("不是有效的 OpenAPI 文档：缺少 paths。", "Invalid OpenAPI document: paths is required.")); const r = await fetch("/api/tools/import-openapi", { method: "POST", credentials: "same-origin", headers: importHeaders(), body: JSON.stringify({ spec: parsed, namespace }) }); if (!r.ok) throw new Error(`HTTP ${r.status}`); const result = await r.json(); setSpec(""); await load(); setNotice(text(`已导入或更新 ${result.count || 0} 个工具。`, `Imported or updated ${result.count || 0} tool(s).`)); } catch (e) { setError((e as Error).message); } finally { setImporting(false); } };
  const importUrl = async (event: React.FormEvent) => { event.preventDefault(); setImporting(true); setError(""); setNotice(""); try { const r = await fetch("/api/tools/import-url", { method: "POST", credentials: "same-origin", headers: importHeaders(), body: JSON.stringify({ url, namespace }) }); if (!r.ok) throw new Error(`HTTP ${r.status}`); const result = await r.json(); setUrl(""); await load(); setNotice(text(`已导入或更新 ${result.count || 0} 个工具。`, `Imported or updated ${result.count || 0} tool(s).`)); } catch (e) { setError((e as Error).message); } finally { setImporting(false); } };
  const saveTool = async (event: React.FormEvent<HTMLFormElement>) => { event.preventDefault(); if (!editing) return; const id = catalogId(editing, "tools"); const data = new FormData(event.currentTarget); setBusyId(id); setError(""); try { const r = await fetch(`/api/tools/${encodeURIComponent(id)}`, { method: "PATCH", credentials: "same-origin", headers: importHeaders(), body: JSON.stringify({ description: String(data.get("description") || ""), status: String(data.get("status") || "ACTIVE") }) }); if (!r.ok) throw new Error(`HTTP ${r.status}`); setEditing(null); await load(); setNotice(text("工具已更新。", "Tool updated.")); } catch (e) { setError((e as Error).message); } finally { setBusyId(""); } };
  const retireTool = async () => { if (!retiring) return; const id = catalogId(retiring, "tools"); setBusyId(id); setError(""); try { const r = await fetch(`/api/tools/${encodeURIComponent(id)}`, { method: "DELETE", credentials: "same-origin", headers: importHeaders() }); if (!r.ok) throw new Error(`HTTP ${r.status}`); setRetiring(null); if (selected && catalogId(selected, "tools") === id) setSelected(null); await load(); setNotice(text("工具已停用并从可用目录移除。", "Tool retired and removed from the available catalog.")); } catch (e) { setError((e as Error).message); } finally { setBusyId(""); } };
  return <section><div className="subhead"><h2>{text("工具目录", "Tool catalog")}</h2><button className="icon-button" title={text("刷新", "Refresh")} onClick={() => void load()}><RefreshCw size={16} /></button></div>
    <div className="tool-import-layout">
      <section className="info-panel tool-import-panel">
        <div className="panel-title"><h2>{text("新增工具", "Add tools")}</h2></div>
        <div className="view-toggle" role="tablist">
          <button type="button" role="tab" aria-selected={mode === "json"} className={mode === "json" ? "active" : ""} onClick={() => setMode("json")}>{text("粘贴 JSON", "Paste JSON")}</button>
          <button type="button" role="tab" aria-selected={mode === "url"} className={mode === "url" ? "active" : ""} onClick={() => setMode("url")}>{text("导入 URL", "Import URL")}</button>
        </div>
        <form className="tool-import-form" onSubmit={mode === "json" ? importSpec : importUrl}>
          <label className="tool-namespace">{text("命名空间", "Namespace")}<input value={namespace} onChange={event => setNamespace(event.target.value)} maxLength={64} pattern="[A-Za-z0-9][A-Za-z0-9_.-]{0,63}" required /></label>
          {mode === "json" ? <label>{text("OpenAPI JSON", "OpenAPI JSON")}<textarea value={spec} onChange={event => setSpec(event.target.value)} required /></label>
            : <label>{text("OpenAPI 地址", "OpenAPI URL")}<input type="url" value={url} onChange={event => setUrl(event.target.value)} placeholder="https://example.test/openapi.json" required /></label>}
          <div className="tool-import-actions"><button className="primary-button" disabled={importing}><Plus size={14} />{importing ? text("正在导入", "Importing") : mode === "json" ? text("校验并导入", "Validate and import") : text("读取并导入", "Fetch and import")}</button></div>
        </form>
        {notice && <p role="status">{notice}</p>}{error && <p role="alert">{error}</p>}
      </section>
      <section className="info-panel tool-list-panel">
        <div className="panel-title"><h2>{text("已注册工具", "Registered tools")}</h2></div>
        <div className="page-toolbar"><input aria-label={text("搜索工具", "Search tools")} placeholder={text("搜索工具", "Search tools")} value={query} onChange={(event) => setQuery(event.target.value)} /></div>
        {loading && <p role="status">{text("正在加载", "Loading")}</p>}
        <div className="table-wrap"><table><thead><tr><th>{text("工具", "Tool")}</th><th>{text("命名空间", "Namespace")}</th><th>{text("版本", "Version")}</th><th>{text("状态", "Status")}</th><th>{text("操作", "Actions")}</th></tr></thead>
          <tbody>{rows.filter((row) => `${row.tool_name || row.name} ${row.description || ""}`.toLowerCase().includes(query.toLowerCase())).map((row) => { const id = catalogId(row, "tools"); return <tr key={id}><td data-label={text("工具", "Tool")}><button className="text-button" onClick={() => setSelected(row)}>{row.tool_name || row.name || id}</button></td><td data-label={text("命名空间", "Namespace")}>{row.tool_namespace || "-"}</td><td data-label={text("版本", "Version")}>{row.tool_version || "-"}</td><td data-label={text("状态", "Status")}>{row.status || "-"}</td><td data-label={text("操作", "Actions")}><span className="tool-row-actions"><button type="button" className="icon-button" title={text("查看详情", "View details")} aria-label={text("查看详情", "View details")} onClick={() => setSelected(row)}><Eye size={15} /></button><button type="button" className="icon-button" title={text("编辑工具", "Edit tool")} aria-label={text("编辑工具", "Edit tool")} onClick={() => setEditing(row)}><Pencil size={15} /></button><button type="button" className="icon-button danger" title={text("停用工具", "Retire tool")} aria-label={text("停用工具", "Retire tool")} disabled={busyId === id} onClick={() => setRetiring(row)}><Trash2 size={15} /></button></span></td></tr>; })}</tbody>
        </table></div>
        {!loading && !error && !rows.length && <p className="empty-state">{text("尚未注册工具", "No tools registered")}</p>}
      </section>
    </div>
    {selected && <div className="detail-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setSelected(null); }}><aside className="detail-drawer" role="dialog" aria-modal="true"><div className="subhead"><h2>{text("工具详情", "Tool details")}</h2><button className="icon-button" aria-label={text("关闭", "Close")} onClick={() => setSelected(null)}><X size={18} /></button></div><RecordDetails value={selected} text={text} /></aside></div>}
    {editing && <div className="detail-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !busyId) setEditing(null); }}><aside className="detail-drawer" role="dialog" aria-modal="true" aria-labelledby="tool-edit-title"><div className="subhead"><h2 id="tool-edit-title">{text("编辑工具", "Edit tool")}</h2><button type="button" className="icon-button" aria-label={text("关闭", "Close")} disabled={Boolean(busyId)} onClick={() => setEditing(null)}><X size={18} /></button></div><form className="cx-form" onSubmit={saveTool}><p><strong>{editing.tool_name || editing.name}</strong><br /><small>{editing.tool_namespace || "-"} · {editing.tool_version || "-"}</small></p><label>{text("说明", "Description")}<textarea name="description" defaultValue={editing.description || ""} maxLength={2000} /></label><label>{text("状态", "Status")}<select name="status" defaultValue={String(editing.status || "ACTIVE").toUpperCase()}><option value="ACTIVE">ACTIVE</option><option value="DEPRECATED">DEPRECATED</option></select></label><div className="actions-row"><button className="primary-button" disabled={Boolean(busyId)}>{text("保存", "Save")}</button><button type="button" className="small-button" disabled={Boolean(busyId)} onClick={() => setEditing(null)}>{text("取消", "Cancel")}</button></div></form></aside></div>}
    {retiring && <div className="detail-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !busyId) setRetiring(null); }}><aside className="detail-drawer tool-confirm-drawer" role="alertdialog" aria-modal="true" aria-labelledby="tool-retire-title"><div className="subhead"><h2 id="tool-retire-title">{text("停用工具", "Retire tool")}</h2><button type="button" className="icon-button" aria-label={text("关闭", "Close")} disabled={Boolean(busyId)} onClick={() => setRetiring(null)}><X size={18} /></button></div><p>{text(`停用“${retiring.tool_name || retiring.name}”后，它将从可用工具目录中移除。`, `Retiring “${retiring.tool_name || retiring.name}” removes it from the available tool catalog.`)}</p><div className="actions-row"><button type="button" className="small-button danger" disabled={Boolean(busyId)} onClick={() => void retireTool()}>{text("确认停用", "Confirm retirement")}</button><button type="button" className="small-button" disabled={Boolean(busyId)} onClick={() => setRetiring(null)}>{text("取消", "Cancel")}</button></div></aside></div>}
  </section>;
}
