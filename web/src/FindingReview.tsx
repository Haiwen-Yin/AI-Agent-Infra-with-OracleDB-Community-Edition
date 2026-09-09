import React, { useState } from "react";
import { Check, ClipboardCheck } from "lucide-react";
type Row = Record<string, any>;
export default function FindingReview({ finding, text, onReview, onRemediate }: {
  finding: Row; text: (zh: string, en: string) => string;
  onReview: (body: Row) => Promise<void>; onRemediate: (body: Row) => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const closed = ["RESOLVED", "CLOSED"].includes(finding.status);
  return <form className="cx-form" onSubmit={async (event) => {
    event.preventDefault(); if (busy) return;
    const data = Object.fromEntries(new FormData(event.currentTarget).entries()); setBusy(true); setError("");
    try {
      if (data.decision === "REMEDIATE") await onRemediate({required_action: data.required_action, reason: data.reason});
      else await onReview({...data, expected_status: finding.status, expected_observed_at: finding.last_observed_at});
    } catch (error) { setError((error as Error).message); } finally { setBusy(false); }
  }}>
    <h3>{text("处理与复核", "Review and remediation")}</h3>
    <label>{text("处理决定", "Decision")}<select name="decision" defaultValue={closed ? "REOPEN" : "RESOLVE"}>
      {closed ? <option value="REOPEN">{text("重新打开", "Reopen")}</option> : <><option value="RESOLVE">{text("确认已处理", "Confirm resolved")}</option>{finding.status === "OPEN" && <option value="ACKNOWLEDGE">{text("确认收到", "Acknowledge")}</option>}<option value="REMEDIATE">{text("发起整改", "Request remediation")}</option></>}
    </select></label>
    <label>{text("处理说明", "Review reason")}<textarea name="reason" required minLength={3} maxLength={2000} /></label>
    <label>{text("复核证据引用", "Review evidence reference")}<input name="evidence_ref" maxLength={2000} /></label>
    <label>{text("整改要求", "Required remediation")}<input name="required_action" maxLength={128} /></label>
    <p>{text("确认已处理仅记录本次人工复核；Agent 的隔离、禁用和权限恢复需单独审批。", "Resolution records this human review. Agent isolation, disablement and access recovery require separate approval.")}</p>
    <button className="primary-button" disabled={busy}><ClipboardCheck size={16} />{text("提交处理", "Submit review")}</button>
    {error && <p role="alert">{error}</p>}
  </form>;
}
