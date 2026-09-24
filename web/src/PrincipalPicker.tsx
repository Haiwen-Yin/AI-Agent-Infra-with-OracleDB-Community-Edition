import React, { useEffect, useRef, useState } from "react";

type Row = Record<string, any>;
export default function PrincipalPicker({ name, text, kind = "", channelId = "", endpoint = "", required = false, multiple = false, defaultValue = "" }: {
  name: string; text: (zh: string, en: string) => string; kind?: "" | "HUMAN" | "AGENT";
  channelId?: string; endpoint?: string; required?: boolean; multiple?: boolean; defaultValue?: string;
}) {
  const [query, setQuery] = useState("");
  const [rows, setRows] = useState<Row[]>([]);
  const [selected, setSelected] = useState<string[]>(defaultValue ? [defaultValue] : []);
  const [selectedRows, setSelectedRows] = useState<Row[]>([]);
  const [after, setAfter] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const container = useRef<HTMLDivElement>(null);
  const sequence = useRef(0);
  useEffect(() => { setSelected(defaultValue ? [defaultValue] : []); setSelectedRows([]); }, [kind, channelId, endpoint, defaultValue]);
  const load = async (position = "") => {
    const request = ++sequence.current;
    setLoading(true); setError("");
    try {
      const params = new URLSearchParams({query, kind, channel_id: channelId, after: position});
      const response = await fetch(endpoint || `/api/principal-options?${params}`, {credentials: "same-origin"});
      if (!response.ok) throw new Error();
      const result = await response.json();
      if (request !== sequence.current) return;
      const found = (result.items || []).filter((row: Row) => (!kind || row.principal_type === kind) &&
        (!endpoint || `${row.display_name} ${row.username || ""} ${row.principal_id}`.toLowerCase().includes(query.toLowerCase())));
      setRows(current => position ? [...current, ...found] : found);
      setAfter(result.next_after || "");
    } catch {
      if (request === sequence.current) setError(text("候选成员加载失败，请重试", "Could not load candidates; retry"));
    } finally { if (request === sequence.current) setLoading(false); }
  };
  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 200);
    return () => { window.clearTimeout(timer); sequence.current++; };
  }, [query, kind, channelId, endpoint]);
  useEffect(() => {
    const form = container.current?.closest("form");
    const reset = () => { setSelected(defaultValue ? [defaultValue] : []); setSelectedRows([]); setQuery(""); };
    form?.addEventListener("reset", reset);
    return () => form?.removeEventListener("reset", reset);
  }, [defaultValue]);
  const options = [...rows, ...selectedRows.filter(item => !rows.some(row => row.principal_id === item.principal_id))];
  return <div ref={container} className="principal-picker">
    <input type="search" aria-label={text("按名称或用户名搜索", "Search by name or username")} placeholder={text("搜索名称或用户名", "Search name or username")} value={query} onChange={event => setQuery(event.target.value)} />
    {multiple && <input type="hidden" name={name} value={selected.join(",")} />}
    <select name={multiple ? undefined : name} multiple={multiple} required={required}
      aria-label={text("选择人员或智能体", "Select a person or Agent")}
      value={multiple ? selected : selected[0] || ""} onChange={event => {
        const values = Array.from(event.target.selectedOptions).map(item => item.value).filter(Boolean);
        setSelected(values); setSelectedRows(options.filter(item => values.includes(item.principal_id)));
      }}>
      {!multiple && <option value="">{text("请选择", "Select")}</option>}
      {selected.filter(id => !options.some(row => row.principal_id === id)).map(id => <option key={id} value={id}>{id}</option>)}
      {options.map(row => <option key={row.principal_id} value={row.principal_id}>
        {row.display_name || row.username || row.principal_id}{row.username ? ` · ${row.username}` : ""} · {row.principal_type === "HUMAN" ? text("人员", "Person") : "Agent"} · {row.principal_id}
      </option>)}
    </select>
    {loading && <small role="status">{text("正在加载", "Loading")}</small>}
    {after && <button type="button" className="small-button" disabled={loading} onClick={() => void load(after)}>{text("加载更多", "Load more")}</button>}
    {error && <span role="alert">{error} <button type="button" className="small-button" onClick={() => void load()}>{text("重试", "Retry")}</button></span>}
    {!loading && !error && !rows.length && <small>{text(channelId ? "没有可添加的成员。请先在安全域管理中授权该成员，再加入频道。" : "没有匹配的可见成员", channelId ? "No eligible members. Grant Security Domain membership before adding them to this Channel." : "No matching visible members")}</small>}
  </div>;
}
