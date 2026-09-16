import React, { useRef, useState } from "react";
type Row = Record<string, any>;
type Props = { request: (path: string, options?: RequestInit) => Promise<Row>; text: (zh: string, en: string) => string; domain: string; workId?: string; sources: Row[]; canWrite: boolean };

export default function ContinuityRuntime({ request, text, domain, workId, sources, canWrite }: Props) {
  const [agents, setAgents] = useState<Row[]>([]);
  const [cursor, setCursor] = useState("");
  const [execution, setExecution] = useState<Row | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const lock = useRef(false);
  const pending = useRef(new Map<string, Row>());
  const run = async (operation: () => Promise<void>) => {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError("");
    try { await operation(); } catch (e) { setError(e instanceof Error ? e.message : text("执行请求失败", "Execution request failed")); }
    finally { lock.current = false; setBusy(false); }
  };
  const load = async (next = "") => {
    const result = await request(`/api/context/runtime-agents?security_domain_id=${encodeURIComponent(domain)}${next ? `&cursor=${encodeURIComponent(next)}` : ""}`);
    setAgents(previous => next ? [...previous, ...result.items] : result.items); setCursor(result.next_cursor || "");
  };
  const state = (value: string) => ({ PENDING: text("等待 Worker 执行", "Waiting for Worker"), CLAIMED: text("执行中", "Running"), COMPLETED: text("已完成", "Completed"), FAILED: text("执行失败", "Failed"), SENT: text("已取得输入回执", "Input receipt recorded"), UNOBSERVED: text("发送结果未观测", "Send outcome unobserved"), SENDING: text("发送中", "Sending") }[value] || value);
  return <section className="panel" aria-label={text("使用上下文执行", "Execute with context")}>
    <h3>{text("使用上下文执行", "Execute with context")}</h3>
    <p>{text("将当前工作与上方填写的来源交给原生 Agent 处理。发起者与 Agent 都需要来源读取权限。", "Ask a native Agent to use the selected work and sources entered above. Both requester and Agent need permission to read the sources.")}</p>
    {error && <p role="alert">{error}</p>}
    <div className="page-toolbar"><button type="button" className="small-button" disabled={busy || !canWrite} onClick={() => void run(() => load())}>{text("加载可执行 Agent", "Load available Agents")}</button>{cursor && <button type="button" className="small-button" disabled={busy} onClick={() => void run(() => load(cursor))}>{text("加载更多 Agent", "Load more Agents")}</button>}</div>
    <form onSubmit={e => {
      e.preventDefault(); const form = new FormData(e.currentTarget);
      void run(async () => {
        const body = { agent_id: String(form.get("agent")), messages: [{ role: "user", content: String(form.get("prompt")) }], reason: String(form.get("reason")),
          context: { security_domain_id: domain, work_contract_id: form.get("work") ? workId : null, sources, purpose: String(form.get("reason")), token_budget: Number(form.get("budget")), entry_limit: 100, ttl_seconds: 900 } };
        const signature = JSON.stringify(body), id = crypto.randomUUID();
        const payload = pending.current.get(signature) || { ...body, idempotency_key: id, context: { ...body.context, request_id: id, idempotency_key: id } };
        pending.current.set(signature, payload);
        const receipt = await request("/api/context/runtime-executions", { method: "POST", body: JSON.stringify(payload) });
        setExecution(receipt); pending.current.delete(signature);
      });
    }}><fieldset className="operation-explainer-form" disabled={busy || !canWrite}><legend>{text("提交执行请求", "Submit execution request")}</legend>
      <label className="workbench-field"><span>{text("执行 Agent", "Execution Agent")}</span><select name="agent" required><option value="">{text("选择已加载的 Agent", "Select a loaded Agent")}</option>{agents.map(agent => <option key={agent.agent_id} value={agent.agent_id}>{agent.display_name || agent.agent_id}</option>)}</select></label>
      {workId && <label key={workId}><input type="checkbox" name="work" defaultChecked />{text("使用当前工作契约", "Use selected work contract")}</label>}
      <label className="workbench-field"><span>{text("给 Agent 的任务", "Task for the Agent")}</span><textarea name="prompt" required maxLength={32768} rows={3} /></label>
      <label className="workbench-field"><span>{text("上下文预算上限", "Context budget")}</span><input type="number" name="budget" min={1} max={131072} defaultValue={4096} required /></label>
      <label className="workbench-field"><span>{text("操作原因与用途", "Reason and purpose")}</span><input name="reason" required maxLength={1000} /></label>
      <p>{text("上下文有效期为 15 分钟。排队超时或权限变化会阻止发送；结果不确定时不会自动重试。", "Context is valid for 15 minutes. Expiry or permission changes block sending; uncertain sends are not retried automatically.")}</p>
      <button className="primary-button">{text("提交给 Agent", "Submit to Agent")}</button>
    </fieldset></form>
    {execution && <section aria-label={text("上下文执行结果", "Context execution result")}><p role="status">{state(execution.status || "PENDING")} · {execution.execution_id}</p>
      <button type="button" className="small-button" disabled={busy} onClick={() => void run(async () => {
        const id = execution.execution_id; setExecution({ execution_id: id, status: execution.status });
        setExecution(await request(`/api/context/runtime-executions/${encodeURIComponent(id)}`));
      })}>{text("刷新执行结果", "Refresh execution result")}</button>
      {execution.input_receipt && <p>{text("输入回执", "Input receipt")}: {state(execution.input_receipt.status)} · {execution.input_receipt.item_count} {text("条来源", "sources")}</p>}
      {execution.output?.content && <p className="continuity-body">{execution.output.content}</p>}
    </section>}
  </section>;
}
