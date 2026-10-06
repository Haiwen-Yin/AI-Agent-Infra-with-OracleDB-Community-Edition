import React, { useEffect, useId, useRef, useState } from "react";
import { Bot, Check, ChevronDown, Search, User, X } from "lucide-react";

type Row = Record<string, any>;
export default function PrincipalPicker({ name, text, kind = "", channelId = "", endpoint = "", required = false, multiple = false, defaultValue = "", defaultDisplayName = "" }: {
  name: string; text: (zh: string, en: string) => string; kind?: "" | "HUMAN" | "AGENT";
  channelId?: string; endpoint?: string; required?: boolean; multiple?: boolean; defaultValue?: string; defaultDisplayName?: string;
}) {
  const [query, setQuery] = useState("");
  const [rows, setRows] = useState<Row[]>([]);
  const [selected, setSelected] = useState<string[]>(defaultValue ? [defaultValue] : []);
  const [selectedRows, setSelectedRows] = useState<Row[]>([]);
  const [after, setAfter] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const container = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const sequence = useRef(0);
  const pending = useRef<AbortController | null>(null);
  const listId = useId();
  const label = (row: Row) => String(row.display_name || row.username || row.principal_id);
  const selectionMessage = text("请从搜索结果中选择成员", "Select a member from the search results");
  useEffect(() => {
    setSelected(defaultValue ? [defaultValue] : []); setSelectedRows([]);
    setQuery(""); setOpen(false); setActive(-1);
  }, [kind, channelId, endpoint, defaultValue]);
  useEffect(() => {
    input.current?.setCustomValidity(required && !selected.length ? selectionMessage : "");
  }, [required, selected, selectionMessage]);
  const load = async (position = "") => {
    pending.current?.abort();
    const controller = new AbortController();
    pending.current = controller;
    const request = ++sequence.current;
    setLoading(true); setError("");
    try {
      const params = new URLSearchParams({query, kind, channel_id: channelId, after: position});
      const response = await fetch(endpoint || `/api/principal-options?${params}`, {credentials: "same-origin", signal: controller.signal});
      if (!response.ok) throw new Error();
      const result = await response.json();
      if (request !== sequence.current || controller.signal.aborted) return;
      const found: Row[] = (result.items || []).filter((row: Row) => (!kind || row.principal_type === kind) &&
        (!endpoint || `${row.display_name} ${row.username || ""} ${row.principal_id}`.toLowerCase().includes(query.toLowerCase())));
      setRows(current => Array.from(new Map<string, Row>((position ? [...current, ...found] : found).map(row => [String(row.principal_id), row])).values()));
      setAfter(result.next_after || "");
      setActive(-1);
      setSelectedRows(current => current.map(row => found.find((item: Row) => item.principal_id === row.principal_id) || row));
    } catch {
      if (request === sequence.current && !controller.signal.aborted) setError(text("候选成员加载失败，请重试", "Could not load candidates; retry"));
    } finally { if (request === sequence.current && !controller.signal.aborted) setLoading(false); }
  };
  useEffect(() => {
    // Remove old-scope results immediately, including during the debounce interval.
    setRows([]); setAfter(""); setError(""); setLoading(true); setActive(-1);
    if (!open) { setLoading(false); return; }
    const timer = window.setTimeout(() => void load(), 200);
    return () => { window.clearTimeout(timer); sequence.current++; pending.current?.abort(); };
  }, [query, kind, channelId, endpoint, open]);
  useEffect(() => {
    const form = container.current?.closest("form");
    const reset = () => { setSelected(defaultValue ? [defaultValue] : []); setSelectedRows([]); setQuery(""); setOpen(false); };
    form?.addEventListener("reset", reset);
    return () => form?.removeEventListener("reset", reset);
  }, [defaultValue]);
  useEffect(() => {
    if (active >= 0) document.getElementById(`${listId}-${active}`)?.scrollIntoView({ block: "nearest" });
  }, [active, listId]);
  const choose = (row: Row) => {
    const id = String(row.principal_id);
    const values = multiple ? selected.includes(id) ? selected.filter(item => item !== id) : [...selected, id] : [id];
    setSelected(values);
    setSelectedRows(values.map(value => [...rows, ...selectedRows].find(item => String(item.principal_id) === value) || { principal_id: value }));
    input.current?.focus();
    if (!multiple) { setOpen(false); setQuery(""); }
  };
  const keyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault(); setOpen(true);
      if (rows.length) setActive(current => event.key === "ArrowDown" ? (current + 1) % rows.length : (current <= 0 ? rows.length - 1 : current - 1));
    } else if (event.key === "Enter" && open) {
      event.preventDefault(); if (active >= 0 && rows[active]) choose(rows[active]);
    } else if (event.key === "Escape") {
      event.preventDefault(); event.stopPropagation(); setOpen(false); setActive(-1);
    }
  };
  return <div ref={container} className={`principal-picker${open ? " is-open" : ""}`} onBlur={event => {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) { setOpen(false); setActive(-1); }
  }}>
    <input type="hidden" name={name} value={multiple ? selected.join(",") : selected[0] || ""} />
    <div className="principal-picker-search">
      <Search size={15} aria-hidden="true" />
      <input ref={input} type="search" role="combobox" autoComplete="off"
        aria-label={text("按名称或用户名搜索", "Search by name or username")}
        aria-expanded={open} aria-controls={open ? listId : undefined} aria-autocomplete="list"
        aria-activedescendant={open && active >= 0 ? `${listId}-${active}` : undefined}
        aria-required={required} placeholder={text("搜索名称或用户名", "Search name or username")}
        value={query} onChange={event => { setQuery(event.target.value); setOpen(true); }}
        onFocus={() => setOpen(true)} onClick={() => setOpen(true)} onKeyDown={keyDown} onInvalid={() => { setOpen(true); input.current?.focus(); }} />
      <button type="button" className="principal-picker-toggle" aria-label={text("展开或收起候选成员", "Show or hide candidates")}
        aria-expanded={open} onMouseDown={event => event.preventDefault()} onClick={event => {
          event.preventDefault(); input.current?.focus(); setOpen(!open);
        }}><ChevronDown size={15} aria-hidden="true" /></button>
    </div>
    {selected.length > 0 && <div className="principal-picker-selection" aria-label={text("已选成员", "Selected members")}>
      {selected.map(id => {
        const row = [...rows, ...selectedRows].find(item => String(item.principal_id) === id) || { principal_id: id, display_name: id === defaultValue ? defaultDisplayName : "" };
        return <span className="principal-picker-chip" key={id} title={id}>
          <Check size={13} aria-hidden="true" /><span>{label(row)}{row.username && row.username !== row.display_name ? ` · ${row.username}` : ""}</span>
          <button type="button" aria-label={`${text("移除", "Remove")} ${label(row)}`} onClick={event => {
            event.preventDefault(); setSelected(current => current.filter(value => value !== id)); setSelectedRows(current => current.filter(item => String(item.principal_id) !== id));
          }}><X size={13} aria-hidden="true" /></button>
        </span>;
      })}
    </div>}
    {open && <div className="principal-picker-results">
      {loading && <small role="status">{text("正在加载", "Loading")}</small>}
      {error && <div className="principal-picker-feedback" role="alert"><span>{error}</span><button type="button" className="small-button" onClick={() => void load()}>{text("重试", "Retry")}</button></div>}
      <div id={listId} role="listbox" aria-label={text("可选成员", "Available members")} aria-multiselectable={multiple || undefined} aria-busy={loading} className="principal-picker-options">
        {rows.map((row, index) => <button type="button" role="option" id={`${listId}-${index}`} key={row.principal_id}
          aria-selected={selected.includes(String(row.principal_id))} tabIndex={-1}
          className={`principal-picker-option${active === index ? " active" : ""}`}
          onMouseDown={event => event.preventDefault()} onMouseEnter={() => setActive(index)} onClick={event => { event.preventDefault(); choose(row); }}>
          {row.principal_type === "HUMAN" ? <User size={16} aria-hidden="true" /> : <Bot size={16} aria-hidden="true" />}
          <span><b>{label(row)}</b><small>{row.principal_type === "HUMAN" ? text("人员", "Person") : "Agent"} · {row.username || row.principal_id}</small></span>
          {selected.includes(String(row.principal_id)) && <Check size={15} aria-hidden="true" />}
        </button>)}
      </div>
      {after && <button type="button" className="small-button principal-picker-more" disabled={loading} onClick={() => void load(after)}>{text("加载更多", "Load more")}</button>}
      {!loading && !error && !rows.length && <small>{text(channelId ? "没有可添加的成员。请先在安全域管理中授权该成员，再加入频道。" : "没有匹配的可见成员", channelId ? "No eligible members. Grant Security Domain membership before adding them to this Channel." : "No matching visible members")}</small>}
    </div>}
  </div>;
}
