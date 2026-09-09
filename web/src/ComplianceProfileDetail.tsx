import React, { useState } from "react";
import { Save, Copy, Check, Send } from "lucide-react";
import CatalogPicker from "./CatalogPicker";
import RecordDetails from "./RecordDetails";

type Row = Record<string, any>;
export default function ComplianceProfileDetail({ profile, editable, text, onSave, onCopy, onValidate, onWorkflow, agents = [] }: {
  profile: Row; editable: boolean; text: (zh: string, en: string) => string;
  onSave: (content: Row, reason: string) => Promise<void>;
  onCopy: (key: string, name: string, content: Row, reason: string) => Promise<void>;
  onValidate?: (content: Row) => Promise<Row>;
  onWorkflow?: (reason: string, agentId?: string, environment?: string) => Promise<Row>;
  agents?: Row[];
}) {
  const [content, setContent] = useState(JSON.stringify(profile.content, null, 2));
  const [reason, setReason] = useState("");
  const [copy, setCopy] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [key, setKey] = useState("");
  const [name, setName] = useState(profile.display_name || "");
  const [validation, setValidation] = useState<Row | null>(null);
  const [editor, setEditor] = useState<"form" | "json">("form");
  const [workflow, setWorkflow] = useState<Row | null>(null);
  let parsedContent: Row | null = null;
  try { const value = JSON.parse(content); if (value && typeof value === "object" && !Array.isArray(value)) parsedContent = value; } catch { /* Preserve malformed JSON until it is repaired. */ }
  const controls = parsedContent?.controls || {};
  const schema = profile.content_schema?.properties?.controls?.properties || {};
  const controlNames: Record<string, [string, string]> = {
    database: ["数据库访问", "Database access"], database_access: ["数据库访问", "Database access"],
    network: ["网络出口", "Network egress"], network_egress: ["网络出口", "Network egress"],
    secrets: ["凭据访问", "Credential access"], commands: ["命令执行", "Command execution"],
    approval: ["审批策略", "Approval policy"], approval_policy: ["审批策略", "Approval policy"],
    audit: ["审计策略", "Audit policy"], audit_retention: ["审计留存", "Audit retention"],
    data: ["数据处理", "Data processing"], export: ["数据导出", "Data export"], retention: ["证据留存", "Evidence retention"],
    tools: ["工具策略", "Tool policy"], skills: ["技能策略", "Skill policy"],
    classification_ceiling: ["数据分类上限", "Classification ceiling"],
    allowed_tools: ["允许的工具", "Allowed tools"], allowed_skills: ["允许的技能", "Allowed skills"],
  };
  const aliases: Record<string, string> = {database_access: "database", network_egress: "network", approval_policy: "approval", audit_retention: "audit"};
  const updateControl = (key: string, value: any) => {
    if (!parsedContent) return;
    const next = {...controls};
    if (value === undefined) delete next[key]; else next[key] = value;
    setContent(JSON.stringify({...parsedContent, controls: next}, null, 2)); setValidation(null);
  };
  const originalControls = profile.content?.controls || {};
  const changedControls = [...new Set([...Object.keys(originalControls), ...Object.keys(controls)])]
    .filter((key) => JSON.stringify(originalControls[key]) !== JSON.stringify(controls[key]));
  return <div className="page-stack">
    <dl className="profile-version-meta"><dt>{text("版本", "Version")}</dt><dd>{profile.version_label}</dd><dt>{text("状态", "Status")}</dt><dd>{profile.status}</dd><dt>{text("内容摘要", "Content digest")}</dt><dd>{profile.content_digest}</dd></dl>
    <h3>{text("有效控制配置", "Effective controls")}</h3>
    {profile.validation?.status === "INVALID" && <p role="alert">{text("继承校验未通过：", "Inheritance validation failed: ")}{profile.validation.reason}</p>}
    <div className="table-scroll"><table><thead><tr><th>{text("配置项", "Control")}</th><th>{text("值", "Value")}</th><th>{text("来源版本", "Source version")}</th></tr></thead><tbody>{Object.entries(profile.effective_content?.controls || {}).map(([field, value]) => <tr key={field}><td>{field}{profile.effective_content?.locked_fields?.includes(field) ? text("（锁定）", " (locked)") : ""}</td><td>{typeof value === "string" ? value : JSON.stringify(value)}</td><td>{profile.field_sources?.[`controls.${field}`]}</td></tr>)}</tbody></table></div>
    <details><summary>{text("完整配置与继承链", "Full configuration and inheritance")}</summary><pre className="decision-box">{JSON.stringify({ effective_content: profile.effective_content, field_sources: profile.field_sources, parent_chain: profile.parent_chain }, null, 2)}</pre></details>
    {editable && <form className="cx-form" onSubmit={async (event) => {
      event.preventDefault(); if (busy) return; setBusy(true); setError(""); setValidation(null);
      try {
        const parsed = JSON.parse(content);
        if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") throw new Error(text("配置必须是 JSON 对象", "Configuration must be a JSON object"));
        if (copy) await onCopy(key, name, parsed, reason); else await onSave(parsed, reason);
      } catch (error) { setError(error instanceof Error ? error.message : String(error)); }
      finally { setBusy(false); }
    }}>
      <label className="profile-copy-toggle"><input type="checkbox" checked={copy} onChange={(event) => setCopy(event.target.checked)} />{text("复制为新模板草稿", "Copy to a new template draft")}</label>
      {copy && <><label>{text("模板键", "Template key")}<input required value={key} maxLength={128} onChange={(event) => setKey(event.target.value)} /></label><label>{text("名称", "Name")}<input required value={name} maxLength={256} onChange={(event) => setName(event.target.value)} /></label></>}
      {(copy || profile.status === "DRAFT") && <>
        {Object.keys(schema).length > 0 && <div role="tablist" aria-label={text("配置编辑", "Configuration editor")} className="actions-row">{(["form", "json"] as const).map((mode) => <button key={mode} type="button" role="tab" aria-selected={editor === mode} className="small-button" onClick={() => setEditor(mode)}>{mode === "form" ? text("结构化配置", "Structured controls") : "JSON"}</button>)}</div>}
        {editor === "form" && Object.keys(schema).length > 0 && parsedContent && <div className="configuration-form">
          {Object.entries(schema).filter(([key]) => !(aliases[key] && !(key in controls)) && !Object.entries(aliases).some(([alias, canonical]) => canonical === key && alias in controls)).map(([key, rule]) => {
            const definition = rule as Row;
            const title = controlNames[key];
            if (key === "allowed_skills" || key === "allowed_tools") return <div key={key}><span>{text(...controlNames[key])}</span><CatalogPicker kind={key === "allowed_skills" ? "skills" : "tools"} value={controls[key] || []} onChange={(values) => updateControl(key, values)} disabled={busy} text={text} /><button type="button" className="text-button" disabled={busy} onClick={() => updateControl(key, undefined)}>{text("继承 / 不额外设置", "Inherit / no override")}</button></div>;
            return <label key={key}>{title ? text(...title) : key}{definition.enum ? <select aria-label={title ? text(...title) : key} disabled={busy} value={controls[key] ?? ""} onChange={(event) => updateControl(key, event.target.value || undefined)}>
              <option value="">{text("继承 / 不额外设置", "Inherit / no override")}</option>
              {definition.enum.filter((value: string) => value === value.toUpperCase() || value === controls[key] || value === originalControls[key]).map((value: string) => <option key={value} value={value}>{value}</option>)}
            </select> : <input disabled={busy} value={Array.isArray(controls[key]) ? controls[key].join(", ") : ""} onChange={(event) => updateControl(key, event.target.value.trim() ? event.target.value.split(",").map((value) => value.trim()).filter(Boolean) : undefined)} />}</label>;
          })}
        </div>}
        {(editor === "json" || !Object.keys(schema).length || !parsedContent) && <label>{text("草稿配置", "Draft configuration")}<textarea className="profile-json-editor" value={content} disabled={busy} onChange={(event) => { setContent(event.target.value); setValidation(null); }} required spellCheck={false} /></label>}
        {changedControls.length > 0 && <details><summary>{text("控制配置差异", "Control changes")} ({changedControls.length})</summary><div className="table-scroll"><table><thead><tr><th>{text("配置项", "Control")}</th><th>{text("原值", "Before")}</th><th>{text("新值", "After")}</th></tr></thead><tbody>{changedControls.map((key) => <tr key={key}><td>{key}</td><td>{JSON.stringify(originalControls[key]) ?? text("未设置", "Unset")}</td><td>{JSON.stringify(controls[key]) ?? text("继承", "Inherited")}</td></tr>)}</tbody></table></div></details>}
        <label>{text("变更原因", "Change reason")}<input value={reason} required maxLength={2000} onChange={(event) => setReason(event.target.value)} /></label><div className="actions-row">{onValidate && <button type="button" className="small-button" disabled={busy} onClick={async () => {
        setBusy(true); setError(""); setValidation(null);
        try { setValidation(await onValidate(JSON.parse(content))); }
        catch (error) { setError(error instanceof Error ? error.message : String(error)); }
        finally { setBusy(false); }
      }}><Check size={15} />{text("校验配置", "Validate configuration")}</button>}<button className="primary-button" disabled={busy}>{copy ? <Copy size={15} /> : <Save size={15} />}{copy ? text("创建副本", "Create copy") : text("保存草稿", "Save draft")}</button></div></>}
      {validation && <div role="status"><p>{text("校验通过", "Validation passed")}</p><RecordDetails value={validation.effective_content} text={text} /></div>}
      {error && <p role="alert">{error}</p>}
    </form>}
    {editable && onWorkflow && <form className="configuration-form" onSubmit={async (event) => {
      event.preventDefault(); if (busy) return;
      const data = new FormData(event.currentTarget); setBusy(true); setError("");
      try { setWorkflow(await onWorkflow(String(data.get("workflow_reason") || ""), String(data.get("agent_id") || ""), String(data.get("environment") || "production"))); }
      catch (error) { setError(error instanceof Error ? error.message : String(error)); }
      finally { setBusy(false); }
    }}>
      <h3>{profile.status === "DRAFT" ? text("发布审批", "Publication approval") : text("分配 / 回退审批", "Assignment / rollback approval")}</h3>
      {profile.status === "PUBLISHED" && <><label>{text("目标 Agent", "Target Agent")}<select name="agent_id" required><option value="">{text("请选择", "Select")}</option>{agents.map((agent) => <option key={agent.agent_id} value={agent.agent_id}>{agent.display_name || agent.agent_id}</option>)}</select></label><label>{text("运行环境", "Environment")}<input name="environment" defaultValue="production" required maxLength={64} /></label></>}
      <label>{text("审批原因", "Approval reason")}<input name="workflow_reason" required minLength={3} maxLength={2000} /></label>
      <button className="primary-button" disabled={busy}><Send size={14} />{text("提交审批", "Request approval")}</button>
      {workflow && <p role="status">{text("待审批", "Pending approval")} <code>{workflow.action_id}</code> <a href="/app/channels">{text("管理频道", "Management channel")}</a></p>}
    </form>}
  </div>;
}
