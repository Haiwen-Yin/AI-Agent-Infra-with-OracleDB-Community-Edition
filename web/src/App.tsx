import React, { FormEvent, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  AlertTriangle,
  ArrowDownUp,
  Bot,
  Building2,
  Check,
  ChevronRight,
  CircleHelp,
  Database,
  GitCompareArrows,
  FileKey2,
  Download,
  GitBranch,
  History,
  Layers3,
  List,
  LogOut,
  Maximize2,
  MessageSquare,
  Moon,
  Network,
  PauseCircle,
  PlayCircle,
  Plus,
  Redo2,
  RefreshCw,
  Search,
  ShieldCheck,
  StopCircle,
  Sun,
  Upload,
  UserPlus,
  Users,
  Undo2,
  X,
} from "lucide-react";
import "./app.css";

type Lang = "zh" | "en";
type Theme = "light" | "dark";
type Row = Record<string, any>;
type VisNetwork = {
  destroy: () => void;
  fit: (options?: Row) => void;
  getPositions: (nodeIds?: string[]) => Record<string, { x: number; y: number }>;
  on: (event: string, handler: (params: Row) => void) => void;
};

declare global {
  interface Window {
    vis?: {
      DataSet: new (items: Row[]) => any;
      Network: new (
        container: HTMLElement,
        data: Row,
        options: Row,
      ) => VisNetwork;
    };
  }
}

let activeRequests = 0;
function requestActivity(delta: number) {
  activeRequests = Math.max(0, activeRequests + delta);
  window.dispatchEvent(
    new CustomEvent("cx-request-activity", { detail: activeRequests }),
  );
}

const nav = [
  ["monitor", "监控", "Monitor", Activity],
  ["agents", "智能体", "Agents", Bot],
  ["tasks", "任务", "Tasks", PlayCircle],
  ["workspaces", "工作区", "Workspaces", Layers3],
  ["knowledge", "知识", "Knowledge", Database],
  ["memory", "记忆", "Memory", Network],
  ["skills", "技能", "Skills", FileKey2],
  ["specs", "规格", "Specs", FileKey2],
  ["branches", "分支", "Branches", GitBranch],
  ["collab", "协作", "Collaboration", Users],
  ["loops", "循环", "Loops", RefreshCw],
  ["graph", "图探索", "Graph", Network],
  ["channels", "频道", "Channels", MessageSquare],
  ["barriers", "协作关卡", "Collaboration gates", CircleHelp],
  ["approvals", "审批", "Approvals", ShieldCheck],
  ["audit", "审计", "Audit", FileKey2],
  ["users", "用户管理", "Users", Users],
  ["organization", "组织架构", "Organization", Building2],
] as const;

const tx = (lang: Lang, zh: string, en: string) => (lang === "zh" ? zh : en);
const pageFromPath = () => {
  const parts = window.location.pathname.split("/").filter(Boolean);
  return parts[0] === "app" && parts[1] ? parts[1] : "monitor";
};

async function api<T = Row>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers || {});
  headers.set("Accept", "application/json");
  if (
    options.body &&
    !(options.body instanceof FormData) &&
    !headers.has("Content-Type")
  )
    headers.set("Content-Type", "application/json");
  const csrf = localStorage.getItem("cxCsrf");
  if (csrf && options.method && options.method !== "GET")
    headers.set("X-CSRF-Token", csrf);
  requestActivity(1);
  try {
    const response = await fetch(path, {
      ...options,
      headers,
      credentials: "same-origin",
    });
    const refreshedExpiry = response.headers.get("X-Session-Expires-At");
    if (refreshedExpiry)
      window.dispatchEvent(
        new CustomEvent("cx-session-refresh", { detail: refreshedExpiry }),
      );
    if (!response.ok) {
      let message = response.statusText;
      try {
        const detail = await response.json();
        message =
          typeof detail.detail === "string"
            ? detail.detail
            : detail.error || message;
      } catch {
        /* non-JSON error */
      }
      const error = new Error(message);
      (error as Error & { status?: number }).status = response.status;
      throw error;
    }
    return response.json() as Promise<T>;
  } finally {
    requestActivity(-1);
  }
}

function App() {
  const [page, setPage] = useState(pageFromPath);
  const [lang, setLang] = useState<Lang>(
    () => (localStorage.getItem("cxLang") as Lang) || "zh",
  );
  const [theme, setTheme] = useState<Theme>(
    () => (localStorage.getItem("cxTheme") as Theme) || "light",
  );
  const [me, setMe] = useState<Row | null>(null);
  const [capabilities, setCapabilities] = useState<Row | null>(null);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState("");
  const [authMode, setAuthMode] = useState<"login" | "register">("login");
  const [authSetup, setAuthSetup] = useState<Row | null>(null);
  const [requesting, setRequesting] = useState(false);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("cxTheme", theme);
  }, [theme]);
  useEffect(() => {
    document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
    localStorage.setItem("cxLang", lang);
  }, [lang]);
  useEffect(() => {
    setLoading(true);
    api<Row>("/api/auth/me")
      .then((value) => {
        if (value.mfa_setup_required) {
          setAuthSetup(value);
          setMe(null);
          setCapabilities(null);
          return null;
        }
        setAuthSetup(null);
        setMe(value);
        return api<Row>("/api/capabilities");
      })
      .then((value) => {
        if (value) setCapabilities(value);
      })
      .catch((error) => {
        if ((error as Error & { status?: number }).status === 401) setMe(null);
        else setNotice(error.message);
      })
      .finally(() => setLoading(false));
  }, []);
  useEffect(() => {
    const onPopState = () => setPage(pageFromPath());
    const onRequest = (event: Event) =>
      setRequesting(Number((event as CustomEvent).detail) > 0);
    window.addEventListener("popstate", onPopState);
    window.addEventListener("cx-request-activity", onRequest);
    return () => {
      window.removeEventListener("popstate", onPopState);
      window.removeEventListener("cx-request-activity", onRequest);
    };
  }, []);

  const navigate = (next: string) => {
    if (next === page) return;
    window.history.pushState({}, "", `/app/${next}`);
    setPage(next);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const text = (zh: string, en: string) => tx(lang, zh, en);
  if (loading)
    return (
      <div className="cx-loading">
        <RefreshCw className="spin" size={20} />
        {text("正在连接数据库服务", "Connecting to database services")}
      </div>
    );
  if (!me)
    return (
      <AuthScreen
        initialSetup={authSetup}
        lang={lang}
        mode={authMode}
        onModeChange={setAuthMode}
        onLogin={(value) => {
          if (value.csrf_token)
            localStorage.setItem("cxCsrf", value.csrf_token);
          setAuthSetup(null);
          setMe(value);
          api<Row>("/api/capabilities")
            .then(setCapabilities)
            .catch(() => undefined);
        }}
        onNotice={setNotice}
        notice={notice}
      />
    );

  const allowedPages = new Set<string>(
    capabilities?.pages || nav.map((item) => item[0]),
  );
  return (
    <div className="cx-app">
      {requesting && (
        <div className="cx-request-progress" role="progressbar">
          <span />
        </div>
      )}
      <Header
        lang={lang}
        theme={theme}
        page={page}
        allowedPages={allowedPages}
        releaseVersion={String(capabilities?.release_version || "")}
        expiresAt={me.expires_at}
        onNavigate={navigate}
        onLang={() => setLang(lang === "zh" ? "en" : "zh")}
        onTheme={() => setTheme(theme === "light" ? "dark" : "light")}
        onLogout={async () => {
          try {
            await api("/api/auth/logout", { method: "POST" });
          } finally {
            localStorage.removeItem("cxCsrf");
            setMe(null);
          }
        }}
        text={text}
      />
      <main className="cx-main">
        {notice && (
          <div className="cx-notice" role="status">
            {notice}
            <button
              aria-label={text("关闭", "Close")}
              onClick={() => setNotice("")}
            >
              <X size={15} />
            </button>
          </div>
        )}
        <PageView
          key={page}
          page={allowedPages.has(page) ? page : "monitor"}
          lang={lang}
          me={me}
          capabilities={capabilities}
          text={text}
          onNotice={setNotice}
        />
      </main>
    </div>
  );
}

function Header({
  lang,
  theme,
  page,
  allowedPages,
  releaseVersion,
  expiresAt,
  onNavigate,
  onLang,
  onTheme,
  onLogout,
  text,
}: {
  lang: Lang;
  theme: Theme;
  page: string;
  allowedPages: Set<string>;
  releaseVersion: string;
  expiresAt?: string;
  onNavigate: (page: string) => void;
  onLang: () => void;
  onTheme: () => void;
  onLogout: () => void;
  text: (zh: string, en: string) => string;
}) {
  const [deadline, setDeadline] = useState(expiresAt || "");
  const secondsUntilExpiry = (value = deadline) => {
    const raw = value || "";
    const normalized =
      raw && !/[zZ]|[+-]\d\d:\d\d$/.test(raw) ? `${raw}Z` : raw;
    return Math.max(
      0,
      Math.ceil((new Date(normalized || 0).getTime() - Date.now()) / 1000),
    );
  };
  const [seconds, setSeconds] = useState(() =>
    secondsUntilExpiry(expiresAt || ""),
  );
  useEffect(() => {
    setDeadline(expiresAt || "");
    setSeconds(secondsUntilExpiry(expiresAt || ""));
  }, [expiresAt]);
  useEffect(() => {
    const refresh = (event: Event) => {
      const value = String((event as CustomEvent).detail || "");
      setDeadline(value);
      setSeconds(secondsUntilExpiry(value));
    };
    window.addEventListener("cx-session-refresh", refresh);
    return () => window.removeEventListener("cx-session-refresh", refresh);
  }, []);
  useEffect(() => {
    const timer = window.setInterval(() => {
      const remaining = secondsUntilExpiry();
      setSeconds(remaining);
      if (remaining <= 0) onLogout();
    }, 1000);
    return () => window.clearInterval(timer);
  }, [deadline]);
  const clock = `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
  return (
    <header className="cx-header">
      <a
        className="cx-brand"
        href="/app/monitor"
        onClick={(event) => {
          event.preventDefault();
          onNavigate("monitor");
        }}
        aria-label={text(
          "川序 AI Agent 管理平台",
          "Chuanxu AI Agent Management Platform",
        )}
      >
        <img src="/static/brand/chuanxu-mark.svg" alt="" />
        <span>
          <strong>{text("川序", "Chuanxu")}</strong>
          <small>
            <span className="cx-brand-product">
              {text("AI Agent 管理平台", "AI Agent Management Platform")}
            </span>
            {releaseVersion && (
              <span
                className="cx-release-version"
                title={text("产品版本", "Product version")}
              >
                v{releaseVersion}
              </span>
            )}
          </small>
        </span>
        <span
          className="cx-brand-pillars"
          aria-label={text(
            "可观测、可调度、可运维",
            "Observable, schedulable, operable",
          )}
        >
          <span>{text("可观测", "Observable")}</span>
          <span>{text("可调度", "Schedulable")}</span>
          <span>{text("可运维", "Operable")}</span>
        </span>
      </a>
      <div className="cx-nav-stack">
        <nav
          className="cx-nav"
          aria-label={text("主导航", "Primary navigation")}
        >
          {nav
            .filter((item) => allowedPages.has(item[0]))
            .map(([key, zh, en, Icon]) => (
              <a
                className={key === page ? "active" : ""}
                href={`/app/${key}`}
                onClick={(event) => {
                  event.preventDefault();
                  onNavigate(key);
                }}
                key={key}
              >
                <Icon size={14} />
                <span>{text(zh, en)}</span>
              </a>
            ))}
        </nav>
      </div>
      <div className="cx-actions">
        <button
          className="icon-button"
          onClick={onTheme}
          title={text("切换亮暗色", "Toggle theme")}
          aria-label={text("切换亮暗色", "Toggle theme")}
        >
          {theme === "light" ? <Moon size={17} /> : <Sun size={17} />}
        </button>
        <button
          className="language-button"
          onClick={onLang}
          title={text("切换语言", "Switch language")}
          aria-label={text("切换语言", "Switch language")}
        >
          {lang === "zh" ? "EN" : "中"}
        </button>
        <span
          className={`cx-session-clock ${seconds <= 60 ? "warn" : ""}`}
          title={text("自动登出倒计时", "Automatic logout countdown")}
        >
          {clock}
        </span>
        <button
          className="icon-button"
          onClick={onLogout}
          title={text("登出", "Log out")}
          aria-label={text("登出", "Log out")}
        >
          <LogOut size={17} />
        </button>
      </div>
    </header>
  );
}

function AuthScreen({
  initialSetup,
  lang,
  mode,
  onModeChange,
  onLogin,
  onNotice,
  notice,
}: {
  initialSetup: Row | null;
  lang: Lang;
  mode: "login" | "register";
  onModeChange: (mode: "login" | "register") => void;
  onLogin: (value: Row) => void;
  onNotice: (value: string) => void;
  notice: string;
}) {
  const text = (zh: string, en: string) => tx(lang, zh, en);
  const [busy, setBusy] = useState(false);
  const [setup, setSetup] = useState<Row | null>(initialSetup);
  useEffect(() => setSetup(initialSetup), [initialSetup]);
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusy(true);
    onNotice("");
    const data = Object.fromEntries(
      new FormData(event.currentTarget).entries(),
    );
    try {
      if (mode === "login") {
        const value = await api<Row>("/api/auth/login", {
          method: "POST",
          body: JSON.stringify(data),
        });
        if (value.mfa_setup_required) {
          if (value.csrf_token)
            localStorage.setItem("cxCsrf", value.csrf_token);
          setSetup(value);
          return;
        }
        onLogin(value);
      } else {
        const value = await api<Row>("/api/auth/register", {
          method: "POST",
          body: JSON.stringify(data),
        });
        onNotice(
          value.status === "ACTIVE"
            ? text(
                "注册成功，请登录。",
                "Registration completed. Please log in.",
              )
            : text(
                "注册申请已提交，等待管理员审批。",
                "Registration submitted for administrator approval.",
              ),
        );
        onModeChange("login");
      }
    } catch (error) {
      onNotice(
        error instanceof Error
          ? error.message
          : text("操作失败", "Operation failed"),
      );
    } finally {
      setBusy(false);
    }
  };
  if (setup)
    return (
      <MfaSetupScreen
        lang={lang}
        setup={setup}
        onLogin={onLogin}
        onNotice={onNotice}
        notice={notice}
      />
    );
  return (
    <div className="cx-auth-page">
      <div className="cx-auth-panel">
        <div className="cx-auth-mark">
          <img src="/static/brand/chuanxu-mark.svg" alt="" />
          <div>
            <strong>川序</strong>
            <span>
              {text("AI Agent 管理平台", "AI Agent Management Platform")}
            </span>
          </div>
        </div>
        <div className="cx-auth-tabs">
          <button
            className={mode === "login" ? "active" : ""}
            onClick={() => onModeChange("login")}
          >
            {text("登录", "Sign in")}
          </button>
          <button
            className={mode === "register" ? "active" : ""}
            onClick={() => onModeChange("register")}
          >
            {text("注册", "Register")}
          </button>
        </div>
        <form onSubmit={submit} className="cx-form">
          {mode === "register" && (
            <label>
              {text("姓名", "Full name")}
              <input
                name="display_name"
                autoComplete="name"
                required
                maxLength={256}
              />
            </label>
          )}
          <label>
            {text("用户名", "Username")}
            <input
              name="username"
              autoComplete="username"
              required
              minLength={3}
            />
          </label>
          {mode === "register" && (
            <label>
              {text("邮箱（可选）", "Email (optional)")}
              <input name="email" type="email" autoComplete="email" />
            </label>
          )}
          <label>
            {text("密码", "Password")}
            <input
              name="password"
              type="password"
              autoComplete={
                mode === "login" ? "current-password" : "new-password"
              }
              required
              minLength={mode === "login" ? 1 : 12}
            />
          </label>
          {mode === "login" && (
            <label>
              {text("MFA 验证码（可选）", "MFA code (optional)")}
              <input
                name="mfa_code"
                inputMode="numeric"
                autoComplete="one-time-code"
              />
            </label>
          )}
          {mode === "register" && (
            <p className="cx-form-hint">
              {text(
                "密码至少 12 位。新账号默认进入审批流程，不会自行获得管理权限。",
                "Use at least 12 characters. New accounts enter approval and receive no administrative privileges by themselves.",
              )}
            </p>
          )}
          {mode === "login" && (
            <p className="cx-form-hint">
              {text(
                "已启用 MFA 的账号需要验证码；管理员可登录后在用户管理中注册因子并配置是否强制。",
                "Accounts with MFA enabled need a code. Administrators can enroll a factor and configure enforcement in User Management after login.",
              )}
            </p>
          )}
          {notice && <div className="cx-form-notice">{notice}</div>}
          <button className="primary-button" disabled={busy}>
            {busy ? (
              <RefreshCw className="spin" size={16} />
            ) : (
              <ChevronRight size={16} />
            )}{" "}
            {mode === "login"
              ? text("进入平台", "Enter platform")
              : text("提交注册", "Submit registration")}
          </button>
        </form>
        <p className="cx-auth-foot">
          {text(
            "身份、上下文、执行和审计边界由数据库持久化。",
            "Database-backed identity, context, execution, and audit boundaries.",
          )}
        </p>
      </div>
    </div>
  );
}

function MfaSetupScreen({
  lang,
  setup,
  onLogin,
  onNotice,
  notice,
}: {
  lang: Lang;
  setup: Row;
  onLogin: (value: Row) => void;
  onNotice: (value: string) => void;
  notice: string;
}) {
  const text = (zh: string, en: string) => tx(lang, zh, en);
  const [factor, setFactor] = useState<Row | null>(null);
  const [busy, setBusy] = useState(false);
  const begin = async () => {
    setBusy(true);
    onNotice("");
    try {
      const value = await api<Row>("/api/auth/mfa/enroll", {
        method: "POST",
        body: JSON.stringify({ reason: "initial MFA enrollment" }),
      });
      setFactor(value);
    } catch (error) {
      onNotice(
        error instanceof Error
          ? error.message
          : text("MFA 配置失败", "MFA setup failed"),
      );
    } finally {
      setBusy(false);
    }
  };
  const confirm = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!factor) return;
    setBusy(true);
    onNotice("");
    const data = Object.fromEntries(
      new FormData(event.currentTarget).entries(),
    );
    try {
      const value = await api<Row>("/api/auth/mfa/confirm", {
        method: "POST",
        body: JSON.stringify({
          factor_id: factor.factor_id,
          code: data.code,
          reason: "confirm initial MFA enrollment",
        }),
      });
      onLogin({
        ...setup,
        ...value,
        mfa_setup_required: false,
        mfa_level: "STRONG",
      });
    } catch (error) {
      onNotice(
        error instanceof Error
          ? error.message
          : text("MFA 验证失败", "MFA confirmation failed"),
      );
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="cx-auth-page">
      <div className="cx-auth-panel">
        <div className="cx-auth-mark">
          <img src="/static/brand/chuanxu-mark.svg" alt="" />
          <div>
            <strong>川序</strong>
            <span>
              {text("AI Agent 管理平台", "AI Agent Management Platform")}
            </span>
          </div>
        </div>
        <h2>{text("完成 MFA 配置", "Complete MFA setup")}</h2>
        <p className="cx-form-hint">
          {text(
            "密码已验证。由于当前账号需要 MFA，应用页面在完成配置前保持不可用。",
            "Your password is verified. This account requires MFA, so application pages remain unavailable until setup is complete.",
          )}
        </p>
        {!factor && (
          <button
            className="primary-button"
            type="button"
            disabled={busy}
            onClick={() => void begin()}
          >
            {busy ? (
              <RefreshCw className="spin" size={16} />
            ) : (
              <ChevronRight size={16} />
            )}{" "}
            {text("生成 MFA 配置", "Generate MFA setup")}
          </button>
        )}
        {factor && (
          <>
            <div className="one-time-token">
              <b>
                {text(
                  "在验证器中添加以下密钥",
                  "Add this secret to your authenticator",
                )}
              </b>
              <code>{factor.secret}</code>
              <small>
                {text(
                  "平台只保存加密后的密钥；请完成确认后再继续。",
                  "The platform stores only the encrypted secret; confirm it before continuing.",
                )}
              </small>
            </div>
            <form onSubmit={confirm} className="cx-form">
              <label>
                {text("当前 MFA 验证码", "Current MFA code")}
                <input
                  name="code"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  required
                />
              </label>
              {notice && <div className="cx-form-notice">{notice}</div>}
              <button className="primary-button" disabled={busy}>
                {busy ? (
                  <RefreshCw className="spin" size={16} />
                ) : (
                  <ChevronRight size={16} />
                )}{" "}
                {text("确认并进入平台", "Confirm and enter platform")}
              </button>
            </form>
          </>
        )}
        {!factor && notice && <div className="cx-form-notice">{notice}</div>}
      </div>
    </div>
  );
}

function PageView({
  page,
  lang,
  me,
  capabilities,
  text,
  onNotice,
}: {
  page: string;
  lang: Lang;
  me: Row;
  capabilities: Row | null;
  text: (zh: string, en: string) => string;
  onNotice: (value: string) => void;
}) {
  if (page === "channels")
    return (
      <Channels
        lang={lang}
        capabilities={capabilities}
        text={text}
        onNotice={onNotice}
      />
    );
  if (page === "users")
    return (
      <UsersPage
        lang={lang}
        capabilities={capabilities}
        text={text}
        onNotice={onNotice}
      />
    );
  if (page === "organization")
    return (
      <OrganizationPage
        lang={lang}
        capabilities={capabilities}
        text={text}
        onNotice={onNotice}
      />
    );
  if (page === "agents")
    return (
      <AgentsPage
        lang={lang}
        capabilities={capabilities}
        text={text}
        onNotice={onNotice}
      />
    );
  if (page === "barriers")
    return (
      <BarriersPage
        lang={lang}
        capabilities={capabilities}
        text={text}
        onNotice={onNotice}
      />
    );
  if (page === "monitor")
    return (
      <MonitorPage
        lang={lang}
        capabilities={capabilities}
        text={text}
        onNotice={onNotice}
      />
    );
  if (page === "graph")
    return <GraphPage lang={lang} text={text} onNotice={onNotice} />;
  if (page === "approvals")
    return (
      <ApprovalsPage
        lang={lang}
        capabilities={capabilities}
        text={text}
        onNotice={onNotice}
      />
    );
  if (page === "audit")
    return (
      <AuditPage
        lang={lang}
        capabilities={capabilities}
        text={text}
        onNotice={onNotice}
      />
    );
  if (["skills", "branches", "loops"].includes(page))
    return (
      <>
        <LegacyOperations
          page={page}
          lang={lang}
          capabilities={capabilities}
          text={text}
          onNotice={onNotice}
        />
        <DataPage page={page} lang={lang} text={text} onNotice={onNotice} />
      </>
    );
  return <DataPage page={page} lang={lang} text={text} onNotice={onNotice} />;
}

type DataPageConfig = {
  endpoint: string;
  title: [string, string];
  subtitle: [string, string];
  labels: [string, string][];
  fields: string[][];
  payloadKeys?: string[];
};

const dataPageConfigs: Record<string, DataPageConfig> = {
  tasks: {
    endpoint: "/api/tasks",
    title: ["任务", "Tasks"],
    subtitle: [
      "任务计划、步骤和执行状态来自数据库事实源。",
      "Task plans, steps, and execution status come from the database fact source.",
    ],
    labels: [
      ["ID", "ID"],
      ["目标", "Goal"],
      ["状态", "Status"],
      ["更新时间", "Updated"],
    ],
    fields: [
      ["plan_id", "task_id", "id"],
      ["goal", "input", "title"],
      ["status"],
      ["updated_at", "created_at"],
    ],
    payloadKeys: ["tasks", "plans"],
  },
  workspaces: {
    endpoint: "/api/workspaces?view=summary",
    title: ["工作区", "Workspaces"],
    subtitle: [
      "工作区隔离任务上下文、可见性和协作边界。",
      "Workspaces isolate task context, visibility, and collaboration boundaries.",
    ],
    labels: [
      ["ID", "ID"],
      ["名称", "Name"],
      ["可见性", "Visibility"],
      ["更新时间", "Updated"],
    ],
    fields: [
      ["workspace_id", "id"],
      ["workspace_name", "name", "title"],
      ["visibility", "status"],
      ["updated_at", "created_at"],
    ],
    payloadKeys: ["workspaces"],
  },
  knowledge: {
    endpoint: "/api/knowledge",
    title: ["知识", "Knowledge"],
    subtitle: [
      "知识内容、来源和检索结果由数据库保存并按权限返回。",
      "Knowledge content, provenance, and retrieval results are stored and authorized by the database.",
    ],
    labels: [
      ["ID", "ID"],
      ["标题", "Title"],
      ["领域", "Domain"],
      ["重要度", "Importance"],
    ],
    fields: [
      ["entity_id", "knowledge_id", "id"],
      ["title", "name"],
      ["domain", "category", "topic"],
      ["importance", "status"],
    ],
    payloadKeys: ["knowledge", "items"],
  },
  memory: {
    endpoint: "/api/memory",
    title: ["记忆", "Memory"],
    subtitle: [
      "记忆按智能体、用户和可见性边界读取，避免跨主体上下文污染。",
      "Memory is read within Agent, user, and visibility boundaries to avoid cross-subject context contamination.",
    ],
    labels: [
      ["ID", "ID"],
      ["摘要", "Summary"],
      ["分类", "Category"],
      ["重要度", "Importance"],
    ],
    fields: [
      ["entity_id", "memory_id", "id"],
      ["title", "summary", "name"],
      ["category", "visibility"],
      ["importance", "status"],
    ],
    payloadKeys: ["memories", "memory", "items"],
  },
  skills: {
    endpoint: "/api/skills",
    title: ["技能清单", "Skill inventory"],
    subtitle: [
      "选择上方管理区中的已有技能，可以更新元数据、替换资源、下载或删除。",
      "Select an existing Skill in the management area above to update metadata, replace resources, download, or delete it.",
    ],
    labels: [
      ["ID", "ID"],
      ["技能", "Skill"],
      ["版本", "Version"],
      ["状态", "Status"],
    ],
    fields: [
      ["skill_id", "entity_id", "id"],
      ["skill_name", "name", "title"],
      ["skill_version", "version"],
      ["skill_status", "status", "visibility"],
    ],
    payloadKeys: ["skills", "items"],
  },
  specs: {
    endpoint: "/api/specs",
    title: ["规格", "Specs"],
    subtitle: [
      "规格定义任务约束、复杂度和可验证的执行意图。",
      "Specs define task constraints, complexity, and verifiable execution intent.",
    ],
    labels: [
      ["ID", "ID"],
      ["标题", "Title"],
      ["状态", "Status"],
      ["复杂度", "Complexity"],
    ],
    fields: [
      ["spec_id", "entity_id", "id"],
      ["title", "name"],
      ["spec_status", "status"],
      ["complexity", "scope"],
    ],
    payloadKeys: ["specs", "items"],
  },
  branches: {
    endpoint: "/api/branches",
    title: ["分支清单", "Branch inventory"],
    subtitle: [
      "分支隔离并行工作；打开分支详情可查看工作区、父子分支和执行智能体关系。",
      "Branches isolate parallel work; the relationship view also shows Workspace, parent-Branch, and execution-Agent ownership.",
    ],
    labels: [
      ["ID", "ID"],
      ["分支", "Branch"],
      ["状态", "Status"],
      ["归属/更新时间", "Owner / updated"],
    ],
    fields: [
      ["branch_id", "id"],
      ["branch_name", "name", "title"],
      ["branch_status", "status"],
      ["agent_id", "owner_id", "created_by", "updated_at"],
    ],
    payloadKeys: ["branches", "items"],
  },
  collab: {
    endpoint: "/api/collab",
    title: ["协作", "Collaboration"],
    subtitle: [
      "旧版协作组作为兼容视图保留；新的多人协作应使用具备主体与安全域边界的频道。",
      "Legacy collaboration groups remain as a compatibility view; new collaboration should use Principal- and Security Domain-governed Channels.",
    ],
    labels: [
      ["ID", "ID"],
      ["协作组", "Group"],
      ["协调者", "Coordinator"],
      ["状态", "Status"],
      ["成员", "Members"],
    ],
    fields: [
      ["group_id", "id"],
      ["group_name", "name"],
      ["coordinator_agent_id", "created_by"],
      ["status"],
      ["member_count"],
    ],
    payloadKeys: ["groups", "items"],
  },
  loops: {
    endpoint: "/api/loops",
    title: ["循环", "Loops"],
    subtitle: [
      "循环是可重复执行的任务单元，可被图编排并在协作关卡处等待。",
      "A Loop is a repeatable task unit that Graph can orchestrate and pause at Collaboration gates.",
    ],
    labels: [
      ["ID", "ID"],
      ["循环", "Loop"],
      ["状态", "Status"],
      ["运行/更新时间", "Runs / updated"],
    ],
    fields: [
      ["loop_id", "id"],
      ["name", "title"],
      ["status"],
      ["run_count", "updated_at"],
    ],
    payloadKeys: ["loops", "items"],
  },
};

const statusLabels: Record<string, [string, string]> = {
  ACTIVE: ["活动", "Active"],
  RUNNING: ["运行中", "Running"],
  WAITING: ["等待中", "Waiting"],
  READY: ["待放行", "Ready"],
  RELEASED: ["已放行", "Released"],
  REJECTED: ["已拒绝", "Rejected"],
  PROPOSED: ["待审批", "Proposed"],
  DISABLED: ["已禁用", "Disabled"],
  PENDING: ["待处理", "Pending"],
  FAILED: ["失败", "Failed"],
  PAUSED: ["已暂停", "Paused"],
  COMPLETED: ["已完成", "Completed"],
  QUARANTINED: ["已隔离", "Quarantined"],
  APPROVED: ["已批准", "Approved"],
  DENIED: ["已拒绝", "Denied"],
  EXPIRED: ["已过期", "Expired"],
  REVOKED: ["已撤销", "Revoked"],
  ACKED: ["已确认", "Acknowledged"],
  DEAD_LETTER: ["死信", "Dead letter"],
  INACTIVE: ["非活动", "Inactive"],
  ERROR: ["错误", "Error"],
  PENDING_CONFIRMATION: ["待确认", "Pending confirmation"],
  CANCELLED: ["已取消", "Cancelled"],
  REVIEW_REQUIRED: ["需要复核", "Review required"],
};

const valueLabels: Record<string, [string, string]> = {
  PUBLIC: ["公开", "Public"],
  INTERNAL: ["内部", "Internal"],
  CONFIDENTIAL: ["机密", "Confidential"],
  RESTRICTED: ["受限", "Restricted"],
  PRIVATE: ["私有", "Private"],
  OWNER: ["所有者", "Owner"],
  MEMBER: ["成员", "Member"],
  PRIMARY_OWNER: ["主所有者", "Primary owner"],
  SPONSOR: ["发起者", "Sponsor"],
  OPERATOR: ["操作员", "Operator"],
  VIEWER: ["查看者", "Viewer"],
  MANAGER: ["管理者", "Manager"],
  REVIEWER: ["复核者", "Reviewer"],
  APPROVER: ["审批者", "Approver"],
  HUMAN: ["人", "Human"],
  AGENT: ["智能体", "Agent"],
  TEAM: ["团队", "Team"],
  DIRECT: ["直接", "Direct"],
  CHANNEL: ["频道", "Channel"],
  TEXT: ["文本", "Text"],
  ACTION: ["动作", "Action"],
  GRAPH: ["图", "Graph"],
  LOOP: ["循环", "Loop"],
  TOOL: ["工具", "Tool"],
  SKILL: ["技能", "Skill"],
  APPROVAL: ["审批", "Approval"],
  EXECUTION_GRAPH: ["执行图", "Execution graph"],
  PROPERTY_GRAPH: ["实体关系图", "Entity relationship graph"],
  KNOWLEDGE_GRAPH: ["知识图", "Knowledge graph"],
  WORKFLOW: ["工作流", "Workflow"],
  NODE: ["节点", "Node"],
  EDGE: ["边", "Edge"],
  DEVELOPMENT: ["开发", "Development"],
  PRODUCTION: ["生产", "Production"],
  STAGING: ["预发布", "Staging"],
  LOW: ["低", "Low"],
  STANDARD: ["标准", "Standard"],
  HIGH: ["高", "High"],
  END_USER: ["普通用户", "End user"],
  SYSTEM_ADMIN: ["系统管理员", "System admin"],
  SECURITY_ADMIN: ["安全管理员", "Security admin"],
  AGENT_MANAGER: ["智能体管理者", "Agent manager"],
  USER_ADMIN: ["用户管理员", "User admin"],
  ROLE_ADMIN: ["角色管理员", "Role admin"],
  AUDITOR: ["审计员", "Auditor"],
  DEVELOPER: ["开发者", "Developer"],
  ORG_MANAGER: ["组织管理员", "Organization manager"],
  DIRECT_REPORTS: ["直接下属", "Direct reports"],
  ORG_SUBTREE: ["组织子树", "Organization subtree"],
  RESPONSIBLE_GROUP: ["责任组", "Responsible group"],
  SECURITY_DOMAIN: ["安全域", "Security domain"],
  OWNED: ["所有者范围", "Owned"],
  ASSIGNED: ["分配范围", "Assigned"],
  NONE: ["无", "None"],
  ALL: ["全部", "All"],
  OWNER_TRANSFER_REQUIRED: ["需要转移所有权", "Owner transfer required"],
  CHANNEL_CREATE: ["创建频道", "Create channel"],
  CHANNEL_MESSAGE_CREATE: ["发送频道消息", "Post channel message"],
  BARRIER_CREATE: ["创建协作关卡", "Create collaboration gate"],
  BARRIER_RELEASED: ["放行协作关卡", "Release collaboration gate"],
  BARRIER_REJECTED: ["拒绝协作关卡", "Reject collaboration gate"],
  HUMAN_REGISTER: ["注册用户", "Register human"],
  USER_ROLE_ASSIGN: ["分配用户角色", "Assign user role"],
  USER_PERMISSION_OVERRIDE: ["修改用户权限", "Override user permission"],
};

function listPayload(payload: Row, keys: string[] = []): Row[] {
  if (Array.isArray(payload)) return payload;
  for (const key of [
    ...keys,
    "items",
    "records",
    "data",
    "tasks",
    "plans",
    "workspaces",
    "knowledge",
    "memory",
    "memories",
    "skills",
    "specs",
    "branches",
    "loops",
    "messages",
  ]) {
    if (payload && Array.isArray(payload[key])) return payload[key];
  }
  return payload && typeof payload === "object" && Object.keys(payload).length
    ? [payload]
    : [];
}

function rowField(row: Row, names: string[]): any {
  for (const name of names) {
    if (row?.[name] !== undefined && row?.[name] !== null && row?.[name] !== "")
      return row[name];
    const key = Object.keys(row || {}).find(
      (candidate) => candidate.toLowerCase() === name.toLowerCase(),
    );
    if (key && row[key] !== undefined && row[key] !== null && row[key] !== "")
      return row[key];
  }
  return "-";
}

function displayRowValue(lang: Lang, value: any): string {
  if (value === null || value === undefined || value === "") return "-";
  const normalized = String(value).toUpperCase();
  if (statusLabels[normalized])
    return tx(lang, statusLabels[normalized][0], statusLabels[normalized][1]);
  return valueLabels[normalized]
    ? tx(lang, valueLabels[normalized][0], valueLabels[normalized][1])
    : String(value);
}

function jsonArray(value: any): any[] {
  if (Array.isArray(value)) return value;
  if (typeof value !== "string") return [];
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function approvalStatus(value: any): string {
  const normalized = String(value || "").toUpperCase();
  if (["PROPOSED", "OPEN", "PENDING", "APPROVAL_REQUIRED"].includes(normalized))
    return "PENDING";
  if (
    ["APPROVED", "APPROVE", "ALLOW", "RELEASED", "CONFIRMED"].includes(
      normalized,
    )
  )
    return "APPROVED";
  if (["REJECTED", "REJECT", "DENIED", "DENY", "EXPIRED"].includes(normalized))
    return normalized === "EXPIRED" ? "EXPIRED" : "REJECTED";
  return normalized || "UNKNOWN";
}

function canAction(capabilities: Row | null, action: string): boolean {
  return capabilities?.actions?.[action]?.decision === "ALLOW";
}

function askReason(
  text: (zh: string, en: string) => string,
  defaultValue: string,
): string | null {
  const reason = window.prompt(
    text("请输入原因", "Enter reason"),
    defaultValue,
  );
  return reason && reason.trim() ? reason.trim() : null;
}

function parseIds(value: string): string[] {
  return Array.from(
    new Set(
      value
        .split(/[,\n\s]+/)
        .map((item) => item.trim())
        .filter(Boolean),
    ),
  );
}

function DataPage({
  page,
  lang,
  text,
  onNotice,
}: {
  page: string;
  lang: Lang;
  text: (zh: string, en: string) => string;
  onNotice: (value: string) => void;
}) {
  const config = dataPageConfigs[page] || dataPageConfigs.tasks;
  const [items, setItems] = useState<Row[]>([]);
  const [graphData, setGraphData] = useState<Row>({ nodes: [], edges: [] });
  const [detail, setDetail] = useState<Row | null>(null);
  const [loading, setLoading] = useState(true);
  const [view, setView] = useState<"list" | "graph">("list");
  const load = async () => {
    setLoading(true);
    try {
      const value = await api<Row>(config.endpoint);
      setItems(listPayload(value, [...(config.payloadKeys || []), "nodes"]));
      setGraphData({ nodes: value.nodes || [], edges: value.edges || [] });
    } catch (error) {
      onNotice(
        error instanceof Error
          ? error.message
          : text("加载失败", "Loading failed"),
      );
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    void load();
  }, [config.endpoint]);
  const rows = items.map((row) =>
    config.fields.map((fields, index) => {
      const value = displayRowValue(lang, rowField(row, fields));
      return index === 0 ? (
        <button className="text-button" onClick={() => setDetail(row)}>
          {value}
        </button>
      ) : (
        value
      );
    }),
  );
  const graphTitle =
    page === "knowledge"
      ? text("知识图谱", "Knowledge graph")
      : text("记忆图谱", "Memory graph");
  const visual = ["knowledge", "memory"].includes(page);
  return (
    <section>
      <SectionHeading
        title={text(config.title[0], config.title[1])}
        subtitle={text(config.subtitle[0], config.subtitle[1])}
        text={text}
      />
      {visual && (
        <ViewToggle
          value={view}
          options={[
            ["list", text("列表", "List"), List],
            ["graph", text("关系图", "Graph"), Network],
          ]}
          onChange={(value) => setView(value as "list" | "graph")}
        />
      )}{" "}
      {visual && view === "graph" ? (
        <NetworkGraph
          nodes={graphData.nodes || []}
          edges={graphData.edges || []}
          lang={lang}
          title={graphTitle}
          loading={loading}
          text={text}
          onSelect={setDetail}
        />
      ) : (
        <InfoPanel title={text("数据库记录", "Database records")} text={text}>
          <div className="page-toolbar">
            <span className="data-count">
              {text("当前可见记录：", "Visible records: ")}
              <b>{items.length}</b>
            </span>
            <button
              className="icon-button"
              onClick={() => void load()}
              title={text("刷新", "Refresh")}
            >
              <RefreshCw className={loading ? "spin" : ""} size={15} />
              {text("刷新", "Refresh")}
            </button>
          </div>
          {loading ? (
            <PageLoading text={text} />
          ) : (
            <DataTable
              headers={config.labels.map((label) => text(label[0], label[1]))}
              rows={rows}
              empty={text(
                "当前权限范围内没有数据",
                "No data is visible within the current authorization scope",
              )}
              text={text}
            />
          )}
        </InfoPanel>
      )}
      <DetailDrawer
        open={Boolean(detail)}
        title={
          page === "branches"
            ? text("分支详情", "Branch detail")
            : text("条目详情", "Record detail")
        }
        onClose={() => setDetail(null)}
        text={text}
        wide={page === "branches"}
      >
        <p className="cx-form-hint">
          {text(
            "点击遮罩或关闭按钮可退出详情；详情仍受当前权限范围约束。",
            "Click the backdrop or close button to exit; details remain within the current authorization scope.",
          )}
        </p>
        {page === "branches" && detail && (
          <NetworkGraph
            nodes={branchDetailVisualization(detail, items, text).nodes}
            edges={branchDetailVisualization(detail, items, text).edges}
            lang={lang}
            title={text("分支关系", "Branch relationships")}
            loading={false}
            text={text}
            onSelect={setDetail}
            compact
            hierarchical
            showFilters={false}
          />
        )}
        <pre>{JSON.stringify(detail, null, 2)}</pre>
      </DetailDrawer>
    </section>
  );
}

function branchDetailVisualization(
  selected: Row,
  items: Row[],
  text: (zh: string, en: string) => string,
): Row {
  const nodes: Row[] = [];
  const edges: Row[] = [];
  const known = new Set<string>();
  const addNode = (node: Row) => {
    const id = String(node.id);
    if (!known.has(id)) {
      known.add(id);
      nodes.push(node);
    }
  };
  const branchId = String(rowField(selected, ["branch_id", "id"]));
  const parentId = String(rowField(selected, ["parent_branch_id"]));
  const workspaceId = String(rowField(selected, ["workspace_id"]));
  const agentId = String(rowField(selected, ["agent_id", "owner_id"]));
  const branchNode = (item: Row, level: number, focus = false) => ({
    ...item,
    id: String(rowField(item, ["branch_id", "id"])),
    label: item.branch_name || String(rowField(item, ["branch_id", "id"])),
    entity_type: "BRANCH",
    level,
    size: focus ? 22 : 16,
    color: focus
      ? { background: "#0f6f82", border: "#083f4c" }
      : { background: "#4d8792", border: "#285e68" },
  });

  addNode(branchNode(selected, 2, true));
  if (workspaceId !== "-") {
    const id = `workspace:${workspaceId}`;
    addNode({
      id,
      label: workspaceId,
      entity_type: "WORKSPACE",
      level: 0,
      color: { background: "#b36b2c", border: "#75431d" },
    });
    edges.push({
      from: id,
      to: branchId,
      label: text("包含", "contains"),
    });
  }
  if (parentId !== "-") {
    const parent = items.find(
      (item) => String(rowField(item, ["branch_id", "id"])) === parentId,
    );
    addNode(
      parent
        ? branchNode(parent, 1)
        : {
            id: parentId,
            label: parentId,
            entity_type: "BRANCH",
            level: 1,
          },
    );
    edges.push({
      from: parentId,
      to: branchId,
      label: text("派生", "fork"),
    });
  }
  items
    .filter(
      (item) =>
        String(rowField(item, ["parent_branch_id"])) === branchId &&
        String(rowField(item, ["branch_id", "id"])) !== branchId,
    )
    .forEach((child) => {
      const childId = String(rowField(child, ["branch_id", "id"]));
      addNode(branchNode(child, 3));
      edges.push({
        from: branchId,
        to: childId,
        label: text("派生", "fork"),
      });
    });
  if (agentId !== "-") {
    const id = `agent:${agentId}`;
    addNode({
      id,
      label: agentId,
      entity_type: "AGENT",
      level: 1,
      color: { background: "#5f7f6f", border: "#355445" },
    });
    edges.push({
      from: id,
      to: branchId,
      label: text("执行", "executes"),
    });
  }
  return { nodes, edges };
}

let visLoader: Promise<void> | null = null;
function loadVisNetwork(): Promise<void> {
  if (window.vis) return Promise.resolve();
  if (!visLoader)
    visLoader = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = "/static/vis-network.min.js";
      script.onload = () => resolve();
      script.onerror = () =>
        reject(new Error("vis-network could not be loaded"));
      document.head.appendChild(script);
    });
  return visLoader;
}

function NetworkGraph({
  nodes,
  edges,
  lang,
  title,
  loading,
  text,
  onSelect,
  compact = false,
  hierarchical = false,
  showFilters = true,
}: {
  nodes: Row[];
  edges: Row[];
  lang: Lang;
  title: string;
  loading: boolean;
  text: (zh: string, en: string) => string;
  onSelect: (row: Row) => void;
  compact?: boolean;
  hierarchical?: boolean;
  showFilters?: boolean;
}) {
  const container = useRef<HTMLDivElement | null>(null);
  const network = useRef<VisNetwork | null>(null);
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState("ALL");
  const [edgeTypeFilter, setEdgeTypeFilter] = useState("ALL");
  const [error, setError] = useState("");
  const types = Array.from(
    new Set(
      nodes.map((node) =>
        String(
          node.entity_type || node.group || node.category || "OTHER",
        ).toUpperCase(),
      ),
    ),
  ).sort();
  const edgeTypes = Array.from(
    new Set(
      edges.map((edge) =>
        String(edge.label || edge.edge_type || "RELATED").toUpperCase(),
      ),
    ),
  ).sort();
  const filteredNodes = nodes.filter((node) => {
    const type = String(
      node.entity_type || node.group || node.category || "OTHER",
    ).toUpperCase();
    const haystack =
      `${node.label || ""} ${node.title || ""} ${node.content || ""} ${type}`.toLowerCase();
    return (
      (typeFilter === "ALL" || type === typeFilter) &&
      (!search.trim() || haystack.includes(search.trim().toLowerCase()))
    );
  });
  useEffect(() => {
    let cancelled = false;
    void loadVisNetwork()
      .then(() => {
        if (cancelled || !container.current || !window.vis) return;
        network.current?.destroy();
        const visible = new Set(filteredNodes.map((node) => String(node.id)));
        const dark = document.documentElement.dataset.theme === "dark";
        const graphNodes = filteredNodes.map((node) => ({
          ...node,
          id: String(node.id),
          label: String(node.label || node.title || node.id),
          shape: "dot",
          size: Number(node.size || 14),
          color: node.color || { background: "#0f6f82", border: "#0b4d5c" },
          font: {
            color: dark ? "#e7eff0" : "#182936",
            size: 12,
            strokeWidth: 4,
            strokeColor: dark ? "#172228" : "#f0f2f2",
          },
        }));
        const graphEdges = edges
          .filter(
            (edge) =>
              visible.has(String(edge.from)) &&
              visible.has(String(edge.to)) &&
              (edgeTypeFilter === "ALL" ||
                String(
                  edge.label || edge.edge_type || "RELATED",
                ).toUpperCase() === edgeTypeFilter),
          )
          .map((edge, index) => ({
            ...edge,
            id: edge.id || `edge-${index}`,
            from: String(edge.from),
            to: String(edge.to),
            arrows: edge.arrows || "to",
            font: {
              color: dark ? "#d4e1e2" : "#263b45",
              size: 10,
              strokeWidth: 4,
              strokeColor: dark ? "#172228" : "#f0f2f2",
            },
            color: edge.color || { color: dark ? "#8ba3a8" : "#647a80" },
          }));
        network.current = new window.vis.Network(
          container.current,
          {
            nodes: new window.vis.DataSet(graphNodes),
            edges: new window.vis.DataSet(graphEdges),
          },
          {
            autoResize: true,
            layout: hierarchical
              ? {
                  hierarchical: {
                    enabled: true,
                    direction: "LR",
                    sortMethod: "directed",
                    levelSeparation: 170,
                    nodeSpacing: 110,
                  },
                }
              : undefined,
            interaction: {
              hover: true,
              navigationButtons: true,
              keyboard: true,
            },
            physics: hierarchical
              ? false
              : {
                  stabilization: { iterations: 120 },
                  barnesHut: {
                    gravitationalConstant: -2600,
                    springLength: 125,
                  },
                },
            edges: { smooth: { type: "continuous" } },
          },
        );
        network.current.on("click", (params) => {
          if (params.nodes?.[0] !== undefined) {
            const selected = nodes.find(
              (node) => String(node.id) === String(params.nodes[0]),
            );
            if (selected) onSelect(selected);
          }
        });
        setError("");
      })
      .catch((reason) =>
        setError(reason instanceof Error ? reason.message : String(reason)),
      );
    return () => {
      cancelled = true;
      network.current?.destroy();
      network.current = null;
    };
  }, [nodes, edges, search, typeFilter, edgeTypeFilter, lang, hierarchical]);
  const visibleNodeIds = new Set(filteredNodes.map((node) => String(node.id)));
  const visibleEdgeCount = edges.filter(
    (edge) =>
      visibleNodeIds.has(String(edge.from)) &&
      visibleNodeIds.has(String(edge.to)) &&
      (edgeTypeFilter === "ALL" ||
        String(edge.label || edge.edge_type || "RELATED").toUpperCase() ===
          edgeTypeFilter),
  ).length;
  return (
    <InfoPanel title={title} text={text}>
      {showFilters && (
        <div className="graph-toolbar">
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={text("搜索节点", "Search nodes")}
          />
          <div className="graph-filter-groups">
            <label>
              <span>{text("节点类型", "Node type")}</span>
              <select
                value={typeFilter}
                onChange={(event) => setTypeFilter(event.target.value)}
              >
                <option value="ALL">{text("全部节点", "All nodes")}</option>
                {types.map((type) => (
                  <option value={type} key={type}>
                    {displayRowValue(lang, type)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>{text("关系类型", "Relationship type")}</span>
              <select
                value={edgeTypeFilter}
                onChange={(event) => setEdgeTypeFilter(event.target.value)}
              >
                <option value="ALL">
                  {text("全部关系", "All relationships")}
                </option>
                {edgeTypes.map((type) => (
                  <option value={type} key={type}>
                    {displayRowValue(lang, type)}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <span className="data-count">
            {filteredNodes.length} {text("个节点", "nodes")} ·{" "}
            {visibleEdgeCount} {text("条边", "edges")}
          </span>
        </div>
      )}
      <div className={`network-frame ${compact ? "compact" : ""}`}>
        {loading ? (
          <PageLoading text={text} />
        ) : error ? (
          <div className="empty-state">{error}</div>
        ) : !filteredNodes.length ? (
          <div className="empty-state">
            {text(
              "当前过滤条件下没有节点",
              "No nodes match the current filter",
            )}
          </div>
        ) : null}
        <div
          ref={container}
          className={`network-canvas ${compact ? "compact" : ""}`}
        />
      </div>
    </InfoPanel>
  );
}

function GraphVisualization({
  lang,
  text,
  onNotice,
}: {
  lang: Lang;
  text: (zh: string, en: string) => string;
  onNotice: (value: string) => void;
}) {
  const [data, setData] = useState<Row>({ nodes: [], edges: [] });
  const [loading, setLoading] = useState(true);
  const [detail, setDetail] = useState<Row | null>(null);
  useEffect(() => {
    api<Row>("/api/graph/all")
      .then(setData)
      .catch((error) =>
        onNotice(
          error instanceof Error
            ? error.message
            : text("实体关系加载失败", "Entity relationships loading failed"),
        ),
      )
      .finally(() => setLoading(false));
  }, []);
  return (
    <section className="graph-visualization">
      <NetworkGraph
        nodes={data.nodes || []}
        edges={data.edges || []}
        lang={lang}
        title={text("实体关系探索", "Entity relationship explorer")}
        loading={loading}
        text={text}
        onSelect={setDetail}
      />
      <DetailDrawer
        open={Boolean(detail)}
        title={text("图节点详情", "Graph node detail")}
        onClose={() => setDetail(null)}
        text={text}
      >
        <pre>{JSON.stringify(detail, null, 2)}</pre>
      </DetailDrawer>
    </section>
  );
}

function GraphPage({
  lang,
  text,
  onNotice,
}: {
  lang: Lang;
  text: (zh: string, en: string) => string;
  onNotice: (value: string) => void;
}) {
  const [graphs, setGraphs] = useState<Row[]>([]);
  const [types, setTypes] = useState<Row[]>([]);
  const [runs, setRuns] = useState<Row[]>([]);
  const [filter, setFilter] = useState("ALL");
  const [detail, setDetail] = useState<Row | null>(null);
  const [view, setView] = useState("overview");
  const [loading, setLoading] = useState(true);
  const load = async () => {
    setLoading(true);
    try {
      const values = await Promise.all([
        api<Row>("/api/graphs"),
        api<Row>("/api/graph-types"),
        api<Row>("/api/graph-runs"),
      ]);
      setGraphs(listPayload(values[0], ["graphs"]));
      setTypes(listPayload(values[1], ["types"]));
      setRuns(listPayload(values[2], ["runs"]));
    } catch (error) {
      onNotice(
        error instanceof Error
          ? error.message
          : text("图数据加载失败", "Graph data could not be loaded"),
      );
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    void load();
  }, []);
  const typeNames = types
    .map((row) => String(rowField(row, ["kind", "type", "graph_type", "name"])))
    .filter((value) => value !== "-");
  const filtered =
    filter === "ALL"
      ? graphs
      : graphs.filter(
          (row) =>
            String(
              rowField(row, ["kind", "type", "graph_type"]),
            ).toUpperCase() === filter.toUpperCase(),
        );
  const activeRunCount = runs.filter((row) =>
    ["RUNNING", "ACTIVE", "WAITING"].includes(
      String(rowField(row, ["status", "run_status"])).toUpperCase(),
    ),
  ).length;
  const tabs: [string, string, React.ComponentType<{ size?: number }>?][] = [
    ["overview", text("概览", "Overview"), Activity],
    ["definitions", text("图定义", "Definitions"), Network],
    ["types", text("图类型", "Types"), Layers3],
    ["runs", text("运行记录", "Runs"), PlayCircle],
    ["relationships", text("实体关系", "Entity relationships"), GitBranch],
  ];
  return (
    <section>
      <SectionHeading
        title={text("图探索", "Graph")}
        subtitle={text(
          "图定义、类型、运行和实体关系分区呈现；节点与边均来自数据库。",
          "Definitions, types, runs, and entity relationships are separated into focused views; both nodes and edges come from the database.",
        )}
        text={text}
      />
      <ViewToggle value={view} options={tabs} onChange={setView} />
      {loading ? (
        <PageLoading text={text} />
      ) : (
        <>
          {view === "overview" && (
            <div className="metric-grid">
              <div className="metric">
                <span>{text("图定义", "Graph definitions")}</span>
                <strong>{graphs.length}</strong>
              </div>
              <div className="metric">
                <span>{text("图类型", "Graph types")}</span>
                <strong>{types.length}</strong>
              </div>
              <div className="metric">
                <span>{text("运行记录", "Runs")}</span>
                <strong>{runs.length}</strong>
              </div>
              <div className="metric">
                <span>{text("活动运行", "Active runs")}</span>
                <strong>{activeRunCount}</strong>
              </div>
            </div>
          )}
          {view === "definitions" && (
            <>
              <InfoPanel title={text("类型过滤", "Type filter")} text={text}>
                <div className="filter-row">
                  <button
                    className={`filter-button ${filter === "ALL" ? "active" : ""}`}
                    onClick={() => setFilter("ALL")}
                  >
                    {text("全部", "All")}
                  </button>
                  {Array.from(new Set(typeNames)).map((name) => (
                    <button
                      className={`filter-button ${filter === name ? "active" : ""}`}
                      key={name}
                      onClick={() => setFilter(name)}
                    >
                      {displayRowValue(lang, name)}
                    </button>
                  ))}
                  <button
                    className="icon-button filter-refresh"
                    onClick={() => void load()}
                  >
                    <RefreshCw size={15} />
                    {text("刷新", "Refresh")}
                  </button>
                </div>
              </InfoPanel>
              <InfoPanel
                title={text("图定义", "Graph definitions")}
                text={text}
              >
                <DataTable
                  headers={[
                    "ID",
                    text("名称", "Name"),
                    text("类型", "Type"),
                    text("状态", "Status"),
                    text("版本", "Version"),
                  ]}
                  rows={filtered.map((row) => [
                    <button
                      className="text-button"
                      onClick={() => setDetail(row)}
                    >
                      {String(
                        rowField(row, ["graph_id", "definition_id", "id"]),
                      )}
                    </button>,
                    displayRowValue(lang, rowField(row, ["name", "title"])),
                    displayRowValue(
                      lang,
                      rowField(row, ["kind", "type", "graph_type"]),
                    ),
                    displayRowValue(lang, rowField(row, ["status"])),
                    String(rowField(row, ["version", "graph_version"])),
                  ])}
                  empty={text("暂无图定义", "No Graph definitions")}
                  text={text}
                />
              </InfoPanel>
            </>
          )}
          {view === "types" && (
            <InfoPanel title={text("图类型", "Graph types")} text={text}>
              <DataTable
                headers={[
                  text("类型", "Type"),
                  text("名称", "Name"),
                  text("状态", "Status"),
                  text("说明", "Description"),
                ]}
                rows={types.map((row) => [
                  displayRowValue(
                    lang,
                    rowField(row, ["kind", "type", "graph_type"]),
                  ),
                  String(rowField(row, ["name", "title"])),
                  displayRowValue(lang, rowField(row, ["status"])),
                  String(rowField(row, ["description", "summary"])),
                ])}
                empty={text("暂无图类型", "No Graph types")}
                text={text}
              />
            </InfoPanel>
          )}
          {view === "runs" && (
            <InfoPanel title={text("运行记录", "Graph runs")} text={text}>
              <DataTable
                headers={[
                  "ID",
                  text("图", "Graph"),
                  text("状态", "Status"),
                  text("更新时间", "Updated"),
                ]}
                rows={runs.map((row) => [
                  <button
                    className="text-button"
                    onClick={() => setDetail(row)}
                  >
                    {String(rowField(row, ["run_id", "id"]))}
                  </button>,
                  String(rowField(row, ["graph_id", "definition_id"])),
                  displayRowValue(lang, rowField(row, ["status"])),
                  String(rowField(row, ["updated_at", "created_at"])),
                ])}
                empty={text("暂无运行记录", "No runs")}
                text={text}
              />
            </InfoPanel>
          )}
          {view === "relationships" && (
            <GraphVisualization lang={lang} text={text} onNotice={onNotice} />
          )}
        </>
      )}
      <DetailDrawer
        open={Boolean(detail)}
        title={text("图数据详情", "Graph data detail")}
        onClose={() => setDetail(null)}
        text={text}
      >
        <p className="cx-form-hint">
          {text(
            "当前配置不会把实验能力自动用于生产。",
            "Experimental capability is not automatically used in production.",
          )}
        </p>
        <pre>{JSON.stringify(detail, null, 2)}</pre>
      </DetailDrawer>
    </section>
  );
}

type OrganizationMode = "organization" | "people" | "agents" | "anomalies";
type OrganizationOrientation = "UD" | "LR";

const organizationModeLabels: Record<OrganizationMode, [string, string]> = {
  organization: ["组织", "Organization"],
  people: ["人员归属", "People assignment"],
  agents: ["智能体归属", "Agent responsibility"],
  anomalies: ["异常关系", "Anomalies"],
};

function organizationItems(payload: any, keys: string[]): Row[] {
  return listPayload(payload, [...keys, "items", "results", "organizations"]);
}

function organizationNodeId(row: Row): string {
  return String(
    rowField(row, [
      "id",
      "node_id",
      "organization_id",
      "principal_id",
      "agent_id",
    ]),
  );
}

function organizationNodeType(row: Row): string {
  return String(
    rowField(row, ["entity_type", "node_type", "kind", "type"]),
  ).toUpperCase();
}

function organizationResourceId(row: Row): string {
  const explicit = rowField(row, [
    "organization_id",
    "principal_id",
    "agent_id",
  ]);
  if (explicit && explicit !== "-") return String(explicit);
  const nodeId = organizationNodeId(row);
  return organizationNodeType(row).includes("ORG") && nodeId.startsWith("org:")
    ? nodeId.slice(4)
    : nodeId;
}

function organizationNodeLabel(row: Row): string {
  return String(
    rowField(row, [
      "label",
      "organization_name",
      "display_name",
      "agent_name",
      "username",
      "name",
      "id",
    ]),
  );
}

function organizationCanvasLabel(
  row: Row,
  text: (zh: string, en: string) => string,
): string {
  const type = organizationNodeType(row);
  const raw = organizationNodeLabel(row).trim();
  const resourceId = organizationResourceId(row);
  let label = raw;

  // Machine identifiers remain available in the inspector. The canvas uses a
  // compact alias so unbroken Principal and Agent IDs cannot widen the layout.
  if (
    (type.includes("PERSON") || type.includes("HUMAN") || type.includes("ANOMAL")) &&
    (raw === resourceId || /^HP_[A-Za-z0-9_-]+$/.test(raw))
  ) {
    label = `${text("人员", "Person")} · ${resourceId.slice(-7)}`;
  } else if (type.includes("AGENT")) {
    label = raw.replace(/^AGENT_/i, "") || raw;
  }

  const characters = Array.from(label);
  return characters.length <= 16
    ? label
    : `${characters.slice(0, 9).join("")}…${characters.slice(-6).join("")}`;
}

function organizationDetailValue(
  lang: Lang,
  row: Row,
  key: string,
  value: unknown,
  text: (zh: string, en: string) => string,
): string {
  const normalized = key.toLowerCase();
  const type = organizationNodeType(row);
  if (
    typeof value === "string" &&
    value.length > 20 &&
    ["id", "label", "principal_id", "subject_id", "agent_id"].includes(normalized) &&
    (type.includes("PERSON") || type.includes("HUMAN") || type.includes("AGENT") || type.includes("ANOMAL"))
  ) {
    const kind = type.includes("AGENT") || normalized === "agent_id" ? "AGENT" : "PERSON";
    const identifier = value.replace(/^(?:person|agent|anomaly):/i, "");
    return organizationCanvasLabel(
      {
        ...row,
        id: identifier,
        kind,
        label: identifier,
        [kind === "AGENT" ? "agent_id" : "principal_id"]: identifier,
      },
      text,
    );
  }
  return typeof value === "object"
    ? JSON.stringify(value)
    : displayRowValue(lang, value);
}

function organizationActionAllowed(
  capabilities: Row | null,
  ...actions: string[]
): boolean {
  return actions.some((action) => canAction(capabilities, action));
}

const organizationFieldLabels: Record<string, [string, string]> = {
  display_name: ["姓名", "Full name"],
  organization_id: ["组织 ID", "Organization ID"],
  organization_name: ["组织名称", "Organization name"],
  organization_code: ["组织编码", "Organization code"],
  organization_type: ["组织类型", "Organization type"],
  parent_id: ["上级组织", "Parent organization"],
  responsible_principal_id: ["负责人", "Responsible person"],
  security_domain_id: ["安全域", "Security Domain"],
  membership_kind: ["成员关系", "Membership kind"],
  relationship_type: ["关系类型", "Relationship type"],
  people_count: ["人员数量", "People"],
  agent_count: ["智能体数量", "Agents"],
  anomaly_count: ["异常数量", "Anomalies"],
  status: ["状态", "Status"],
  source_type: ["数据来源", "Source"],
  valid_from: ["生效时间", "Valid from"],
  valid_until: ["失效时间", "Valid until"],
  row_version: ["数据版本", "Row version"],
  updated_at: ["更新时间", "Updated at"],
};

function organizationFieldLabel(lang: Lang, key: string): string {
  const label = organizationFieldLabels[key.toLowerCase()];
  return label ? tx(lang, ...label) : key.replaceAll("_", " ");
}

function OrganizationCanvas({
  nodes,
  edges,
  mode,
  orientation,
  loading,
  editable,
  layoutVersion,
  text,
  onSelect,
  onFocus,
  onMove,
}: {
  nodes: Row[];
  edges: Row[];
  mode: OrganizationMode;
  orientation: OrganizationOrientation;
  loading: boolean;
  editable: boolean;
  layoutVersion: number;
  text: (zh: string, en: string) => string;
  onSelect: (row: Row) => void;
  onFocus: (row: Row) => void;
  onMove: (source: Row, target: Row) => void;
}) {
  const container = useRef<HTMLDivElement | null>(null);
  const network = useRef<VisNetwork | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    void loadVisNetwork()
      .then(() => {
        if (cancelled || !container.current || !window.vis) return;
        network.current?.destroy();
        const dark = document.documentElement.dataset.theme === "dark";
        const sortedNodes = [...nodes].sort((left, right) => {
          const leftOrder = Number(left.sort_order ?? left.order ?? 0);
          const rightOrder = Number(right.sort_order ?? right.order ?? 0);
          return (
            leftOrder - rightOrder ||
            organizationNodeLabel(left).localeCompare(
              organizationNodeLabel(right),
            )
          );
        });
        const graphNodes = sortedNodes.map((node) => {
          const type = organizationNodeType(node);
          const anomaly = Boolean(
            node.anomaly || node.anomaly_count || type.includes("ANOMAL"),
          );
          const colors = anomaly
            ? { background: "#a84842", border: "#7f302c" }
            : type.includes("AGENT")
              ? { background: "#557866", border: "#355445" }
              : type.includes("PERSON") || type.includes("HUMAN")
                ? { background: "#b36b2c", border: "#75431d" }
                : { background: "#0f6f82", border: "#0b4d5c" };
          const countParts = [
            node.people_count !== undefined
              ? `${node.people_count} ${text("人", "people")}`
              : "",
            node.agent_count !== undefined
              ? `${node.agent_count} ${text("智能体", "Agents")}`
              : "",
            node.anomaly_count
              ? `${node.anomaly_count} ${text("异常", "anomalies")}`
              : "",
          ].filter(Boolean);
          return {
            ...node,
            id: organizationNodeId(node),
            label: `${organizationCanvasLabel(node, text)}${countParts.length ? `\n${countParts.join(" · ")}` : ""}`,
            shape: "box",
            margin: { top: 11, right: 14, bottom: 11, left: 14 },
            widthConstraint: { minimum: 135, maximum: 180 },
            color: colors,
            borderWidth: anomaly ? 3 : 1,
            font: {
              color: "#ffffff",
              size: 12,
              face: "Noto Sans SC, Source Sans 3, sans-serif",
              multi: false,
            },
          };
        });
        const known = new Set(graphNodes.map((node) => String(node.id)));
        const graphEdges = edges
          .map((edge, index) => ({
            ...edge,
            id: edge.id || edge.edge_id || `organization-edge-${index}`,
            from: String(edge.from ?? edge.source ?? edge.parent_id),
            to: String(edge.to ?? edge.target ?? edge.child_id),
            arrows: edge.arrows || "to",
            label: String(edge.label || edge.relationship_type || ""),
            color: { color: dark ? "#9eb1b5" : "#61777d" },
            font: {
              color: dark ? "#e7eff0" : "#263b45",
              size: 10,
              strokeWidth: 4,
              strokeColor: dark ? "#223238" : "#f0f2f2",
            },
          }))
          .filter((edge) => known.has(edge.from) && known.has(edge.to));
        const instance = new window.vis.Network(
          container.current,
          {
            nodes: new window.vis.DataSet(graphNodes),
            edges: new window.vis.DataSet(graphEdges),
          },
          {
            autoResize: true,
            layout: {
              hierarchical: {
                enabled: true,
                direction: orientation,
                sortMethod: "directed",
                shakeTowards: "roots",
                // Spacing must exceed the constrained node size. Long Human or
                // Agent identifiers otherwise overlap adjacent organization nodes.
                levelSeparation: orientation === "UD" ? 155 : 240,
                nodeSpacing: orientation === "UD" ? 230 : 125,
                treeSpacing: 260,
                blockShifting: true,
                edgeMinimization: true,
                parentCentralization: true,
              },
            },
            interaction: {
              dragNodes: editable,
              dragView: true,
              hover: true,
              keyboard: true,
              navigationButtons: true,
              selectable: true,
              zoomView: true,
            },
            physics: false,
            nodes: { chosen: true },
            edges: {
              smooth: {
                enabled: true,
                type: "cubicBezier",
                forceDirection: orientation === "UD" ? "vertical" : "horizontal",
                roundness: 0.45,
              },
            },
          },
        );
        network.current = instance;
        instance.on("click", (params) => {
          const selected = nodes.find(
            (node) => organizationNodeId(node) === String(params.nodes?.[0]),
          );
          if (selected) onSelect(selected);
        });
        instance.on("doubleClick", (params) => {
          const selected = nodes.find(
            (node) => organizationNodeId(node) === String(params.nodes?.[0]),
          );
          if (selected && organizationNodeType(selected).includes("ORG"))
            onFocus(selected);
        });
        if (editable) {
          instance.on("dragEnd", (params) => {
            const sourceId = String(params.nodes?.[0] ?? "");
            const source = nodes.find(
              (node) => organizationNodeId(node) === sourceId,
            );
            if (!source || !params.pointer?.canvas) return;
            const pointer = params.pointer.canvas as { x: number; y: number };
            const positions = instance.getPositions();
            let target: Row | undefined;
            let nearest = Number.POSITIVE_INFINITY;
            nodes.forEach((candidate) => {
              const candidateId = organizationNodeId(candidate);
              if (
                candidateId === sourceId ||
                !organizationNodeType(candidate).includes("ORG")
              )
                return;
              const position = positions[candidateId];
              if (!position) return;
              const distance = Math.hypot(
                position.x - pointer.x,
                position.y - pointer.y,
              );
              if (distance < nearest) {
                nearest = distance;
                target = candidate;
              }
            });
            if (target && nearest < 140) onMove(source, target);
            else window.setTimeout(() => instance.fit({ animation: false }), 0);
          });
        }
        setError("");
      })
      .catch((reason) =>
        setError(reason instanceof Error ? reason.message : String(reason)),
      );
    return () => {
      cancelled = true;
      network.current?.destroy();
      network.current = null;
    };
  }, [nodes, edges, orientation, editable, layoutVersion]);

  return (
    <div className="organization-canvas-frame">
      {loading ? (
        <PageLoading text={text} />
      ) : error ? (
        <div className="empty-state">{error}</div>
      ) : !nodes.length ? (
        <div className="empty-state">
          {mode === "anomalies"
            ? text(
                "当前范围未发现异常关系",
                "No anomalous relationships were found in this scope",
              )
            : text(
                "当前范围内没有可显示的组织关系",
                "No organization relationships are visible in this scope",
              )}
        </div>
      ) : null}
      <div ref={container} className="organization-canvas" />
    </div>
  );
}

function OrganizationPage({
  lang,
  capabilities,
  text,
  onNotice,
}: {
  lang: Lang;
  capabilities: Row | null;
  text: (zh: string, en: string) => string;
  onNotice: (value: string) => void;
}) {
  const [roots, setRoots] = useState<Row[]>([]);
  const [scopeNodes, setScopeNodes] = useState<Row[]>([]);
  const [graph, setGraph] = useState<Row>({ nodes: [], edges: [] });
  const [focusId, setFocusId] = useState("");
  const [selected, setSelected] = useState<Row | null>(null);
  const [detail, setDetail] = useState<Row | null>(null);
  const [search, setSearch] = useState("");
  const [searchResults, setSearchResults] = useState<Row[]>([]);
  const [mode, setMode] = useState<OrganizationMode>("organization");
  const [orientation, setOrientation] =
    useState<OrganizationOrientation>("UD");
  const [panel, setPanel] = useState("details");
  const [changes, setChanges] = useState<Row[]>([]);
  const [draft, setDraft] = useState<Row | null>(null);
  const [historyRows, setHistoryRows] = useState<Row[]>([]);
  const [conflicts, setConflicts] = useState<Row[]>([]);
  const [loading, setLoading] = useState(true);
  const [sideLoading, setSideLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [layoutVersion, setLayoutVersion] = useState(0);
  const graphRequest = useRef(0);
  const [desktopEditing, setDesktopEditing] = useState(() =>
    !window.matchMedia("(max-width: 780px)").matches,
  );
  const canEdit = organizationActionAllowed(
    capabilities,
    "organizations.changes.write",
    "organizations.changes.create",
    "organizations.manage",
  );
  const canvasEditable = canEdit && desktopEditing;

  useEffect(() => {
    const media = window.matchMedia("(max-width: 780px)");
    const update = () => setDesktopEditing(!media.matches);
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  const loadChanges = async () => {
    try {
      const value = await api<Row>("/api/organization/changes");
      const rows = organizationItems(value, ["changes", "change_sets"]);
      setChanges(rows);
      const active = rows.find((row) =>
        ["DRAFT", "VALIDATING", "APPROVAL_REQUIRED"].includes(
          String(row.status || "").toUpperCase(),
        ),
      );
      if (active && !draft) setDraft(active);
    } catch {
      setChanges([]);
    }
  };

  const loadGraph = async (nextFocus = focusId, nextMode = mode) => {
    const requestId = ++graphRequest.current;
    setLoading(true);
    try {
      const query = new URLSearchParams({ mode: nextMode, limit: "250" });
      if (nextFocus) query.set("focus_id", nextFocus);
      const value = await api<Row>(`/api/organization/graph?${query}`);
      if (requestId !== graphRequest.current) return;
      setGraph({
        ...value,
        nodes: organizationItems(value, ["nodes"]),
        edges: value.edges || value.relationships || [],
      });
    } catch (error) {
      if (requestId !== graphRequest.current) return;
      setGraph({ nodes: [], edges: [] });
      onNotice(
        error instanceof Error
          ? error.message
          : text("组织图加载失败", "Organization graph could not be loaded"),
      );
    } finally {
      if (requestId === graphRequest.current) setLoading(false);
    }
  };

  const loadAuthorizedScope = async () => {
    try {
      const query = new URLSearchParams({
        mode: "organization",
        depth: "10",
        limit: "250",
      });
      const value = await api<Row>(`/api/organization/graph?${query}`);
      setScopeNodes(
        organizationItems(value, ["nodes"]).filter((node) =>
          organizationNodeType(node).includes("ORG"),
        ),
      );
    } catch {
      // Roots remain a safe fallback when the complete authorized tree fails.
      setScopeNodes([]);
    }
  };

  useEffect(() => {
    setLoading(true);
    api<Row>("/api/organization/roots")
      .then((value) => {
        const rows = organizationItems(value, ["roots", "nodes"]);
        setRoots(rows);
        const firstId = rows[0] ? organizationResourceId(rows[0]) : "";
        setFocusId(firstId);
      })
      .catch((error) => {
        setLoading(false);
        onNotice(
          error instanceof Error
            ? error.message
            : text("组织根节点加载失败", "Organization roots could not be loaded"),
        );
      });
    void loadChanges();
    void loadAuthorizedScope();
  }, []);

  useEffect(() => {
    if (focusId) void loadGraph(focusId, mode);
  }, [focusId, mode]);

  const focusNode = (node: Row) => {
    const id = organizationResourceId(node);
    setFocusId(id);
    setSelected(node);
    setDetail(node);
  };

  const selectNode = async (node: Row) => {
    setSelected(node);
    setDetail(node);
    setPanel("details");
    setSideLoading(true);
    try {
      setDetail(
        await api<Row>(
          `/api/organization/nodes/${encodeURIComponent(organizationResourceId(node))}`,
        ),
      );
    } catch {
      setDetail(node);
    } finally {
      setSideLoading(false);
    }
  };

  const runSearch = async (event: FormEvent) => {
    event.preventDefault();
    if (!search.trim()) {
      setSearchResults([]);
      return;
    }
    setSideLoading(true);
    try {
      const value = await api<Row>(
        `/api/organization/search?q=${encodeURIComponent(search.trim())}&limit=30`,
      );
      setSearchResults(organizationItems(value, ["results", "nodes"]));
    } catch (error) {
      onNotice(error instanceof Error ? error.message : text("搜索失败", "Search failed"));
    } finally {
      setSideLoading(false);
    }
  };

  const addOperation = async (operation: Row, reason = "") => {
    if (!canEdit) return;
    setBusy(true);
    try {
      let value: Row;
      const draftId = draft
        ? String(rowField(draft, ["change_set_id", "change_id", "id"]))
        : "";
      if (draftId && draftId !== "-") {
        value = await api<Row>(
          `/api/organization/changes/${encodeURIComponent(draftId)}/operations`,
          { method: "POST", body: JSON.stringify({ operation }) },
        );
      } else {
        value = await api<Row>("/api/organization/changes", {
          method: "POST",
          body: JSON.stringify({ reason, operations: [operation] }),
        });
      }
      setDraft(value.change || value.change_set || value);
      setPanel("draft");
      setLayoutVersion((current) => current + 1);
      await loadChanges();
      onNotice(text("变更已加入草稿，尚未发布", "Change added to draft and not published"));
    } catch (error) {
      onNotice(error instanceof Error ? error.message : text("草稿更新失败", "Draft update failed"));
      setLayoutVersion((current) => current + 1);
    } finally {
      setBusy(false);
    }
  };

  const moveByDrag = (source: Row, target: Row) => {
    const confirmed = window.confirm(
      text(
        `将“${organizationNodeLabel(source)}”移动至“${organizationNodeLabel(target)}”下方并加入草稿？`,
        `Move “${organizationNodeLabel(source)}” under “${organizationNodeLabel(target)}” in the draft?`,
      ),
    );
    if (!confirmed) {
      setLayoutVersion((current) => current + 1);
      return;
    }
    void addOperation({
      operation_type: "MOVE_ORGANIZATION",
      organization_id: organizationResourceId(source),
      new_parent_id: organizationResourceId(target),
    });
  };

  const submitOperation = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.currentTarget).entries());
    const operationType = String(data.operation_type || "MOVE_ORGANIZATION");
    const operation: Row = {
      operation_type: operationType,
      subject_id: data.subject_id || organizationResourceId(selected || {}),
      target_id: data.target_id || undefined,
      name: data.name || undefined,
      membership_kind: data.membership_kind || undefined,
      effective_at: data.effective_at || undefined,
    };
    if (operationType === "MOVE_ORGANIZATION") {
      operation.organization_id = operation.subject_id;
      operation.new_parent_id = operation.target_id;
    }
    void addOperation(operation, String(data.reason || ""));
  };

  const draftAction = async (action: "undo" | "redo" | "validate" | "submit") => {
    if (!draft) return;
    const id = String(rowField(draft, ["change_set_id", "change_id", "id"]));
    if (!id || id === "-") return;
    setBusy(true);
    try {
      const value = await api<Row>(
        `/api/organization/changes/${encodeURIComponent(id)}/${action}`,
        { method: "POST", body: JSON.stringify({}) },
      );
      setDraft(value.change || value.change_set || value);
      setPanel(action === "validate" ? "impact" : "draft");
      await loadChanges();
    } catch (error) {
      onNotice(error instanceof Error ? error.message : text("操作失败", "Operation failed"));
    } finally {
      setBusy(false);
    }
  };

  const openPanel = async (next: string) => {
    setPanel(next);
    if (next === "history") {
      setSideLoading(true);
      try {
        const query = focusId ? `?focus_id=${encodeURIComponent(focusId)}` : "";
        const value = await api<Row>(`/api/organization/history${query}`);
        setHistoryRows(organizationItems(value, ["history", "versions"]));
      } catch (error) {
        onNotice(error instanceof Error ? error.message : text("历史加载失败", "History loading failed"));
      } finally {
        setSideLoading(false);
      }
    }
    if (next === "sync") {
      setSideLoading(true);
      try {
        const value = await api<Row>("/api/organization/sync/conflicts");
        setConflicts(organizationItems(value, ["conflicts"]));
      } catch (error) {
        onNotice(error instanceof Error ? error.message : text("同步冲突加载失败", "Sync conflicts loading failed"));
      } finally {
        setSideLoading(false);
      }
    }
  };

  const organizationNodes = (graph.nodes || []).filter((node: Row) =>
    organizationNodeType(node).includes("ORG"),
  );
  const treeNodes = Array.from(
    new Map(
      [...roots, ...scopeNodes].map((node) => [
        organizationResourceId(node),
        node,
      ]),
    ).values(),
  );
  const targetNodes = treeNodes;
  const operations = organizationItems(draft, ["operations"]);
  const diffRows = organizationItems(draft?.diff, ["diff", "items", "operations"]);
  const impact = draft?.impact || draft?.impact_summary || {};
  const breadcrumbs = organizationItems(graph, ["breadcrumbs", "ancestors"]);

  return (
    <section className="organization-page">
      <SectionHeading
        title={text("组织架构", "Organization")}
        subtitle={text(
          "以数据库中的组织、人员与智能体责任事实为基础，检索、查看并通过受治理草稿配置企业关系。",
          "Search, inspect, and configure governed enterprise relationships from database-backed organization, people, and Agent responsibility facts.",
        )}
        text={text}
      />
      <div className="organization-modebar">
        <ViewToggle
          value={mode}
          options={(Object.keys(organizationModeLabels) as OrganizationMode[]).map(
            (key) => [
              key,
              text(...organizationModeLabels[key]),
              key === "organization"
                ? Building2
                : key === "people"
                  ? Users
                  : key === "agents"
                    ? Bot
                    : AlertTriangle,
            ],
          )}
          onChange={(value) => setMode(value as OrganizationMode)}
        />
        <div className="organization-layout-actions">
          <button
            className={`filter-button ${orientation === "UD" ? "active" : ""}`}
            onClick={() => setOrientation("UD")}
          >
            <ArrowDownUp size={14} />
            {text("纵向", "Vertical")}
          </button>
          <button
            className={`filter-button ${orientation === "LR" ? "active" : ""}`}
            onClick={() => setOrientation("LR")}
          >
            <GitBranch size={14} />
            {text("横向", "Horizontal")}
          </button>
          <button
            className="icon-button"
            onClick={() => setLayoutVersion((current) => current + 1)}
            title={text("重新规整画布", "Refit regular layout")}
          >
            <Maximize2 size={15} />
            {text("规整", "Refit")}
          </button>
        </div>
      </div>

      <div className="organization-workspace">
        <aside className="organization-browser" aria-label={text("组织浏览", "Organization browser")}>
          <form className="organization-search" onSubmit={runSearch}>
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder={text("搜索组织、人员或智能体", "Search organization, person, or Agent")}
            />
            <button className="icon-button" aria-label={text("搜索", "Search")}>
              <Search size={15} />
            </button>
          </form>
          {sideLoading && <span className="organization-inline-loading"><RefreshCw className="spin" size={13} />{text("读取中", "Loading")}</span>}
          {searchResults.length > 0 && (
            <div className="organization-search-results">
              <b>{text("搜索结果", "Search results")}</b>
              {searchResults.map((row) => (
                <button key={organizationNodeId(row)} onClick={() => focusNode(row)}>
                  <span>{organizationNodeLabel(row)}</span>
                  <small>{displayRowValue(lang, organizationNodeType(row))}</small>
                </button>
              ))}
            </div>
          )}
          <div className="organization-tree-head">
            <div className="organization-protected-title">
              <b>{text("授权组织范围", "Authorized organization scope")}</b>
              <span className="organization-protected-label"><ShieldCheck size={11} />{text("受保护视图", "Protected view")}</span>
            </div>
            <button
              className="icon-button"
              onClick={() => {
                void loadAuthorizedScope();
                void loadGraph();
              }}
              title={text("刷新", "Refresh")}
            >
              <RefreshCw className={loading ? "spin" : ""} size={14} />
            </button>
          </div>
          <div className="organization-tree" role="tree">
            {treeNodes.map((row) => {
              const id = organizationResourceId(row);
              const depth = Math.max(0, Number(row.depth ?? row.level ?? 0));
              return (
                <button
                  role="treeitem"
                  aria-selected={id === focusId}
                  className={id === focusId ? "active" : ""}
                  style={{ paddingLeft: `${10 + Math.min(depth, 5) * 13}px` }}
                  key={id}
                  onClick={() => focusNode(row)}
                >
                  <ChevronRight size={13} />
                  <span>
                    <b>{organizationNodeLabel(row)}</b>
                    <small>{row.organization_type ? displayRowValue(lang, row.organization_type) : text("组织单元", "Organization unit")}</small>
                  </span>
                </button>
              );
            })}
            {!treeNodes.length && !loading && <p className="empty-text">{text("当前范围内没有组织", "No organizations in the current scope")}</p>}
          </div>
        </aside>

        <div className="organization-stage">
          <div className="organization-breadcrumbs" aria-label={text("当前位置", "Current location")}>
            {(breadcrumbs.length ? breadcrumbs : roots.filter((row) => organizationResourceId(row) === focusId)).map((row, index) => (
              <React.Fragment key={organizationResourceId(row)}>
                {index > 0 && <ChevronRight size={12} />}
                <button onClick={() => focusNode(row)}>{organizationNodeLabel(row)}</button>
              </React.Fragment>
            ))}
            <span className="organization-protected-label"><ShieldCheck size={11} />{text("受保护视图", "Protected view")}</span>
            <span className="organization-metrics">{(graph.nodes || []).length} {text("节点", "nodes")} · {(graph.edges || []).length} {text("关系", "relationships")}</span>
          </div>
          <OrganizationCanvas
            nodes={graph.nodes || []}
            edges={graph.edges || []}
            mode={mode}
            orientation={orientation}
            loading={loading}
            editable={canvasEditable}
            layoutVersion={layoutVersion}
            text={text}
            onSelect={(row) => void selectNode(row)}
            onFocus={focusNode}
            onMove={moveByDrag}
          />
          <p className="organization-canvas-help">
            {canvasEditable
              ? text("双击组织聚焦子树；拖动节点到新父组织只会生成草稿，不会保存画布坐标。", "Double-click an organization to focus its subtree. Dropping a node on a new parent creates a draft and never persists canvas coordinates.")
              : canEdit
                ? text("双击组织聚焦子树；移动端为查询与审批模式，请在桌面端进行复杂编辑。", "Double-click an organization to focus its subtree. Mobile is intended for search and approval; use desktop for complex editing.")
                : text("双击组织聚焦子树；当前权限仅允许查询。", "Double-click an organization to focus its subtree. Current access is read-only.")}
          </p>
        </div>

        <aside className="organization-inspector">
          <div className="organization-inspector-protection">
            <span className="organization-protected-label"><ShieldCheck size={11} />{text("受保护视图", "Protected view")}</span>
          </div>
          <div className="organization-tabs" role="tablist">
            {[
              ["details", text("详情", "Details"), List],
              ["draft", text("草稿", "Draft"), GitBranch],
              ["diff", text("差异", "Diff"), GitCompareArrows],
              ["impact", text("影响", "Impact"), AlertTriangle],
              ["history", text("历史", "History"), History],
              ["sync", text("同步", "Sync"), RefreshCw],
            ].map(([key, label, Icon]: any) => (
              <button key={key} role="tab" aria-selected={panel === key} className={panel === key ? "active" : ""} onClick={() => void openPanel(key)}>
                <Icon size={13} /><span>{label}</span>
              </button>
            ))}
          </div>
          <div className="organization-panel-content">
            {panel === "details" && (
              <>
                <h2>{selected ? organizationCanvasLabel(selected, text) : text("选择一个节点", "Select a node")}</h2>
                {sideLoading ? <PageLoading text={text} /> : detail ? (
                  <div className="organization-detail-list">
                    {Object.entries(detail).slice(0, 18).map(([key, value]) => (
                      <div key={key}>
                        <span>{organizationFieldLabel(lang, key)}</span>
                        <b title={typeof value === "string" ? value : undefined}>
                          {organizationDetailValue(lang, detail, key, value, text)}
                        </b>
                      </div>
                    ))}
                  </div>
                ) : <p className="empty-text">{text("在画布或左侧组织树中选择节点查看详情。", "Select a node in the canvas or organization tree to inspect it.")}</p>}
              </>
            )}
            {panel === "draft" && (
              <>
                <div className="organization-panel-heading">
                  <h2>{text("语义变更草稿", "Semantic change draft")}</h2>
                  {draft && <span className="tag">{displayRowValue(lang, draft.status || "DRAFT")}</span>}
                </div>
                {!canEdit && <p className="organization-readonly-note"><ShieldCheck size={14} />{text("当前权限不允许配置组织关系。", "Current access cannot configure organization relationships.")}</p>}
                <form className="compact-form organization-change-form org-edit-only" onSubmit={submitOperation}>
                  <label>{text("操作", "Operation")}
                    <select name="operation_type" disabled={!canEdit || busy}>
                      <option value="MOVE_ORGANIZATION">{text("移动组织", "Move organization")}</option>
                      <option value="CREATE_ORGANIZATION">{text("创建组织", "Create organization")}</option>
                      <option value="UPDATE_ORGANIZATION">{text("修改组织", "Update organization")}</option>
                      <option value="ASSIGN_PERSON">{text("分配人员", "Assign person")}</option>
                      <option value="ASSIGN_AGENT">{text("配置智能体责任", "Configure Agent responsibility")}</option>
                    </select>
                  </label>
                  <label>{text("对象 ID", "Subject ID")}<input name="subject_id" defaultValue={selected ? organizationResourceId(selected) : ""} disabled={!canEdit || busy} required /></label>
                  <label>{text("目标组织", "Target organization")}
                    <select name="target_id" disabled={!canEdit || busy}>
                      <option value="">{text("请选择", "Select")}</option>
                      {targetNodes.map((node) => <option key={organizationNodeId(node)} value={organizationResourceId(node)}>{organizationNodeLabel(node)}</option>)}
                    </select>
                  </label>
                  <label>{text("名称或配置值（按需）", "Name or configuration value (when needed)")}<input name="name" disabled={!canEdit || busy} /></label>
                  <label>{text("成员关系", "Membership kind")}
                    <select name="membership_kind" disabled={!canEdit || busy}><option value="">-</option><option value="PRIMARY">{text("主组织", "Primary")}</option><option value="SECONDARY">{text("兼职组织", "Secondary")}</option></select>
                  </label>
                  {!draft && <label>{text("变更原因", "Change reason")}<textarea name="reason" required disabled={!canEdit || busy} /></label>}
                  <button className="primary-button" disabled={!canEdit || busy}><Plus size={14} />{text("加入草稿", "Add to draft")}</button>
                </form>
                <div className="organization-draft-actions org-edit-only">
                  <button className="small-button" disabled={!draft || busy} onClick={() => void draftAction("undo")}><Undo2 size={13} />{text("撤销", "Undo")}</button>
                  <button className="small-button" disabled={!draft || busy} onClick={() => void draftAction("redo")}><Redo2 size={13} />{text("重做", "Redo")}</button>
                  <button className="small-button" disabled={!draft || busy} onClick={() => void draftAction("validate")}><Check size={13} />{text("校验与影响分析", "Validate and analyze")}</button>
                  <button className="small-button" disabled={!draft || busy} onClick={() => void draftAction("submit")}><ShieldCheck size={13} />{text("提交审批", "Submit for approval")}</button>
                </div>
                <div className="organization-operation-list">
                  {operations.map((row, index) => <div key={String(row.operation_id || index)}><b>{displayRowValue(lang, row.operation_type || row.type)}</b><small>{String(row.subject_id || row.organization_id || "-")} → {String(row.target_id || row.new_parent_id || "-")}</small></div>)}
                  {!operations.length && <p className="empty-text">{text("当前没有草稿操作", "No draft operations")}</p>}
                </div>
                {changes.length > 0 && <select className="organization-change-picker" value={draft ? String(rowField(draft, ["change_set_id", "change_id", "id"])) : ""} onChange={(event) => setDraft(changes.find((row) => String(rowField(row, ["change_set_id", "change_id", "id"])) === event.target.value) || null)}><option value="">{text("选择变更集", "Select change set")}</option>{changes.map((row) => { const id = String(rowField(row, ["change_set_id", "change_id", "id"])); return <option value={id} key={id}>{id} · {displayRowValue(lang, row.status)}</option>; })}</select>}
              </>
            )}
            {panel === "diff" && (
              <><h2>{text("提交前差异", "Pre-publication diff")}</h2>{diffRows.length ? <div className="organization-operation-list">{diffRows.map((row, index) => <div key={index}><b>{displayRowValue(lang, row.operation_type || row.type || row.field)}</b><small>{String(row.before ?? row.old_value ?? "-")} → {String(row.after ?? row.new_value ?? "-")}</small></div>)}</div> : <pre className="organization-json">{draft?.diff ? JSON.stringify(draft.diff, null, 2) : text("校验草稿后显示权威差异。", "Validate the draft to display the authoritative diff.")}</pre>}</>
            )}
            {panel === "impact" && (
              <><h2>{text("权限与责任影响", "Authority and responsibility impact")}</h2><pre className="organization-json">{Object.keys(impact).length ? JSON.stringify(impact, null, 2) : text("校验后显示受影响的组织、人员、会话、智能体及工作。", "Validation shows affected organizations, people, sessions, Agents, and work.")}</pre></>
            )}
            {panel === "history" && (
              <><h2>{text("组织版本历史", "Organization version history")}</h2>{sideLoading ? <PageLoading text={text} /> : <div className="organization-operation-list">{historyRows.map((row, index) => <div key={String(row.version_id || index)}><b>{String(row.version || row.version_id || row.effective_at || "-")}</b><small>{displayRowValue(lang, row.status || row.change_type)} · {String(row.created_at || row.effective_at || "-")}</small></div>)}{!historyRows.length && <p className="empty-text">{text("暂无可见历史", "No visible history")}</p>}</div>}</>
            )}
            {panel === "sync" && (
              <><h2>{text("目录同步冲突", "Directory sync conflicts")}</h2><p className="cx-form-hint">{text("同步差异先形成变更集；未解决的高风险冲突不会直接覆盖平台事实。", "Synchronization differences become change sets; unresolved high-risk conflicts never overwrite platform facts directly.")}</p>{sideLoading ? <PageLoading text={text} /> : <div className="organization-operation-list">{conflicts.map((row, index) => <div key={String(row.conflict_id || index)}><b>{String(row.field_name || row.conflict_type || row.conflict_id)}</b><small>{displayRowValue(lang, row.status)} · {String(row.source || row.connector_type || "-")}</small></div>)}{!conflicts.length && <p className="empty-text">{text("当前没有可见同步冲突", "No visible sync conflicts")}</p>}</div>}</>
            )}
          </div>
        </aside>
      </div>
    </section>
  );
}

function ApprovalsPage({
  lang,
  capabilities,
  text,
  onNotice,
}: {
  lang: Lang;
  capabilities: Row | null;
  text: (zh: string, en: string) => string;
  onNotice: (value: string) => void;
}) {
  const [items, setItems] = useState<Row[]>([]);
  const [filter, setFilter] = useState("ALL");
  const [detail, setDetail] = useState<Row | null>(null);
  const load = async () => {
    try {
      const value = await api<Row>("/api/approvals");
      setItems(listPayload(value, ["approvals"]));
    } catch (error) {
      onNotice(
        error instanceof Error
          ? error.message
          : text("审批加载失败", "Approvals could not be loaded"),
      );
    }
  };
  useEffect(() => {
    void load();
  }, []);
  const decide = async (row: Row, decision: string) => {
    const reason = window.prompt(
      text("请输入审批原因", "Enter decision reason"),
      text("完成人工复核", "Human review completed"),
    );
    if (!reason) return;
    try {
      await api(
        `/api/approvals/${encodeURIComponent(String(rowField(row, ["approval_id", "request_id", "id"])))}/${decision}`,
        { method: "POST", body: JSON.stringify({ reason }) },
      );
      await load();
    } catch (error) {
      onNotice(
        error instanceof Error
          ? error.message
          : text("审批操作失败", "Approval action failed"),
      );
    }
  };
  const visible =
    filter === "ALL"
      ? items
      : items.filter(
          (row) =>
            approvalStatus(
              rowField(row, ["approval_status", "status", "decision"]),
            ) === filter,
        );
  const states: [string, string, string][] = [
    ["ALL", "全部", "All"],
    ["PENDING", "待处理", "Pending"],
    ["APPROVED", "已批准", "Approved"],
    ["REJECTED", "已拒绝", "Rejected"],
    ["EXPIRED", "已过期", "Expired"],
  ];
  const emptyByState: Record<string, [string, string]> = {
    ALL: [
      "当前授权范围内没有审批请求",
      "No approval requests are visible within the current authorization scope",
    ],
    PENDING: ["当前没有待处理审批", "No pending approvals"],
    APPROVED: ["当前没有已批准审批", "No approved requests"],
    REJECTED: ["当前没有已拒绝审批", "No rejected requests"],
    EXPIRED: ["当前没有已过期审批", "No expired requests"],
  };
  return (
    <section>
      <SectionHeading
        title={text("审批", "Approvals")}
        subtitle={text(
          "高风险执行需要有原因的审批决定，并保留职责分离和审计证据。",
          "High-risk execution requires reasoned approval decisions with separation of duties and audit evidence.",
        )}
        text={text}
      />
      <InfoPanel title={text("状态过滤", "Status filter")} text={text}>
        <div className="filter-row">
          {states.map(([key, zh, en]) => (
            <button
              className={`filter-button ${filter === key ? "active" : ""}`}
              key={key}
              onClick={() => setFilter(key)}
            >
              {text(zh, en)}
            </button>
          ))}
          <button
            className="icon-button filter-refresh"
            onClick={() => void load()}
            title={text("刷新", "Refresh")}
          >
            <RefreshCw size={15} />
            {text("刷新", "Refresh")}
          </button>
        </div>
      </InfoPanel>
      <InfoPanel title={text("审批请求", "Approval requests")} text={text}>
        <DataTable
          headers={[
            "ID",
            text("资源/动作", "Resource / action"),
            text("状态", "Status"),
            text("操作", "Actions"),
          ]}
          rows={visible.map((row) => {
            const id = String(
              rowField(row, ["approval_id", "request_id", "id"]),
            );
            const status = approvalStatus(
              rowField(row, ["approval_status", "status", "decision"]),
            );
            return [
              <button className="text-button" onClick={() => setDetail(row)}>
                {id}
              </button>,
              `${displayRowValue(lang, rowField(row, ["entity_type", "resource_type", "action"]))} · ${String(rowField(row, ["entity_id", "resource_id"]))}`,
              displayRowValue(lang, status),
              status === "PENDING" ? (
                <span className="row-actions">
                  <button
                    className="small-button"
                    disabled={!canAction(capabilities, "approvals.decide")}
                    onClick={() => void decide(row, "approve")}
                  >
                    <Check size={14} />
                    {text("批准", "Approve")}
                  </button>
                  <button
                    className="small-button danger"
                    disabled={!canAction(capabilities, "approvals.decide")}
                    onClick={() => void decide(row, "reject")}
                  >
                    <X size={14} />
                    {text("拒绝", "Reject")}
                  </button>
                </span>
              ) : (
                "-"
              ),
            ];
          })}
          empty={text(emptyByState[filter][0], emptyByState[filter][1])}
          text={text}
        />
      </InfoPanel>
      <DetailDrawer
        open={Boolean(detail)}
        title={text("审批详情", "Approval detail")}
        onClose={() => setDetail(null)}
        text={text}
      >
        <p className="cx-form-hint">
          {text(
            "审批操作仍需要原因和服务器端职责分离。",
            "Decisions still require a reason and server-side separation of duties.",
          )}
        </p>
        <pre>{JSON.stringify(detail, null, 2)}</pre>
      </DetailDrawer>
    </section>
  );
}

function AuditPage({
  lang,
  capabilities,
  text,
  onNotice,
}: {
  lang: Lang;
  capabilities: Row | null;
  text: (zh: string, en: string) => string;
  onNotice: (value: string) => void;
}) {
  const [items, setItems] = useState<Row[]>([]);
  const [detail, setDetail] = useState<Row | null>(null);
  const load = async () => {
    try {
      const value = await api<Row>("/api/audit");
      setItems(listPayload(value, ["events", "audit"]));
    } catch (error) {
      onNotice(
        error instanceof Error
          ? error.message
          : text("审计加载失败", "Audit could not be loaded"),
      );
    }
  };
  useEffect(() => {
    void load();
  }, []);
  const exportEvidence = async () => {
    const reason = window.prompt(
      text("请输入证据导出原因", "Enter evidence export reason"),
      text("合规复核", "Compliance review"),
    );
    if (!reason) return;
    try {
      await api(
        `/api/governance/evidence/export?reason=${encodeURIComponent(reason)}`,
        { method: "GET" },
      );
      onNotice(
        text("证据导出请求已提交。", "Evidence export request submitted."),
      );
    } catch (error) {
      onNotice(
        error instanceof Error
          ? error.message
          : text("证据导出失败", "Evidence export failed"),
      );
    }
  };
  return (
    <section>
      <SectionHeading
        title={text("审计", "Audit")}
        subtitle={text(
          "点击条目查看详情。审计事件、留存和证据均按当前用户授权范围返回。",
          "Click an item to inspect details. Audit events, retention, and evidence are returned within the current authorization scope.",
        )}
        text={text}
      />
      <InfoPanel title={text("审计事件", "Audit events")} text={text}>
        <DataTable
          headers={[
            "ID",
            text("动作", "Action"),
            text("主体", "Actor"),
            text("结果", "Outcome"),
            text("时间", "Time"),
          ]}
          rows={items.map((row) => [
            <button className="text-button" onClick={() => setDetail(row)}>
              {String(rowField(row, ["audit_id", "event_id", "id"]))}
            </button>,
            displayRowValue(
              lang,
              rowField(row, ["audit_type", "action", "action_name"]),
            ),
            String(
              rowField(row, [
                "agent_id",
                "actor_id",
                "principal_id",
                "entity_id",
              ]),
            ),
            displayRowValue(
              lang,
              rowField(row, ["resolution_status", "outcome", "status"]),
            ),
            String(rowField(row, ["created_at", "event_time"])),
          ])}
          empty={text(
            "当前授权范围内没有审计事件",
            "No audit events are visible within the current authorization scope",
          )}
          text={text}
        />
      </InfoPanel>
      <InfoPanel
        title={text("留存与证据", "Retention and evidence")}
        text={text}
      >
        <p>
          {text(
            "导出、法律保全和证据复核必须由授权人员执行，并填写原因；法律保全会固定指定范围内的审计证据，暂停到期清理，解除保全仍需授权和原因。智能体不获得导出权限。",
            "Exports, legal holds, and evidence review require an authorized human and a recorded reason. A legal hold freezes the selected audit evidence from retention cleanup; releasing it also requires authorization and a reason. Agents never receive export authority.",
          )}
        </p>
        <p className="cx-form-hint">
          {text(
            "操作流程：先确定审计范围，再由授权人员填写原因并提交法律保全或导出；平台记录范围、原因、操作者和证据摘要。保全解除同样需要授权和原因。",
            "Process: define the audit scope, then have an authorized human provide a reason and submit a legal hold or export. The platform records scope, reason, actor, and evidence digest. Releasing a hold also requires authorization and a reason.",
          )}
        </p>
        <div className="row-actions evidence-actions">
          <button
            className="primary-button"
            disabled={!canAction(capabilities, "audit.export")}
            onClick={() => void exportEvidence()}
          >
            <FileKey2 size={15} />
            {text("导出证据", "Export evidence")}
          </button>
          <button
            className="icon-button"
            onClick={() => void load()}
            title={text("刷新", "Refresh")}
          >
            <RefreshCw size={15} />
            {text("刷新", "Refresh")}
          </button>
        </div>
      </InfoPanel>
      <DetailDrawer
        open={Boolean(detail)}
        title={text("审计事件详情", "Audit event detail")}
        onClose={() => setDetail(null)}
        text={text}
      >
        <p className="cx-form-hint">
          {text(
            "详情仅显示当前权限范围内的记录。",
            "Details are limited to the current authorization scope.",
          )}
        </p>
        <pre>{JSON.stringify(detail, null, 2)}</pre>
      </DetailDrawer>
    </section>
  );
}

function MonitorPage({
  lang,
  capabilities,
  text,
  onNotice,
}: {
  lang: Lang;
  capabilities: Row | null;
  text: (zh: string, en: string) => string;
  onNotice: (value: string) => void;
}) {
  const [view, setView] = useState("overview");
  const [data, setData] = useState<Row>({});
  const [profile, setProfile] = useState<Row>({});
  const [notifications, setNotifications] = useState<Row[]>([]);
  const [profileResult, setProfileResult] = useState<Row | null>(null);
  const [loading, setLoading] = useState(true);
  const load = async () => {
    setLoading(true);
    try {
      const [overview, runtimeProfile, notificationData] = await Promise.all([
        api<Row>("/api/monitor/overview"),
        api<Row>("/api/runtime/profile"),
        api<Row>("/api/notifications"),
      ]);
      setData(overview);
      setProfile(runtimeProfile);
      setNotifications(listPayload(notificationData));
    } catch (error) {
      onNotice(
        error instanceof Error
          ? error.message
          : text("监控加载失败", "Monitor loading failed"),
      );
      setNotifications([]);
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    void load();
  }, []);
  const preflight = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = Object.fromEntries(
      new FormData(event.currentTarget).entries(),
    );
    try {
      setProfileResult(
        await api<Row>("/api/runtime/profile/preflight", {
          method: "POST",
          body: JSON.stringify(data),
        }),
      );
    } catch (error) {
      onNotice(
        error instanceof Error
          ? error.message
          : text("预检失败", "Preflight failed"),
      );
    }
  };
  const activate = async () => {
    if (!profileResult?.change_id) return;
    const reason = askReason(
      text,
      text("完成运行配置复核", "Runtime profile reviewed"),
    );
    if (!reason) return;
    try {
      setProfileResult(
        await api<Row>(
          `/api/runtime/profile/${profileResult.change_id}/activate`,
          {
            method: "POST",
            body: JSON.stringify({ decision: "ACTIVATE", reason }),
          },
        ),
      );
      onNotice(
        text(
          "运行配置已记录；请受控重启当前节点后使其生效。",
          "The runtime profile was recorded; restart this node under change control to apply it.",
        ),
      );
    } catch (error) {
      onNotice(
        error instanceof Error
          ? error.message
          : text("激活失败", "Activation failed"),
      );
    }
  };
  const acknowledge = async (item: Row) => {
    try {
      await api(
        `/api/notifications/${encodeURIComponent(String(item.notification_id))}/ack`,
        { method: "POST" },
      );
      await load();
    } catch (error) {
      onNotice(
        error instanceof Error
          ? error.message
          : text("通知确认失败", "Notification acknowledgement failed"),
      );
    }
  };
  const profileName = String(profile.profile || "production").toLowerCase();
  const profileLabel = (value: string) => {
    const labels: Record<string, [string, string]> = {
      production: ["生产", "Production"],
      "graph-preview": ["图工程预览", "Graph Engineering preview"],
      development: ["开发实验", "Development experiments"],
      "experimental-4.2": ["4.2 实验兼容", "4.2 experimental compatibility"],
    };
    const label = labels[value.toLowerCase()];
    return label ? text(label[0], label[1]) : value;
  };
  const metrics = [
    [text("智能体总数", "Total Agents"), data.agents?.total ?? "-"],
    [text("在线智能体", "Online Agents"), data.agents?.online ?? "-"],
    [text("空闲智能体", "Idle Agents"), data.agents?.idle ?? "-"],
    [text("活动会话", "Active Sessions"), data.sessions?.active ?? "-"],
    [
      text("运行任务计划", "Running Task Plans"),
      data.tasks?.running_plans ?? "-",
    ],
    [text("运行循环", "Running Loops"), data.tasks?.running_loops ?? "-"],
    [text("停滞智能体", "Stalled Agents"), data.stalled_count ?? "-"],
    [text("当前运行配置", "Runtime Profile"), profileLabel(profileName)],
  ];
  return (
    <section>
      <SectionHeading
        title={text("运行概览", "Runtime overview")}
        subtitle={text(
          "统一观察身份、运行状态和数据库持久化边界。生产配置承载稳定能力，图预览等实验能力按受控配置启用。",
          "Observe identity, runtime state, and database persistence boundaries. The production profile carries stable capabilities; Graph Preview and other experimental capabilities remain explicitly controlled.",
        )}
        text={text}
      />
      <ViewToggle
        value={view}
        options={[
          ["overview", text("运行概览", "Runtime overview"), Activity],
          [
            "experiments",
            text("实验功能", "Experimental features"),
            CircleHelp,
          ],
        ]}
        onChange={setView}
      />
      {loading ? (
        <PageLoading text={text} />
      ) : view === "overview" ? (
        <>
          <div className="metric-grid">
            {metrics.map(([label, value]) => (
              <div className="metric" key={String(label)}>
                <span>{label}</span>
                <strong>{String(value)}</strong>
              </div>
            ))}
          </div>
          <div className="split-grid">
            <InfoPanel
              title={text("稳定能力", "Stable capabilities")}
              text={text}
            >
              <p>
                {text(
                  "身份注册、权限、记忆、知识、工作区、任务计划、技能、审计和智能体生命周期继续使用数据库作为权威事实源。",
                  "Identity, authorization, memory, knowledge, workspaces, task plans, Skills, audit, and Agent lifecycle remain database-authoritative.",
                )}
              </p>
            </InfoPanel>
            <InfoPanel
              title={text("运行边界", "Runtime boundary")}
              text={text}
            >
              <p>
                {text(
                  "频道、协作关卡、网关与图工程共用主体、实例隔离、短期令牌、租约和审计边界；线程权限不会扩大数据、工具或技能权限。",
                  "Channels, Collaboration gates, Gateways, and Graph Engineering share Principal, instance-isolation, short-lived-token, lease, and audit boundaries; thread membership never expands data, Tool, or Skill authority.",
                )}
              </p>
            </InfoPanel>
          </div>
        </>
      ) : (
        <InfoPanel
          title={text("实验功能配置", "Experimental feature configuration")}
          text={text}
        >
          <div className="profile-status">
            <div>
              <span>{text("当前配置", "Current profile")}</span>
              <strong>{profileLabel(profileName)}</strong>
            </div>
            <span
              className={`tag ${profile.capabilities?.graph_preview ? "warning" : ""}`}
            >
              {profile.capabilities?.graph_preview
                ? text("实验功能已开启", "Experiments enabled")
                : text("实验功能未开启", "Experiments disabled")}
            </span>
          </div>
          <p className="cx-form-hint">
            {text(
              "生产配置仅启用稳定能力；图工程预览用于受控验证；开发配置还会启用诊断与实验连接器。配置变化必须先检查依赖、活动任务和重启影响，再由授权人员激活。",
              "Production enables stable capabilities only. Graph Engineering preview supports controlled evaluation. Development also enables diagnostics and experimental connectors. Every change requires dependency, active-work, and restart-impact checks before authorized activation.",
            )}
          </p>
          <form className="inline-form" onSubmit={preflight}>
            <select name="target_profile" defaultValue="graph-preview">
              <option value="production">
                {text("生产（关闭实验功能）", "Production (experiments off)")}
              </option>
              <option value="graph-preview">
                {text("图工程预览", "Graph Engineering preview")}
              </option>
              <option value="development">
                {text("开发实验功能", "Development experiments")}
              </option>
            </select>
            <input
              name="reason"
              required
              placeholder={text("预检原因", "Preflight reason")}
            />
            <button
              className="primary-button"
              disabled={!canAction(capabilities, "profile.update")}
            >
              <PlayCircle size={15} />
              {text("检查影响", "Check impact")}
            </button>
          </form>
          {profileResult && (
            <div className="decision-box">
              <p className="cx-form-hint">
                {profileResult.safe_to_activate
                  ? text(
                      "影响检查已通过。激活后需要受控重启当前节点；其他节点不会被自动变更。",
                      "Impact checks passed. Activation requires a controlled restart of this node; other nodes are not changed automatically.",
                    )
                  : text(
                      "影响检查未通过，请先处理活动任务或依赖问题。",
                      "Impact checks did not pass. Resolve active work or dependency blockers first.",
                    )}
              </p>
              <pre>{JSON.stringify(profileResult, null, 2)}</pre>
              {profileResult.safe_to_activate && (
                <button
                  className="small-button"
                  onClick={() => void activate()}
                >
                  {text("激活配置", "Activate profile")}
                </button>
              )}
            </div>
          )}
        </InfoPanel>
      )}
      {!loading && view === "overview" && (
        <>
          <InfoPanel
            title={text("通知与待办", "Notifications and work items")}
            text={text}
          >
            {notifications.length ? (
              notifications.map((item) => (
                <div className="notification-item" key={item.notification_id}>
                  <div>
                    <b>{displayRowValue(lang, item.level || "INFO")}</b>
                    <p>{String(item.notification_type || "Notification")}</p>
                    <small>{item.deadline_at || item.created_at || ""}</small>
                  </div>
                  {item.acknowledged_at ? (
                    <span className="tag">
                      {text("已确认", "Acknowledged")}
                    </span>
                  ) : (
                    <button
                      className="small-button"
                      onClick={() => void acknowledge(item)}
                    >
                      {text("确认", "Acknowledge")}
                    </button>
                  )}
                </div>
              ))
            ) : (
              <div className="empty-state">
                {text("暂无待办通知", "No pending notifications")}
              </div>
            )}
          </InfoPanel>
          <MonitorDetails lang={lang} text={text} onNotice={onNotice} />
        </>
      )}
    </section>
  );
}

function AgentsPage({
  lang,
  capabilities,
  text,
  onNotice,
}: {
  lang: Lang;
  capabilities: Row | null;
  text: (zh: string, en: string) => string;
  onNotice: (value: string) => void;
}) {
  const [agents, setAgents] = useState<Row[]>([]);
  const [grants, setGrants] = useState<Row[]>([]);
  const [token, setToken] = useState<Row | null>(null);
  const load = async () => {
    try {
      const [registered, grantData] = await Promise.all([
        api<Row>("/api/agents"),
        api<Row>("/api/enrollment/grants"),
      ]);
      const governed = (registered.items || []).map((item: Row) => ({
        ...item,
        inventory_source: "GOVERNED",
      }));
      if (canAction(capabilities, "agents.read.all")) {
        const legacy = await api<Row>("/api/monitor/agents");
        const known = new Set(
          governed.map((item: Row) => String(item.agent_id)),
        );
        governed.push(
          ...(legacy.agents || [])
            .filter((item: Row) => !known.has(String(item.agent_id)))
            .map((item: Row) => ({ ...item, inventory_source: "LEGACY" })),
        );
      }
      setAgents(governed);
      setGrants(grantData.items || []);
    } catch (error) {
      onNotice(
        error instanceof Error
          ? error.message
          : text("智能体清单加载失败", "Agent inventory loading failed"),
      );
    }
  };
  useEffect(() => {
    void load();
  }, []);
  const createGrant = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    try {
      const body = Object.fromEntries(
        new FormData(event.currentTarget).entries(),
      );
      const value = await api<Row>("/api/enrollment/grants", {
        method: "POST",
        body: JSON.stringify({
          ...body,
          ttl_seconds: Number(body.ttl_seconds || 900),
        }),
      });
      setToken(value);
      await load();
    } catch (error) {
      onNotice(
        error instanceof Error
          ? error.message
          : text("生成失败", "Creation failed"),
      );
    }
  };
  const status = async (item: Row, value: string) => {
    const reason = askReason(
      text,
      text("智能体状态调整", "Agent status adjustment"),
    );
    if (!reason) return;
    try {
      await api(
        `/api/agents/${encodeURIComponent(String(item.agent_id))}/status`,
        { method: "POST", body: JSON.stringify({ decision: value, reason }) },
      );
      await load();
    } catch (error) {
      onNotice(
        error instanceof Error
          ? error.message
          : text("状态调整失败", "Status change failed"),
      );
    }
  };
  const transfer = async (item: Row) => {
    const owner = window.prompt(
      text("输入新的人员主体 ID", "Enter new Human Principal ID"),
    );
    if (!owner) return;
    const reason = askReason(
      text,
      text("完成智能体归属复核", "Agent ownership reviewed"),
    );
    if (!reason) return;
    try {
      await api(
        `/api/agents/${encodeURIComponent(String(item.agent_id))}/owner-transfer`,
        {
          method: "POST",
          body: JSON.stringify({ new_owner_principal_id: owner, reason }),
        },
      );
      await load();
    } catch (error) {
      onNotice(
        error instanceof Error
          ? error.message
          : text("归属转移失败", "Ownership transfer failed"),
      );
    }
  };
  const offboard = async (item: Row) => {
    const reason = askReason(
      text,
      text("完成智能体下线复核", "Agent offboarding reviewed"),
    );
    if (!reason) return;
    try {
      await api(
        `/api/agents/${encodeURIComponent(String(item.agent_id))}/offboard`,
        {
          method: "POST",
          body: JSON.stringify({
            owner_type: "HUMAN",
            has_responsible_group: false,
            environment: "DEVELOPMENT",
            reason,
          }),
        },
      );
      await load();
    } catch (error) {
      onNotice(
        error instanceof Error
          ? error.message
          : text("智能体下线失败", "Agent offboarding failed"),
      );
    }
  };
  const agentRows = agents.map((item) => {
    const current = String(item.status || "").toUpperCase();
    const governed = item.inventory_source === "GOVERNED";
    const controls = governed ? (
      <span className="row-actions">
        {current === "ACTIVE" && (
          <button
            className="small-button"
            onClick={() => void status(item, "DISABLED")}
          >
            {text("暂停", "Pause")}
          </button>
        )}
        {current !== "ACTIVE" && (
          <button
            className="small-button"
            onClick={() => void status(item, "ACTIVE")}
          >
            {text("启用", "Enable")}
          </button>
        )}
        {canAction(capabilities, "agents.transfer") && (
          <button className="small-button" onClick={() => void transfer(item)}>
            {text("转移归属", "Transfer owner")}
          </button>
        )}
        {canAction(capabilities, "agents.offboard") && (
          <button
            className="small-button danger"
            onClick={() => void offboard(item)}
          >
            {text("下线", "Offboard")}
          </button>
        )}
      </span>
    ) : (
      <span className="tag">
        {text("旧版清单（只读）", "Legacy inventory (read-only)")}
      </span>
    );
    return [
      String(item.agent_id),
      displayRowValue(lang, item.status),
      displayRowValue(lang, item.relationship_role || item.db_status || "-"),
      controls,
    ];
  });
  return (
    <section>
      <SectionHeading
        title={text("智能体与注册", "Agents and enrollment")}
        subtitle={text(
          "智能体归属由一次性注册令牌固定，长期凭证只用于换取实例级短期令牌。所有状态、归属转移和下线操作都必须有原因。",
          "Ownership is fixed by a one-time Enrollment Token; long-lived credentials only exchange for instance-scoped short-lived tokens. Status, ownership transfer, and offboarding are reasoned operations.",
        )}
        text={text}
      />
      <div className="split-grid">
        <InfoPanel
          title={text("生成注册令牌", "Create Enrollment Token")}
          text={text}
        >
          <form className="compact-form" onSubmit={createGrant}>
            <label>
              {text("运行时", "Runtime")}
              <input name="runtime" defaultValue="OpenClaw / Hermes" />
            </label>
            <label>
              {text("环境", "Environment")}
              <select name="environment">
                <option value="development">
                  {text("开发", "Development")}
                </option>
                <option value="production">{text("生产", "Production")}</option>
              </select>
            </label>
            <label>
              {text("风险等级", "Risk tier")}
              <select name="risk_tier">
                <option value="LOW">{text("低", "Low")}</option>
                <option value="STANDARD">{text("标准", "Standard")}</option>
                <option value="RESTRICTED">{text("受限", "Restricted")}</option>
              </select>
            </label>
            <label>
              {text("有效秒数", "TTL seconds")}
              <input
                name="ttl_seconds"
                type="number"
                min="60"
                max="3600"
                defaultValue="900"
              />
            </label>
            <button className="primary-button">
              <Plus size={16} />
              {text("生成并仅显示一次", "Create and show once")}
            </button>
          </form>
          {token && (
            <div className="one-time-token">
              <b>{text("请立即保存令牌", "Save this Token now")}</b>
              <code>{token.token}</code>
              <small>
                {text(
                  "平台只保存摘要，不会再次显示明文。",
                  "Only a digest is stored; plaintext will not be shown again.",
                )}
              </small>
            </div>
          )}
        </InfoPanel>
        <InfoPanel
          title={text("已登记智能体", "Registered Agents")}
          text={text}
        >
          <DataTable
            headers={[
              text("智能体 ID", "Agent ID"),
              text("状态", "Status"),
              text("关系", "Relationship"),
              text("操作", "Actions"),
            ]}
            rows={agentRows}
            empty={text(
              "当前用户没有可见智能体",
              "No visible Agents for this user",
            )}
            text={text}
          />
        </InfoPanel>
      </div>
      <InfoPanel
        title={text("Enrollment 历史", "Enrollment history")}
        text={text}
      >
        <DataTable
          headers={[
            text("Grant", "Grant"),
            text("运行时", "Runtime"),
            text("环境", "Environment"),
            text("使用", "Usage"),
            text("状态", "Status"),
          ]}
          rows={grants.map((item) => [
            item.grant_id,
            item.runtime,
            displayRowValue(lang, item.environment),
            `${item.used_count || 0}/${item.max_uses || 1}`,
            displayRowValue(lang, item.status),
          ])}
          empty={text("暂无记录", "No records")}
          text={text}
        />
      </InfoPanel>
    </section>
  );
}

function Channels({
  lang,
  capabilities,
  text,
  onNotice,
}: {
  lang: Lang;
  capabilities: Row | null;
  text: (zh: string, en: string) => string;
  onNotice: (value: string) => void;
}) {
  const [channels, setChannels] = useState<Row[]>([]);
  const [selected, setSelected] = useState<Row | null>(null);
  const [messages, setMessages] = useState<Row[]>([]);
  const [members, setMembers] = useState<Row[]>([]);
  const [threads, setThreads] = useState<Row[]>([]);
  const [summary, setSummary] = useState<Row>({});
  const [actions, setActions] = useState<Row[]>([]);
  const [candidates, setCandidates] = useState<Row[]>([]);
  const [bridges, setBridges] = useState<Row[]>([]);
  const [body, setBody] = useState("");
  const [threadId, setThreadId] = useState("");
  const [view, setView] = useState("chat");
  const load = async () => {
    try {
      const value = await api<Row>("/api/channels");
      const list = value.items || [];
      setChannels(list);
      if (!selected && list[0]) setSelected(list[0]);
    } catch (error) {
      onNotice(
        error instanceof Error
          ? error.message
          : text("频道加载失败", "Channel loading failed"),
      );
    }
  };
  const loadSelected = async (channel: Row) => {
    const id = encodeURIComponent(String(channel.channel_id));
    const optional = async (path: string): Promise<Row> => {
      try {
        return await api<Row>(path);
      } catch {
        return {};
      }
    };
    const [
      messageValue,
      memberValue,
      threadValue,
      summaryValue,
      actionValue,
      candidateValue,
    ] = await Promise.all([
      optional(`/api/channels/${id}/messages`),
      optional(`/api/channels/${id}/members`),
      optional(`/api/channels/${id}/threads`),
      optional(`/api/channels/${id}/summary`),
      optional(`/api/channels/${id}/actions`),
      optional(`/api/channels/${id}/memory-candidates`),
    ]);
    setMessages((messageValue.items || []).reverse());
    setMembers(memberValue.items || []);
    setThreads(threadValue.items || []);
    setSummary(summaryValue);
    setActions(actionValue.items || []);
    setCandidates(candidateValue.items || []);
    setBridges((await optional("/api/bridges")).items || []);
  };
  useEffect(() => {
    void load();
  }, []);
  useEffect(() => {
    if (selected) {
      setThreadId("");
      void loadSelected(selected);
    }
  }, [selected]);
  const refresh = async () => {
    await load();
    if (selected) await loadSelected(selected);
  };
  const createChannel = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = Object.fromEntries(new FormData(form).entries());
    try {
      const created = await api<Row>("/api/channels", {
        method: "POST",
        body: JSON.stringify(data),
      });
      form.reset();
      await load();
      setSelected(created);
      onNotice(
        text(
          "频道已创建，创建者已成为频道所有者。",
          "Channel created; its creator is now the owner.",
        ),
      );
    } catch (error) {
      onNotice(
        error instanceof Error
          ? error.message
          : text("频道创建失败", "Channel creation failed"),
      );
    }
  };
  const send = async (event: FormEvent) => {
    event.preventDefault();
    if (!selected || !body.trim()) return;
    try {
      await api(
        `/api/channels/${encodeURIComponent(selected.channel_id)}/messages`,
        {
          method: "POST",
          body: JSON.stringify({
            body,
            thread_type: threadId
              ? threads.find((item) => item.thread_id === threadId)
                  ?.thread_type || "CHANNEL"
              : "CHANNEL",
            thread_id: threadId,
          }),
        },
      );
      setBody("");
      await loadSelected(selected);
    } catch (error) {
      onNotice(
        error instanceof Error
          ? error.message
          : text("发送失败", "Send failed"),
      );
    }
  };
  const createThread = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selected) return;
    const data = Object.fromEntries(
      new FormData(event.currentTarget).entries(),
    );
    try {
      await api(
        `/api/channels/${encodeURIComponent(selected.channel_id)}/threads`,
        {
          method: "POST",
          body: JSON.stringify({
            thread_type: data.thread_type,
            classification: data.classification,
            participant_principal_ids: parseIds(
              String(data.participants || ""),
            ),
          }),
        },
      );
      await loadSelected(selected);
    } catch (error) {
      onNotice(
        error instanceof Error
          ? error.message
          : text("线程创建失败", "Thread creation failed"),
      );
    }
  };
  const memberAdd = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selected) return;
    const data = Object.fromEntries(
      new FormData(event.currentTarget).entries(),
    );
    try {
      await api(
        `/api/channels/${encodeURIComponent(selected.channel_id)}/members`,
        {
          method: "POST",
          body: JSON.stringify({
            principal_id: data.principal_id,
            member_role: data.member_role,
            reason: data.reason,
          }),
        },
      );
      await loadSelected(selected);
    } catch (error) {
      onNotice(
        error instanceof Error
          ? error.message
          : text("成员添加失败", "Member addition failed"),
      );
    }
  };
  const memberRemove = async (item: Row) => {
    if (!selected) return;
    const reason = askReason(
      text,
      text("移除频道成员", "Remove Channel member"),
    );
    if (!reason) return;
    try {
      await api(
        `/api/channels/${encodeURIComponent(selected.channel_id)}/members/${encodeURIComponent(String(item.principal_id))}`,
        {
          method: "DELETE",
          body: JSON.stringify({ principal_id: item.principal_id, reason }),
        },
      );
      await loadSelected(selected);
    } catch (error) {
      onNotice(
        error instanceof Error
          ? error.message
          : text("成员移除失败", "Member removal failed"),
      );
    }
  };
  const lifecycle = async (status: string) => {
    if (!selected) return;
    const reason = askReason(
      text,
      text("频道生命周期调整", "Channel lifecycle adjustment"),
    );
    if (!reason) return;
    try {
      await api(
        `/api/channels/${encodeURIComponent(selected.channel_id)}/lifecycle`,
        { method: "POST", body: JSON.stringify({ status, reason }) },
      );
      await refresh();
    } catch (error) {
      onNotice(
        error instanceof Error
          ? error.message
          : text("生命周期调整失败", "Lifecycle change failed"),
      );
    }
  };
  const legalHold = async (enabled: boolean) => {
    if (!selected) return;
    const reason = askReason(
      text,
      enabled
        ? text("设置法律保全", "Set legal hold")
        : text("解除法律保全", "Release legal hold"),
      enabled
        ? text("保全审计证据", "Preserve audit evidence")
        : text("完成证据复核", "Evidence review completed"),
    );
    if (!reason) return;
    try {
      await api(
        `/api/channels/${encodeURIComponent(selected.channel_id)}/legal-hold`,
        {
          method: "POST",
          body: JSON.stringify({
            decision: enabled ? "ENABLE" : "DISABLE",
            reason,
          }),
        },
      );
      await refresh();
    } catch (error) {
      onNotice(
        error instanceof Error
          ? error.message
          : text("法律保全操作失败", "Legal hold operation failed"),
      );
    }
  };
  const reviewCandidate = async (item: Row, decision: string) => {
    const reason = askReason(
      text,
      text("记忆候选复核", "Review Memory Candidate"),
    );
    if (!reason) return;
    try {
      await api(
        `/api/memory-candidates/${encodeURIComponent(String(item.candidate_id))}/review`,
        { method: "POST", body: JSON.stringify({ decision, reason }) },
      );
      if (selected) await loadSelected(selected);
    } catch (error) {
      onNotice(
        error instanceof Error
          ? error.message
          : text("候选复核失败", "Candidate review failed"),
      );
    }
  };
  const decideAction = async (item: Row, decision: string) => {
    const reason = askReason(
      text,
      text("Action Card 决定", "Action Card decision"),
    );
    if (!reason) return;
    try {
      await api(
        `/api/actions/${encodeURIComponent(String(item.action_id))}/decision`,
        { method: "POST", body: JSON.stringify({ decision, reason }) },
      );
      if (selected) await loadSelected(selected);
    } catch (error) {
      onNotice(
        error instanceof Error
          ? error.message
          : text("动作决定失败", "Action decision failed"),
      );
    }
  };
  const approveBridge = async (item: Row) => {
    const reason = askReason(text, text("跨域桥接审批", "Bridge approval"));
    if (!reason) return;
    try {
      await api(
        `/api/bridges/${encodeURIComponent(String(item.bridge_id))}/approve`,
        {
          method: "POST",
          body: JSON.stringify({ decision: "APPROVE", reason }),
        },
      );
      if (selected) await loadSelected(selected);
    } catch (error) {
      onNotice(
        error instanceof Error
          ? error.message
          : text("跨域桥接审批失败", "Bridge approval failed"),
      );
    }
  };
  const createPanel = (
    <InfoPanel title={text("创建频道", "Create Channel")} text={text}>
      <p className="cx-form-hint">
        {text(
          "频道必须绑定安全域；默认安全域为 DEFAULT。创建频道不会扩大成员对数据、API、工具或技能的权限。",
          "A Channel must bind a Security Domain; the bootstrap domain is DEFAULT. Creating a Channel never widens member access to data, APIs, Tools, or Skills.",
        )}
      </p>
      <form className="inline-form wide-inline-form" onSubmit={createChannel}>
        <input
          name="channel_name"
          required
          placeholder={text("频道名称", "Channel name")}
        />
        <input
          name="security_domain_id"
          required
          defaultValue="DEFAULT"
          placeholder={text("安全域 ID", "Security Domain ID")}
        />
        <select name="classification" defaultValue="INTERNAL">
          <option value="INTERNAL">{text("内部", "Internal")}</option>
          <option value="CONFIDENTIAL">{text("机密", "Confidential")}</option>
          <option value="RESTRICTED">{text("受限", "Restricted")}</option>
        </select>
        <select name="channel_type" defaultValue="TEAM">
          <option value="TEAM">{text("团队", "Team")}</option>
          <option value="WORKFLOW">{text("工作流", "Workflow")}</option>
        </select>
        <button
          className="primary-button"
          disabled={!canAction(capabilities, "channels.create")}
        >
          <Plus size={15} />
          {text("创建频道", "Create Channel")}
        </button>
      </form>
    </InfoPanel>
  );
  if (!selected)
    return (
      <section>
        <SectionHeading
          title={text("频道", "Channels")}
          subtitle={text(
            "人和智能体在受安全域约束的频道中协作。",
            "Humans and Agents collaborate inside Security Domain-bound Channels.",
          )}
          text={text}
        />
        <ViewToggle
          value={view}
          options={[
            ["chat", text("频道聊天", "Channel chat"), MessageSquare],
            ["manage", text("频道管理", "Channel management"), ShieldCheck],
          ]}
          onChange={setView}
        />
        {view === "manage" && createPanel}
        <div className="empty-state">
          {text(
            "暂无频道。最高管理员可查看全部频道；其他用户仅查看所属频道。",
            "No Channels. The highest administrator can view all Channels; other users see memberships only.",
          )}
        </div>
      </section>
    );
  const threadOptions = threads.map((item) => (
    <option key={item.thread_id} value={item.thread_id}>
      {displayRowValue(lang, item.thread_type)} · {item.thread_id}
    </option>
  ));
  return (
    <section>
      <SectionHeading
        title={text("频道", "Channels")}
        subtitle={text(
          "人和智能体在受安全域约束的频道中协作；消息不会自动获得数据、工具或技能权限。私有/直接线程另行校验参与者。",
          "Humans and Agents collaborate inside Security Domain-bound Channels; messages never grant data, Tool, or Skill authority. Private and direct threads recheck explicit participants.",
        )}
        text={text}
      />
      <ViewToggle
        value={view}
        options={[
          ["chat", text("频道聊天", "Channel chat"), MessageSquare],
          ["manage", text("频道管理", "Channel management"), ShieldCheck],
        ]}
        onChange={setView}
      />
      {view === "chat" && (
        <div className="channel-layout">
          <aside className="channel-list">
            <div className="subhead">
              <b>{text("可访问频道", "Accessible channels")}</b>
              <button
                className="icon-button"
                onClick={() => void refresh()}
                title={text("刷新", "Refresh")}
              >
                <RefreshCw size={15} />
              </button>
            </div>
            {channels.map((item) => (
              <button
                key={item.channel_id}
                className={`channel-item ${selected.channel_id === item.channel_id ? "active" : ""}`}
                onClick={() => setSelected(item)}
              >
                <MessageSquare size={15} />
                <span>
                  <strong>{item.channel_name}</strong>
                  <small>
                    {displayRowValue(lang, item.classification)} ·{" "}
                    {displayRowValue(lang, item.member_role)}
                  </small>
                </span>
              </button>
            ))}
          </aside>
          <div className="channel-main">
            <div className="channel-title">
              <div>
                <h2>{selected.channel_name}</h2>
                <span>
                  {displayRowValue(lang, selected.classification)} ·{" "}
                  {text("数据库授权频道", "Database-governed Channel")}
                </span>
              </div>
              <ShieldCheck size={18} />
            </div>
            <div className="message-stream">
              {messages.map((item) => (
                <article className="message" key={item.message_id}>
                  <div className="message-avatar">
                    <Bot size={15} />
                  </div>
                  <div>
                    <div className="message-meta">
                      <b>{item.principal_id}</b>
                      <span>{item.created_at || ""}</span>
                    </div>
                    <p>{item.body_text}</p>
                    {item.thread_id && (
                      <span className="tag">
                        {displayRowValue(lang, item.thread_type)} ·{" "}
                        {item.thread_id}
                      </span>
                    )}
                  </div>
                </article>
              ))}
              {!messages.length && (
                <div className="empty-state">
                  {text(
                    "频道尚无消息，发送第一条受审计的消息。",
                    "No messages yet. Send the first attributable message.",
                  )}
                </div>
              )}
            </div>
            <form className="message-compose" onSubmit={send}>
              <textarea
                value={body}
                onChange={(event) => setBody(event.target.value)}
                placeholder={text(
                  "输入消息；命令不会直接执行。",
                  "Write a message; commands are never executed directly.",
                )}
              />
              <div className="compose-controls">
                <select
                  value={threadId}
                  onChange={(event) => setThreadId(event.target.value)}
                >
                  <option value="">
                    {text("频道消息", "Channel message")}
                  </option>
                  {threadOptions}
                </select>
                <button className="primary-button" disabled={!body.trim()}>
                  <ChevronRight size={16} />
                  {text("发送", "Send")}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
      {view === "manage" && (
        <>
          {createPanel}
          <InfoPanel title={text("管理频道", "Managed Channel")} text={text}>
            <div className="page-toolbar channel-management-picker">
              <label>
                <span>{text("当前频道", "Current Channel")}</span>
                <select
                  value={String(selected.channel_id)}
                  onChange={(event) => {
                    const next = channels.find(
                      (item) => String(item.channel_id) === event.target.value,
                    );
                    if (next) setSelected(next);
                  }}
                >
                  {channels.map((item) => (
                    <option
                      value={String(item.channel_id)}
                      key={item.channel_id}
                    >
                      {item.channel_name} · {displayRowValue(lang, item.status)}
                    </option>
                  ))}
                </select>
              </label>
              <button className="icon-button" onClick={() => void refresh()}>
                <RefreshCw size={15} />
                {text("刷新", "Refresh")}
              </button>
            </div>
          </InfoPanel>
          <div className="metric-grid">
            <div className="metric">
              <span>{text("成员", "Members")}</span>
              <strong>{summary.member_count ?? members.length}</strong>
            </div>
            <div className="metric">
              <span>{text("消息", "Messages")}</span>
              <strong>{summary.message_count ?? messages.length}</strong>
            </div>
            <div className="metric">
              <span>{text("活动智能体", "Active Agents")}</span>
              <strong>{summary.active_agent_count ?? "-"}</strong>
            </div>
            <div className="metric">
              <span>{text("开放协作关卡", "Open Collaboration gates")}</span>
              <strong>{summary.open_barrier_count ?? "-"}</strong>
            </div>
          </div>
          <div className="split-grid">
            <InfoPanel
              title={text("线程与成员", "Threads and members")}
              text={text}
            >
              <form className="compact-form" onSubmit={createThread}>
                <label>
                  {text("线程类型", "Thread type")}
                  <select name="thread_type">
                    <option value="CHANNEL">{text("频道", "Channel")}</option>
                    <option value="TASK">{text("任务", "Task")}</option>
                    <option value="RUN">{text("运行", "Run")}</option>
                    <option value="PRIVATE">{text("私有", "Private")}</option>
                    <option value="DIRECT">{text("直接", "Direct")}</option>
                  </select>
                </label>
                <label>
                  {text(
                    "参与者主体 ID（私有/直接必填）",
                    "Participant Principal IDs (required for private/direct)",
                  )}
                  <input name="participants" placeholder="HP_xxx, AG_xxx" />
                </label>
                <button className="small-button">
                  <Plus size={14} />
                  {text("创建线程", "Create thread")}
                </button>
              </form>
              <div className="mini-list">
                {threads.map((item) => (
                  <button
                    className={`list-row ${threadId === item.thread_id ? "active" : ""}`}
                    key={item.thread_id}
                    onClick={() => setThreadId(item.thread_id)}
                  >
                    <span>
                      <b>{displayRowValue(lang, item.thread_type)}</b>
                      <small>
                        {item.thread_id} ·{" "}
                        {displayRowValue(lang, item.classification)}
                      </small>
                    </span>
                  </button>
                ))}
                {!threads.length && (
                  <p className="empty-text">{text("暂无线程", "No threads")}</p>
                )}
              </div>
              <div className="member-list">
                {members.map((item) => (
                  <div className="member-row" key={item.member_id}>
                    <span>
                      <b>{item.principal_id}</b>
                      <small>
                        {displayRowValue(lang, item.principal_type)} ·{" "}
                        {displayRowValue(lang, item.member_role)}
                      </small>
                    </span>
                    {item.member_role !== "OWNER" &&
                      canAction(capabilities, "channels.manage_members") && (
                        <button
                          className="small-button danger"
                          onClick={() => void memberRemove(item)}
                        >
                          {text("移除", "Remove")}
                        </button>
                      )}
                  </div>
                ))}
              </div>
              <form className="inline-form" onSubmit={memberAdd}>
                <input
                  name="principal_id"
                  required
                  placeholder={text("成员主体 ID", "Member Principal ID")}
                />
                <select name="member_role">
                  <option value="MEMBER">{text("成员", "Member")}</option>
                  <option value="OPERATOR">{text("操作员", "Operator")}</option>
                  <option value="REVIEWER">{text("复核者", "Reviewer")}</option>
                </select>
                <input
                  name="reason"
                  required
                  placeholder={text("加入原因", "Addition reason")}
                />
                <button
                  className="small-button"
                  disabled={!canAction(capabilities, "channels.manage_members")}
                >
                  <UserPlus size={14} />
                  {text("添加", "Add")}
                </button>
              </form>
            </InfoPanel>
            <InfoPanel
              title={text("生命周期与保全", "Lifecycle and legal hold")}
              text={text}
            >
              <p className="cx-form-hint">
                {text(
                  "生命周期会影响实例租约、待处理记忆候选和延迟清理；法律保全优先于到期清理。",
                  "Lifecycle affects instance leases, pending Memory Candidates, and delayed cleanup; legal hold takes precedence over retention cleanup.",
                )}
              </p>
              <div className="row-actions">
                <button
                  className="small-button"
                  disabled={!canAction(capabilities, "channels.lifecycle")}
                  onClick={() => void lifecycle("READ_ONLY")}
                >
                  {text("只读", "Read only")}
                </button>
                <button
                  className="small-button"
                  disabled={!canAction(capabilities, "channels.lifecycle")}
                  onClick={() => void lifecycle("ARCHIVED")}
                >
                  {text("归档", "Archive")}
                </button>
                <button
                  className="small-button danger"
                  disabled={!canAction(capabilities, "channels.lifecycle")}
                  onClick={() => void lifecycle("QUARANTINED")}
                >
                  {text("隔离", "Quarantine")}
                </button>
                {selected.legal_hold ? (
                  <button
                    className="small-button"
                    onClick={() => void legalHold(false)}
                  >
                    {text("解除保全", "Release hold")}
                  </button>
                ) : (
                  <button
                    className="small-button"
                    onClick={() => void legalHold(true)}
                  >
                    {text("设置保全", "Set hold")}
                  </button>
                )}
              </div>
              <p>
                {text("当前状态：", "Current status: ")}
                <b>{displayRowValue(lang, selected.status)}</b> ·{" "}
                {selected.legal_hold
                  ? text("法律保全中", "Legal hold")
                  : text("未保全", "No hold")}
              </p>
            </InfoPanel>
          </div>
          <div className="split-grid">
            <InfoPanel title={text("动作卡片", "Action Cards")} text={text}>
              <p className="cx-form-hint">
                {text(
                  "动作先提出，再由不同主体审批；消息本身不能直接执行命令。",
                  "Actions are proposed and then decided by a separate authority; messages never execute commands directly.",
                )}
              </p>
              {actions.map((item) => (
                <div className="governance-row" key={item.action_id}>
                  <span>
                    <b>{displayRowValue(lang, item.action_type)}</b>
                    <small>
                      {displayRowValue(lang, item.status)} · {item.reason || ""}
                    </small>
                  </span>
                  {item.status === "PROPOSED" &&
                    canAction(capabilities, "channels.actions.decide") && (
                      <span className="row-actions">
                        <button
                          className="small-button"
                          onClick={() => void decideAction(item, "CONFIRM")}
                        >
                          {text("确认", "Confirm")}
                        </button>
                        <button
                          className="small-button danger"
                          onClick={() => void decideAction(item, "REJECT")}
                        >
                          {text("拒绝", "Reject")}
                        </button>
                      </span>
                    )}
                </div>
              ))}
              {!actions.length && (
                <div className="empty-state">
                  {text("暂无动作卡片", "No Action Cards")}
                </div>
              )}
            </InfoPanel>
            <InfoPanel
              title={text("记忆候选", "Memory Candidates")}
              text={text}
            >
              <p className="cx-form-hint">
                {text(
                  "候选内容不会自动升级为长期记忆，必须按安全域、分类、来源和原因复核。",
                  "Candidates never become durable memory automatically; review uses domain, classification, provenance, and purpose.",
                )}
              </p>
              {candidates.map((item) => (
                <div className="governance-row" key={item.candidate_id}>
                  <span>
                    <b>{item.candidate_id}</b>
                    <small>
                      {displayRowValue(lang, item.status)} ·{" "}
                      {displayRowValue(lang, item.classification)}
                    </small>
                  </span>
                  {item.status === "PROPOSED" &&
                    canAction(capabilities, "memory.review") && (
                      <span className="row-actions">
                        <button
                          className="small-button"
                          onClick={() => void reviewCandidate(item, "APPROVE")}
                        >
                          {text("批准", "Approve")}
                        </button>
                        <button
                          className="small-button danger"
                          onClick={() => void reviewCandidate(item, "REJECT")}
                        >
                          {text("拒绝", "Reject")}
                        </button>
                      </span>
                    )}
                </div>
              ))}
              {!candidates.length && (
                <div className="empty-state">
                  {text("暂无候选内容", "No candidates")}
                </div>
              )}
            </InfoPanel>
          </div>
          <InfoPanel
            title={text("跨域桥接", "Cross-domain Bridges")}
            text={text}
          >
            <p className="cx-form-hint">
              {text(
                "跨域桥接默认只保存元数据和摘要；跨域传递必须有目的、期限、接收者和独立审批。",
                "A Bridge stores metadata and summaries by default; cross-domain transfer requires purpose, expiry, recipients, and independent approval.",
              )}
            </p>
            <DataTable
              headers={[
                "ID",
                text("状态", "Status"),
                text("源域", "Source"),
                text("目标域", "Target"),
                text("操作", "Actions"),
              ]}
              rows={bridges.map((item) => [
                item.bridge_id,
                displayRowValue(lang, item.status),
                item.source_domain_id,
                item.target_domain_id,
                item.status === "PENDING" &&
                canAction(capabilities, "channels.bridge") ? (
                  <button
                    className="small-button"
                    onClick={() => void approveBridge(item)}
                  >
                    {text("审批", "Approve")}
                  </button>
                ) : (
                  "-"
                ),
              ])}
              empty={text("暂无跨域桥接", "No Bridges")}
              text={text}
            />
          </InfoPanel>
        </>
      )}
    </section>
  );
}

function BarriersPage({
  lang,
  capabilities,
  text,
  onNotice,
}: {
  lang: Lang;
  capabilities: Row | null;
  text: (zh: string, en: string) => string;
  onNotice: (value: string) => void;
}) {
  const [items, setItems] = useState<Row[]>([]);
  const [detail, setDetail] = useState<Row | null>(null);
  const load = () =>
    api<Row>("/api/barriers")
      .then((value) => setItems(value.items || []))
      .catch((error) =>
        onNotice(
          error instanceof Error
            ? error.message
            : text("协作关卡加载失败", "Collaboration gate loading failed"),
        ),
      );
  useEffect(() => {
    void load();
  }, []);
  const decide = async (item: Row, decision: string) => {
    const reason = askReason(
      text,
      text("人工复核协作关卡", "Review Collaboration gate decision"),
    );
    if (!reason) return;
    try {
      await api(
        `/api/barriers/${encodeURIComponent(String(item.barrier_id))}/decision`,
        { method: "POST", body: JSON.stringify({ decision, reason }) },
      );
      await load();
    } catch (error) {
      onNotice(
        error instanceof Error
          ? error.message
          : text("协作关卡决定失败", "Collaboration gate decision failed"),
      );
    }
  };
  const recover = async (item: Row, action: string, substitute = "") => {
    const reason = askReason(
      text,
      text("协作关卡恢复原因", "Collaboration gate recovery reason"),
    );
    if (!reason) return;
    try {
      await api(
        `/api/barriers/${encodeURIComponent(String(item.barrier_id))}/recover`,
        {
          method: "POST",
          body: JSON.stringify({
            action,
            reason,
            substitute_principal_id: substitute,
          }),
        },
      );
      await load();
      if (detail?.barrier_id === item.barrier_id)
        setDetail(
          await api<Row>(
            `/api/barriers/${encodeURIComponent(String(item.barrier_id))}`,
          ),
        );
    } catch (error) {
      onNotice(
        error instanceof Error
          ? error.message
          : text("协作关卡恢复失败", "Collaboration gate recovery failed"),
      );
    }
  };
  const substitute = async (item: Row) => {
    const value = window.prompt(
      text(
        "输入已授权的替代主体 ID",
        "Enter an explicitly authorized substitute Principal ID",
      ),
    );
    if (value?.trim()) await recover(item, "SUBSTITUTE", value.trim());
  };
  const actionButtons = (item: Row) => {
    const status = String(item.status || "").toUpperCase();
    const terminal = ["RELEASED", "REJECTED", "CANCELLED", "EXPIRED"].includes(
      status,
    );
    if (terminal)
      return <span className="tag">{displayRowValue(lang, status)}</span>;
    return (
      <span className="row-actions">
        {canAction(capabilities, "barriers.release") && (
          <button
            className="small-button"
            onClick={() => void decide(item, "RELEASE")}
          >
            <Check size={14} />
            {text("继续", "Release")}
          </button>
        )}
        {canAction(capabilities, "barriers.release") && (
          <button
            className="small-button danger"
            onClick={() => void decide(item, "REJECT")}
          >
            <X size={14} />
            {text("拒绝", "Reject")}
          </button>
        )}
        {canAction(capabilities, "barriers.recover") && (
          <button
            className="small-button"
            onClick={() => void recover(item, "RETRY")}
          >
            <RefreshCw size={14} />
            {text("重试", "Retry")}
          </button>
        )}
        {canAction(capabilities, "barriers.recover") && (
          <button
            className="small-button"
            onClick={() => void recover(item, "RESTORE_CHECKPOINT")}
          >
            <Database size={14} />
            {text("恢复检查点", "Restore checkpoint")}
          </button>
        )}
        {canAction(capabilities, "barriers.recover") && (
          <button
            className="small-button"
            onClick={() => void substitute(item)}
          >
            <Users size={14} />
            {text("替代", "Substitute")}
          </button>
        )}
        {canAction(capabilities, "barriers.recover") && (
          <button
            className="small-button"
            onClick={() => void recover(item, "ESCALATE")}
          >
            <ShieldCheck size={14} />
            {text("升级复核", "Escalate")}
          </button>
        )}
      </span>
    );
  };
  return (
    <section>
      <SectionHeading
        title={text("协作关卡", "Collaboration gates")}
        subtitle={text(
          "协作关卡是图中的治理节点：参与者到达、报告、复核和决定都持久化，等待不会占用工作节点租约。重试、检查点恢复、替代和升级都必须有原因并由服务器重新校验。",
          "A Collaboration gate is a governed Graph node: arrivals, reports, review, and decisions are durable, and waiting does not hold a Worker lease. Retry, checkpoint restoration, substitution, and escalation are reasoned server-side operations.",
        )}
        text={text}
      />
      <InfoPanel
        title={text("协作关卡列表", "Collaboration gate inventory")}
        text={text}
      >
        <p className="cx-form-hint">
          {text(
            "点击节点查看详情。恢复动作不会直接放大权限；替代主体必须已在频道中且被协作关卡策略明确授权。",
            "Click a node to inspect details. Recovery never widens authority; a substitute must already belong to the Channel and be explicitly authorized by the Collaboration gate policy.",
          )}
        </p>
        <DataTable
          headers={[
            text("节点", "Node"),
            text("状态", "Status"),
            text("参与快照", "Participants"),
            text("检查点", "Checkpoint"),
            text("超时", "Timeout"),
            text("操作", "Actions"),
          ]}
          rows={items.map((item) => [
            <button
              className="text-button"
              onClick={() =>
                api<Row>(
                  `/api/barriers/${encodeURIComponent(String(item.barrier_id))}`,
                )
                  .then(setDetail)
                  .catch((error) => onNotice(error.message))
              }
            >
              {item.node_key}
            </button>,
            displayRowValue(lang, item.status),
            jsonArray(item.participant_snapshot).length || "-",
            item.checkpoint_id || "-",
            item.timeout_at || "-",
            actionButtons(item),
          ])}
          empty={text("暂无协作关卡", "No Collaboration gates")}
          text={text}
        />
      </InfoPanel>
      <DetailDrawer
        open={Boolean(detail)}
        title={
          detail?.node_key || text("协作关卡详情", "Collaboration gate detail")
        }
        onClose={() => setDetail(null)}
        text={text}
      >
        {detail && (
          <>
            <p>
              {text("状态", "Status")}:{" "}
              <b>{displayRowValue(lang, detail.status)}</b>
            </p>
            <p>
              {text("检查点", "Checkpoint")}:{" "}
              <code>{detail.checkpoint_id || "-"}</code>
            </p>
            <p className="cx-form-hint">
              {text(
                "到达报告、参与者快照和检查点引用仅在当前授权范围内显示；所有恢复操作都需要填写原因。",
                "Arrival reports, participant snapshots, and checkpoint references are shown only within the current authorization scope; every recovery operation requires a reason.",
              )}
            </p>
            <pre>
              {JSON.stringify(
                {
                  participants: jsonArray(detail.participant_snapshot),
                  arrivals: detail.arrivals || [],
                  policy: detail.policy_json,
                  recovery: {
                    action: detail.last_recovery_action,
                    reason: detail.recovery_reason,
                  },
                },
                null,
                2,
              )}
            </pre>
            <div className="row-actions">{actionButtons(detail)}</div>
          </>
        )}
      </DetailDrawer>
    </section>
  );
}

function UsersPage({
  lang,
  capabilities,
  text,
  onNotice,
}: {
  lang: Lang;
  capabilities: Row | null;
  text: (zh: string, en: string) => string;
  onNotice: (value: string) => void;
}) {
  const [users, setUsers] = useState<Row[]>([]);
  const [requests, setRequests] = useState<Row[]>([]);
  const [organizations, setOrganizations] = useState<Row[]>([]);
  const [approvalOrganizations, setApprovalOrganizations] = useState<Record<string, string>>({});
  const [selected, setSelected] = useState<Row | null>(null);
  const [roles, setRoles] = useState<Row[]>([]);
  const [security, setSecurity] = useState<Row | null>(null);
  const [entryAccess, setEntryAccess] = useState<Row | null>(null);
  const [access, setAccess] = useState<Row | null>(null);
  const [factor, setFactor] = useState<Row | null>(null);
  const [busy, setBusy] = useState(false);
  const userRequest = useRef(0);

  const load = () =>
    Promise.all([
      api<Row>("/api/users"),
      api<Row>("/api/registration/requests?status=PENDING"),
      api<Row>("/api/organization/options"),
    ])
      .then(([userResponse, requestResponse, organizationResponse]) => {
        const pending = requestResponse.items || [];
        const options = organizationResponse.items || [];
        setUsers(userResponse.items || []);
        setRequests(pending);
        setOrganizations(options);
        setApprovalOrganizations((current) => {
          const next = { ...current };
          for (const item of pending) {
            const key = String(item.request_id);
            if (!next[key] && options[0]?.organization_id)
              next[key] = String(options[0].organization_id);
          }
          return next;
        });
      })
      .catch((error) =>
        onNotice(
          error instanceof Error
            ? error.message
            : text("用户数据加载失败", "Unable to load users"),
        ),
      );

  useEffect(() => {
    void load();
  }, []);

  const choose = async (user: Row) => {
    const requestId = ++userRequest.current;
    setSelected(user);
    setEntryAccess(null);
    setAccess(null);
    setFactor(null);
    const entryRequest = api<Row>(
      `/api/users/${encodeURIComponent(String(user.principal_id))}/entry-access`,
    )
      .then((entryResponse) => {
        if (requestId === userRequest.current) setEntryAccess(entryResponse);
      })
      .catch((error) => {
        if (requestId !== userRequest.current) return;
        onNotice(
          error instanceof Error
            ? error.message
            : text("入口策略加载失败", "Unable to load access policy"),
        );
      });
    try {
      const [roleResponse, securityResponse] = await Promise.all([
        api<Row>(
          `/api/users/${encodeURIComponent(String(user.principal_id))}/roles`,
        ),
        api<Row>(
          `/api/users/${encodeURIComponent(String(user.principal_id))}/security`,
        ),
      ]);
      if (requestId !== userRequest.current) return;
      setRoles(roleResponse.items || []);
      setSecurity(securityResponse);
    } catch (error) {
      if (requestId !== userRequest.current) return;
      onNotice(
        error instanceof Error
          ? error.message
          : text("用户安全信息加载失败", "Unable to load user security data"),
      );
    }
    await entryRequest;
  };

  const run = async (request: Promise<Row>, success: string) => {
    setBusy(true);
    try {
      const value = await request;
      onNotice(value?.message || success);
      return value;
    } catch (error) {
      onNotice(
        error instanceof Error
          ? error.message
          : text("操作失败", "Operation failed"),
      );
      return null;
    } finally {
      setBusy(false);
    }
  };

  const approve = async (requestId: string) => {
    const organizationId = approvalOrganizations[requestId];
    if (!organizationId) {
      onNotice(text("请先选择主组织", "Select a primary organization first"));
      return;
    }
    const reason = window.prompt(
      text("请输入审批原因", "Enter approval reason"),
      text("完成注册审核", "Registration reviewed"),
    );
    if (!reason?.trim()) return;
    await run(
      api(
        `/api/registration/requests/${encodeURIComponent(requestId)}/approve`,
        {
          method: "POST",
          body: JSON.stringify({
            decision: "APPROVE",
            reason,
            organization_id: organizationId,
          }),
        },
      ),
      text("注册已批准", "Registration approved"),
    );
    await load();
  };

  const reject = async (requestId: string) => {
    const reason = window.prompt(
      text("请输入拒绝原因", "Enter a rejection reason"),
    );
    if (!reason?.trim()) return;
    await run(
      api(
        `/api/registration/requests/${encodeURIComponent(requestId)}/reject`,
        {
          method: "POST",
          body: JSON.stringify({ decision: "REJECT", reason }),
        },
      ),
      text("注册已拒绝", "Registration rejected"),
    );
    await load();
  };

  const assign = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selected) return;
    const data = Object.fromEntries(
      new FormData(event.currentTarget).entries(),
    );
    const value = await run(
      api(
        `/api/users/${encodeURIComponent(String(selected.principal_id))}/roles`,
        { method: "POST", body: JSON.stringify(data) },
      ),
      text("角色已分配", "Role assigned"),
    );
    if (value) {
      event.currentTarget.reset();
      await choose(selected);
    }
  };

  const revokeRole = async (role: Row) => {
    if (!selected) return;
    const reason = window.prompt(
      text("请输入撤销角色的原因", "Enter a role revocation reason"),
    );
    if (!reason?.trim()) return;
    const value = await run(
      api(
        `/api/users/${encodeURIComponent(String(selected.principal_id))}/roles/${encodeURIComponent(String(role.user_role_id))}`,
        { method: "DELETE", body: JSON.stringify({ reason }) },
      ),
      text("角色已撤销", "Role revoked"),
    );
    if (value) await choose(selected);
  };

  const changeEntryAccess = async (appEnabled: boolean) => {
    if (!selected || entryAccess?.protected_system_admin) return;
    if (Boolean(entryAccess?.app_enabled) === appEnabled) return;
    const reason = window.prompt(
      text("请输入登录入口变更原因", "Enter the access-surface change reason"),
    );
    if (!reason?.trim()) return;
    const value = await run(
      api(
        `/api/users/${encodeURIComponent(String(selected.principal_id))}/entry-access`,
        {
          method: "POST",
          body: JSON.stringify({ app_enabled: appEnabled, reason }),
        },
      ),
      text("登录入口已更新", "Access surfaces updated"),
    );
    if (value) {
      setEntryAccess(value);
      setUsers((current) =>
        current.map((item) =>
          item.principal_id === selected.principal_id
            ? { ...item, ...value }
            : item,
        ),
      );
    }
  };

  const toggleMfa = async () => {
    if (!selected) return;
    const reason = window.prompt(
      text("请输入 MFA 策略变更原因", "Enter the MFA policy change reason"),
    );
    if (!reason?.trim()) return;
    const value = await run(
      api(
        `/api/users/${encodeURIComponent(String(selected.principal_id))}/mfa/policy`,
        {
          method: "POST",
          body: JSON.stringify({
            required: !Boolean(security?.mfa_required),
            reason,
          }),
        },
      ),
      text("MFA 策略已更新", "MFA policy updated"),
    );
    if (value) await choose(selected);
  };

  const enrollMfa = async () => {
    if (!selected) return;
    const reason = window.prompt(
      text("请输入 MFA 注册原因", "Enter the MFA enrollment reason"),
    );
    if (!reason?.trim()) return;
    const value = await run(
      api(
        `/api/users/${encodeURIComponent(String(selected.principal_id))}/mfa/enroll`,
        { method: "POST", body: JSON.stringify({ reason }) },
      ),
      text(
        "MFA 因子已生成，请在验证器中确认",
        "MFA factor generated; confirm it in the authenticator",
      ),
    );
    if (value) setFactor(value);
  };

  const confirmMfa = async () => {
    if (!selected || !factor?.factor_id) return;
    const code = window.prompt(
      text(
        "请输入验证器中的 6 位验证码",
        "Enter the 6-digit authenticator code",
      ),
    );
    if (!code?.trim()) return;
    const reason = window.prompt(
      text("请输入 MFA 确认原因", "Enter the MFA confirmation reason"),
      text("完成 MFA 注册", "Complete MFA enrollment"),
    );
    if (!reason?.trim()) return;
    const value = await run(
      api(
        `/api/users/${encodeURIComponent(String(selected.principal_id))}/mfa/confirm`,
        {
          method: "POST",
          body: JSON.stringify({ factor_id: factor.factor_id, code, reason }),
        },
      ),
      text("MFA 已确认", "MFA confirmed"),
    );
    if (value) {
      setFactor(null);
      await choose(selected);
    }
  };

  const issueRecovery = async () => {
    if (!selected) return;
    const reason = window.prompt(
      text("请输入生成恢复码的原因", "Enter the recovery-code issuance reason"),
    );
    if (!reason?.trim()) return;
    const value = await run(
      api(
        `/api/users/${encodeURIComponent(String(selected.principal_id))}/mfa/recovery-codes`,
        { method: "POST", body: JSON.stringify({ reason, count: 8 }) },
      ),
      text("恢复码已生成", "Recovery codes generated"),
    );
    if (value?.codes?.length)
      onNotice(
        `${text("恢复码仅显示一次，请使用安全渠道保存：", "Recovery codes are shown once; store them through a secure channel:")} ${value.codes.join(" ")}`,
      );
  };

  const revokeSession = async (session: Row) => {
    if (!selected) return;
    const reason = window.prompt(
      text("请输入终止会话的原因", "Enter the session revocation reason"),
    );
    if (!reason?.trim()) return;
    const value = await run(
      api("/api/sessions/revoke", {
        method: "POST",
        body: JSON.stringify({
          target_principal_id: selected.principal_id,
          session_digest: session.session_digest,
          reason,
        }),
      }),
      text("会话已终止", "Session revoked"),
    );
    if (value) await choose(selected);
  };

  const linkIdentity = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selected) return;
    const data = Object.fromEntries(
      new FormData(event.currentTarget).entries(),
    );
    const value = await run(
      api(
        `/api/users/${encodeURIComponent(String(selected.principal_id))}/identities`,
        {
          method: "POST",
          body: JSON.stringify({
            ...data,
            target_principal_id: selected.principal_id,
          }),
        },
      ),
      text("外部身份已绑定", "External identity linked"),
    );
    if (value) {
      event.currentTarget.reset();
      await choose(selected);
    }
  };

  const simulate = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selected) return;
    const data = new FormData(event.currentTarget);
    const action = String(data.get("action") || "profile.read");
    const value = await run(
      api(
        `/api/users/${encodeURIComponent(String(selected.principal_id))}/access?action=${encodeURIComponent(action)}`,
      ),
      text("访问模拟已完成", "Access simulation completed"),
    );
    if (value) setAccess(value);
  };

  const createDelegation = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = Object.fromEntries(
      new FormData(event.currentTarget).entries(),
    );
    const permissions = String(data.permissions || "")
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
    const value = await run(
      api("/api/delegations", {
        method: "POST",
        body: JSON.stringify({
          grantee_principal_id: data.grantee_principal_id,
          permissions,
          data_scope: data.data_scope,
          valid_until: data.valid_until || null,
          reason: data.reason,
        }),
      }),
      text("委派已创建", "Delegation created"),
    );
    if (value && selected) {
      event.currentTarget.reset();
      await choose(selected);
    }
  };

  const revokeDelegation = async (delegation: Row) => {
    const reason = window.prompt(
      text("请输入撤销委派的原因", "Enter the delegation revocation reason"),
    );
    if (!reason?.trim()) return;
    await run(
      api(
        `/api/delegations/${encodeURIComponent(String(delegation.delegation_id))}/revoke`,
        { method: "POST", body: JSON.stringify({ reason }) },
      ),
      text("委派已撤销", "Delegation revoked"),
    );
    if (selected) await choose(selected);
  };

  const selectedSessions = security?.sessions || [];
  const selectedIdentities = security?.identities || [];
  const selectedDelegations = security?.delegations || [];
  return (
    <section>
      <SectionHeading
        title={text("用户管理", "User Management")}
        subtitle={text(
          "管理员可以配置角色、权限、数据范围和安全生命周期；每项变更立即刷新 permission version，并保留原因与审计记录。",
          "Administrators manage roles, permissions, data scopes, and the security lifecycle. Every change immediately refreshes the permission version and retains a reasoned audit record.",
        )}
        text={text}
      />
      <div className="split-grid">
        <InfoPanel
          title={text("注册审批", "Registration requests")}
          text={text}
        >
          <p className="cx-form-hint">
            {text(
              "注册不会自动获得管理权限；审批通过后仍需在下方分配角色。",
              "Registration never grants administrative access; assign roles below after approval.",
            )}
          </p>
          <DataTable
            headers={[
              text("用户", "User"),
              text("邮箱", "Email"),
              text("主组织", "Primary organization"),
              text("状态", "Status"),
              text("操作", "Action"),
            ]}
            rows={requests.map((item) => [
              item.username,
              item.email || "-",
              <select
                aria-label={text("主组织", "Primary organization")}
                value={approvalOrganizations[String(item.request_id)] || ""}
                onChange={(event) =>
                  setApprovalOrganizations((current) => ({
                    ...current,
                    [String(item.request_id)]: event.target.value,
                  }))
                }
              >
                {!organizations.length && <option value="">{text("无可用组织", "No organization available")}</option>}
                {organizations.map((organization) => (
                  <option key={organization.organization_id} value={organization.organization_id}>
                    {organization.organization_name}
                  </option>
                ))}
              </select>,
              displayRowValue(lang, item.status),
              <span className="row-actions">
                <button
                  className="small-button"
                  disabled={busy || !canAction(capabilities, "users.approve")}
                  onClick={() => void approve(item.request_id)}
                >
                  <Check size={14} />
                  {text("批准", "Approve")}
                </button>
                <button
                  className="small-button danger"
                  disabled={busy || !canAction(capabilities, "users.approve")}
                  onClick={() => void reject(item.request_id)}
                >
                  <X size={14} />
                  {text("拒绝", "Reject")}
                </button>
              </span>,
            ])}
            empty={text("没有待审批注册", "No pending registrations")}
            text={text}
          />
        </InfoPanel>
        <InfoPanel title={text("用户清单", "Users")} text={text}>
          <div className="user-list">
            {users.map((user) => (
              <button
                className={`user-item ${selected?.principal_id === user.principal_id ? "active" : ""}`}
                key={user.principal_id}
                onClick={() => void choose(user)}
              >
                <Users size={15} />
                <span>
                  <b>{user.display_name || user.username}</b>
                  <small>
                    {user.username ? `${user.username} · ` : ""}
                    {user.protected_system_admin
                      ? text("系统账号", "System account")
                      : user.organization_name || text("组织待修复", "Organization required")} {" · "}
                    {user.app_enabled
                      ? text("Portal + App", "Portal + App")
                      : text("仅 Portal", "Portal only")}{" "}
                    · {displayRowValue(lang, user.status)} · v{user.permission_version}
                  </small>
                </span>
              </button>
            ))}
            {!users.length && (
              <p className="empty-text">{text("暂无用户", "No users")}</p>
            )}
          </div>
        </InfoPanel>
      </div>
      {selected && (
        <>
          <InfoPanel title={text("登录入口", "Access surfaces")} text={text}>
            <div className="governance-row">
              <span>
                <b>{text("允许使用的页面", "Allowed surfaces")}</b>
                <small>
                  {entryAccess?.protected_system_admin
                    ? text(
                        "受保护的内置系统管理员必须同时保留 Portal 与 App。",
                        "The protected bootstrap administrator must retain both Portal and App access.",
                      )
                    : text(
                        "Portal 始终可用；App 包含 Dashboard 及其应用接口。变更会立即终止该用户的现有会话。",
                        "Portal remains available. App includes the Dashboard and its application APIs. A change immediately revokes the user's active sessions.",
                      )}
                </small>
              </span>
              {entryAccess === null ? (
                <span className="secure-badge" role="status">
                  <RefreshCw className="spin" size={14} />
                  {text("正在读取入口策略", "Loading access policy")}
                </span>
              ) : entryAccess.protected_system_admin ? (
                <span className="secure-badge">
                  <ShieldCheck size={14} />
                  {text("Portal + App（系统保护）", "Portal + App (protected)")}
                </span>
              ) : (
                <span className="view-toggle entry-access-toggle">
                  <button
                    className={!entryAccess.app_enabled ? "active" : ""}
                    disabled={busy || !canAction(capabilities, "users.permissions.manage")}
                    onClick={() => void changeEntryAccess(false)}
                  >
                    {text("仅 Portal", "Portal only")}
                  </button>
                  <button
                    className={entryAccess.app_enabled ? "active" : ""}
                    disabled={busy || !canAction(capabilities, "users.permissions.manage")}
                    onClick={() => void changeEntryAccess(true)}
                  >
                    {text("Portal + App", "Portal + App")}
                  </button>
                </span>
              )}
            </div>
          </InfoPanel>
          <InfoPanel
            title={`${selected.display_name || selected.username} · ${text("身份与角色", "Identity and roles")}`}
            text={text}
          >
            <div className="role-tags">
              {roles.map((role) => (
                <span className="tag" key={role.user_role_id}>
                  {role.protected && <ShieldCheck size={13} />}
                  {displayRowValue(lang, role.role_code)}{" "}
                  {role.role_code !== "END_USER" && !role.protected && (
                    <button
                      className="text-button"
                      onClick={() => void revokeRole(role)}
                      aria-label={text("撤销角色", "Revoke role")}
                    >
                      ×
                    </button>
                  )}
                </span>
              ))}
            </div>
            <form className="inline-form" onSubmit={assign}>
              <select name="role_code" defaultValue="END_USER">
                <option value="END_USER">{text("普通用户", "End user")}</option>
                <option value="AGENT_MANAGER">
                  {text("智能体管理者", "Agent manager")}
                </option>
                <option value="OPERATOR">{text("操作员", "Operator")}</option>
                <option value="APPROVER">{text("审批者", "Approver")}</option>
                <option value="AUDITOR">{text("审计员", "Auditor")}</option>
                <option value="DEVELOPER">{text("开发者", "Developer")}</option>
                <option value="SYSTEM_ADMIN">
                  {text("系统管理员", "System admin")}
                </option>
              </select>
              <input
                name="reason"
                required
                placeholder={text("变更原因", "Change reason")}
              />
              <button
                className="primary-button"
                disabled={
                  busy || !canAction(capabilities, "users.roles.manage")
                }
              >
                <Plus size={15} />
                {text("分配角色", "Assign role")}
              </button>
            </form>
            <p className="cx-form-hint">
              {text(
                "角色分配不会绕过当前管理员的授权边界，也不能通过自我分配实现权限提升。",
                "Role assignment remains within the administrator's delegation and cannot be used for self-elevation.",
              )}
            </p>
          </InfoPanel>
          <div className="split-grid">
            <InfoPanel
              title={text("安全概览", "Security overview")}
              text={text}
            >
              <div className="governance-row">
                <span>
                  <b>{text("MFA 策略", "MFA policy")}</b>
                  <small>
                    {security?.mfa_required
                      ? text("强制", "Required")
                      : text("未强制", "Not required")}
                  </small>
                </span>
                <button
                  className="small-button"
                  disabled={
                    busy || !canAction(capabilities, "users.security.manage")
                  }
                  onClick={() => void toggleMfa()}
                >
                  {security?.mfa_required
                    ? text("取消强制", "Disable")
                    : text("强制 MFA", "Require MFA")}
                </button>
              </div>
              <div className="row-actions evidence-actions">
                <button
                  className="small-button"
                  disabled={busy || !canAction(capabilities, "profile.update")}
                  onClick={() => void enrollMfa()}
                >
                  <UserPlus size={14} />
                  {text("注册 TOTP", "Enroll TOTP")}
                </button>
                <button
                  className="small-button"
                  disabled={
                    busy || !canAction(capabilities, "users.security.manage")
                  }
                  onClick={() => void issueRecovery()}
                >
                  <FileKey2 size={14} />
                  {text("生成恢复码", "Issue recovery codes")}
                </button>
                {factor && (
                  <button
                    className="small-button"
                    onClick={() => void confirmMfa()}
                  >
                    <Check size={14} />
                    {text("确认因子", "Confirm factor")}
                  </button>
                )}
              </div>
              {factor && (
                <div className="one-time-token">
                  <small>
                    {text(
                      "仅在确认前显示此密钥；确认成功后不再返回。",
                      "This secret is shown only until confirmation; it is not returned after confirmation.",
                    )}
                  </small>
                  <code>{factor.secret}</code>
                  <code>{factor.otpauth_uri}</code>
                </div>
              )}
              <p className="cx-form-hint">
                {text(
                  "先注册并确认 TOTP，再按需开启强制 MFA。策略变更会终止该账号现有会话；登录失败达到阈值会触发数据库锁定。",
                  "Enroll and confirm TOTP before optionally requiring MFA. A policy change revokes the account's existing sessions; repeated login failures trigger a database lock.",
                )}
              </p>
            </InfoPanel>
            <InfoPanel
              title={text("有效访问模拟", "Effective access simulator")}
              text={text}
            >
              <form className="inline-form" onSubmit={simulate}>
                <input
                  name="action"
                  defaultValue="agents.read"
                  placeholder={text(
                    "例如 agents.read",
                    "For example agents.read",
                  )}
                />
                <span></span>
                <button
                  className="primary-button"
                  disabled={busy || !canAction(capabilities, "users.read")}
                >
                  <ShieldCheck size={15} />
                  {text("模拟", "Simulate")}
                </button>
              </form>
              {access && (
                <pre className="access-output">
                  {JSON.stringify(access, null, 2)}
                </pre>
              )}
            </InfoPanel>
          </div>
          <div className="split-grid">
            <InfoPanel title={text("登录会话", "Login sessions")} text={text}>
              <DataTable
                headers={[
                  text("节点", "Node"),
                  text("认证", "Auth"),
                  text("MFA", "MFA"),
                  text("到期", "Expires"),
                  text("操作", "Action"),
                ]}
                rows={selectedSessions.map((item) => [
                  item.node_id || "-",
                  item.auth_method || "-",
                  item.mfa_level || "NONE",
                  item.expires_at || "-",
                  item.revoked_at ? (
                    <span className="tag">{text("已撤销", "Revoked")}</span>
                  ) : (
                    <button
                      className="small-button danger"
                      disabled={
                        busy || !canAction(capabilities, "sessions.revoke")
                      }
                      onClick={() => void revokeSession(item)}
                    >
                      <X size={14} />
                      {text("终止", "Revoke")}
                    </button>
                  ),
                ])}
                empty={text("没有活跃会话", "No sessions")}
                text={text}
              />
            </InfoPanel>
            <InfoPanel
              title={text("外部登录身份", "External identities")}
              text={text}
            >
              <DataTable
                headers={[
                  text("类型", "Type"),
                  text("提供方", "Provider"),
                  text("主体", "Subject"),
                  text("状态", "Status"),
                ]}
                rows={selectedIdentities.map((item) => [
                  displayRowValue(lang, item.identity_type),
                  item.provider || "-",
                  item.subject_key || "-",
                  displayRowValue(lang, item.status),
                ])}
                empty={text("未绑定外部身份", "No external identities")}
                text={text}
              />
              <form
                className="inline-form wide-inline-form"
                onSubmit={linkIdentity}
              >
                <select name="identity_type" defaultValue="OIDC">
                  <option value="OIDC">OIDC</option>
                  <option value="LDAP">LDAP</option>
                </select>
                <input
                  name="provider"
                  required
                  placeholder={text("提供方", "Provider")}
                />
                <input
                  name="subject_key"
                  required
                  placeholder={text("不可变主体 ID", "Immutable subject ID")}
                />
                <input
                  name="reason"
                  required
                  placeholder={text("绑定原因", "Link reason")}
                />
                <button
                  className="primary-button"
                  disabled={
                    busy || !canAction(capabilities, "users.identity.link")
                  }
                >
                  <Plus size={15} />
                  {text("绑定", "Link")}
                </button>
              </form>
            </InfoPanel>
          </div>
          <div className="split-grid">
            <InfoPanel title={text("委派", "Delegations")} text={text}>
              <DataTable
                headers={[
                  text("受让人", "Grantee"),
                  text("范围", "Scope"),
                  text("有效期", "Valid until"),
                  text("状态", "Status"),
                  text("操作", "Action"),
                ]}
                rows={selectedDelegations.map((item) => [
                  item.grantee_principal_id,
                  displayRowValue(lang, item.data_scope),
                  item.valid_until || text("长期", "No expiry"),
                  displayRowValue(lang, item.status),
                  item.status === "ACTIVE" ? (
                    <button
                      className="small-button danger"
                      disabled={
                        busy ||
                        !canAction(capabilities, "users.delegations.manage")
                      }
                      onClick={() => void revokeDelegation(item)}
                    >
                      <X size={14} />
                      {text("撤销", "Revoke")}
                    </button>
                  ) : (
                    "-"
                  ),
                ])}
                empty={text("没有当前委派", "No delegations")}
                text={text}
              />
              <form
                className="inline-form wide-inline-form"
                onSubmit={createDelegation}
              >
                <input
                  name="grantee_principal_id"
                  required
                  placeholder={text("受让人主体 ID", "Grantee Principal ID")}
                />
                <input
                  name="permissions"
                  required
                  placeholder={text(
                    "权限，逗号分隔",
                    "Permissions, comma separated",
                  )}
                />
                <select name="data_scope" defaultValue="ASSIGNED">
                  <option value="ASSIGNED">
                    {text("分配范围", "Assigned")}
                  </option>
                  <option value="OWNED">{text("所有者范围", "Owned")}</option>
                  <option value="ORG_SUBTREE">
                    {text("组织子树", "Organization subtree")}
                  </option>
                </select>
                <input
                  name="valid_until"
                  placeholder={text(
                    "有效期 ISO 时间（可选）",
                    "Valid-until ISO time (optional)",
                  )}
                />
                <input
                  name="reason"
                  required
                  placeholder={text("委派原因", "Delegation reason")}
                />
                <button
                  className="primary-button"
                  disabled={
                    busy || !canAction(capabilities, "users.delegations.manage")
                  }
                >
                  <Plus size={15} />
                  {text("创建委派", "Create delegation")}
                </button>
              </form>
            </InfoPanel>
            <InfoPanel
              title={text("安全边界", "Security boundary")}
              text={text}
            >
              <p>
                {text(
                  "用户归属、角色、数据范围、会话和身份绑定由数据库事实源决定。页面本身不会扩大权限；智能体的实际运行还要经过独立注册、实例和安全域校验。",
                  "Ownership, roles, data scopes, sessions, and linked identities come from the database fact source. The page cannot widen authority; Agent execution still requires independent Enrollment, instance, and Security Domain checks.",
                )}
              </p>
              <p className="cx-form-hint">
                {text(
                  "外部身份绑定必须证明当前身份并满足 MFA/审批条件；跨组织委派、权限覆盖和系统级角色会由服务端再次校验。",
                  "External identity linking requires proof of the current identity and MFA/approval conditions. Cross-organization delegation, permission overrides, and system roles are checked again server-side.",
                )}
              </p>
            </InfoPanel>
          </div>
        </>
      )}
    </section>
  );
}

function MonitorDetails({
  lang,
  text,
  onNotice,
}: {
  lang: Lang;
  text: (zh: string, en: string) => string;
  onNotice: (value: string) => void;
}) {
  const [agents, setAgents] = useState<Row[]>([]);
  const [metrics, setMetrics] = useState<Row>({});
  const [filter, setFilter] = useState("ALL");
  const [loading, setLoading] = useState(true);
  const load = async () => {
    setLoading(true);
    try {
      const [agentData, metricData] = await Promise.all([
        api<Row>("/api/monitor/agents"),
        api<Row>("/api/monitor/metrics"),
      ]);
      setAgents(agentData.agents || []);
      setMetrics(metricData);
    } catch (error) {
      onNotice(
        error instanceof Error
          ? error.message
          : text("监控明细加载失败", "Monitor details loading failed"),
      );
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 30000);
    return () => window.clearInterval(timer);
  }, []);
  const statuses = Array.from(
    new Set(
      agents.map((item) => String(item.status || "UNKNOWN").toUpperCase()),
    ),
  ).sort();
  const visible =
    filter === "ALL"
      ? agents
      : agents.filter(
          (item) => String(item.status || "").toUpperCase() === filter,
        );
  const duration = (value: any) =>
    value === null || value === undefined
      ? text("无样本", "No samples")
      : `${Math.round(Number(value))}s`;
  return (
    <section className="monitor-details">
      <InfoPanel title={text("性能指标", "Performance metrics")} text={text}>
        <div className="metric-grid compact-metrics">
          <div className="metric">
            <span>{text("平均会话时长", "Average session duration")}</span>
            <strong>{duration(metrics.avg_session_duration)}</strong>
            <small>
              {metrics.session_sample_count || 0} {text("个样本", "samples")}
            </small>
          </div>
          <div className="metric">
            <span>{text("平均循环时长", "Average Loop duration")}</span>
            <strong>{duration(metrics.avg_loop_duration)}</strong>
            <small>
              {metrics.loop_sample_count || 0} {text("个样本", "samples")}
            </small>
          </div>
          <div className="metric">
            <span>{text("平均工具耗时", "Average Tool latency")}</span>
            <strong>
              {metrics.avg_tool_duration_ms == null
                ? text("无样本", "No samples")
                : `${Math.round(Number(metrics.avg_tool_duration_ms))}ms`}
            </strong>
            <small>
              {metrics.tool_sample_count || 0} {text("个样本", "samples")}
            </small>
          </div>
          <div className="metric">
            <span>{text("24 小时实体访问", "24h entity access")}</span>
            <strong>{metrics.entity_access_count_24h ?? 0}</strong>
          </div>
        </div>
      </InfoPanel>
      <InfoPanel title={text("智能体列表", "Agent inventory")} text={text}>
        <div className="filter-row">
          <button
            className={`filter-button ${filter === "ALL" ? "active" : ""}`}
            onClick={() => setFilter("ALL")}
          >
            {text("全部", "All")} · {agents.length}
          </button>
          {statuses.map((status) => (
            <button
              className={`filter-button ${filter === status ? "active" : ""}`}
              key={status}
              onClick={() => setFilter(status)}
            >
              {displayRowValue(lang, status)} ·{" "}
              {
                agents.filter(
                  (item) => String(item.status).toUpperCase() === status,
                ).length
              }
            </button>
          ))}
          <button
            className="icon-button filter-refresh"
            onClick={() => void load()}
          >
            <RefreshCw className={loading ? "spin" : ""} size={15} />
            {text("刷新", "Refresh")}
          </button>
        </div>
        {loading ? (
          <PageLoading text={text} />
        ) : (
          <DataTable
            headers={[
              text("智能体 ID", "Agent ID"),
              text("名称", "Name"),
              text("状态", "Status"),
              text("活动任务", "Active tasks"),
              text("运行循环", "Running Loops"),
              text("最后活动", "Last active"),
              text("停滞秒数", "Stale seconds"),
            ]}
            rows={visible.map((item) => [
              item.agent_id,
              item.agent_name || "-",
              displayRowValue(lang, item.status),
              item.active_plan_count || 0,
              item.running_loop_count || 0,
              item.last_active_at || text("从未", "Never"),
              item.stale_seconds ?? "-",
            ])}
            empty={text(
              "当前过滤条件下没有智能体",
              "No Agents match the current filter",
            )}
            text={text}
          />
        )}
      </InfoPanel>
    </section>
  );
}

function FilePicker({
  name,
  accept,
  text,
}: {
  name: string;
  accept?: string;
  text: (zh: string, en: string) => string;
}) {
  const input = useRef<HTMLInputElement | null>(null);
  const [filename, setFilename] = useState("");
  useEffect(() => {
    const form = input.current?.form;
    if (!form) return;
    const reset = () => setFilename("");
    form.addEventListener("reset", reset);
    return () => form.removeEventListener("reset", reset);
  }, []);
  return (
    <span className="file-picker">
      <input
        ref={input}
        className="visually-hidden-file"
        type="file"
        name={name}
        accept={accept}
        required
        onChange={(event) => setFilename(event.target.files?.[0]?.name || "")}
      />
      <button
        type="button"
        className="small-button"
        onClick={() => input.current?.click()}
      >
        <Upload size={14} />
        {text("选择文件", "Choose file")}
      </button>
      <span title={filename}>
        {filename || text("未选择文件", "No file selected")}
      </span>
    </span>
  );
}

function LegacyOperations({
  page,
  lang,
  capabilities,
  text,
  onNotice,
}: {
  page: string;
  lang: Lang;
  capabilities: Row | null;
  text: (zh: string, en: string) => string;
  onNotice: (value: string) => void;
}) {
  const [items, setItems] = useState<Row[]>([]);
  const [selected, setSelected] = useState("");
  const [runs, setRuns] = useState<Row[]>([]);
  const endpoint =
    page === "skills"
      ? "/api/skills"
      : page === "branches"
        ? "/api/branches"
        : "/api/loops";
  const key =
    page === "skills" ? "skills" : page === "branches" ? "branches" : "loops";
  const idField =
    page === "skills"
      ? "entity_id"
      : page === "branches"
        ? "branch_id"
        : "loop_id";
  const load = async () => {
    try {
      const value = await api<Row>(endpoint);
      const list = listPayload(value, [key]);
      setItems(list);
      if (!selected && list[0]) setSelected(String(list[0][idField]));
    } catch (error) {
      onNotice(
        error instanceof Error
          ? error.message
          : text("管理操作加载失败", "Management operations loading failed"),
      );
    }
  };
  useEffect(() => {
    void load();
  }, [page]);
  useEffect(() => {
    if (page !== "loops" || !selected) {
      setRuns([]);
      return;
    }
    api<Row>(`/api/loops/${encodeURIComponent(selected)}/runs`)
      .then((value) => setRuns(listPayload(value, ["runs"])))
      .catch((error) =>
        onNotice(
          error instanceof Error
            ? error.message
            : text("循环运行加载失败", "Loop runs could not be loaded"),
        ),
      );
  }, [page, selected]);
  const run = async (path: string, body: Row = {}) => {
    try {
      await api(path, { method: "POST", body: JSON.stringify(body) });
      await load();
      onNotice(
        text(
          "操作已完成并写入数据库。",
          "The operation completed and was persisted.",
        ),
      );
    } catch (error) {
      onNotice(
        error instanceof Error
          ? error.message
          : text("操作失败", "Operation failed"),
      );
    }
  };
  if (page === "skills") {
    const target = items.find((item) => String(item[idField]) === selected);
    const upload = async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      const form = new FormData(event.currentTarget);
      try {
        await api("/api/skill/create", { method: "POST", body: form });
        event.currentTarget.reset();
        await load();
        onNotice(text("技能包已创建。", "Skill package created."));
      } catch (error) {
        onNotice(
          error instanceof Error
            ? error.message
            : text("技能包创建失败", "Skill package creation failed"),
        );
      }
    };
    const update = async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (!selected) return;
      const data = Object.fromEntries(
        new FormData(event.currentTarget).entries(),
      );
      await run(`/api/skill/${encodeURIComponent(selected)}/update`, data);
    };
    const uploadResource = async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (!selected) return;
      const form = new FormData(event.currentTarget);
      try {
        await api(`/api/skill/${encodeURIComponent(selected)}/upload`, {
          method: "POST",
          body: form,
        });
        event.currentTarget.reset();
        await load();
        onNotice(text("技能资源已更新。", "Skill resource updated."));
      } catch (error) {
        onNotice(
          error instanceof Error
            ? error.message
            : text("技能资源更新失败", "Skill resource update failed"),
        );
      }
    };
    return (
      <InfoPanel title={text("技能管理", "Skill management")} text={text}>
        <p className="cx-form-hint">
          {text(
            "上传包含 SKILL.md 的 ZIP 创建技能；选择已有技能后可更新元数据、替换资源、下载资源或删除。",
            "Upload a ZIP containing SKILL.md to create a Skill; select an existing Skill to update metadata, replace or download its resource, or delete it.",
          )}
        </p>
        <form className="inline-form" onSubmit={upload}>
          <FilePicker name="file" accept=".zip" text={text} />
          <span></span>
          <button
            className="primary-button"
            disabled={!canAction(capabilities, "skills.write")}
          >
            <Plus size={15} />
            {text("创建技能", "Create Skill")}
          </button>
        </form>
        <div className="page-toolbar evidence-actions">
          <select
            value={selected}
            onChange={(event) => setSelected(event.target.value)}
          >
            {items.map((item) => (
              <option key={item[idField]} value={item[idField]}>
                {item.skill_name || item.title || item[idField]}
              </option>
            ))}
          </select>
          <span className="row-actions">
            <a
              className={`small-button ${!selected ? "disabled" : ""}`}
              href={
                selected
                  ? `/api/skill/${encodeURIComponent(selected)}/resource`
                  : undefined
              }
            >
              <Download size={14} />
              {text("下载资源", "Download resource")}
            </a>
            <button
              className="small-button danger"
              disabled={!selected || !canAction(capabilities, "skills.write")}
              onClick={() => {
                const reason = askReason(
                  text,
                  text("删除不再使用的技能", "Remove an unused Skill"),
                );
                if (reason)
                  void run(
                    `/api/skill/${encodeURIComponent(selected)}/delete`,
                    { reason },
                  );
              }}
            >
              <X size={14} />
              {text("删除所选技能", "Delete selected Skill")}
            </button>
          </span>
        </div>
        {target && (
          <div className="split-grid operation-form">
            <form className="compact-form" onSubmit={update}>
              <label>
                {text("技能名称", "Skill name")}
                <input
                  name="skill_name"
                  defaultValue={target.skill_name || ""}
                  required
                />
              </label>
              <label>
                {text("版本", "Version")}
                <input
                  name="skill_version"
                  defaultValue={target.skill_version || "1.0.0"}
                  required
                />
              </label>
              <label>
                {text("状态", "Status")}
                <select
                  name="skill_status"
                  defaultValue={
                    target.skill_status || target.status || "ACTIVE"
                  }
                >
                  <option value="ACTIVE">{text("活动", "Active")}</option>
                  <option value="INACTIVE">{text("非活动", "Inactive")}</option>
                  <option value="DEPRECATED">
                    {text("已弃用", "Deprecated")}
                  </option>
                </select>
              </label>
              <button
                className="primary-button"
                disabled={!canAction(capabilities, "skills.write")}
              >
                <RefreshCw size={14} />
                {text("更新元数据", "Update metadata")}
              </button>
            </form>
            <form className="compact-form" onSubmit={uploadResource}>
              <label>
                {text("替换技能资源", "Replace Skill resource")}
                <FilePicker name="file" text={text} />
              </label>
              <p className="cx-form-hint">
                {target.resource_filename ||
                  text("当前没有单独资源文件", "No separate resource file")}
              </p>
              <button
                className="primary-button"
                disabled={!canAction(capabilities, "skills.write")}
              >
                <Upload size={14} />
                {text("上传资源", "Upload resource")}
              </button>
            </form>
          </div>
        )}
      </InfoPanel>
    );
  }
  if (page === "branches") {
    const fork = async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      const body = Object.fromEntries(
        new FormData(event.currentTarget).entries(),
      );
      await run("/api/branch/fork", body);
      event.currentTarget.reset();
    };
    const target = items.find((item) => String(item.branch_id) === selected);
    return (
      <InfoPanel title={text("分支操作", "Branch operations")} text={text}>
        <form className="compact-form operation-form" onSubmit={fork}>
          <div className="operation-grid">
            <input
              name="workspace_id"
              required
              placeholder={text("工作区 ID", "Workspace ID")}
            />
            <input
              name="fork_context_id"
              placeholder={text("上下文 ID（可选）", "Context ID (optional)")}
            />
            <input
              name="branch_name"
              required
              placeholder={text("分支名称", "Branch name")}
            />
            <select name="branch_type" defaultValue="EXPERIMENT">
              <option value="EXPERIMENT">{text("实验", "Experiment")}</option>
              <option value="HANDOFF">{text("移交", "Handoff")}</option>
              <option value="PARALLEL">{text("并行", "Parallel")}</option>
            </select>
            <input
              name="agent_id"
              required
              placeholder={text("目标智能体 ID", "Target Agent ID")}
            />
            <input
              name="source_agent_id"
              placeholder={text("源智能体 ID", "Source Agent ID")}
            />
            <input
              name="purpose"
              required
              placeholder={text("分支目的", "Branch purpose")}
            />
          </div>
          <button
            className="primary-button"
            disabled={!canAction(capabilities, "branches.write")}
          >
            <GitBranch size={15} />
            {text("创建分支", "Fork branch")}
          </button>
        </form>
        <div className="page-toolbar evidence-actions">
          <select
            value={selected}
            onChange={(event) => setSelected(event.target.value)}
          >
            {items.map((item) => (
              <option key={item.branch_id} value={item.branch_id}>
                {item.branch_name || item.branch_id}
              </option>
            ))}
          </select>
          <span className="row-actions">
            <button
              className="small-button"
              disabled={!selected || !canAction(capabilities, "branches.write")}
              onClick={() =>
                void run(
                  `/api/branch/${encodeURIComponent(selected)}/${String(target?.branch_status || "").toUpperCase() === "PAUSED" ? "resume" : "pause"}`,
                )
              }
            >
              {String(target?.branch_status || "").toUpperCase() === "PAUSED"
                ? text("恢复", "Resume")
                : text("暂停", "Pause")}
            </button>
            <button
              className="small-button danger"
              disabled={!selected || !canAction(capabilities, "branches.write")}
              onClick={() => {
                const reason = askReason(
                  text,
                  text("废弃分支", "Abandon branch"),
                );
                if (reason)
                  void run(
                    `/api/branch/${encodeURIComponent(selected)}/abandon`,
                    { reason },
                  );
              }}
            >
              <X size={14} />
              {text("废弃", "Abandon")}
            </button>
          </span>
        </div>
      </InfoPanel>
    );
  }
  const createLoop = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = Object.fromEntries(
      new FormData(event.currentTarget).entries(),
    );
    await run("/api/loops/create", {
      title: data.title,
      summary: data.summary,
      visibility: data.visibility,
      goal_definition: { goal: data.goal || data.title },
      stop_conditions: { max_iterations: Number(data.max_iterations || 10) },
      evaluation_config: { eval_type: "MANUAL" },
    });
    event.currentTarget.reset();
  };
  const controlRun = async (
    runId: string,
    action: "pause" | "resume" | "stop",
  ) => {
    const reason =
      action === "stop"
        ? askReason(text, text("停止循环运行", "Stop Loop run"))
        : "operator control";
    if (!reason) return;
    await run(`/api/loops/runs/${action}`, { run_id: runId, reason });
    const value = await api<Row>(
      `/api/loops/${encodeURIComponent(selected)}/runs`,
    );
    setRuns(listPayload(value, ["runs"]));
  };
  const selectedLoop = items.find((item) => String(item.loop_id) === selected);
  const startRun = async () => {
    if (!selected) return;
    try {
      await api("/api/loops/runs/start", {
        method: "POST",
        body: JSON.stringify({
          loop_id: selected,
          agent_id:
            selectedLoop?.owned_by_agent || selectedLoop?.agent_id || "system",
        }),
      });
      const value = await api<Row>(
        `/api/loops/${encodeURIComponent(selected)}/runs`,
      );
      setRuns(listPayload(value, ["runs"]));
      await load();
      onNotice(text("循环运行已启动。", "Loop run started."));
    } catch (error) {
      onNotice(
        error instanceof Error
          ? error.message
          : text("循环启动失败", "Loop start failed"),
      );
    }
  };
  return (
    <InfoPanel title={text("循环操作", "Loop operations")} text={text}>
      <form className="operation-grid" onSubmit={createLoop}>
        <input
          name="title"
          required
          placeholder={text("循环标题", "Loop title")}
        />
        <input name="goal" required placeholder={text("目标", "Goal")} />
        <input name="summary" placeholder={text("摘要", "Summary")} />
        <input name="max_iterations" type="number" min="1" defaultValue="10" />
        <select name="visibility" defaultValue="PRIVATE">
          <option value="PRIVATE">{text("私有", "Private")}</option>
          <option value="SHARED">{text("共享", "Shared")}</option>
        </select>
        <button
          className="primary-button"
          disabled={!canAction(capabilities, "loops.write")}
        >
          <Plus size={15} />
          {text("创建循环", "Create Loop")}
        </button>
      </form>
      <div className="page-toolbar evidence-actions">
        <select
          value={selected}
          onChange={(event) => setSelected(event.target.value)}
        >
          {items.map((item) => (
            <option key={item.loop_id} value={item.loop_id}>
              {item.title || item.loop_id} ·{" "}
              {displayRowValue(lang, item.status)}
            </option>
          ))}
        </select>
        <span className="row-actions">
          <button
            className="small-button"
            disabled={!selected || !canAction(capabilities, "loops.write")}
            onClick={() => void startRun()}
          >
            <PlayCircle size={14} />
            {text("启动运行", "Start run")}
          </button>
          <button
            className="small-button danger"
            disabled={!selected || !canAction(capabilities, "loops.write")}
            onClick={() => void run("/api/loops/delete", { loop_id: selected })}
          >
            <X size={14} />
            {text("删除循环", "Delete Loop")}
          </button>
        </span>
      </div>
      <DataTable
        headers={[
          text("运行 ID", "Run ID"),
          text("状态", "Status"),
          text("迭代", "Iterations"),
          text("令牌", "Tokens"),
          text("操作", "Actions"),
        ]}
        rows={runs.map((item) => {
          const status = String(item.status || "").toUpperCase();
          return [
            item.run_id,
            displayRowValue(lang, status),
            item.iteration_count || 0,
            item.total_tokens || 0,
            <span className="row-actions">
              {status === "RUNNING" && (
                <button
                  className="small-button"
                  disabled={!canAction(capabilities, "loops.write")}
                  onClick={() => void controlRun(String(item.run_id), "pause")}
                >
                  <PauseCircle size={14} />
                  {text("暂停", "Pause")}
                </button>
              )}
              {status === "PAUSED" && (
                <button
                  className="small-button"
                  disabled={!canAction(capabilities, "loops.write")}
                  onClick={() => void controlRun(String(item.run_id), "resume")}
                >
                  <PlayCircle size={14} />
                  {text("恢复", "Resume")}
                </button>
              )}
              {["RUNNING", "PAUSED"].includes(status) && (
                <button
                  className="small-button danger"
                  disabled={!canAction(capabilities, "loops.write")}
                  onClick={() => void controlRun(String(item.run_id), "stop")}
                >
                  <StopCircle size={14} />
                  {text("停止", "Stop")}
                </button>
              )}
            </span>,
          ];
        })}
        empty={text("所选循环暂无运行记录", "No runs for the selected Loop")}
        text={text}
      />
    </InfoPanel>
  );
}

function SectionHeading({
  title,
  subtitle,
  text,
}: {
  title: string;
  subtitle: string;
  text: (zh: string, en: string) => string;
}) {
  return (
    <div className="section-heading">
      <div>
        <p className="eyebrow">{text("川序控制台", "CHUANXU CONSOLE")}</p>
        <h1>{title}</h1>
        <p>{subtitle}</p>
      </div>
      <span className="secure-badge">
        <ShieldCheck size={15} />
        {text("数据库授权", "DB governed")}
      </span>
    </div>
  );
}
function PageLoading({ text }: { text: (zh: string, en: string) => string }) {
  return (
    <div className="empty-state cx-data-loading" role="status">
      <span className="cx-loader spinner" aria-hidden="true" />
      <span>{text("正在读取数据库", "Reading database")}</span>
      <span className="loading-dots" aria-hidden="true">
        <i />
        <i />
        <i />
      </span>
    </div>
  );
}
function InfoPanel({
  title,
  children,
  text,
}: {
  title: string;
  children: React.ReactNode;
  text: (zh: string, en: string) => string;
}) {
  return (
    <section className="info-panel">
      <div className="panel-title">
        <h2>{title}</h2>
        <span>{text("受保护视图", "Protected view")}</span>
      </div>
      {children}
    </section>
  );
}
function ViewToggle({
  value,
  options,
  onChange,
}: {
  value: string;
  options: [string, string, React.ComponentType<{ size?: number }>?][];
  onChange: (value: string) => void;
}) {
  return (
    <div className="view-toggle" role="tablist">
      {options.map(([key, label, Icon]) => (
        <button
          type="button"
          role="tab"
          aria-selected={value === key}
          className={value === key ? "active" : ""}
          key={key}
          onClick={() => onChange(key)}
        >
          {Icon && <Icon size={14} />}
          <span>{label}</span>
        </button>
      ))}
    </div>
  );
}
function DetailDrawer({
  open,
  title,
  onClose,
  text,
  children,
  wide = false,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  text: (zh: string, en: string) => string;
  children: React.ReactNode;
  wide?: boolean;
}) {
  useEffect(() => {
    if (!open) return;
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div
      className="detail-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <aside
        className={`detail-drawer ${wide ? "wide" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <div className="subhead">
          <h2>{title}</h2>
          <button
            className="icon-button"
            onClick={onClose}
            aria-label={text("关闭", "Close")}
          >
            <X size={16} />
          </button>
        </div>
        {children}
      </aside>
    </div>
  );
}
function DataTable({
  headers,
  rows,
  empty,
  text,
}: {
  headers: string[];
  rows: React.ReactNode[][];
  empty: string;
  text: (zh: string, en: string) => string;
}) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {headers.map((header) => (
              <th key={header}>{header}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length ? (
            rows.map((row, index) => (
              <tr key={index}>
                {row.map((value, cell) => (
                  <td key={cell}>{value}</td>
                ))}
              </tr>
            ))
          ) : (
            <tr>
              <td colSpan={headers.length} className="empty-cell">
                {empty}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
