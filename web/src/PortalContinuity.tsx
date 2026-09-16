import React, { useEffect, useRef, useState } from "react";
import ContinuityWorkbench from "./ContinuityWorkbench";

type Row = Record<string, any>;

/** A Portal session remains a Portal session; no Dashboard credential bridge. */
export default function PortalContinuity() {
  const [lang, setLang] = useState(localStorage.getItem("cxLang") || "zh");
  const [theme, setTheme] = useState(localStorage.getItem("cxTheme") || "light");
  const [session, setSession] = useState<Row | null>(null);
  const [error, setError] = useState("");
  const expiry = useRef(0);
  const text = (zh: string, en: string) => lang === "zh" ? zh : en;
  const request = async (path: string, options: RequestInit = {}): Promise<Row> => {
    let client = sessionStorage.getItem("cxPortalClientInstance");
    if (!client) { client = crypto.randomUUID(); sessionStorage.setItem("cxPortalClientInstance", client); }
    let page = sessionStorage.getItem("cxPortalPageInstance");
    if (!page) { page = client; sessionStorage.setItem("cxPortalPageInstance", page); }
    const headers = new Headers(options.headers);
    headers.set("X-CX-Client-Instance", client); headers.set("X-CX-Page-Instance", page);
    if (options.method && !["GET", "HEAD"].includes(options.method.toUpperCase())) {
      headers.set("X-CSRF-Token", localStorage.getItem("cxPortalCsrf") || ""); headers.set("Content-Type", "application/json");
    }
    const response = await fetch(path.replace(/^\/api/, "/portal/api/continuity"), { ...options, headers, credentials: "same-origin" });
    if (response.status === 401) { window.location.assign("/portal/login"); throw new Error(text("登录已失效", "Session expired")); }
    const expires = response.headers.get("X-Session-Expires-At");
    if (expires && Number.isFinite(Date.parse(expires))) expiry.current = Date.parse(expires);
    const result = await response.json();
    if (!response.ok) {
      const detail = result.detail;
      throw new Error(typeof detail === "string" ? detail : detail?.message || result.message || text("操作未完成，请检查当前权限和服务状态。", "Operation failed; check current permissions and service status."));
    }
    return result;
  };
  useEffect(() => { document.documentElement.lang = lang === "zh" ? "zh-CN" : "en"; localStorage.setItem("cxLang", lang); }, [lang]);
  useEffect(() => { document.documentElement.dataset.theme = theme; localStorage.setItem("cxTheme", theme); }, [theme]);
  useEffect(() => {
    let active = true;
    void request("/api/session").then(value => { if (active) setSession(value); }).catch(e => { if (active) setError(e.message); });
    const timer = window.setInterval(() => { if (expiry.current && Date.now() >= expiry.current) window.location.assign("/portal/login"); }, 1000);
    return () => { active = false; clearInterval(timer); };
  }, []);
  return <main className="portal-continuity cx-app"><header className="page-toolbar"><a className="secondary-button" href="/portal/chat">{text("返回 Portal", "Back to Portal")}</a><button className="small-button" onClick={() => setLang(lang === "zh" ? "en" : "zh")}>{lang === "zh" ? "English" : "中文"}</button><button className="small-button" onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>{text(theme === "dark" ? "浅色" : "深色", theme === "dark" ? "Light" : "Dark")}</button></header>
    <h1>{text("工作交接", "Work continuity")}</h1><p>{text("在当前权限范围内记录目标、处理交接和审核候选。", "Record objectives, manage handoffs and review candidates within your current permissions.")} {session?.release_version && `v${session.release_version}`}</p>
    {error && <p role="alert">{error}</p>}
    {session && <>{session.read_only && <p role="status">{text("当前页面仅可读取；写入需要有效的页面租约和操作权限。", "This page is read-only; writes require a current page lease and operation permissions.")}</p>}<ContinuityWorkbench request={request} text={text} principalId={session.principal_id} canWrite={session.can_write && !session.read_only} /></>}
  </main>;
}
