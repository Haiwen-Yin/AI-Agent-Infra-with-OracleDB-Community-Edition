import React from "react";

type Text = (zh: string, en: string) => string;
const names: Record<string, string> = {
  status: "状态", name: "名称", title: "标题", description: "说明", summary: "摘要", content: "内容", detail: "详情",
  agent_id: "智能体", principal_id: "主体", entity_id: "实体编号", created_at: "创建时间", updated_at: "更新时间",
  severity: "严重程度", rule_code: "检查规则", rule_version: "规则版本", finding_id: "发现编号", case_id: "整改编号",
  evidence_id: "证据编号", response_evidence_id: "整改证据", required_action: "整改要求", deadline_at: "截止时间",
  first_observed_at: "首次发现", last_observed_at: "最近发现", automatic_action: "自动响应", reason: "原因",
  version: "版本", version_id: "版本编号", family_id: "记忆族", type: "类型", entity_type: "实体类型", category: "分类",
  controls: "控制配置", allowed_tools: "允许的工具", allowed_skills: "允许的技能", network: "网络出口",
  network_egress: "网络出口", database: "数据库访问", database_access: "数据库访问", approval: "审批策略",
  approval_policy: "审批策略", audit: "审计策略", audit_retention: "审计留存", classification_ceiling: "数据分类上限",
  parameters: "参数", input_schema: "输入参数", output_schema: "输出结果", tool_name: "工具名称", tool_id: "工具编号",
  display_name: "显示名称", owner_ref: "所有者", permission: "权限", enabled: "启用", metadata: "元数据",
  graph_id: "图编号", graph_version_id: "图版本", run_id: "运行编号", visibility: "可见范围", tags: "标签",
};
const states: Record<string, string> = { OPEN: "待处理", ACKNOWLEDGED: "已确认 / 待复核", REMEDIATING: "整改中", RESOLVED: "已处理", CLOSED: "已关闭", ACTIVE: "有效", INACTIVE: "停用", DRAFT: "草稿", PUBLISHED: "已发布", HIGH: "高", MEDIUM: "中", LOW: "低", CRITICAL: "严重", ALLOW: "允许", DENY: "禁止", REQUIRED: "必须", NONE: "无", INTERNAL: "内部", CONFIDENTIAL: "机密", RESTRICTED: "受限", ALLOWLIST: "白名单", ISOLATED: "隔离", GATEWAY_ONLY: "仅网关", EVIDENCE_REQUIRED: "必须保留证据" };

export default function RecordDetails({ value, text, raw = true, depth = 0 }: { value: any; text: Text; raw?: boolean; depth?: number }) {
  const render = (item: any): React.ReactNode => {
    if (item === null || item === undefined || item === "") return text("未设置", "Not set");
    if (typeof item === "boolean") return item ? text("是", "Yes") : text("否", "No");
    if (typeof item === "object") return depth >= 6 ? <details><summary>{text("展开内容", "Expand content")}</summary><pre>{JSON.stringify(item, null, 2)}</pre></details> : <RecordDetails value={item} text={text} raw={false} depth={depth + 1} />;
    const str = String(item);
    if (states[str]) return text(states[str], str);
    if (/^[\[{]/.test(str)) { try { return render(JSON.parse(str)); } catch { /* Preserve plain text. */ } }
    return str;
  };
  return <div className="record-details">
    {Array.isArray(value) ? (value.length ? <ul>{value.map((item, i) => <li key={i}>{render(item)}</li>)}</ul> : <span>{text("无条目", "No entries")}</span>) : value && typeof value === "object" ? <dl>{Object.entries(value).filter(([key]) => key !== "kind").map(([key, item]) => <div key={key}><dt>{names[key] ? text(names[key], key.replaceAll("_", " ")) : key.replaceAll("_", " ")}</dt><dd>{render(item)}</dd></div>)}</dl> : render(value)}
    {raw && <details className="record-raw"><summary>{text("原始数据", "Raw data")}</summary><pre>{JSON.stringify(value, null, 2)}</pre></details>}
  </div>;
}
