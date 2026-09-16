import React, { useRef, useState } from "react";
import ContinuityRuntime from "./ContinuityRuntime";

type Row = Record<string, any>;
type Source = { family: string; entity_id: string; revision_id: string; content_digest: string };
type Props = { request: (path: string, options?: RequestInit) => Promise<Row>; text: (zh: string, en: string) => string; domain: string; domains: Row[]; workId?: string; handoffId?: string; canWrite: boolean };
const blank = (): Source => ({ family: "HANDOFF", entity_id: "", revision_id: "", content_digest: "" });

export default function ContinuityContext({ request, text, domain, domains, workId, handoffId, canWrite }: Props) {
  const [sources, setSources] = useState<Source[]>([]);
  const [publicationSource, setPublicationSource] = useState<Source>(blank());
  const [assemblies, setAssemblies] = useState<Row[]>([]);
  const [assemblyCursor, setAssemblyCursor] = useState("");
  const [assembly, setAssembly] = useState<Row | null>(null);
  const [publications, setPublications] = useState<Row[]>([]);
  const [publicationCursor, setPublicationCursor] = useState("");
  const [publication, setPublication] = useState<Row | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const pending = useRef(new Map<string, Row>());
  const requestId = useRef(crypto.randomUUID());
  const lock = useRef(false);
  const status = (value: string) => ({ PREPARED: text("已组装，尚未发送", "Prepared, not sent"), SENDING: text("正在发送", "Sending"), SENT: text("已取得输入回执", "Input receipt recorded"), UNOBSERVED: text("发送结果未观测", "Delivery unobserved"), PUBLISHED: text("已发布", "Published"), REVOKED: text("已撤回", "Revoked") }[value] || value);
  const familyName = (value: string) => ({ WORK: text("工作契约", "Work contract"), HANDOFF: text("交接", "Handoff"), HANDOFF_OUTCOME: text("交接结果", "Handoff outcome"), MEMORY: text("记忆", "Memory"), KNOWLEDGE: text("知识", "Knowledge"), EXPERIENCE: text("经验", "Experience"), SKILL: text("技能", "Skill"), TASK: text("任务快照", "Task snapshot"), GRAPH: text("图运行快照", "Graph run snapshot"), DB4A2A: text("数据库派发快照", "Database dispatch snapshot"), AUDIT: text("安全事件摘要", "Security event summary") }[value] || value);
  const run = async (action: () => Promise<void>) => { if (lock.current) return; lock.current = true; setBusy(true); setError(""); setNotice(""); try { await action(); } catch (e) { setError(e instanceof Error ? e.message : text("操作失败", "Operation failed")); } finally { lock.current = false; setBusy(false); } };
  const post = async (path: string, body: Row, expiryHours?: number) => { const signature = path + JSON.stringify({ ...body, expiryHours }); const payload = pending.current.get(signature) || { ...body, idempotency_key: crypto.randomUUID(), ...(expiryHours === undefined ? {} : { expires_at: new Date(Date.now() + expiryHours * 3600000).toISOString() }) }; pending.current.set(signature, payload); const value = await request(path, { method: "POST", body: JSON.stringify(payload) }); pending.current.delete(signature); return value; };
  const sourceFields = (source: Source, change: (value: Source) => void, publish = false) => <>
    <label className="workbench-field"><span>{text("来源类型", "Source family")}</span><select value={source.family} onChange={e => change({ ...source, family: e.target.value })}>{["HANDOFF", "MEMORY", "KNOWLEDGE", "EXPERIENCE", "SKILL", ...(publish ? [] : ["HANDOFF_OUTCOME", "TASK", "GRAPH", "DB4A2A", "AUDIT"])].map(value => <option value={value} key={value}>{familyName(value)}</option>)}</select></label>
    {([["entity_id", "实体标识", "Entity ID"], ["revision_id", "精确版本标识", "Exact revision ID"], ["content_digest", "内容摘要（SHA-256）", "Content digest (SHA-256)"]] as const).map(([name, zh, en]) => <label className="workbench-field" key={name}><span>{text(zh, en)}</span><input required value={source[name]} maxLength={name === "content_digest" ? 64 : 128} pattern={name === "content_digest" ? "[0-9a-f]{64}" : undefined} onChange={e => change({ ...source, [name]: e.target.value })} /></label>)}
  </>;
  const list = async (kind: "assembly" | "publication", cursor = "") => {
    const path = kind === "assembly" ? "context/assemblies" : "context-publications";
    const value = await request(`/api/${path}?security_domain_id=${encodeURIComponent(domain)}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`);
    if (kind === "assembly") { setAssemblies(previous => cursor ? [...previous, ...value.items] : value.items); setAssemblyCursor(value.next_cursor || ""); }
    else { setPublications(previous => cursor ? [...previous, ...value.items] : value.items); setPublicationCursor(value.next_cursor || ""); setPublication(null); }
  };
  const reason = <label className="workbench-field"><span>{text("操作原因", "Reason")}</span><input name="reason" required maxLength={1000} /></label>;
  return <>
    <section className="panel" aria-label={text("上下文组装与证据", "Context assembly and evidence")}><h3>{text("上下文组装与证据", "Context assembly and evidence")}</h3>
      {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
      <p>{text("按明确来源和预算组装短期上下文。空结果是合法结果；完成组装不表示已发送给模型，也不会自动写入长期记忆。", "Prepare short-lived context from explicit sources within a budget. Empty results are valid. Preparation does not mean delivery to a model and does not create long-term memory.")}</p>
      <form onSubmit={e => { e.preventDefault(); const data = new FormData(e.currentTarget); void run(async () => {
        const value = await post("/api/context/native-sources", { family: String(data.get("family")), entity_id: String(data.get("entity_id")), security_domain_id: domain, reason: String(data.get("reason")) });
        setSources(previous => [...previous, value.source]); setNotice(text("已固定来源版本：", "Source version captured: ") + value.source.revision_id);
      }); }}><fieldset className="operation-explainer-form" disabled={busy || !canWrite || sources.length >= 100}><legend>{text("固定原生来源版本", "Capture native source version")}</legend>
        <label className="workbench-field"><span>{text("原生来源", "Native source")}</span><select name="family">{["TASK", "GRAPH", "DB4A2A", "AUDIT"].map(family => <option value={family} key={family}>{familyName(family)}</option>)}</select></label>
        <label className="workbench-field"><span>{text("原记录标识", "Original record ID")}</span><input name="entity_id" required maxLength={128} /></label>{reason}
        <button className="primary-button">{text("固定并添加来源", "Capture and add source")}</button>
        <p>{text("快照包含任务与步骤、图运行与节点状态、派发契约或本人安全事件摘要，并保留采集时间。原记录的后续变化不修改快照；权限撤销或原记录删除后不能继续读取。仅在原安全域内使用。", "Snapshots preserve capture time with task/step progress, graph run/node progress, dispatch contracts or your own security event summaries. Later changes do not alter the snapshot. Revocation or deletion of the original record blocks further reads. Use is limited to the original domain.")}</p>
      </fieldset></form>
      <form onSubmit={e => { e.preventDefault(); const data = new FormData(e.currentTarget); void run(async () => {
        const value = await post("/api/context/assemble", { request_id: String(data.get("request_id")), security_domain_id: domain,
          work_contract_id: data.get("include_work") && workId ? workId : null, handoff_id: data.get("include_handoff") && handoffId ? handoffId : null,
          sources, token_budget: Number(data.get("token_budget")), entry_limit: Number(data.get("entry_limit")), ttl_seconds: Number(data.get("ttl_seconds")), purpose: String(data.get("purpose")) });
        setAssembly(await request(`/api/context/assemblies/${encodeURIComponent(value.assembly_id)}`)); await list("assembly");
      }); }}><fieldset className="operation-explainer-form" disabled={busy}><legend>{text("准备上下文", "Prepare context")}</legend>
        <label className="workbench-field"><span>{text("请求标识", "Request ID")}</span><input name="request_id" required maxLength={128} defaultValue={requestId.current} /></label>
        {workId && <label key={workId}><input name="include_work" type="checkbox" />{text("包含当前选择的工作契约", "Include the selected work contract")} · {workId}</label>}
        {handoffId && <label key={handoffId}><input name="include_handoff" type="checkbox" />{text("包含当前选择的交接", "Include the selected handoff")} · {handoffId}</label>}
        {sources.map((source, i) => <fieldset className="operation-explainer-form" key={i}><legend>{text("组装来源", "Assembly source")} {i + 1}</legend>{sourceFields(source, value => setSources(previous => previous.map((item, index) => index === i ? value : item)))}<button type="button" className="small-button" onClick={() => setSources(previous => previous.filter((_, index) => index !== i))}>{text("移除此来源", "Remove source")}</button></fieldset>)}
        <button type="button" className="small-button" disabled={sources.length >= 100} onClick={() => setSources(previous => [...previous, blank()])}>{text("添加组装来源", "Add assembly source")}</button>
        {([["token_budget", "Token 预算上限", "Token budget", 4096, 1, 131072], ["entry_limit", "最多条目数", "Maximum entries", 20, 0, 100], ["ttl_seconds", "有效秒数", "Validity (seconds)", 300, 30, 3600]] as const).map(([name, zh, en, value, min, max]) => <label className="workbench-field" key={name}><span>{text(zh, en)}</span><input type="number" name={name} defaultValue={value} min={min} max={max} required /></label>)}
        <label className="workbench-field"><span>{text("使用目的", "Purpose")}</span><input name="purpose" required maxLength={1000} /></label><button className="primary-button">{text("组装上下文", "Assemble context")}</button>
      </fieldset></form>
      <div className="page-toolbar"><button type="button" className="small-button" disabled={busy} onClick={() => void run(() => list("assembly"))}>{text("加载我的组装记录", "Load my assemblies")}</button><select disabled={busy} aria-label={text("选择组装记录", "Select assembly")} value={assembly?.assembly_id || ""} onChange={e => { const id = e.target.value; if (id) void run(async () => { setAssembly(null); setAssembly(await request(`/api/context/assemblies/${encodeURIComponent(id)}`)); }); }}><option value="">{text("选择组装记录", "Select assembly")}</option>{assemblies.map(item => <option key={item.assembly_id} value={item.assembly_id}>{String(item.assembly_id).slice(-12)} · {status(item.status)}</option>)}</select>{assemblyCursor && <button type="button" className="small-button" disabled={busy} onClick={() => void run(() => list("assembly", assemblyCursor))}>{text("加载更多组装记录", "Load more assemblies")}</button>}</div>
      {assembly && <section aria-label={text("已组装上下文", "Prepared context")}><h4>{status(assembly.status)}</h4><p>{assembly.assembly_id} · {assembly.content_digest}</p><p>{text("条目数", "Entries")}: {assembly.item_count} · {text("Token 计数方法", "Token accounting")}: {text("UTF-8 字节数保守上限", "Conservative UTF-8 byte upper bound")}</p><p>{text("选取方式：按请求顺序，受条数和预算限制；使用时重新校验权限。", "Selection follows request order within entry and budget limits; use rechecks current authority.")}</p><ul>{assembly.items.map((item: Row) => <li key={item.item_no}>{familyName(item.family)} · {item.entity_id} · {item.revision_id} · {item.content_digest} · {text("预算用量", "Budget usage")}: {item.rendered_tokens}</li>)}</ul><details><summary>{text("查看已授权正文", "View authorized content")}</summary><p className="continuity-body">{assembly.text || text("没有选中条目。", "No entries selected.")}</p></details></section>}
    </section>
    <section className="panel" aria-label={text("上下文发布与撤回", "Context publication and revocation")}><h3>{text("上下文发布与撤回", "Context publication and revocation")}</h3><p>{text("发布固定精确来源版本、目标安全域、用途、密级和有效期。撤回后新请求不可再使用此授权，历史仍保留。", "A publication pins an exact source revision, target domain, purpose, classification and expiry. Revocation prevents further use of that grant while retaining history.")}</p>
      <form onSubmit={e => { e.preventDefault(); const data = new FormData(e.currentTarget); void run(async () => {
        const value = await post("/api/context-publications", { source: publicationSource, target_security_domain_id: String(data.get("target")), purpose: String(data.get("purpose")), classification: String(data.get("classification")), reason: String(data.get("reason")) }, Number(data.get("hours")));
        await list("publication"); setNotice(text("发布已记录：", "Publication recorded: ") + value.publication_id);
      }); }}><fieldset className="operation-explainer-form" disabled={busy || !canWrite}><legend>{text("创建精确发布", "Create exact publication")}</legend>{sourceFields(publicationSource, setPublicationSource, true)}
        <label className="workbench-field"><span>{text("目标安全域", "Target Security Domain")}</span><select name="target" required><option value="">{text("选择目标域", "Select target domain")}</option>{domains.filter(item => item.security_domain_id !== domain).map(item => <option key={item.security_domain_id} value={item.security_domain_id}>{item.domain_name || item.security_domain_id}</option>)}</select></label>
        <label className="workbench-field"><span>{text("发布用途", "Publication purpose")}</span><input name="purpose" maxLength={1000} required /></label>
        <label className="workbench-field"><span>{text("密级", "Classification")}</span><select name="classification" defaultValue="INTERNAL">{[["PUBLIC", "公开", "Public"], ["INTERNAL", "内部", "Internal"], ["CONFIDENTIAL", "保密", "Confidential"], ["RESTRICTED", "严格受限", "Restricted"]].map(([value, zh, en]) => <option key={value} value={value}>{text(zh, en)}</option>)}</select></label>
        <label className="workbench-field"><span>{text("有效小时数", "Validity (hours)")}</span><input type="number" name="hours" min={1} max={168} defaultValue={24} required /></label>{reason}<button className="primary-button">{text("发布上下文", "Publish context")}</button>
      </fieldset></form>
      <div className="page-toolbar"><button className="small-button" type="button" disabled={busy} onClick={() => void run(() => list("publication"))}>{text("管理本域发布", "Manage publications from this domain")}</button><select aria-label={text("选择发布记录", "Select publication")} value={publication?.publication_id || ""} disabled={busy} onChange={e => setPublication(publications.find(item => item.publication_id === e.target.value) || null)}><option value="">{text("选择发布记录", "Select publication")}</option>{publications.map(item => <option key={item.publication_id} value={item.publication_id}>{String(item.publication_id).slice(-12)} · {status(item.status)}</option>)}</select>{publicationCursor && <button type="button" className="small-button" disabled={busy} onClick={() => void run(() => list("publication", publicationCursor))}>{text("加载更多发布", "Load more publications")}</button>}</div>
      {publication && <form onSubmit={e => { e.preventDefault(); const data = new FormData(e.currentTarget); void run(async () => { const id = publication.publication_id; await post(`/api/context-publications/${encodeURIComponent(id)}/revoke`, { expected_version: publication.version, reason: String(data.get("reason")) }); await list("publication"); setNotice(text("发布已撤回：", "Publication revoked: ") + id); }); }}><fieldset className="operation-explainer-form" disabled={busy || !canWrite || publication.status !== "PUBLISHED"}><legend>{text("撤回所选发布", "Revoke selected publication")}</legend><p>{familyName(publication.family)} · {publication.entity_id} · {publication.source_revision_id} · {publication.content_digest}</p><p>{text("目标域", "Target domain")}: {publication.target_security_domain_id} · {publication.purpose}</p>{reason}<button className="primary-button">{text("撤回发布", "Revoke publication")}</button></fieldset></form>}
    </section>
    <ContinuityRuntime request={request} text={text} domain={domain} workId={workId} sources={sources} canWrite={canWrite} />
  </>;
}
