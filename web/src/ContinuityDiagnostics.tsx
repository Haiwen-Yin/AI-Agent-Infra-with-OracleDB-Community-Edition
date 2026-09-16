import React, { useRef, useState } from "react";

type Row = Record<string, any>;
type Props = { request: (path: string, options?: RequestInit) => Promise<Row>; text: (zh: string, en: string) => string; domain: string };

export default function ContinuityDiagnostics({ request, text, domain }: Props) {
  const [capabilities, setCapabilities] = useState<Row | null>(null);
  const [diagnostic, setDiagnostic] = useState<Row | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  const pending = useRef(new Map<string, Row>());
  const status = (value: string) => ({ PASS: text("通过", "Pass"), FAIL: text("失败", "Fail"), UNAVAILABLE: text("不可用", "Unavailable"), UNOBSERVED: text("未观测", "Unobserved") }[value] || value);
  const names: Record<string, string> = { PRINCIPAL: text("主体", "Principal"), DOMAIN: text("安全域", "Domain"), DATABASE: text("数据库", "Database"), INSTANCE: text("实例租约", "Instance lease"), CONTEXT_INPUT: text("实际上下文输入", "Actual context input"), SKILL_DELIVERY: text("Skill 分发与激活", "Skill delivery and activation"), ENTRYPOINT_PARITY: text("跨入口观测", "Cross-entrypoint observation"), SOURCE_ACCESS: text("来源访问", "Source access") };
  const family = (value: string) => ({ MEMORY: text("记忆", "Memory"), KNOWLEDGE: text("知识", "Knowledge"), EXPERIENCE: text("经验", "Experience"), SKILL: text("技能", "Skill"), HANDOFF: text("交接", "Handoff"), HANDOFF_OUTCOME: text("交接结果", "Handoff outcome"), TASK: text("任务", "Task"), GRAPH: text("图运行", "Graph run"), DB4A2A: text("数据库派发", "Database dispatch"), AUDIT: text("安全事件摘要", "Security event summary") }[value] || value);
  const sourceState = (value: string) => ({ EXACT_VERSION: text("精确版本", "Exact version"), PROMOTED_ARTIFACT_ONLY: text("已审核提升的对象", "Reviewed and promoted objects"), CAPTURED_NATIVE_PROJECTION: text("已采集的原生快照", "Captured native snapshots"), UNAVAILABLE: text("不可用", "Unavailable") }[value] || value);
  const detail = (value: string) => ({ CURRENT_DOMAIN_AUTHORITY: text("当前安全域权限有效", "Current domain authority is valid"), PRINCIPAL_STATUS: text("已检查主体状态", "Principal status checked"), DATABASE_QUERY: text("已执行数据库查询", "Database query executed"), CURRENT_INSTANCE_LEASE: text("已检查当前实例租约", "Current instance lease checked"), EXACT_INPUT_RECEIPT: text("已检查精确输入回执", "Exact input receipt checked"), NO_COMPLETED_INPUT_OBSERVATION: text("尚无完成的输入回执", "No completed input receipt"), RUNTIME_SWITCH_NOT_OBSERVED: text("服务端尚未独立观测外部运行切换", "External runtime switch has not been independently observed"), ENTRYPOINT_PARITY_NOT_OBSERVED: text("此次请求不能证明其他入口也已通过验证", "This request does not verify the other entrypoints"), ACCESS_DENIED: text("当前权限不允许访问", "Current authority denies access"), CHECK_SERVICE_UNAVAILABLE: text("所需诊断服务或记录不可用", "Required diagnostic service or record is unavailable"), INVALID_DISTRIBUTION_STATE: text("分发状态或签名证据不完整", "Distribution state or signature evidence is incomplete") }[value] || value);
  const run = async (action: () => Promise<void>) => {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError("");
    try { await action(); } catch (e) { setError(e instanceof Error ? e.message : text("诊断失败", "Diagnostics failed")); }
    finally { lock.current = false; setBusy(false); }
  };
  return <section className="panel" aria-label={text("当前授权与数据库诊断", "Current authority and database diagnostics")}>
    <h3>{text("当前授权与数据库诊断", "Current authority and database diagnostics")}</h3>
    {error && <p role="alert">{error}</p>}
    <p>{text("诊断记录实际检查结果。未执行或无法独立观测的检查不会标记为通过；能力可用也不代表已获具体资源的权限。", "Diagnostics record actual checks. Unperformed or independently unobserved checks do not pass. Available capabilities do not grant resource authority.")}</p>
    <button className="small-button" disabled={busy} onClick={() => void run(async () => setCapabilities(await request(`/api/continuity-capabilities?security_domain_id=${encodeURIComponent(domain)}`)))}>{text("查看当前能力", "View current capabilities")}</button>
    {capabilities && <div aria-label={text("当前能力", "Current capabilities")}>
      <p>{text("数据库", "Database")}: {capabilities.database} · {text("服务端版本", "Server version")}: {capabilities.database_version?.version || text("当前权限下未取得版本元数据", "Version metadata is unavailable with current authority")}</p>
      <ul>{Object.entries(capabilities.sources || {}).map(([name, value]) => <li key={name}>{family(name)}: {sourceState(String(value))}</li>)}</ul>
      <p>{text("Dashboard、Portal、Gateway、MCP 和 CLI 已提供统一操作契约。原生执行输入按每次组装的回执验证；Linux Skill 包装器只协调主动接入的运行进程。", "Dashboard, Portal, Gateway, MCP and CLI expose shared operation contracts. Native context input is verified per assembly receipt; the Linux Skill wrapper coordinates participating runtime processes.")}</p>
    </div>}
    <form onSubmit={e => { e.preventDefault(); const data = new FormData(e.currentTarget); void run(async () => {
      const body: Row = { security_domain_id: domain, purpose: String(data.get("purpose")), checks: ["PRINCIPAL", "DOMAIN", "DATABASE"] };
      for (const [field, check] of [["instance_id", "INSTANCE"], ["assembly_id", "CONTEXT_INPUT"], ["distribution_id", "SKILL_DELIVERY"]]) if (data.get(field)) { body[field] = String(data.get(field)); body.checks.push(check); }
      if (data.get("parity")) body.checks.push("ENTRYPOINT_PARITY");
      const signature = JSON.stringify(body);
      const payload = pending.current.get(signature) || { ...body, request_id: crypto.randomUUID(), idempotency_key: crypto.randomUUID() };
      pending.current.set(signature, payload);
      const result = await request("/api/diagnostics/runs", { method: "POST", body: JSON.stringify(payload) });
      pending.current.delete(signature); setDiagnostic(result);
    }); }}><fieldset className="operation-explainer-form" disabled={busy}>
      <legend>{text("运行服务端检查", "Run server checks")}</legend>
      <label className="workbench-field"><span>{text("检查用途", "Purpose")}</span><input name="purpose" required maxLength={1000} defaultValue={text("工作连续性诊断", "Work continuity diagnostics")} /></label>
      {[["instance_id", "实例标识（可选）", "Instance ID (optional)"], ["assembly_id", "组装记录标识（可选）", "Assembly ID (optional)"], ["distribution_id", "Skill 分发标识（可选）", "Skill distribution ID (optional)"]].map(([name, zh, en]) => <label className="workbench-field" key={name}><span>{text(zh, en)}</span><input name={name} maxLength={128} /></label>)}
      <label><input type="checkbox" name="parity" /> {text("包括跨入口观测检查", "Include cross-entrypoint observation")}</label>
      <button className="primary-button">{text("运行诊断", "Run diagnostics")}</button>
    </fieldset></form>
    {diagnostic && <><p role="status">{status(diagnostic.status)}</p><p>{text("诊断记录", "Diagnostic record")}: {diagnostic.run_id}</p><ul>{diagnostic.checks.map((item: Row) => <li key={item.check_code}>{names[String(item.check_code)] || String(item.check_code)}: {status(item.status)} · {detail(item.detail_code)}</li>)}</ul></>}
  </section>;
}
