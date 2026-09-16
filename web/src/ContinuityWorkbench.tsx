import React, { FormEvent, useEffect, useRef, useState } from "react";
import { RefreshCw } from "lucide-react";
import ContinuityCandidates from "./ContinuityCandidates";
import ContinuityContext from "./ContinuityContext";
import ContinuityDiagnostics from "./ContinuityDiagnostics";

type Row = Record<string, any>;
type Props = { request: (path: string, options?: RequestInit) => Promise<Row>; text: (zh: string, en: string) => string; principalId: string; canWrite: boolean };
const key = () => crypto.randomUUID();
const lines = (value: FormDataEntryValue | null) => String(value || "").split("\n").map(x => x.trim()).filter(Boolean);

export default function ContinuityWorkbench({ request, text, principalId, canWrite }: Props) {
  const [domains, setDomains] = useState<Row[]>([]);
  const [domain, setDomain] = useState("");
  const [members, setMembers] = useState<Row[]>([]);
  const [works, setWorks] = useState<Row[]>([]);
  const [work, setWork] = useState<Row | null>(null);
  const [handoffs, setHandoffs] = useState<Row[]>([]);
  const [handoff, setHandoff] = useState<Row | null>(null);
  const [handoffHistory, setHandoffHistory] = useState<Row[]>([]);
  const [historical, setHistorical] = useState<Row | null>(null);
  const [recordedOutcome, setRecordedOutcome] = useState<Row | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [workCursor, setWorkCursor] = useState("");
  const [handoffCursor, setHandoffCursor] = useState("");
  const [domainCursor, setDomainCursor] = useState("");
  const [memberCursor, setMemberCursor] = useState("");
  const pendingKeys = useRef(new Map<string, Row>());
  const locked = useRef(false);
  const generation = useRef(0);
  const currentDomain = useRef(domain);
  currentDomain.current = domain;
  const status = (value: string) => ({ OPEN: text("待处理", "Open"), IN_PROGRESS: text("进行中", "In progress"), BLOCKED: text("受阻", "Blocked"), COMPLETED: text("已完成", "Completed"), CANCELLED: text("已取消", "Cancelled"), EXPIRED: text("已过期", "Expired"), OFFERED: text("待接收", "Offered"), ACKNOWLEDGED: text("已接收", "Acknowledged"), REJECTED: text("已拒绝", "Rejected"), PASS: text("通过", "Pass"), FAIL: text("失败", "Fail"), UNAVAILABLE: text("不可用", "Unavailable"), UNOBSERVED: text("未观测", "Unobserved") }[value] || value);
  const run = async (operation: () => Promise<void>) => {
    if (locked.current) return;
    locked.current = true; setBusy(true); setError(""); setNotice("");
    try { await operation(); } catch (e) { setError(e instanceof Error ? e.message : text("操作失败", "Operation failed")); }
    finally { locked.current = false; setBusy(false); }
  };
  const post = async (path: string, body: Row, expiryHours?: number) => {
    const signature = path + JSON.stringify({ ...body, idempotency_key: undefined, expiryHours });
    const payload = pendingKeys.current.get(signature) || { ...body,
      ...(expiryHours === undefined ? {} : { expires_at: new Date(Date.now() + expiryHours * 3600000).toISOString() }) };
    pendingKeys.current.set(signature, payload);
    const result = await request(path, { method: "POST", body: JSON.stringify(payload) });
    pendingKeys.current.delete(signature); return result;
  };
  useEffect(() => {
    let active = true;
    void request("/api/continuity-domains").then(value => {
      if (active) { setDomains(value.items || []); setDomainCursor(value.next_cursor || ""); }
    }).catch(e => { if (active) setError(e instanceof Error ? e.message : text("安全域加载失败", "Domain loading failed")); });
    return () => { active = false; generation.current++; };
  }, []);
  const load = async (selectedDomain: string) => {
    const next = ++generation.current;
    if (!selectedDomain) return;
    const [w, h, m] = await Promise.all([
      request(`/api/work-contracts?security_domain_id=${encodeURIComponent(selectedDomain)}`),
      request(`/api/handoffs?security_domain_id=${encodeURIComponent(selectedDomain)}`),
      request(`/api/continuity-recipients?security_domain_id=${encodeURIComponent(selectedDomain)}`),
    ]);
    if (generation.current !== next || currentDomain.current !== selectedDomain) return;
    setWorks(w.items || []); setHandoffs(h.items || []); setMembers(m.items || m.members || []);
    setWorkCursor(w.next_cursor || ""); setHandoffCursor(h.next_cursor || "");
    setMemberCursor(m.next_cursor || "");
  };
  const selectDomain = (value: string) => {
    currentDomain.current = value; setDomain(value); setWork(null); setHandoff(null); setHistorical(null); setHandoffHistory([]); setRecordedOutcome(null); setWorks([]); setHandoffs([]); setMembers([]); setWorkCursor(""); setHandoffCursor("");
    void run(() => load(value));
  };
  const more = async (kind: "work" | "handoff") => {
    const cursor = kind === "work" ? workCursor : handoffCursor;
    if (!cursor) return;
    const value = await request(`/api/${kind === "work" ? "work-contracts" : "handoffs"}?security_domain_id=${encodeURIComponent(domain)}&cursor=${encodeURIComponent(cursor)}`);
    if (kind === "work") { setWorks(items => [...items, ...(value.items || [])]); setWorkCursor(value.next_cursor || ""); }
    else { setHandoffs(items => [...items, ...(value.items || [])]); setHandoffCursor(value.next_cursor || ""); }
  };
  const moreChoices = async (kind: "domain" | "recipient") => {
    const cursor = kind === "domain" ? domainCursor : memberCursor;
    if (!cursor) return;
    const value = await request(`/api/continuity-${kind === "domain" ? "domains" : "recipients"}?cursor=${encodeURIComponent(cursor)}${kind === "recipient" ? `&security_domain_id=${encodeURIComponent(domain)}` : ""}`);
    if (kind === "domain") { setDomains(items => [...items, ...(value.items || [])]); setDomainCursor(value.next_cursor || ""); }
    else { setMembers(items => [...items, ...(value.items || [])]); setMemberCursor(value.next_cursor || ""); }
  };
  const selectWork = async (id: string) => {
    const value = await request(`/api/work-contracts/${encodeURIComponent(id)}`);
    setWork(value); setHandoff(null); setHistorical(null); setHandoffHistory([]); setRecordedOutcome(null);
  };
  const selectHandoff = async (id: string) => {
    setRecordedOutcome(null);
    const history = await request(`/api/handoffs/${encodeURIComponent(id)}/history`);
    const latest = history.revisions?.[history.revisions.length - 1]?.revision_no;
    const value = latest ? await request(`/api/handoffs/${encodeURIComponent(id)}/history?revision=${latest}`) : history;
    const acceptedWork = value.expired ? null : await request(`/api/work-contracts/${encodeURIComponent(value.work_contract_id)}?revision=${value.work_revision_no}`);
    const currentWork = value.expired ? null : await request(`/api/work-contracts/${encodeURIComponent(value.work_contract_id)}`);
    setHandoff({ ...value, accepted_work: acceptedWork, current_work: currentWork }); setWork(null); setHistorical(null); setHandoffHistory(history.revisions || []);
    if (value.status === "COMPLETED") setRecordedOutcome(await request(`/api/handoffs/${encodeURIComponent(id)}/outcome`));
  };
  const saveWork = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); const form = event.currentTarget; const data = new FormData(form);
    void run(async () => {
      const criteria = work ? work.content.criteria.map((item: Row, i: number) => ({ ...item, description: String(data.get(`criteria-${i}`)), verification: String(data.get(`verification-${i}`)) })) : lines(data.get("criteria")).map((description, i) => ({ criterion_id: `criterion-${i + 1}`, description, verification: String(data.get("verification")) }));
      const content = { objective: String(data.get("objective")), criteria, constraints: lines(data.get("constraints")), sources: work?.content.sources || [] };
      const value = await post(work ? `/api/work-contracts/${encodeURIComponent(work.work_contract_id)}/revisions` : "/api/work-contracts", work ? {
        expected_version: work.version, content, reason: String(data.get("reason")), idempotency_key: key(),
      } : { security_domain_id: domain, owner_principal_id: principalId, content,
        ...Object.fromEntries(["workspace_id", "task_id", "graph_run_id"].map(name => [name, String(data.get(name) || "").trim() || null])),
        reason: String(data.get("reason")), idempotency_key: key() });
      await load(domain); await selectWork(value.work_contract_id); setNotice(text("工作契约已保存。", "Work contract saved."));
    });
  };
  const offer = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); const data = new FormData(event.currentTarget);
    void run(async () => {
      const recipient = String(data.get("recipient"));
      const value = await post(`/api/work-contracts/${encodeURIComponent(work!.work_contract_id)}/handoffs`, {
        expected_work_version: work!.version, recipient_principal_id: recipient, kind: "HUMAN_TO_AGENT",
        content: { summary: String(data.get("summary")), next_actions: [{ action_id: "next-action", description: String(data.get("action")), responsible_principal_id: recipient, acceptance: String(data.get("acceptance")) }] },
        reason: String(data.get("reason")), idempotency_key: key(),
      }, Number(data.get("hours")));
      await load(domain); await selectHandoff(value.handoff_id); setNotice(text("交接已发起。", "Handoff offered."));
    });
  };
  const saveHandoffPolicy = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); const data = new FormData(event.currentTarget);
    void run(async () => {
      const id = work!.work_contract_id;
      await post(`/api/work-contracts/${encodeURIComponent(id)}/handoff-policy`, {
        expected_version: work!.version, max_active_recipients: Number(data.get("max_active_recipients")),
        reason: String(data.get("reason")), idempotency_key: key(),
      });
      await load(domain); await selectWork(id);
      setNotice(text("交接策略已保存，历史策略保留。", "Handoff policy saved; historical policies are retained."));
    });
  };
  const decide = async (decision: string, reason: string) => {
    await post(`/api/handoffs/${encodeURIComponent(handoff!.handoff_id)}/acknowledge`, { expected_version: handoff!.version,
      expected_revision_no: handoff!.revision_no, decision, reason, idempotency_key: key() });
    await load(domain); await selectHandoff(handoff!.handoff_id);
  };
  const reviseHandoff = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); const data = new FormData(event.currentTarget);
    void run(async () => {
      // Bind the version displayed before submission, never a silently fetched
      // newer revision. The server rejects concurrent changes.
      const current = handoff!.current_work;
      await post(`/api/handoffs/${encodeURIComponent(handoff!.handoff_id)}/revisions`, {
        expected_version: handoff!.version, expected_revision_no: handoff!.revision_no,
        expected_work_version: current.version,
        content: { ...handoff!.content, summary: String(data.get("summary")),
          next_actions: handoff!.content.next_actions.map((item: Row, i: number) => ({ ...item,
            description: String(data.get(`action-${i}`)), acceptance: String(data.get(`acceptance-${i}`)),
          })) }, reason: String(data.get("reason")), idempotency_key: key(),
      });
      await load(domain); await selectHandoff(handoff!.handoff_id);
      setNotice(text("交接修订已保存，旧版本保留。", "Handoff revision saved; previous revisions are retained."));
    });
  };
  const outcome = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); const data = new FormData(event.currentTarget);
    void run(async () => {
      const acceptedWork = await request(`/api/work-contracts/${encodeURIComponent(handoff!.work_contract_id)}?revision=${handoff!.work_revision_no}`);
      await post(`/api/handoffs/${encodeURIComponent(handoff!.handoff_id)}/outcome`, {
        expected_version: handoff!.version, expected_revision_no: handoff!.revision_no,
        result: String(data.get("result")), summary: String(data.get("summary")),
        satisfied_criteria: data.get("verified") ? acceptedWork.content.criteria.map((item: Row) => item.criterion_id) : [],
        reason: String(data.get("reason")), idempotency_key: key(),
      });
      await load(domain); await selectHandoff(handoff!.handoff_id); setNotice(text("交接结果已记录。", "Handoff outcome recorded."));
    });
  };
  const field = (name: string, zh: string, en: string, value = "", multiline = false) => <label className="workbench-field"><span>{text(zh, en)}</span>{multiline ? <textarea name={name} required defaultValue={value} maxLength={4000} rows={3} /> : <input name={name} required defaultValue={value} maxLength={4000} />}</label>;
  const recipientCanRespond = !!handoff && handoff.to_principal_id === principalId && !handoff.expired && handoff.executable !== false;
  return <section className="page-stack continuity-workbench" aria-label={text("工作交接", "Work continuity")}>
    <div className="page-toolbar"><label>{text("安全域", "Security Domain")}<select value={domain} disabled={busy} onChange={e => selectDomain(e.target.value)}><option value="">{text("请选择安全域", "Select a Security Domain")}</option>{domains.map(item => <option key={item.security_domain_id} value={item.security_domain_id}>{item.display_name || item.domain_name || item.security_domain_id}</option>)}</select></label><button type="button" className="small-button" disabled={busy || !domain} onClick={() => void run(() => load(domain))}><RefreshCw size={14} />{text("刷新", "Refresh")}</button></div>
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    {domainCursor && <button type="button" className="small-button" disabled={busy} onClick={() => void run(() => moreChoices("domain"))}>{text("加载更多安全域", "Load more domains")}</button>}
    {domain && <>
      <section className="panel"><h3>{text("我负责或创建的工作", "Work I own or created")}</h3>
        {workCursor && <button className="small-button" type="button" disabled={busy} onClick={() => void run(() => more("work"))}>{text("加载更多工作", "Load more work")}</button>}
        <div className="page-toolbar"><select aria-label={text("选择工作契约", "Select work contract")} disabled={busy} value={work?.work_contract_id || ""} onChange={e => e.target.value && void run(() => selectWork(e.target.value))}><option value="">{text("选择工作", "Select work")}</option>{works.map(item => <option key={item.work_contract_id} value={item.work_contract_id}>{String(item.work_contract_id).slice(-12)} · {status(item.status)}</option>)}</select><button type="button" className="small-button" disabled={busy} onClick={() => { setWork(null); setHandoff(null); }}>{text("新建工作", "New work")}</button></div>
        {!handoff && <form key={work ? `${work.work_contract_id}-${work.version}` : `new-${domain}`} onSubmit={saveWork}><fieldset disabled={busy || !canWrite || !!work && work.owner_principal_id !== principalId} className="operation-explainer-form"><legend>{work ? text("修订工作契约", "Revise work contract") : text("创建工作契约", "Create work contract")}</legend>
          {field("objective", "工作目标", "Objective", work?.content.objective || "", true)}
          {!work && <details><summary>{text("关联已有执行资源（可选）", "Link existing execution resources (optional)")}</summary><p>{text("关联保留原资源权限，接收交接不会自动获得这些资源的访问权。", "Links retain the original resource permissions; accepting a handoff does not grant access to them.")}</p>{[
            ["workspace_id", "工作区标识", "Workspace ID"], ["task_id", "任务标识", "Task ID"], ["graph_run_id", "图运行标识", "Graph Run ID"],
          ].map(([name, zh, en]) => <label key={name} className="workbench-field"><span>{text(zh, en)}</span><input name={name} maxLength={128} /></label>)}</details>}
          {!!work?.execution_links?.length && <ul>{work.execution_links.map((link: Row) => <li key={link.link_kind}>{({ WORKSPACE: text("工作区", "Workspace"), TASK: text("任务", "Task"), GRAPH: text("图运行", "Graph Run") } as Record<string, string>)[link.link_kind]}: {link.entity_id}</li>)}</ul>}
          {work ? work.content.criteria.map((item: Row, i: number) => <React.Fragment key={item.criterion_id}>{field(`criteria-${i}`, "验收条件", "Acceptance criterion", item.description, true)}{field(`verification-${i}`, "验证方法", "Verification method", item.verification)}</React.Fragment>) : <>{field("criteria", "验收条件（每行一项）", "Acceptance criteria (one per line)", "", true)}{field("verification", "验证方法", "Verification method")}</>}
          <label className="workbench-field"><span>{text("约束（每行一项，可选）", "Constraints (one per line, optional)")}</span><textarea name="constraints" maxLength={4000} rows={3} defaultValue={work?.content.constraints.join("\n") || ""} /></label>
          {field("reason", "操作原因", "Reason")}<button className="primary-button">{text("保存工作契约", "Save work contract")}</button>
        </fieldset></form>}
        {work && <form onSubmit={e => { e.preventDefault(); const data = new FormData(e.currentTarget); void run(async () => { await post(`/api/work-contracts/${encodeURIComponent(work.work_contract_id)}/status`, { expected_version: work.version, status: String(data.get("status")), reason: String(data.get("reason")), idempotency_key: key() }); await load(domain); await selectWork(work.work_contract_id); }); }}><fieldset disabled={busy || !canWrite || work.owner_principal_id !== principalId || !["OPEN", "IN_PROGRESS", "BLOCKED"].includes(work.status)} className="operation-explainer-form"><legend>{text("更新工作状态", "Update work status")}</legend><select name="status" aria-label={text("目标状态", "Target status")}>{["IN_PROGRESS", "BLOCKED", "COMPLETED", "CANCELLED", "EXPIRED"].map(value => <option key={value} value={value}>{status(value)}</option>)}</select>{field("reason", "状态变更原因", "Reason for status change")}<button className="primary-button">{text("更新状态", "Update status")}</button></fieldset></form>}
        {work && <form onSubmit={e => { e.preventDefault(); const data = new FormData(e.currentTarget); void run(async () => setHistorical(await request(`/api/work-contracts/${encodeURIComponent(work.work_contract_id)}?revision=${Number(data.get("revision"))}`))); }}><fieldset disabled={busy} className="operation-explainer-form"><legend>{text("查看工作历史", "View work history")}</legend><label className="workbench-field"><span>{text("历史修订号", "Historical revision")}</span><input name="revision" type="number" min={1} max={work.revision_no || work.version} defaultValue={1} required /></label><button className="small-button">{text("读取历史版本", "Read historical revision")}</button></fieldset></form>}
        {work && <form key={`policy-${work.work_contract_id}-${work.version}`} onSubmit={saveHandoffPolicy}><fieldset disabled={busy || !canWrite || work.owner_principal_id !== principalId || !["OPEN", "IN_PROGRESS", "BLOCKED"].includes(work.status)} className="operation-explainer-form"><legend>{text("交接策略", "Handoff policy")}</legend>
          <p>{work.handoff_policy?.max_active_recipients > 1 ? text("并行交接由当前协调者保留工作责任，接收者分别确认和提交结果。", "Parallel handoffs retain the coordinator; recipients accept and submit outcomes independently.") : text("默认串行：同一时刻一名接收者，确认接收后转移工作责任。", "Serial by default: one active recipient, with responsibility transferred on acceptance.")}</p>
          <label className="workbench-field"><span>{text("最大活动接收者数", "Maximum active recipients")}</span><input name="max_active_recipients" type="number" min={1} max={16} defaultValue={work.handoff_policy?.max_active_recipients || 1} required /></label>
          <p>{text("设置为 2 至 16 可启用并行交接。须先结束或等待现有交接过期，才能修改策略。", "Choose 2–16 to enable parallel handoffs. Existing handoffs must finish or expire before policy changes.")}</p>
          {field("reason", "策略变更原因", "Reason for policy change")}<button className="primary-button">{text("保存交接策略", "Save handoff policy")}</button>
        </fieldset></form>}
        {work && <form onSubmit={offer}><fieldset disabled={busy || !canWrite || work.owner_principal_id !== principalId || !["OPEN", "IN_PROGRESS", "BLOCKED"].includes(work.status)} className="operation-explainer-form"><legend>{text("交接给 Agent", "Hand off to an Agent")}</legend>
          <label className="workbench-field"><span>{text("接收者", "Recipient")}</span><select name="recipient" required><option value="">{text("选择 Agent", "Select Agent")}</option>{members.filter(item => item.principal_type === "AGENT" && item.status === "ACTIVE").map(item => <option key={item.principal_id} value={item.principal_id}>{item.display_name || item.principal_id}</option>)}</select></label>
          {memberCursor && <button type="button" className="small-button" onClick={() => void run(() => moreChoices("recipient"))}>{text("加载更多接收者", "Load more recipients")}</button>}
          {field("summary", "已完成事项与当前状态", "Progress and current state", "", true)}{field("action", "下一步行动", "Next action")}{field("acceptance", "行动验收标准", "Action acceptance")}
          <label className="workbench-field"><span>{text("有效时长（小时）", "Valid for (hours)")}</span><input name="hours" type="number" min={1} max={168} defaultValue={24} required /></label>{field("reason", "交接原因", "Reason for handoff")}<button className="primary-button">{text("发起交接", "Offer handoff")}</button>
        </fieldset></form>}
      </section>
      <section className="panel"><h3>{text("我的交接", "My handoffs")}</h3><select aria-label={text("选择交接", "Select handoff")} disabled={busy} value={handoff?.handoff_id || ""} onChange={e => e.target.value && void run(() => selectHandoff(e.target.value))}><option value="">{text("选择交接记录", "Select handoff")}</option>{handoffs.map(item => <option key={item.handoff_id} value={item.handoff_id}>{String(item.handoff_id).slice(-12)} · {status(item.status)}</option>)}</select>
        {handoffCursor && <button className="small-button" type="button" disabled={busy} onClick={() => void run(() => more("handoff"))}>{text("加载更多交接", "Load more handoffs")}</button>}
        {handoff?.accepted_work && <section><h4>{text("交接时的验收条件", "Acceptance criteria at handoff")}</h4><ul>{handoff.accepted_work.content.criteria.map((item: Row) => <li key={item.criterion_id}>{item.description} — {item.verification}</li>)}</ul></section>}
        {handoff && <><p>{status(handoff.status)} · {text("修订", "Revision")} {handoff.revision_no}</p>{handoff.expired ? <p>{text("交接已过期，正文不再用于执行。", "This handoff expired; its content is no longer executable.")}</p> : <><p className="continuity-body">{handoff.content.summary}</p><ul>{handoff.content.next_actions.map((item: Row) => <li key={item.action_id}>{item.description} — {item.acceptance}</li>)}</ul></>}
          <label className="workbench-field"><span>{text("交接历史修订", "Handoff history revision")}</span><select value={historical?.handoff_id ? String(historical.revision_no) : ""} disabled={busy} onChange={e => { const revision = e.target.value; if (revision) void run(async () => setHistorical(await request(`/api/handoffs/${encodeURIComponent(handoff.handoff_id)}/history?revision=${revision}`))); }}><option value="">{text("选择历史修订", "Select historical revision")}</option>{handoffHistory.map(item => <option key={item.revision_no} value={item.revision_no}>{text("修订", "Revision")} {item.revision_no} · {item.reason}</option>)}</select></label>
          {!handoff.expired && handoff.from_principal_id === principalId && handoff.status === "OFFERED" && <form key={`${handoff.handoff_id}-${handoff.version}`} onSubmit={reviseHandoff}><fieldset disabled={busy || !canWrite} className="operation-explainer-form"><legend>{text("修订待接收交接", "Revise offered handoff")}</legend><p>{text("本次关联的工作修订", "Work revision linked by this change")}: {handoff.current_work.revision_no}</p><p className="continuity-body">{handoff.current_work.content.objective}</p><ul>{handoff.current_work.content.criteria.map((item: Row) => <li key={item.criterion_id}>{item.description} — {item.verification}</li>)}</ul>{field("summary", "修订后的交接说明", "Revised handoff summary", handoff.content.summary, true)}{handoff.content.next_actions.map((item: Row, i: number) => <React.Fragment key={item.action_id}>{field(`action-${i}`, "下一步行动", "Next action", item.description)}{field(`acceptance-${i}`, "行动验收标准", "Action acceptance", item.acceptance)}</React.Fragment>)}{field("reason", "修订原因", "Revision reason")}<p>{text("保存时关联上述工作版本，接收者须确认新的交接修订。", "Saving links the work revision shown above; the recipient must acknowledge the new handoff revision.")}</p><button className="primary-button">{text("保存交接修订", "Save handoff revision")}</button></fieldset></form>}
          <form onSubmit={e => { e.preventDefault(); const data = new FormData(e.currentTarget); void run(() => decide(String(data.get("decision")), String(data.get("reason")))); }}><fieldset disabled={busy || !canWrite || !recipientCanRespond || !["OFFERED", "ACKNOWLEDGED", "IN_PROGRESS"].includes(handoff.status)} className="operation-explainer-form"><legend>{text("处理交接", "Respond to handoff")}</legend><select key={handoff.status} name="decision" aria-label={text("处理方式", "Decision")}>{handoff.status === "OFFERED" && <option value="ACKNOWLEDGED">{text("确认接收", "Accept")}</option>}{handoff.status === "ACKNOWLEDGED" && <option value="IN_PROGRESS">{text("开始执行", "Start")}</option>}<option value="REJECTED">{text("拒绝", "Reject")}</option></select>{field("reason", "处理原因", "Decision reason")}<button className="primary-button">{text("提交决定", "Submit decision")}</button></fieldset></form>
          <form onSubmit={outcome}><fieldset disabled={busy || !canWrite || !recipientCanRespond || !["ACKNOWLEDGED", "IN_PROGRESS"].includes(handoff.status)} className="operation-explainer-form"><legend>{text("提交执行结果", "Submit outcome")}</legend><select key={handoff.status} name="result" aria-label={text("结果", "Result")}>{handoff.status === "IN_PROGRESS" && <option value="COMPLETED">{text("已完成", "Completed")}</option>}<option value="BLOCKED">{text("受阻", "Blocked")}</option><option value="FAILED">{text("失败", "Failed")}</option></select>{handoff.status === "ACKNOWLEDGED" && <p>{text("请先开始执行，再提交已完成的结果。", "Start execution before submitting a completed outcome.")}</p>}{field("summary", "结果说明", "Outcome summary", "", true)}<label><input name="verified" type="checkbox" />{text("我已验证交接时的全部验收条件", "I verified every criterion in the offered work revision")}</label>{field("reason", "提交原因", "Submission reason")}<button className="primary-button">{text("记录结果", "Record outcome")}</button></fieldset></form>
          {recordedOutcome && <section><h4>{text("已记录的执行结果", "Recorded outcome")}</h4><p>{status(recordedOutcome.result)} · {recordedOutcome.summary}</p><form onSubmit={e => {
            e.preventDefault(); const data = new FormData(e.currentTarget);
            void run(async () => {
              const result = await post(`/api/handoffs/${encodeURIComponent(handoff.handoff_id)}/experience-candidates`, {
                expected_outcome_id: recordedOutcome.outcome_id, expected_digest: recordedOutcome.content_digest,
                content: { family: "EXPERIENCE", ...Object.fromEntries(["title", "problem", "solution", "validation", "applicability"].map(name => [name, String(data.get(name))])) },
                reason: String(data.get("reason")), idempotency_key: key(),
              });
              setNotice(text("经验候选已提交，等待独立审核：", "Experience candidate submitted for independent review: ") + result.candidate_id);
            });
          }}><fieldset disabled={busy || !canWrite} className="operation-explainer-form"><legend>{text("提议沉淀为经验", "Propose as experience")}</legend>
            {field("title", "经验标题", "Experience title")}{field("problem", "遇到的问题", "Problem", "", true)}{field("solution", "解决方法", "Solution", "", true)}{field("validation", "验证结果", "Validation", recordedOutcome.summary, true)}{field("applicability", "适用范围", "Applicability", "", true)}{field("reason", "提议原因", "Proposal reason")}
            <p>{text("提交后进入候选审核，不会自动写入正式知识。", "Submission enters candidate review and does not automatically create formal knowledge.")}</p><button className="primary-button">{text("提交经验候选", "Submit experience candidate")}</button>
          </fieldset></form></section>}
        </>}
      </section>
      {historical && <section className="panel" aria-label={text("历史版本只读预览", "Read-only historical revision")}><h3>{text("历史版本只读预览", "Read-only historical revision")}</h3><p>{text("修订", "Revision")} {historical.revision_no} · {historical.content_digest}</p>{historical.expired ? <p>{text("正文已过期，仅保留历史元数据。", "Content expired; only historical metadata remains available.")}</p> : <><p className="continuity-body">{historical.content?.objective || historical.content?.summary}</p><ul>{(historical.content?.criteria || historical.content?.next_actions || []).map((item: Row) => <li key={item.criterion_id || item.action_id}>{item.description} — {item.verification || item.acceptance}</li>)}</ul></>}<button type="button" className="small-button" onClick={() => setHistorical(null)}>{text("关闭历史预览", "Close historical preview")}</button></section>}
      <ContinuityCandidates key={`${domain}-candidates`} request={request} text={text} domain={domain} principalId={principalId} canWrite={canWrite} />
      <ContinuityContext key={`context-${domain}`} request={request} text={text} domain={domain} domains={domains} workId={work?.work_contract_id} handoffId={!handoff?.expired ? handoff?.handoff_id : undefined} canWrite={canWrite} />
      <ContinuityDiagnostics key={`${domain}-diagnostics`} request={request} text={text} domain={domain} />
    </>}
  </section>;
}
