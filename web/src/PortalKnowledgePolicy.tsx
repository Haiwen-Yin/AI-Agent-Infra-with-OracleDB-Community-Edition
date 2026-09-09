import React, { useEffect, useRef, useState } from "react";
import { RefreshCw, Save } from "lucide-react";

type Row = Record<string, any>;
export default function PortalKnowledgePolicy({ request, text }: {
  request: (path: string, options?: RequestInit) => Promise<Row>;
  text: (zh: string, en: string) => string;
}) {
  const [policy, setPolicy] = useState<Row | null>(null);
  const [profiles, setProfiles] = useState<Row[]>([]);
  const [mode, setMode] = useState("KNOWLEDGE_FIRST");
  const [supplement, setSupplement] = useState(false);
  const [disclosure, setDisclosure] = useState<string[]>([]);
  const [reason, setReason] = useState("");
  const [organizations, setOrganizations] = useState<Row[]>([]);
  const [organizationId, setOrganizationId] = useState("");
  const [organizationKnowledge, setOrganizationKnowledge] = useState<Row[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const mounted = useRef(false);
  const locked = useRef(false);
  const load = async () => {
    const [next, models, orgs] = await Promise.all([
      request("/api/platform/portal-knowledge-policy"), request("/api/platform/portal-llm-policy"),
      request("/api/knowledge/access-options"),
    ]);
    if (!mounted.current) return;
    setPolicy(next); setMode(next.mode); setSupplement(next.allow_model_supplement === "Y");
    setDisclosure(next.disclosure_profiles); setProfiles(models.profiles || []); setOrganizations(orgs.items || []); setReason("");
  };
  const loadOrganizationKnowledge = async (id: string) => {
    setOrganizationId(id); setOrganizationKnowledge(id ? ((await request(`/api/knowledge/organization-groups/${encodeURIComponent(id)}`)).knowledge || []) : []);
  };
  const run = async (save: boolean) => {
    if (locked.current) return;
    locked.current = true; setBusy(true); setError(""); setSaved(false);
    try {
      if (save && policy) await request("/api/platform/portal-knowledge-policy", {
        method: "PUT", body: JSON.stringify({ mode, allow_model_supplement: mode === "KNOWLEDGE_FIRST" && supplement,
          disclosure_profiles: disclosure, expected_version: policy.version, reason: reason.trim() }),
      });
      await load();
      if (mounted.current) setSaved(save);
    } catch (error) {
      if (mounted.current) setError(error instanceof Error ? error.message : String(error));
    } finally { locked.current = false; if (mounted.current) setBusy(false); }
  };
  useEffect(() => { mounted.current = true; void run(false); return () => { mounted.current = false; }; }, []);
  const known = new Set(profiles.map((item) => String(item.profile_id)));
  return <section className="page-stack" aria-label={text("Portal 知识回答策略", "Portal knowledge answer policy")}>
    <h3>{text("Portal 知识回答策略", "Portal knowledge answer policy")}</h3>
    {error && <p role="alert">{error}</p>}
    {saved && <p role="status">{text("知识回答策略已保存", "Knowledge answer policy saved")}</p>}
    <button type="button" className="small-button" disabled={busy} onClick={() => void run(false)}><RefreshCw size={14} />{text("重新读取", "Reload")}</button>
    {policy && <form className="configuration-form" onSubmit={(event) => { event.preventDefault(); void run(true); }}>
      <fieldset disabled={busy} className="page-stack">
        <legend>{text("策略版本", "Policy version")} {policy.version}</legend>
        <label>{text("回答模式", "Answer mode")}<select value={mode} onChange={(event) => { setMode(event.target.value); setSaved(false); }}>
          <option value="KNOWLEDGE_FIRST">{text("知识优先", "Knowledge first")}</option>
          <option value="KNOWLEDGE_ONLY">{text("仅知识", "Knowledge only")}</option>
        </select></label>
        <label className="checkbox-field"><input type="checkbox" checked={mode === "KNOWLEDGE_FIRST" && supplement} disabled={mode === "KNOWLEDGE_ONLY"} onChange={(event) => { setSupplement(event.target.checked); setSaved(false); }} />{text("允许用户选择通用模型补充", "Allow users to select general model supplementation")}</label>
        <fieldset><legend>{text("允许接收授权知识的模型配置", "Model profiles permitted to receive authorized knowledge")}</legend>
          {[...profiles, ...disclosure.filter((id) => !known.has(id)).map((id) => ({ profile_id: id, profile_key: id, status: "UNAVAILABLE" }))].map((item) => {
            const id = String(item.profile_id);
            return <label className="checkbox-field" key={id}><input type="checkbox" checked={disclosure.includes(id)} onChange={(event) => { setDisclosure((old) => event.target.checked ? [...old, id] : old.filter((value) => value !== id)); setSaved(false); }} />{String(item.profile_key || id)}{!known.has(id) && text("（不可用）", " (unavailable)")}</label>;
          })}
          {!profiles.length && !disclosure.length && <p>{text("暂无模型配置", "No model profiles")}</p>}
        </fieldset>
        <label>{text("变更原因", "Change reason")}<input required minLength={3} maxLength={2000} value={reason} onChange={(event) => { setReason(event.target.value); setSaved(false); }} /></label>
        <button className="primary-button" disabled={reason.trim().length < 3}><Save size={14} />{text("保存知识策略", "Save knowledge policy")}</button>
      </fieldset>
    </form>}
    <fieldset className="configuration-form" disabled={busy}>
      <legend>{text("组织知识覆盖", "Organization knowledge coverage")}</legend>
      <label>{text("组织范围", "Organization scope")}
        <select value={organizationId} onChange={(event) => void loadOrganizationKnowledge(event.target.value)}>
          <option value="">{text("选择组织查看覆盖", "Select an organization")}</option>
          {organizations.map((item) => <option key={String(item.organization_id)} value={String(item.organization_id)}>{String(item.organization_name || item.organization_id)}</option>)}
        </select>
      </label>
      <p role="status">{organizationId ? text(`当前组织有 ${organizationKnowledge.length} 条有效知识策略`, `${organizationKnowledge.length} active knowledge policies`) : text("尚未选择组织", "No organization selected")}</p>
      {organizationKnowledge.slice(0, 20).map((item) => <div key={String(item.entity_id || item.policy_id)}>{String(item.title || item.entity_id)} · {String(item.scope_type)}</div>)}
    </fieldset>
  </section>;
}
