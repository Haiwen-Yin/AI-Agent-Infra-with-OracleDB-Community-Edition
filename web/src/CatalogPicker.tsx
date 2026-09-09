import React, { useRef, useState } from "react";
import { ListFilter, X } from "lucide-react";
type Row = Record<string, any>;
export async function readCatalog(kind: "skills" | "tools"): Promise<Row[]> {
  const response = await fetch(`/api/${kind}?limit=500`, { credentials: "same-origin" });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const data = await response.json();
  return Array.isArray(data) ? data : data.items || data[kind] || [];
}
export function catalogId(row: Row, kind: "skills" | "tools") { return String(kind === "skills" ? row.entity_id || row.skill_id || row.id : row.tool_id || row.id || row.tool_name || row.name); }
export default function CatalogPicker({ kind, value, onChange, name, text, disabled = false }: {
  kind: "skills" | "tools"; value?: string[]; onChange?: (items: string[]) => void; name?: string;
  text: (zh: string, en: string) => string; disabled?: boolean;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [local, setLocal] = useState<string[]>([]);
  const [draft, setDraft] = useState<string[]>([]);
  const [rows, setRows] = useState<Row[]>([]);
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const selected = value ?? local;
  const label = kind === "skills" ? text("选择技能", "Select skills") : text("选择工具", "Select tools");
  const open = async () => {
    setDraft([...selected]); setQuery(""); setError(""); setRows([]); setLoading(true); dialog.current?.showModal();
    try { setRows(await readCatalog(kind)); } catch { setError(text("目录加载失败，请重新打开重试", "Catalog unavailable; reopen to retry")); } finally { setLoading(false); }
  };
  return <div className="catalog-picker">
    {name && <input type="hidden" name={name} value={selected.join(",")} />}
    <button type="button" className="small-button" disabled={disabled} onClick={() => void open()}><ListFilter size={15} />{label} ({selected.length})</button>
    <dialog ref={dialog} className="catalog-dialog" onClick={(event) => { if (event.target === dialog.current) dialog.current?.close(); }}>
      <div className="subhead"><h3>{label}</h3><button type="button" className="icon-button" aria-label={text("关闭", "Close")} onClick={() => dialog.current?.close()}><X size={18} /></button></div>
      <input aria-label={text("搜索目录", "Search catalog")} value={query} onChange={(event) => setQuery(event.target.value)} />
      {error && <p role="alert">{error}</p>}
      <div className="catalog-options">
        {loading ? <p role="status">{text("正在加载", "Loading")}</p> : [...rows, ...draft.filter((id) => !rows.some((row) => catalogId(row, kind) === id)).map((id): Row => ({ id, name: id }))].filter((row) => `${row.title || row.tool_name || row.name || ""} ${catalogId(row, kind)}`.toLowerCase().includes(query.toLowerCase())).map((row) => {
          const id = catalogId(row, kind);
          return <label key={id}><input type="checkbox" checked={draft.includes(id)} onChange={(event) => setDraft(event.target.checked ? [...draft, id] : draft.filter((item) => item !== id))} /><span>{row.title || row.tool_name || row.name || id}<small>{id}</small></span></label>;
        })}
        {!loading && !rows.length && !draft.length && !error && <p>{text("当前没有可见条目", "No visible entries")}</p>}
      </div>
      <button type="button" className="primary-button" disabled={loading || Boolean(error)} onClick={() => { setLocal(draft); onChange?.(draft); dialog.current?.close(); }}>{text("确认选择", "Confirm selection")} ({draft.length})</button>
    </dialog>
  </div>;
}
