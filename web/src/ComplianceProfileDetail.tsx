import React, { useState } from "react";
import { Save, Copy } from "lucide-react";

type Row = Record<string, any>;
export default function ComplianceProfileDetail({ profile, editable, text, onSave, onCopy }: {
  profile: Row; editable: boolean; text: (zh: string, en: string) => string;
  onSave: (content: Row, reason: string) => Promise<void>;
  onCopy: (key: string, name: string, content: Row, reason: string) => Promise<void>;
}) {
  const [content, setContent] = useState(JSON.stringify(profile.content, null, 2));
  const [reason, setReason] = useState("");
  const [copy, setCopy] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [key, setKey] = useState("");
  const [name, setName] = useState(profile.display_name || "");
  return <div className="page-stack">
    <dl className="profile-version-meta"><dt>{text("版本", "Version")}</dt><dd>{profile.version_label}</dd><dt>{text("状态", "Status")}</dt><dd>{profile.status}</dd><dt>{text("内容摘要", "Content digest")}</dt><dd>{profile.content_digest}</dd></dl>
    <h3>{text("有效控制配置", "Effective controls")}</h3>
    {profile.validation?.status === "INVALID" && <p role="alert">{text("继承校验未通过：", "Inheritance validation failed: ")}{profile.validation.reason}</p>}
    <div className="table-scroll"><table><thead><tr><th>{text("配置项", "Control")}</th><th>{text("值", "Value")}</th><th>{text("来源版本", "Source version")}</th></tr></thead><tbody>{Object.entries(profile.effective_content?.controls || {}).map(([field, value]) => <tr key={field}><td>{field}{profile.effective_content?.locked_fields?.includes(field) ? text("（锁定）", " (locked)") : ""}</td><td>{typeof value === "string" ? value : JSON.stringify(value)}</td><td>{profile.field_sources?.[`controls.${field}`]}</td></tr>)}</tbody></table></div>
    <details><summary>{text("完整配置与继承链", "Full configuration and inheritance")}</summary><pre className="decision-box">{JSON.stringify({ effective_content: profile.effective_content, field_sources: profile.field_sources, parent_chain: profile.parent_chain }, null, 2)}</pre></details>
    {editable && <form className="cx-form" onSubmit={async (event) => {
      event.preventDefault(); if (busy) return; setBusy(true); setError("");
      try {
        const parsed = JSON.parse(content);
        if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") throw new Error(text("配置必须是 JSON 对象", "Configuration must be a JSON object"));
        if (copy) await onCopy(key, name, parsed, reason); else await onSave(parsed, reason);
      } catch (error) { setError(error instanceof Error ? error.message : String(error)); }
      finally { setBusy(false); }
    }}>
      <label className="profile-copy-toggle"><input type="checkbox" checked={copy} onChange={(event) => setCopy(event.target.checked)} />{text("复制为新模板草稿", "Copy to a new template draft")}</label>
      {copy && <><label>{text("模板键", "Template key")}<input required value={key} maxLength={128} onChange={(event) => setKey(event.target.value)} /></label><label>{text("名称", "Name")}<input required value={name} maxLength={256} onChange={(event) => setName(event.target.value)} /></label></>}
      {(copy || profile.status === "DRAFT") && <><label>{text("草稿配置", "Draft configuration")}<textarea className="profile-json-editor" value={content} onChange={(event) => setContent(event.target.value)} required spellCheck={false} /></label><label>{text("变更原因", "Change reason")}<input value={reason} required maxLength={2000} onChange={(event) => setReason(event.target.value)} /></label><button className="primary-button" disabled={busy}>{copy ? <Copy size={15} /> : <Save size={15} />}{copy ? text("创建副本", "Create copy") : text("保存草稿", "Save draft")}</button></>}
      {error && <p role="alert">{error}</p>}
    </form>}
  </div>;
}
