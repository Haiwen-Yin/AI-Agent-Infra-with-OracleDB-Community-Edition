import React, { FormEvent, useEffect, useRef, useState } from "react";

type Row = Record<string, any>;
type Source = { family: string; entity_id: string; revision_id: string; content_digest: string };
type Props = { request: (path: string, options?: RequestInit) => Promise<Row>; text: (zh: string, en: string) => string; domain: string; principalId: string; canWrite: boolean };
const emptySource = (): Source => ({ family: "HANDOFF", entity_id: "", revision_id: "", content_digest: "" });
const fields: Record<string, [string, string, string][]> = {
  MEMORY: [["title", "标题", "Title"], ["body", "记忆正文", "Memory content"]],
  KNOWLEDGE: [["title", "标题", "Title"], ["body", "知识正文", "Knowledge content"]],
  EXPERIENCE: [["title", "标题", "Title"], ["problem", "遇到的问题", "Problem"], ["solution", "解决方法", "Solution"], ["validation", "验证结果", "Validation"], ["applicability", "适用范围", "Applicability"]],
  SKILL: [["title", "标题", "Title"], ["instructions", "操作说明", "Instructions"], ["input_contract", "输入约定", "Input contract"], ["output_contract", "输出约定", "Output contract"]],
};

export default function ContinuityCandidates({ request, text, domain, principalId, canWrite }: Props) {
  const [items, setItems] = useState<Row[]>([]);
  const [cursor, setCursor] = useState("");
  const [candidate, setCandidate] = useState<Row | null>(null);
  const [historical, setHistorical] = useState<Row | null>(null);
  const [family, setFamily] = useState("EXPERIENCE");
  const [sources, setSources] = useState<Source[]>([emptySource()]);
  const [replacement, setReplacement] = useState<Source | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const lock = useRef(false);
  const pending = useRef(new Map<string, string>());
  const mounted = useRef(true);
  const label = (value: string) => ({ MEMORY: text("记忆", "Memory"), KNOWLEDGE: text("知识", "Knowledge"), EXPERIENCE: text("经验", "Experience"), SKILL: text("技能", "Skill"), HANDOFF: text("交接", "Handoff"), HANDOFF_OUTCOME: text("交接结果", "Handoff outcome"), PENDING: text("待审核", "Pending"), APPROVED: text("审核通过", "Approved"), REJECTED: text("已拒绝", "Rejected"), SUPERSEDED: text("已替代", "Superseded"), EXPIRED: text("已过期", "Expired") }[value] || value);
  const run = async (action: () => Promise<void>) => {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError(""); setNotice("");
    try { await action(); } catch (e) { if (mounted.current) setError(e instanceof Error ? e.message : text("操作失败", "Operation failed")); }
    finally { lock.current = false; if (mounted.current) setBusy(false); }
  };
  const post = async (path: string, body: Row) => {
    const signature = path + JSON.stringify(body);
    const id = pending.current.get(signature) || crypto.randomUUID();
    pending.current.set(signature, id);
    const result = await request(path, { method: "POST", body: JSON.stringify({ ...body, idempotency_key: id }) });
    pending.current.delete(signature); return result;
  };
  const load = async (next = "") => {
    const result = await request(`/api/artifact-candidates?security_domain_id=${encodeURIComponent(domain)}${next ? `&cursor=${encodeURIComponent(next)}` : ""}`);
    if (!mounted.current) return;
    setItems(previous => next ? [...previous, ...(result.items || [])] : result.items || []); setCursor(result.next_cursor || "");
  };
  useEffect(() => { mounted.current = true; void run(() => load()); return () => { mounted.current = false; }; }, []);
  const select = async (id: string) => {
    const value = await request(`/api/artifact-candidates/${encodeURIComponent(id)}`);
    if (!mounted.current) return;
    setCandidate(value); setHistorical(null); setFamily(value.payload.content.family); setSources(value.payload.sources); setReplacement(value.payload.replaces);
  };
  const fresh = () => { setCandidate(null); setHistorical(null); setSources([emptySource()]); setReplacement(null); setNotice(""); };
  const sourceFields = (value: Source, change: (value: Source) => void, onlyFamily?: string) => <>
    <label className="workbench-field"><span>{text("来源类型", "Source family")}</span><select value={value.family} onChange={e => change({ ...value, family: e.target.value })}>{(onlyFamily ? [onlyFamily] : ["HANDOFF", "HANDOFF_OUTCOME", "MEMORY", "KNOWLEDGE", "EXPERIENCE", "SKILL"]).map(item => <option key={item} value={item}>{label(item)}</option>)}</select></label>
    {([["entity_id", "实体标识", "Entity ID"], ["revision_id", "精确版本标识", "Exact revision ID"], ["content_digest", "内容摘要（SHA-256）", "Content digest (SHA-256)"]] as const).map(([name, zh, en]) => <label key={name} className="workbench-field"><span>{text(zh, en)}</span><input required value={value[name]} maxLength={name === "content_digest" ? 64 : 128} pattern={name === "content_digest" ? "[0-9a-f]{64}" : undefined} onChange={e => change({ ...value, [name]: e.target.value })} /></label>)}
  </>;
  const save = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); const data = new FormData(event.currentTarget);
    void run(async () => {
      const content: Row = { family, ...Object.fromEntries(fields[family].map(([name]) => [name, String(data.get(name))])) };
      if (family === "MEMORY") content.memory_type = String(data.get("memory_type"));
      if (family === "SKILL") content.required_actions = String(data.get("required_actions") || "").split("\n").map(x => x.trim()).filter(Boolean);
      const body = { security_domain_id: domain, content, sources, replaces: replacement, reason: String(data.get("reason")), ...(candidate ? { expected_version: candidate.version } : {}) };
      const result = await post(candidate ? `/api/artifact-candidates/${encodeURIComponent(candidate.candidate_id)}/revisions` : "/api/artifact-candidates", body);
      await load(); await select(result.candidate_id); setNotice(text("候选已保存，尚未成为正式内容。", "Candidate saved; it has not become a formal artifact."));
    });
  };
  const decision = (event: FormEvent<HTMLFormElement>, operation: "review" | "promote") => {
    event.preventDefault(); const data = new FormData(event.currentTarget);
    void run(async () => {
      await post(`/api/artifact-candidates/${encodeURIComponent(candidate!.candidate_id)}/${operation}`, {
        expected_version: candidate!.version, expected_digest: candidate!.content_digest, reason: String(data.get("reason")),
        ...(operation === "review" ? { decision: String(data.get("decision")) } : {}),
      });
      await load(); await select(candidate!.candidate_id); setNotice(text("操作已记录。", "Operation recorded."));
    });
  };
  const reason = <label className="workbench-field"><span>{text("操作原因", "Reason")}</span><input name="reason" required maxLength={1000} /></label>;
  const contentPreview = (value: Row) => <><p>{text("修订", "Revision")} {value.revision_no} · {value.content_digest}</p>{Object.entries(value.payload.content).filter(([name]) => name !== "family").map(([name, body]) => <p className="continuity-body" key={name}><strong>{fields[value.payload.content.family]?.find(item => item[0] === name)?.slice(1).map(String).reduce((zh, en) => text(zh, en)) || (name === "memory_type" ? text("记忆类型", "Memory type") : text("所需权限", "Required actions"))}</strong>: {Array.isArray(body) ? body.join("\n") : String(body)}</p>)}<ul>{value.payload.sources.map((source: Source, i: number) => <li key={i}>{label(source.family)} · {source.entity_id} · {source.revision_id} · {source.content_digest}</li>)}</ul></>;
  return <section className="panel" aria-label={text("候选审核与正式版本", "Candidate review and formal versions")}>
    <h3>{text("候选审核与正式版本", "Candidate review and formal versions")}</h3>
    <p>{text("先提交带精确来源的候选，由独立审核者审核，再显式生成正式版本。来源权限撤回后，读取、审核和生成都会重新校验。", "Submit a candidate with exact sources, obtain an independent review, then explicitly create a formal revision. Reads, reviews and promotion recheck current source permissions.")}</p>
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    <div className="page-toolbar"><select disabled={busy} value={candidate?.candidate_id || ""} aria-label={text("选择候选", "Select candidate")} onChange={e => e.target.value && void run(() => select(e.target.value))}><option value="">{text("选择候选记录", "Select candidate record")}</option>{items.map(item => <option key={item.candidate_id} value={item.candidate_id}>{label(item.family)} · {String(item.candidate_id).slice(-12)} · {label(item.status)}</option>)}</select><button className="small-button" type="button" disabled={busy} onClick={fresh}>{text("新建候选", "New candidate")}</button><button className="small-button" type="button" disabled={busy} onClick={() => void run(() => load())}>{text("刷新候选", "Refresh candidates")}</button>{cursor && <button className="small-button" type="button" disabled={busy} onClick={() => void run(() => load(cursor))}>{text("加载更多候选", "Load more candidates")}</button>}</div>
    {candidate && <section aria-label={text("当前候选内容", "Current candidate content")}><h4>{label(candidate.status)}</h4>{contentPreview(candidate)}{candidate.result_entity_id && <p>{text("正式实体／版本", "Formal entity / revision")}: {candidate.result_entity_id} / {candidate.result_revision_id}</p>}</section>}
    <form key={candidate ? `${candidate.candidate_id}-${candidate.version}` : `new-${family}`} onSubmit={save}><fieldset className="operation-explainer-form" disabled={busy || !canWrite || !!candidate && (candidate.proposed_by !== principalId || candidate.status !== "PENDING")}><legend>{candidate ? text("修订候选", "Revise candidate") : text("创建候选", "Create candidate")}</legend>
      <label className="workbench-field"><span>{text("候选类型", "Candidate family")}</span><select value={family} disabled={!!candidate} onChange={e => { setFamily(e.target.value); setReplacement(null); }}>{Object.keys(fields).map(item => <option key={item} value={item}>{label(item)}</option>)}</select></label>
      {fields[family].map(([name, zh, en]) => <label key={name} className="workbench-field"><span>{text(zh, en)}</span><textarea name={name} required maxLength={4000} rows={name === "title" ? 1 : 3} defaultValue={candidate?.payload.content[name] || ""} /></label>)}
      {family === "MEMORY" && <label className="workbench-field"><span>{text("记忆类型", "Memory type")}</span><select name="memory_type" defaultValue={candidate?.payload.content.memory_type || "FACT"}>{[["FACT", "事实", "Fact"], ["EPISODIC", "事件", "Event"], ["PREFERENCE", "偏好", "Preference"], ["DECISION", "决定", "Decision"], ["PROCEDURAL", "流程", "Procedure"]].map(([value, zh, en]) => <option key={value} value={value}>{text(zh, en)}</option>)}</select></label>}
      {family === "SKILL" && <label className="workbench-field"><span>{text("所需权限（每行一项，可选）", "Required actions (one per line, optional)")}</span><textarea name="required_actions" maxLength={4000} defaultValue={candidate?.payload.content.required_actions?.join("\n") || ""} /></label>}
      {sources.map((source, i) => <fieldset key={i} className="operation-explainer-form"><legend>{text("精确来源", "Exact source")} {i + 1}</legend>{sourceFields(source, value => setSources(previous => previous.map((item, index) => index === i ? value : item)))}<button className="small-button" type="button" disabled={sources.length === 1} onClick={() => setSources(previous => previous.filter((_, index) => index !== i))}>{text("移除此来源", "Remove source")}</button></fieldset>)}
      <button className="small-button" type="button" disabled={sources.length >= 100} onClick={() => setSources(previous => [...previous, emptySource()])}>{text("添加来源", "Add source")}</button>
      <label><input type="checkbox" checked={!!replacement} onChange={e => setReplacement(e.target.checked ? { ...emptySource(), family } : null)} />{text("替换已有正式版本", "Replace an existing formal revision")}</label>{replacement && <fieldset className="operation-explainer-form"><legend>{text("被替换的精确版本", "Exact revision to replace")}</legend>{sourceFields(replacement, setReplacement, family)}</fieldset>}
      {reason}<button className="primary-button">{text("保存候选", "Save candidate")}</button>
    </fieldset></form>
    {candidate && <>
      <form onSubmit={event => decision(event, "review")}><fieldset className="operation-explainer-form" disabled={busy || !canWrite || candidate.proposed_by === principalId || candidate.status !== "PENDING"}><legend>{text("独立审核", "Independent review")}</legend><select name="decision" aria-label={text("审核决定", "Review decision")}><option value="APPROVED">{text("通过", "Approve")}</option><option value="REJECTED">{text("拒绝", "Reject")}</option></select>{reason}<button className="primary-button">{text("提交审核", "Submit review")}</button></fieldset></form>
      <form onSubmit={event => decision(event, "promote")}><fieldset className="operation-explainer-form" disabled={busy || !canWrite || candidate.proposed_by === principalId || candidate.status !== "APPROVED" || !!candidate.result_entity_id}><legend>{text("生成正式版本", "Create formal revision")}</legend><p>{text("此操作采用上方已读取的版本与摘要，不自动审批其他修订。", "This operation uses the version and digest shown above; other revisions are not automatically approved.")}</p>{reason}<button className="primary-button">{text("生成正式版本", "Create formal revision")}</button></fieldset></form>
      <form onSubmit={e => { e.preventDefault(); const data = new FormData(e.currentTarget); void run(async () => { const value = await request(`/api/artifact-candidates/${encodeURIComponent(candidate.candidate_id)}?revision=${Number(data.get("revision"))}`); if (mounted.current) setHistorical(value); }); }}><fieldset className="operation-explainer-form" disabled={busy}><legend>{text("候选历史", "Candidate history")}</legend><label className="workbench-field"><span>{text("修订号", "Revision number")}</span><input type="number" name="revision" min={1} max={candidate.current_revision_no} defaultValue={1} required /></label><button className="small-button">{text("读取候选历史", "Read candidate history")}</button></fieldset></form>
      {historical && <section aria-label={text("候选历史只读预览", "Read-only candidate history")}><h4>{text("候选历史只读预览", "Read-only candidate history")}</h4>{contentPreview(historical)}</section>}
    </>}
  </section>;
}
