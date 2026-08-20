import React, { FormEvent, lazy, Suspense, useEffect, useRef, useState } from "react";
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
  Pin,
  PlayCircle,
  Plus,
  Redo2,
  RefreshCw,
  Search,
  Settings2,
  Send,
  ShieldCheck,
  StopCircle,
  Sun,
  Upload,
  User,
  UserPlus,
  Users,
  Undo2,
  X,
} from "lucide-react";
import "./app.css";

const GraphRoutePage = lazy(() => import("./pages/GraphPage"));

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
  ["compliance", "合规", "Compliance", ShieldCheck],
  ["audit", "审计", "Audit", FileKey2],
  ["users", "用户管理", "Users", Users],
  ["organization", "组织架构", "Organization", Building2],
  ["security-domains", "安全域", "Security Domains", ShieldCheck],
  ["platform", "平台配置", "Platform configuration", Settings2],
] as const;

const tx = (lang: Lang, zh: string, en: string) => (lang === "zh" ? zh : en);
const pageFromPath = () => {
  const parts = window.location.pathname.split("/").filter(Boolean);
  return parts[0] === "app" && parts[1] ? parts[1] : "monitor";
};

function useUrlState<T extends string>(
  key: string,
  allowed: readonly T[],
  fallback: T,
): [T, (value: T) => void] {
  const read = () => {
    const value = new URLSearchParams(window.location.search).get(key);
    return value && allowed.includes(value as T) ? (value as T) : fallback;
  };
  const [state, setState] = useState<T>(read);
  useEffect(() => {
    const onPopState = () => setState(read());
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [key, fallback, allowed.join("|")]);
  const update = (value: T) => {
    if (!allowed.includes(value)) return;
    setState(value);
    const url = new URL(window.location.href);
    if (value === fallback) url.searchParams.delete(key);
    else url.searchParams.set(key, value);
    window.history.replaceState({}, "", url.pathname + url.search);
  };
  return [state, update];
}

function useUrlParam(
  key: string,
  fallback = "",
): [string, (value: string) => void] {
  const read = () => {
    const value = new URLSearchParams(window.location.search).get(key) || "";
    return value.length <= 200 ? value : fallback;
  };
  const [state, setState] = useState<string>(read);
  useEffect(() => {
    const onPopState = () => setState(read());
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [key, fallback]);
  const update = (value: string) => {
    if (value.length > 200) return;
    setState(value);
    const url = new URL(window.location.href);
    if (value) url.searchParams.set(key, value);
    else url.searchParams.delete(key);
    window.history.replaceState({}, "", url.pathname + url.search);
  };
  return [state, update];
}

const validationFieldLabels: Record<string, [string, string]> = {
  reason: ["变更原因", "change reason"],
  profile_key: ["配置键", "profile key"],
  provider_url: ["模型服务地址", "provider URL"],
  model_id: ["模型 ID", "model ID"],
  execution_mode: ["接入模式", "execution mode"],
  dimension: ["向量维度", "vector dimension"],
  distance_metric: ["距离度量", "distance metric"],
  api_key: ["API Key", "API key"],
  secret_reference: ["企业密钥引用", "enterprise secret reference"],
  agent_id: ["智能体 ID", "Agent ID"],
  agent_name: ["智能体名称", "Agent name"],
  principal_id: ["平台主体", "platform principal"],
  security_domain_id: ["安全域", "security domain"],
  channel_name: ["频道名称", "Channel name"],
  display_name: ["显示名称", "display name"],
  package: ["平台新版 ZIP 压缩包", "new platform release ZIP"],
};

function validationMessage(detail: unknown, lang: Lang): string | null {
  if (!Array.isArray(detail) || !detail.length) return null;
  const issue = detail.find(
    (item): item is Row => Boolean(item) && typeof item === "object",
  );
  if (!issue) return null;
  const location = Array.isArray(issue.loc) ? issue.loc : [];
  const field = String(location[location.length - 1] || "");
  const fieldLabel = validationFieldLabels[field]?.[lang === "zh" ? 0 : 1];
  const kind = String(issue.type || "");
  const minimum = Number(issue.ctx?.min_length || 0);
  if (kind === "missing")
    return lang === "zh"
      ? `请填写${fieldLabel || "必填项"}。`
      : `Enter the required ${fieldLabel || "field"}.`;
  if (kind === "string_too_short" && minimum > 0)
    return lang === "zh"
      ? `${fieldLabel || "填写内容"}至少需要 ${minimum} 个字符。`
      : `${fieldLabel || "This field"} must contain at least ${minimum} characters.`;
  return lang === "zh"
    ? `请求内容不符合要求，请检查${fieldLabel || "填写项"}。`
    : `Request validation failed. Check ${fieldLabel || "the submitted fields"}.`;
}

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
  const csrf = localStorage.getItem("cxDashboardCsrf");
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
      const lang = (localStorage.getItem("cxLang") as Lang) || "zh";
      try {
        const detail = await response.json();
        message = validationMessage(detail.detail, lang)
          || (typeof detail.detail === "string" ? detail.detail : "")
          || (typeof detail.error === "string" ? detail.error : message);
      } catch {
        /* non-JSON error */
      }
      const localized: Record<string, [string, string]> = {
        "Monitor inventory is unavailable": ["监控智能体清单暂不可用", "Monitor inventory is unavailable"],
        "Audit service unavailable": ["审计服务暂不可用", "Audit service unavailable"],
        "Native Agent inventory is unavailable": ["平台原生智能体清单暂不可用", "Native Agent inventory is unavailable"],
        "Native Agent activation was denied": ["平台原生智能体激活被拒绝", "Native Agent activation was denied"],
        "Native Agent bootstrap failed": ["平台原生智能体初始化失败", "Native Agent bootstrap failed"],
        "LLM Provider Profile is unavailable": ["LLM 服务商配置不可用", "LLM Provider Profile is unavailable"],
        "LLM provider returned a different model": ["LLM 服务返回的模型与配置不一致，请检查模型 ID 和服务地址。", "The provider returned a different model than configured; check the model ID and provider URL."],
        "Platform Administration service is unavailable": ["平台管理服务暂不可用", "Platform Administration service is unavailable"],
        "Platform Embedding activation failed": ["平台 Embedding 自动配置失败，请检查服务日志或联系平台管理员。", "Platform Embedding activation failed"],
        "Platform Embedding is already deployed; redeploy the platform to change the unified Embedding model": ["平台统一 Embedding 已部署；如需更换模型，请通过重新部署完成变更。", "Platform Embedding is already deployed; redeploy the platform to change the unified Embedding model"],
        UNKNOWN_PLATFORM_COMMAND: ["未知的平台命令。输入 /platform HELP 查看当前可用命令。", "Unknown platform command. Enter /platform HELP to list usable commands."],
        COMMAND_PARAMETER_REQUIRED: ["命令缺少必填参数。请查看命令帮助中的格式说明。", "A required command parameter is missing. Check the syntax in command help."],
        COMMAND_REASON_REQUIRED: ["命令原因至少需要三个字符。", "The command reason must contain at least three characters."],
        COMMAND_EXECUTOR_UNAVAILABLE: ["该命令的执行器当前不可用。", "The command executor is unavailable."],
      };
      const pair = localized[String(message)];
      if (pair) message = pair[lang === "en" ? 1 : 0];
      else if (String(message).startsWith("LLM_PROFILE_IN_USE:")) {
        const labels: Record<string, [string, string]> = {
          PORTAL_DEFAULT: ["Portal 默认模型", "Portal default model"],
          PORTAL_ALLOWLIST: ["Portal 可用模型列表", "Portal allowlist"],
          ACTIVE_NATIVE_AGENT: ["活动的平台原生智能体", "active platform-native Agent"],
          PENDING_AGENT_REQUEST: ["待处理的业务智能体申请", "pending Business Agent request"],
        };
        const blockers = String(message).split(":", 2)[1].split(",").map((item) => {
          const label = labels[item];
          return label ? label[lang === "en" ? 1 : 0] : item;
        });
        message = lang === "en"
          ? `The LLM profile is still in use by ${blockers.join(", ")}. Remove or replace those references before retiring it.`
          : `该 LLM 配置仍被${blockers.join("、")}使用。请先解除或替换这些引用，再执行移除。`;
      }
      else if (String(message).startsWith("COMMAND_PARAMETER_REQUIRED:")) {
        const field = String(message).split(":", 2)[1];
        message = lang === "zh" ? `命令缺少必填参数：${field}。` : `The command is missing required parameter: ${field}.`;
      }
      else if (lang === "zh") {
        message = response.status === 422
          ? "请求内容不符合要求，请检查必填项和格式。"
          : "操作未完成，请检查填写内容、当前权限和服务状态。";
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
  const [authMode, setAuthMode] = useState<"login" | "register">(
    () => (window.location.pathname === "/register" ? "register" : "login"),
  );
  const [authSetup, setAuthSetup] = useState<Row | null>(null);
  const [requesting, setRequesting] = useState(false);
  const [releaseVersion, setReleaseVersion] = useState("");

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(""), 4800);
    return () => window.clearTimeout(timer);
  }, [notice]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("cxTheme", theme);
  }, [theme]);
  useEffect(() => {
    document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
    localStorage.setItem("cxLang", lang);
  }, [lang]);
  useEffect(() => {
    api<Row>("/api/health")
      .then((value) => setReleaseVersion(String(value.version || "")))
      .catch(() => setReleaseVersion(""));
    setLoading(true);
    Promise.all([api<Row>("/api/auth/me"), api<Row>("/api/capabilities")])
      .then(([value, capabilityValue]) => {
        if (value.mfa_setup_required) {
          setAuthSetup(value);
          setMe(null);
          setCapabilities(null);
          return;
        }
        setAuthSetup(null);
        setMe(value);
        setCapabilities(capabilityValue);
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
  const refreshCapabilities = async () => {
    const value = await api<Row>("/api/capabilities");
    setCapabilities(value);
    const pages = new Set<string>(value.pages || []);
    if (!pages.has(page)) {
      const fallback = nav.find((item) => pages.has(item[0]))?.[0] || "agents";
      window.history.replaceState({}, "", `/app/${fallback}`);
      setPage(fallback);
    }
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
        theme={theme}
        releaseVersion={releaseVersion}
        mode={authMode}
        onModeChange={setAuthMode}
        onLang={() => setLang(lang === "zh" ? "en" : "zh")}
        onTheme={() => setTheme(theme === "light" ? "dark" : "light")}
        onLogin={(value) => {
          if (value.csrf_token)
            localStorage.setItem("cxDashboardCsrf", value.csrf_token);
          // A login can happen in a tab that still runs the bundle loaded
          // before a controlled upgrade. Reload at the session boundary so
          // the no-store shell resolves the current hashed UI assets.
          window.location.reload();
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
            localStorage.removeItem("cxDashboardCsrf");
            setMe(null);
          }
        }}
        requesting={requesting}
        text={text}
      />
      {notice && (
        <div className="cx-notice" role="status" aria-live="polite">
          <span>{notice}</span>
          <button
            aria-label={text("关闭", "Close")}
            onClick={() => setNotice("")}
          >
            <X size={15} />
          </button>
        </div>
      )}
      <main className="cx-main">
        <PageErrorBoundary lang={lang} text={text}>
          <PageView
            key={page}
            page={allowedPages.has(page) ? page : (nav.find((item) => allowedPages.has(item[0]))?.[0] || "agents")}
            lang={lang}
            me={me}
            capabilities={capabilities}
            text={text}
            onNotice={setNotice}
            onCapabilitiesChanged={refreshCapabilities}
          />
        </PageErrorBoundary>
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
  requesting,
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
  requesting: boolean;
  text: (zh: string, en: string) => string;
}) {
  const [deadline, setDeadline] = useState(expiresAt || "");
  const parseExpiry = (value: string) => {
    const raw = String(value || "").trim();
    if (!raw) return 0;
    // Older deployments returned a database-local naive timestamp. Treat it
    // as local time for compatibility; new responses include an offset.
    const hasTimezone = /[zZ]|[+-]\d\d:\d\d$/.test(raw);
    const browserValue = hasTimezone ? raw : raw.replace(" ", "T");
    const parsed = new Date(browserValue).getTime();
    return Number.isFinite(parsed) ? parsed : 0;
  };
  const secondsUntilExpiry = (value = deadline) => {
    return Math.max(
      0,
      Math.ceil((parseExpiry(value) - Date.now()) / 1000),
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
        <span
          className={`cx-sync-indicator ${requesting ? "active" : ""}`}
          title={requesting ? text("正在同步数据", "Syncing data") : text("数据已同步", "Data synchronized")}
          aria-label={requesting ? text("正在同步数据", "Syncing data") : text("数据已同步", "Data synchronized")}
        >
          <RefreshCw className={requesting ? "spin" : ""} size={15} />
        </span>
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
  theme,
  releaseVersion,
  mode,
  onModeChange,
  onLang,
  onTheme,
  onLogin,
  onNotice,
  notice,
}: {
  initialSetup: Row | null;
  lang: Lang;
  theme: Theme;
  releaseVersion: string;
  mode: "login" | "register";
  onModeChange: (mode: "login" | "register") => void;
  onLang: () => void;
  onTheme: () => void;
  onLogin: (value: Row) => void;
  onNotice: (value: string) => void;
  notice: string;
}) {
  const text = (zh: string, en: string) => tx(lang, zh, en);
  const [busy, setBusy] = useState(false);
  const [setup, setSetup] = useState<Row | null>(initialSetup);
  const [registrationPolicy, setRegistrationPolicy] = useState<Row | null>(null);
  const registrationPage = window.location.pathname === "/register";
  useEffect(() => setSetup(initialSetup), [initialSetup]);
  useEffect(() => {
    if (mode !== "register") return;
    api<Row>("/api/auth/registration-policy")
      .then(setRegistrationPolicy)
      .catch((error) => onNotice(error instanceof Error ? error.message : text("注册策略读取失败", "Unable to read registration policy")));
  }, [mode]);
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const formElement = event.currentTarget;
    setBusy(true);
    onNotice("");
    const data = Object.fromEntries(
      new FormData(formElement).entries(),
    );
    try {
      if (mode === "login") {
        const value = await api<Row>("/api/auth/login", {
          method: "POST",
          body: JSON.stringify(data),
        });
        if (value.mfa_setup_required) {
          if (value.csrf_token)
            localStorage.setItem("cxDashboardCsrf", value.csrf_token);
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
        formElement.reset();
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
  const fields = registrationPolicy?.fields || {};
  const fieldVisible = (key: string) => !registrationPolicy || fields[key]?.visible !== false && fields[key]?.field_state !== "DISABLED";
  const fieldRequired = (key: string) => fields[key]?.field_state === "REQUIRED";
  const tokenRequired = Boolean(registrationPolicy?.token_required);
  return (
    <div className={`cx-auth-page${registrationPage ? " registration-page" : ""}`}>
      <div className="cx-auth-panel">
        <div className="cx-auth-controls">
          <button className="icon-button" type="button" onClick={onTheme} title={text("切换亮暗色", "Toggle theme")} aria-label={text("切换亮暗色", "Toggle theme")}>
            {theme === "light" ? <Moon size={17} /> : <Sun size={17} />}
          </button>
          <button className="language-button" type="button" onClick={onLang} title={text("切换语言", "Switch language")} aria-label={text("切换语言", "Switch language")}>
            {lang === "zh" ? "EN" : "中"}
          </button>
        </div>
        <div className="cx-auth-mark">
          <img src="/static/brand/chuanxu-mark.svg" alt="" />
          <div>
            <strong>川序</strong>
            <span>
              {text("AI Agent 管理平台", "AI Agent Management Platform")}
            </span>
          </div>
        </div>
        <div className="cx-auth-title">
          <h1>{registrationPage ? text("注册平台账户", "Register platform account") : text("登录管理平台", "Sign in to Dashboard")}</h1>
          <p>{registrationPage ? text("注册信息将按企业策略校验并进入审批流程。", "Registration is validated by enterprise policy and enters approval.") : text("使用获准的平台账户进入 Dashboard。", "Use an approved platform account to enter the Dashboard.")}</p>
        </div>
        <form onSubmit={submit} className="cx-form">
          {mode === "register" && fieldVisible("display_name") && (
            <label>
              {text("姓名", "Full name")}{fieldRequired("display_name") ? " *" : ""}
              <input
                name="display_name"
                autoComplete="name"
                required={fieldRequired("display_name") || !registrationPolicy}
                maxLength={256}
              />
            </label>
          )}
          {mode === "register" && fieldVisible("mobile") && (
            <label>
              {text("手机号（按策略填写）", "Mobile (according to policy)")}{fieldRequired("mobile") ? " *" : ""}
              <input name="mobile" autoComplete="tel" maxLength={64} required={fieldRequired("mobile")} />
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
              {text("注册令牌（如已启用）", "Registration token (when enabled)")}{tokenRequired ? " *" : ""}
              <input name="registration_token" autoComplete="one-time-code" maxLength={512} required={tokenRequired} />
            </label>
          )}
          {mode === "register" && fieldVisible("email") && (
            <label>
              {text("邮箱（按策略填写）", "Email (according to policy)")}{fieldRequired("email") ? " *" : ""}
              <input name="email" type="email" autoComplete="email" required={fieldRequired("email")} />
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
        {registrationPage ? (
          <div className="cx-auth-return-actions">
            <a className="secondary-button" href="/portal/login">{text("返回 Portal 登录", "Back to Portal login")}</a>
            <a className="secondary-button" href="/app">{text("返回 Dashboard 登录", "Back to Dashboard login")}</a>
          </div>
        ) : (
          <a className="cx-auth-register-link" href="/register?entry=dashboard">{text("注册新账户", "Register a new account")}</a>
        )}
        <p className="cx-auth-foot">
          {text(
            "身份、上下文、执行和审计边界由数据库持久化。",
            "Database-backed identity, context, execution, and audit boundaries.",
          )}
          {releaseVersion && <span>{text("版本", "Version")} v{releaseVersion}</span>}
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

class PageErrorBoundary extends React.Component<{
  lang: Lang;
  text: (zh: string, en: string) => string;
  children: React.ReactNode;
}, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  render() {
    if (!this.state.error) return this.props.children;
    const { text } = this.props;
    return <div className="page-stack"><InfoPanel title={text("页面加载失败", "Page rendering failed")} text={text}><p className="cx-form-hint">{text("页面组件发生异常。请记录下面的错误信息并刷新页面。", "A page component failed while rendering. Record the error below and refresh the page.")}</p><pre className="error-detail">{this.state.error.message}</pre></InfoPanel></div>;
  }
}

function PageView({
  page,
  lang,
  me,
  capabilities,
  text,
  onNotice,
  onCapabilitiesChanged,
}: {
  page: string;
  lang: Lang;
  me: Row;
  capabilities: Row | null;
  text: (zh: string, en: string) => string;
  onNotice: (value: string) => void;
  onCapabilitiesChanged: () => Promise<void>;
}) {
  if (page === "platform" || page === "platform-operations" || page === "deployment")
    return <PlatformConfigurationPage lang={lang} capabilities={capabilities} text={text} onNotice={onNotice} onCapabilitiesChanged={onCapabilitiesChanged} initialSection={page === "platform-operations" ? "operations" : page === "deployment" ? "deployment" : undefined} />;
  if (page === "native-agents")
    return <AgentsPage lang={lang} me={me} capabilities={capabilities} text={text} onNotice={onNotice} initialView="native" />;
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
  if (page === "security-domains")
    return (
      <SecurityDomainsPage
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
        me={me}
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
  if (page === "memory")
    return <MemoryLifecyclePage lang={lang} text={text} onNotice={onNotice} />;
  if (page === "specs")
    return <SddWorkbench lang={lang} text={text} onNotice={onNotice} />;
  if (page === "graph")
    return <Suspense fallback={<PageLoading text={text} />}><GraphRoutePage lang={lang} text={text} onNotice={onNotice} /></Suspense>;
  if (page === "approvals")
    return (
      <ApprovalsPage
        lang={lang}
        capabilities={capabilities}
        text={text}
        onNotice={onNotice}
      />
    );
  if (page === "compliance")
    return <CompliancePage lang={lang} capabilities={capabilities} text={text} onNotice={onNotice} />;
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

function PlatformConfigurationPage({
  lang, capabilities, text, onNotice, onCapabilitiesChanged, initialSection,
}: {
  lang: Lang;
  capabilities: Row | null;
  text: (zh: string, en: string) => string;
  onNotice: (value: string) => void;
  onCapabilitiesChanged: () => Promise<void>;
  initialSection?: "capabilities" | "deployment" | "operations";
}) {
  type CapabilitySection = "capabilities" | "graph" | "registration" | "session";
  const capabilitySections: Array<[CapabilitySection, string, string]> = [
    ["capabilities", "功能开关", "Feature switches"],
    ["graph", "图工程配置", "Graph Engineering"],
    ["registration", "外部智能体注册", "External Agent registration"],
    ["session", "会话策略", "Session policies"],
  ];
  type OperationSection = "overview" | "llm-providers" | "admin-management" | "admission" | "agent-pool" | "upgrade" | "containment";
  const operationSections: Array<[OperationSection, string, string]> = [
    ["overview", "运行概览", "Runtime overview"],
    ["llm-providers", "LLM 服务商配置", "LLM Provider Profiles"],
    ["admin-management", "Admin Agent 管理", "Admin Agent management"],
    ["admission", "Admin Agent 接入", "Admin Agent admission"],
    ["agent-pool", "Agent Pool 配置", "Agent Pool configuration"],
    ["upgrade", "升级与 Skill 分发", "Upgrade & Skill distribution"],
    ["containment", "紧急阻断", "Emergency containment"],
  ];
  const platformTabKeys = ["capabilities", "operations", "deployment"] as const;
  const [section, setSection] = useUrlState(
    "config",
    platformTabKeys,
    initialSection || "capabilities",
  );
  const [capabilitySection, setCapabilitySection] = useUrlState(
    "section",
    capabilitySections.map(([key]) => key) as CapabilitySection[],
    "capabilities",
  );
  const [operationSection, setOperationSection] = useUrlState(
    "tab",
    operationSections.map(([key]) => key) as OperationSection[],
    "overview",
  );
  const selectSection = (value: "capabilities" | "deployment" | "operations") => {
    setSection(value);
    const url = new URL(window.location.href);
    url.searchParams.delete("section");
    window.history.replaceState({}, "", url.pathname + url.search);
  };
  return <section className="page-stack platform-configuration-shell">
    <SectionHeading title={text("平台配置", "Platform configuration")} subtitle={text("统一管理平台能力开关、运行节点、共享存储、模型策略、会话和平台管理操作。", "Manage capability switches, runtime nodes, shared storage, model policies, sessions, and platform-management operations in one configuration area.")} text={text} />
    <div className="platform-config-nav-row">
      <div className="view-toggle platform-config-root-tabs" role="tablist" aria-label={text("平台配置分区", "Platform configuration sections")}>
        <button type="button" role="tab" aria-selected={section === "capabilities"} className={section === "capabilities" ? "active" : ""} onClick={() => selectSection("capabilities")}>{text("能力与策略", "Capabilities & policies")}</button>
        <button type="button" role="tab" aria-selected={section === "operations"} className={section === "operations" ? "active" : ""} onClick={() => selectSection("operations")}>{text("平台运行", "Platform operations")}</button>
        <button type="button" role="tab" aria-selected={section === "deployment"} className={section === "deployment" ? "active" : ""} onClick={() => selectSection("deployment")}>{text("模型与部署", "Models & deployment")}</button>
      </div>
      {section === "capabilities" && <div className="platform-config-secondary-tabs view-toggle" role="tablist" aria-label={text("功能配置分区", "Capability configuration sections")}>
        <span className="platform-config-level-separator" aria-hidden="true" />
        {capabilitySections.map(([key, zh, en]) => <button type="button" role="tab" aria-selected={capabilitySection === key} className={capabilitySection === key ? "active" : ""} key={key} onClick={() => setCapabilitySection(key)}>{text(zh, en)}</button>)}
      </div>}
      {section === "operations" && <div className="platform-config-secondary-tabs view-toggle" role="tablist" aria-label={text("平台运行子页面", "Platform operation subsections")}>
        <span className="platform-config-level-separator" aria-hidden="true" />
        {operationSections.map(([key, zh, en]) => <button type="button" role="tab" aria-selected={operationSection === key} className={operationSection === key ? "active" : ""} key={key} onClick={() => setOperationSection(key)}>{text(zh, en)}</button>)}
      </div>}
    </div>
    {section === "capabilities" && <PlatformCapabilitiesPage lang={lang} text={text} onNotice={onNotice} onCapabilitiesChanged={onCapabilitiesChanged} activeTab={capabilitySection} embedded />}
    {section === "deployment" && <DeploymentModelsPage lang={lang} capabilities={capabilities} text={text} onNotice={onNotice} embedded />}
    {section === "operations" && <PlatformOperationsPage lang={lang} capabilities={capabilities} text={text} onNotice={onNotice} activeTab={operationSection} embedded />}
  </section>;
}

function PlatformCapabilitiesPage({
  lang,
  text,
  onNotice,
  onCapabilitiesChanged,
  activeTab,
  embedded,
}: {
  lang: Lang;
  text: (zh: string, en: string) => string;
  onNotice: (value: string) => void;
  onCapabilitiesChanged: () => Promise<void>;
  activeTab: "capabilities" | "graph" | "registration" | "session";
  embedded?: boolean;
}) {
  const [payload, setPayload] = useState<Row>({ items: [], history: [] });
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Row | null>(null);
  const [reason, setReason] = useState("");
  const [graphSelected, setGraphSelected] = useState<Row | null>(null);
  const [graphState, setGraphState] = useState("");
  const [graphReason, setGraphReason] = useState("");
  const [graphEvidence, setGraphEvidence] = useState("");
  const [busy, setBusy] = useState(false);
  const [policies, setPolicies] = useState<Row>({});
  const [graphMatrix, setGraphMatrix] = useState<Row>({ items: [] });
  const load = async () => {
    setLoading(true);
    try {
      const [capabilities, sessionPolicies, graphState] = await Promise.all([
        api<Row>("/api/platform/capabilities?limit=50"),
        api<Row>("/api/platform/session-policies"),
        api<Row>("/api/platform/graph-capabilities"),
      ]);
      setPayload(capabilities);
      setPolicies(sessionPolicies);
      setGraphMatrix(graphState);
    } catch (error) {
      onNotice((error as Error).message);
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { void load(); }, []);
  const items = listPayload(payload, ["items"]);
  const groups: [string, Row[]][] = [
    [text("系统保护能力", "Protected system capabilities"), items.filter((item) => item.mandatory)],
    [text("可配置能力", "Configurable capabilities"), items.filter((item) => !item.mandatory && item.edition_available)],
    [text("当前版本不可用", "Unavailable in this edition"), items.filter((item) => !item.edition_available)],
  ];
  const submit = async () => {
    if (!selected || reason.trim().length < 3) {
      onNotice(text("请输入至少 3 个字符的变更原因", "Enter a change reason of at least 3 characters"));
      return;
    }
    setBusy(true);
    try {
      await api(`/api/platform/capabilities/${encodeURIComponent(String(selected.capability_key))}`, {
        method: "PUT",
        body: JSON.stringify({
          enabled: !selected.effective_enabled,
          expected_version: Number(selected.version),
          reason: reason.trim(),
        }),
      });
      setSelected(null);
      setReason("");
      await Promise.all([load(), onCapabilitiesChanged()]);
      onNotice(text("功能状态已写入数据库并记录审计", "Capability state was committed and audited"));
    } catch (error) {
      onNotice((error as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const updatePolicy = async (kind: "dashboard" | "portal", form: HTMLFormElement) => {
    const data = new FormData(form);
    const current = policies[kind] || {};
    setBusy(true);
    try {
      await api(`/api/platform/session-policies/${kind}`, { method: "PUT", body: JSON.stringify({
        idle_timeout_seconds: Number(data.get("idle_timeout_seconds")),
        absolute_timeout_seconds: Number(data.get("absolute_timeout_seconds")),
        expected_version: Number(current.version || 1), reason: String(data.get("reason") || ""),
      }) });
      await load();
      onNotice(text("会话策略已更新；现有会话将在下一次请求按更严格策略校验。", "Session policy updated; active sessions are checked against a stricter policy on their next request."));
    } catch (error) { onNotice((error as Error).message); } finally { setBusy(false); }
  };
  const updateGraphCapability = async () => {
    if (!graphSelected || graphReason.trim().length < 3) {
      onNotice(text("请输入至少 3 个字符的变更原因", "Enter a change reason of at least 3 characters"));
      return;
    }
    const target = graphState.toUpperCase();
    if (["ENABLED", "CONTROLLED"].includes(target) && graphEvidence.trim().length < 3) {
      onNotice(text("启用或受控启用时必须填写证据引用", "An evidence reference is required when enabling or controlling a capability"));
      return;
    }
    setBusy(true);
    try {
      await api(`/api/platform/graph-capabilities/${encodeURIComponent(String(graphSelected.capability_key))}`, {
        method: "PUT", body: JSON.stringify({ state: target, expected_version: Number(graphSelected.version), reason: graphReason.trim(), evidence_ref: graphEvidence.trim() }),
      });
      setGraphSelected(null); setGraphReason(""); setGraphEvidence(""); await load();
      onNotice(text("图工程能力状态已更新并记录审计", "Graph Engineering capability state was updated and audited"));
    } catch (error) { onNotice((error as Error).message); } finally { setBusy(false); }
  };
  return <>
    {!embedded && <SectionHeading title={text("功能配置", "Capability configuration")} subtitle={text("以数据库为权威来源控制当前实例开放的产品能力；身份、安全、授权与审计边界不可关闭。", "Control product capabilities for this installation from the authoritative database; identity, security, authorization, and audit boundaries cannot be disabled.")} text={text} actions={<PageRefresh loading={loading} onRefresh={load} text={text} />} />}
    {loading ? <PageLoading text={text} /> : activeTab === "capabilities" && groups.map(([title, rows]) => rows.length > 0 && <InfoPanel key={title} title={title} text={text}><div className="capability-list">{rows.map((item) => {
      const blocked = Boolean(item.mandatory) || !item.edition_available;
      return <div className="capability-row" key={String(item.capability_key)}>
        <div><strong>{lang === "zh" ? item.display_name_zh : item.display_name_en}</strong><small>{String(item.capability_key)} · v{String(item.version)}</small></div>
        <div className="capability-dependencies">{item.dependencies?.length ? `${text("依赖", "Depends on")}: ${item.dependencies.join(", ")}` : text("无功能依赖", "No capability dependencies")}</div>
        <button type="button" role="switch" aria-checked={Boolean(item.effective_enabled)} className={`capability-switch ${item.effective_enabled ? "active" : ""}`} disabled={blocked} onClick={() => { setSelected(item); setReason(""); }} title={blocked ? text("系统保护或当前版本不可用", "Protected by the system or unavailable in this edition") : text("变更功能状态", "Change capability state")}><span /><b>{item.effective_enabled ? text("开启", "On") : text("关闭", "Off")}</b></button>
      </div>;
    })}</div></InfoPanel>)}
    {!loading && activeTab === "graph" && <InfoPanel title={text("图工程生产基线", "Graph Engineering Production baseline")} text={text} protectedView>
      <div className="profile-status"><div><span>{text("当前运行档案", "Current runtime profile")}</span><strong>{text("生产", "Production")}</strong></div><span className="tag">Production</span></div>
      <p className="cx-form-hint">{text("运行档案固定为 Production，不提供实验档案切换。以下能力可在生产治理边界内受控调整：变更必须填写原因；启用或受控启用时必须提供证据引用；核心能力和依赖由数据库服务端强制校验。", "The runtime profile is fixed to Production and has no experimental-profile switch. The capabilities below can be adjusted inside governed Production boundaries: every change requires a reason, enablement or controlled enablement requires evidence, and the database enforces core and dependency checks.")}</p>
      <DataTable headers={[text("能力", "Capability"), text("状态", "State"), text("版本", "Version"), text("原因", "Reason"), text("操作", "Action")]} rows={listPayload(graphMatrix, ["items"]).map((item) => { const mandatory = String(item.mandatory || "N").toUpperCase() === "Y"; return [lang === "zh" ? item.display_name_zh : item.display_name_en, displayRowValue(lang, item.state), item.version, item.reason || "-", <button type="button" className="small-button" disabled={busy || mandatory} onClick={() => { setGraphSelected(item); setGraphState(String(item.state || "CONTROLLED").toUpperCase()); setGraphReason(""); setGraphEvidence(""); }}>{mandatory ? text("核心能力", "Core capability") : text("调整", "Adjust")}</button>]; })} empty={text("Graph Production Profile 不可用", "Graph Production Profile unavailable")} text={text} />
    </InfoPanel>}
    {!loading && activeTab === "registration" && <ExternalRegistrationPolicyPanel lang={lang} text={text} onNotice={onNotice} />}
    {!loading && activeTab === "session" && <InfoPanel title={text("会话策略", "Session policies")} text={text}><p className="cx-form-hint">{text("Dashboard 与 Portal 分别配置。空闲超时默认 5 分钟；绝对会话时长限制单次登录的最长存续时间。", "Dashboard and Portal are configured independently. Idle timeout defaults to five minutes; absolute lifetime caps one login session.")}</p><div className="two-column-panels">{(["dashboard", "portal"] as const).map((kind) => <form key={kind} className="compact-form" onSubmit={(event) => { event.preventDefault(); void updatePolicy(kind, event.currentTarget); }}><strong>{kind === "dashboard" ? "Dashboard" : "Portal"}</strong><label>{text("空闲秒数", "Idle seconds")}<input name="idle_timeout_seconds" type="number" min="60" max="86400" defaultValue={String(policies[kind]?.idle_timeout_seconds || 300)} /></label><label>{text("绝对秒数", "Absolute seconds")}<input name="absolute_timeout_seconds" type="number" min="60" max="86400" defaultValue={String(policies[kind]?.absolute_timeout_seconds || 28800)} /></label><label>{text("变更原因", "Change reason")}<input name="reason" required /></label><button className="small-button" disabled={busy}><Check size={14} />{text("保存策略", "Save policy")}</button></form>)}</div></InfoPanel>}
    {activeTab === "capabilities" && <><InfoPanel title={text("最近变更", "Recent changes")} text={text}><DataTable headers={[text("功能", "Capability"), text("变更", "Change"), text("操作人", "Actor"), text("原因", "Reason"), text("时间", "Time")]} rows={listPayload(payload, ["history"]).map((item) => [item.capability_key, `${item.from_enabled} -> ${item.to_enabled}`, item.changed_by, item.reason, displayRowValue(lang, item.created_at)])} empty={text("暂无功能状态变更", "No capability changes yet")} text={text} /></InfoPanel>
    <DetailDrawer open={Boolean(selected)} title={text("确认功能状态变更", "Confirm capability change")} onClose={() => { if (!busy) setSelected(null); }} text={text}>
      {selected && <div className="capability-confirm"><p>{text("目标功能", "Capability")}: <strong>{lang === "zh" ? selected.display_name_zh : selected.display_name_en}</strong></p><p>{text("目标状态", "Target state")}: <strong>{selected.effective_enabled ? text("关闭", "Off") : text("开启", "On")}</strong></p><label>{text("变更原因（必填）", "Change reason (required)")}<textarea value={reason} maxLength={2000} onChange={(event) => setReason(event.target.value)} /></label><button className="primary-button" disabled={busy || reason.trim().length < 3} onClick={() => void submit()}><Check size={15} />{text("确认变更", "Confirm change")}</button></div>}
    </DetailDrawer></>}
    <DetailDrawer open={Boolean(graphSelected)} title={text("调整图工程能力", "Adjust Graph Engineering capability")} onClose={() => { if (!busy) setGraphSelected(null); }} text={text}>
      {graphSelected && <div className="capability-confirm"><p>{text("能力", "Capability")}: <strong>{lang === "zh" ? graphSelected.display_name_zh : graphSelected.display_name_en}</strong></p><p className="cx-form-hint">{text("当前状态", "Current state")}: {displayRowValue(lang, graphSelected.state)} · {text("版本", "Version")}: {graphSelected.version}</p><label>{text("目标状态", "Target state")}<select value={graphState} onChange={(event) => setGraphState(event.target.value)}><option value="ENABLED">{text("启用", "Enabled")}</option><option value="CONTROLLED">{text("受控启用", "Controlled")}</option><option value="DISABLED">{text("关闭", "Disabled")}</option><option value="UNAVAILABLE">{text("不可用", "Unavailable")}</option></select></label><label>{text("变更原因（必填）", "Change reason (required)")}<textarea value={graphReason} maxLength={2000} onChange={(event) => setGraphReason(event.target.value)} /></label>{["ENABLED", "CONTROLLED"].includes(graphState.toUpperCase()) && <label>{text("证据引用（必填）", "Evidence reference (required)")}<input value={graphEvidence} maxLength={256} onChange={(event) => setGraphEvidence(event.target.value)} /></label>}<button className="primary-button" disabled={busy || graphReason.trim().length < 3 || (["ENABLED", "CONTROLLED"].includes(graphState.toUpperCase()) && graphEvidence.trim().length < 3)} onClick={() => void updateGraphCapability()}><Check size={15} />{text("确认受控变更", "Confirm governed change")}</button></div>}
    </DetailDrawer>
  </>;
}

function PlatformPoolGovernancePanelLegacy({
  lang, text, onNotice,
}: { lang: Lang; text: (zh: string, en: string) => string; onNotice: (value: string) => void }) {
  const [data, setData] = useState<Row>({ policy: {}, allowed_profile_ids: [], profiles: [], nodes: [], storage: [], bindings: [], endpoints: [], enhancements: [] });
  const [busy, setBusy] = useState(false);
  const [reason, setReason] = useState("");
  const load = async () => {
    try {
      const [policy, nodes, storage, bindings, endpoints, enhancements] = await Promise.all([
        api<Row>("/api/platform/portal-llm-policy"), api<Row>("/api/platform/managed-nodes"),
        api<Row>("/api/platform/shared-storage"), api<Row>("/api/platform/node-storage-bindings"), api<Row>("/api/platform/external-db-endpoints"),
        api<Row>("/api/platform/portal-enhancements"),
      ]);
      setData({ policy, nodes: listPayload(nodes, ["items"]), storage: listPayload(storage, ["items"]), bindings: listPayload(bindings, ["items"]), endpoints: listPayload(endpoints, ["items"]), enhancements: listPayload(enhancements, ["items"]) });
    } catch (error) { onNotice((error as Error).message); }
  };
  useEffect(() => { void load(); }, []);
  const policy = data.policy || {};
  const profiles: Row[] = policy.profiles || [];
  const allowed = new Set<string>(policy.allowed_profile_ids || []);
  const rolesOf = (item: Row): string[] => {
    if (Array.isArray(item.role_json)) return item.role_json.map(String).map((value) => value.toUpperCase());
    try { return JSON.parse(String(item.role_json || "[]")).map((value: unknown) => String(value).toUpperCase()); } catch { return []; }
  };
  const nodesFor = (role: string) => (data.nodes || []).filter((item: Row) => rolesOf(item).includes(role));
  const storageFor = (purpose: string) => (data.storage || []).filter((item: Row) => String(item.storage_purpose || "ADMIN_RUNTIME").toUpperCase() === purpose);
  const savePolicy = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const selected = profiles.filter((item) => form.get(`profile_${item.profile_id}`) === "on").map((item) => String(item.profile_id));
    const defaultId = String(form.get("default_profile_id") || "");
    setBusy(true);
    try { await api("/api/platform/portal-llm-policy", { method: "PUT", body: JSON.stringify({ default_profile_id: defaultId, allowed_profile_ids: selected, expected_version: Number(policy.policy?.version || 1), reason: String(form.get("reason") || "") }) }); await load(); onNotice(text("Portal Agent Pool LLM 策略已保存", "Portal Agent Pool LLM policy saved")); }
    catch (error) { onNotice((error as Error).message); } finally { setBusy(false); }
  };
  const post = async (url: string, form: HTMLFormElement, message: string) => { const values: Row = Object.fromEntries(new FormData(form).entries()); if (typeof values.roles === "string") values.roles = values.roles.split(",").map((item: string) => item.trim()).filter(Boolean); if ("tls_required" in values) values.tls_required = values.tls_required === "on"; setBusy(true); try { await api(url, { method: "POST", body: JSON.stringify(values) }); form.reset(); await load(); onNotice(message); } catch (error) { onNotice((error as Error).message); } finally { setBusy(false); } };
  const validateResource = async (kind: "node" | "storage", id: string) => { setBusy(true); try { const result = await api<Row>(`/api/platform/${kind === "node" ? "managed-nodes" : "shared-storage"}/${encodeURIComponent(id)}/validate`, { method: "POST", body: "{}" }); await load(); onNotice(`${text("验证结果", "Validation result")}: ${displayRowValue(lang, result.validation_state)} · ${result.detail || ""}`); } catch (error) { onNotice((error as Error).message); } finally { setBusy(false); } };
  const retireResource = async (kind: "node", id: string, label: string) => { const reason = window.prompt(text(`请输入移除“${label}”的原因（至少三个字符）`, `Enter a reason to retire “${label}” (at least 3 characters)`), ""); if (!reason || reason.trim().length < 3) return; setBusy(true); try { await api(`/api/platform/managed-nodes/${encodeURIComponent(id)}`, { method: "DELETE", body: JSON.stringify({ reason: reason.trim() }) }); await load(); onNotice(text("受管节点已归档，历史记录已保留", "Managed node retired; history was retained")); } catch (error) { onNotice((error as Error).message); } finally { setBusy(false); } };
  return <div className="agent-pool-page"><InfoPanel title={text("Agent Pool 配置", "Agent Pool configuration")} text={text}>
    <p className="cx-form-hint">{text("统一管理 Portal 可用模型、Admin/合规/Pool 节点、共享目录和外部注册 Agent 的数据库地址。这里不保存可复用 SSH 密码，也不向 Agent 返回数据库密钥。", "Govern Portal models, Admin/Compliance/Pool nodes, shared storage, and database endpoints for external Agents. Reusable SSH passwords and database keys are never stored or returned to Agents.")}</p>
    <form className="pool-config-block pool-llm-policy-form" onSubmit={(event) => void savePolicy(event)}><strong>{text("Portal Agent Pool LLM 允许列表", "Portal Agent Pool LLM allowlist")}</strong><p className="cx-form-hint">{text("Portal 用户只能在下方勾选的健康配置中切换。默认配置必须包含在允许列表中。", "Portal users can switch only among checked healthy profiles. The default must be allowlisted.")}</p><div className="pool-llm-allowlist">{profiles.length ? profiles.map((item) => <label className="checkbox-field" key={String(item.profile_id)}><input type="checkbox" name={`profile_${item.profile_id}`} defaultChecked={allowed.has(String(item.profile_id))} />{String(item.profile_key)} · {String(item.model_id)} · {String(item.health_state || "UNKNOWN")}</label>) : <p className="cx-form-hint">{text("请先在部署与模型中配置并测试 LLM。", "Configure and test an LLM in Deployment & models first.")}</p>}</div><div className="pool-policy-fields"><ConfigField label={text("默认 LLM", "Default LLM")} hint={text("只能选择已允许且健康的配置。", "Choose an allowlisted healthy profile.")}><select name="default_profile_id" defaultValue={String(policy.policy?.default_profile_id || "")} required><option value="">{text("请选择", "Select")}</option>{profiles.map((item) => <option key={String(item.profile_id)} value={String(item.profile_id)}>{String(item.profile_key)}</option>)}</select></ConfigField><ConfigField label={text("变更原因", "Change reason")} hint={text("写入审计，至少三个字符。", "Audited; at least three characters.")}><input name="reason" required /></ConfigField><ConfigField label={text("操作", "Action")} hint={text("保存后立即应用到 Portal Agent Pool。", "Applied to the Portal Agent Pool after saving.")} action><button className="small-button" disabled={busy}><Check size={14} />{text("保存 Portal 模型策略", "Save Portal model policy")}</button></ConfigField></div></form>
    <div className="pool-config-stack"><form className="compact-form pool-config-block" onSubmit={(event) => { event.preventDefault(); void post("/api/platform/managed-nodes", event.currentTarget, text("受管节点已登记", "Managed node registered")); }}><strong>{text("受管节点", "Managed node")}</strong><p className="cx-form-hint">{text("登记用于运行 Admin Agent、合规 Agent 或 Agent Pool 的操作系统节点。", "Register an operating-system node for Admin Agent, Compliance Agent, or Agent Pool workloads.")}</p><input name="node_key" placeholder={text("节点名称", "Node name")} required /><input name="host_reference" placeholder={text("主机或 IP", "Host or IP")} required /><input name="os_user" placeholder={text("操作系统用户", "OS user")} /><select name="trust_mode" defaultValue="MUTUAL_TRUST"><option value="MUTUAL_TRUST">{text("SSH 互信", "SSH mutual trust")}</option><option value="ONE_USE_PASSWORD">{text("一次性密码验证", "One-use password")}</option></select><input name="failure_domain" placeholder={text("故障域", "Failure domain")} /><input name="roles" placeholder="ADMIN_AGENT,AGENT_POOL" /><input name="reason" placeholder={text("登记原因", "Registration reason")} required /><button className="small-button" disabled={busy}>{text("登记节点", "Register node")}</button></form><form className="compact-form pool-config-block" onSubmit={(event) => { event.preventDefault(); void post("/api/platform/shared-storage", event.currentTarget, text("共享存储配置已登记", "Shared storage profile registered")); }}><strong>{text("共享存储", "Shared storage")}</strong><p className="cx-form-hint">{text("登记目录、挂载点、NFS、对象存储或统一存储的基础位置。", "Register a base location for a directory, mount point, NFS, object storage, or unified storage.")}</p><input name="storage_key" placeholder={text("配置名称", "Profile name")} required /><select name="backend_kind" defaultValue="LOCAL_PATH"><option value="LOCAL_PATH">{text("目录或挂载点", "Directory or mount point")}</option><option value="NFS">NFS</option><option value="OBJECT_STORAGE">{text("对象存储", "Object storage")}</option><option value="UNIFIED_STORAGE">{text("统一存储", "Unified storage")}</option></select><input name="location_ref" placeholder={text("路径或位置", "Path or location")} required /><input name="reason" placeholder={text("配置原因", "Configuration reason")} required /><button className="small-button" disabled={busy}>{text("登记存储", "Register storage")}</button></form></div>
    <div className="pool-config-stack"><form className="compact-form pool-config-block" onSubmit={(event) => { event.preventDefault(); void post("/api/platform/external-db-endpoints", event.currentTarget, text("外部数据库地址已登记", "External database endpoint registered")); }}><strong>{text("外部 Agent 数据库地址", "External Agent database endpoint")}</strong><p className="cx-form-hint">{text("填写注册授权后，只有该授权兑换出的 Agent 才能获得此地址；未绑定授权的 Agent 回退到初始化地址。", "With an enrollment grant, only the Agent redeemed from that grant can receive this endpoint; unbound Agents use the bootstrap endpoint.")}</p><input name="endpoint_key" placeholder={text("地址配置名称", "Endpoint name")} required /><input name="host_reference" placeholder={text("外网主机或 IP", "External host or IP")} required /><input name="port" type="number" placeholder={text("端口", "Port")} required /><input name="database_dialect" placeholder={text("数据库类型", "Database type")} /><input name="registration_grant_id" placeholder={text("注册授权 ID（可选）", "Registration grant ID (optional)")} /><label className="checkbox-field"><input name="tls_required" type="checkbox" defaultChecked />{text("要求 TLS", "TLS required")}</label><input name="reason" placeholder={text("配置原因", "Configuration reason")} required /><button className="small-button" disabled={busy}>{text("登记地址", "Register endpoint")}</button></form><div className="pool-config-block"><strong>{text("Portal 增强组件与模板", "Portal enhancements and templates")}</strong><DataTable headers={[text("模板", "Template"), text("类型", "Kind"), text("状态", "State")]} rows={(data.enhancements || []).map((item: Row) => [item.display_name || item.template_key, item.template_kind, item.status])} empty={text("暂无模板", "No templates")} text={text} /></div></div>
    <InfoPanel title={text("Admin Agent 运行节点共享目录绑定", "Admin Agent runtime shared-directory binding")} text={text}><p className="cx-form-hint">{text("先登记并验证节点、共享存储，再将二者绑定。共享存储登记的是统一位置，节点实际挂载路径是该节点上可访问的目录；绑定不会扩大数据库、Skill 或频道授权。生产环境可将存储配置替换为 NFS、对象存储或统一存储适配器。", "Register and validate a node and a storage profile before binding them. The storage profile is the shared logical location and the node mount path is the directory visible on that node; binding never expands database, Skill, or Channel authorization. Production deployments may replace the basic profile with NFS, object-storage, or unified-storage adapters.")}</p><form className="configuration-form compact-configuration-form node-storage-binding-form" onSubmit={(event) => { event.preventDefault(); void post("/api/platform/node-storage-bindings", event.currentTarget, text("共享目录已绑定到运行节点", "Shared directory bound to runtime node")); }}><ConfigField label={text("运行节点", "Runtime node")} hint={text("选择已登记的 Admin Agent 或平台节点。", "Choose a registered Admin Agent or platform node.")}><select name="node_id" required><option value="">{text("请选择节点", "Select node")}</option>{(data.nodes || []).map((item: Row) => <option key={String(item.node_id)} value={String(item.node_id)}>{String(item.node_key)} · {String(item.host_reference)}</option>)}</select></ConfigField><ConfigField label={text("共享存储配置", "Shared storage profile")} hint={text("选择已登记的目录、NFS 或存储配置。", "Choose a registered directory, NFS, or storage profile.")}><select name="storage_id" required><option value="">{text("请选择存储", "Select storage")}</option>{(data.storage || []).map((item: Row) => <option key={String(item.storage_id)} value={String(item.storage_id)}>{String(item.storage_key)} · {displayRowValue(lang, item.backend_kind)}</option>)}</select></ConfigField><ConfigField label={text("节点实际挂载路径", "Node mount path")} hint={text("填写该运行节点上实际可访问的目录或挂载点。共享存储登记的是统一位置，不同节点的本地路径可能不同；平台不会自动执行挂载。", "Enter the directory or mount point visible on this runtime node. The storage profile is the shared logical location; each node may expose a different local path. The platform does not mount it automatically.")}><input name="mount_reference" required /></ConfigField><ConfigField label={text("角色范围", "Role scope")} hint={text("仅决定哪些平台运行角色使用该位置，不改变数据授权。", "Determines which platform runtime role uses the location; it does not change data authorization.")}><select name="role_scope" defaultValue="ADMIN_AGENT"><option value="ADMIN_AGENT">Admin Agent</option><option value="COMPLIANCE_AGENT">{text("合规 Agent", "Compliance Agent")}</option><option value="AGENT_POOL">Agent Pool</option><option value="ALL_PLATFORM_AGENTS">{text("所有平台管理 Agent", "All platform management Agents")}</option></select></ConfigField><ConfigField label={text("绑定原因", "Binding reason")} hint={text("必填并写入审计。", "Required and audited.")}><input name="reason" required /></ConfigField><ConfigField label={text("操作", "Action")} hint={text("绑定后仍需由受管节点运行时执行实际挂载。", "The managed runtime must still perform the actual mount.")} action><button className="small-button" disabled={busy}><Check size={14} />{text("绑定目录", "Bind directory")}</button></ConfigField></form><DataTable headers={[text("节点", "Node"), text("存储", "Storage"), text("节点实际挂载路径", "Node mount path"), text("角色", "Role"), text("状态", "Status"), text("原因", "Reason")]} rows={(data.bindings || []).map((item: Row) => [item.node_key, item.storage_key, item.mount_reference, item.role_scope, displayRowValue(lang, item.status), item.reason || "-"])} empty={text("暂无节点共享目录绑定", "No node shared-directory bindings")} text={text} /></InfoPanel>
    <div className="data-summary"><strong>{text("当前登记", "Registered")}</strong> · {text("节点", "Nodes")} {data.nodes?.length || 0} · {text("存储", "Storage")} {data.storage?.length || 0} · {text("绑定", "Bindings")} {data.bindings?.length || 0} · {text("外部地址", "External endpoints")} {data.endpoints?.length || 0}</div>
    <DataTable headers={[text("节点", "Node"), text("主机", "Host"), text("角色", "Roles"), text("验证", "Validation"), text("操作", "Action")]} rows={(data.nodes || []).map((item: Row) => [item.node_key, item.host_reference, Array.isArray(item.role_json) ? item.role_json.join(", ") : String(item.role_json || "-"), displayRowValue(lang, item.validation_state), <span className="actions-row">{String(item.created_by || "").toUpperCase() === "SYSTEM_BOOTSTRAP" ? <span className="tag">{text("系统节点，不可移除", "System node; cannot retire")}</span> : <><button className="small-button" disabled={busy} onClick={() => void validateResource("node", String(item.node_id))}>{text("验证可达性", "Validate reachability")}</button>{String(item.status || "").toUpperCase() !== "RETIRED" && <button className="small-button danger-button" disabled={busy} onClick={() => void retireResource("node", String(item.node_id), String(item.node_key))}>{text("移除", "Retire")}</button>}</>}</span>])} empty={text("暂无受管节点", "No managed nodes")} text={text} />
    <DataTable headers={[text("存储", "Storage"), text("类型", "Backend"), text("位置", "Location"), text("验证", "Validation"), text("操作", "Action")]} rows={(data.storage || []).map((item: Row) => [item.storage_key, displayRowValue(lang, item.backend_kind), item.location_ref, displayRowValue(lang, item.validation_state), <button className="small-button" disabled={busy} onClick={() => void validateResource("storage", String(item.storage_id))}>{text("验证可用性", "Validate availability")}</button>])} empty={text("暂无共享存储", "No shared storage")} text={text} />
  </InfoPanel></div>;
}

function PlatformPoolGovernancePanel({
  lang, text, onNotice,
}: { lang: Lang; text: (zh: string, en: string) => string; onNotice: (value: string) => void }) {
  const [data, setData] = useState<Row>({ policy: {}, profiles: [], nodes: [], storage: [], bindings: [], onboardings: [], endpoints: [], enhancements: [] });
  const [busy, setBusy] = useState(false);
  const [bootstrap, setBootstrap] = useState<Row | null>(null);
  const load = async () => {
    try {
      const [policy, nodes, storage, bindings, onboardings, endpoints, enhancements] = await Promise.all([
        api<Row>("/api/platform/portal-llm-policy"), api<Row>("/api/platform/managed-nodes"),
        api<Row>("/api/platform/shared-storage"), api<Row>("/api/platform/node-storage-bindings"),
        api<Row>("/api/platform/agent-pool/onboardings"),
        api<Row>("/api/platform/external-db-endpoints"), api<Row>("/api/platform/portal-enhancements"),
      ]);
      setData({ policy, profiles: policy.profiles || [], nodes: listPayload(nodes, ["items"]), storage: listPayload(storage, ["items"]), bindings: listPayload(bindings, ["items"]), onboardings: listPayload(onboardings, ["items"]), endpoints: listPayload(endpoints, ["items"]), enhancements: listPayload(enhancements, ["items"]) });
    } catch (error) { onNotice((error as Error).message); }
  };
  useEffect(() => { void load(); }, []);
  const post = async (url: string, form: HTMLFormElement, message: string) => {
    const values: Row = Object.fromEntries(new FormData(form).entries());
    if (typeof values.roles === "string") values.roles = values.roles.split(",").map((item: string) => item.trim()).filter(Boolean);
    setBusy(true);
    try { await api(url, { method: "POST", body: JSON.stringify(values) }); form.reset(); await load(); onNotice(message); }
    catch (error) { onNotice((error as Error).message); } finally { setBusy(false); }
  };
  const savePolicy = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const selected = (data.profiles || []).filter((item: Row) => form.get(`profile_${item.profile_id}`) === "on").map((item: Row) => String(item.profile_id));
    setBusy(true);
    try { await api("/api/platform/portal-llm-policy", { method: "PUT", body: JSON.stringify({ default_profile_id: String(form.get("default_profile_id") || ""), allowed_profile_ids: selected, expected_version: Number(data.policy?.policy?.version || 1), reason: String(form.get("reason") || "") }) }); await load(); onNotice(text("Portal Agent Pool LLM 策略已保存", "Portal Agent Pool LLM policy saved")); }
    catch (error) { onNotice((error as Error).message); } finally { setBusy(false); }
  };
  const startBootstrap = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    setBusy(true);
    try {
      const result = await api<Row>("/api/platform/agent-pool/onboardings", { method: "POST", body: JSON.stringify({ node_id: String(form.get("node_id") || ""), reason: String(form.get("reason") || ""), expires_seconds: Number(form.get("expires_seconds") || 1800) }) });
      setBootstrap(result);
      formElement.reset();
      await load();
      onNotice(text("一次性主机引导令牌已生成，请仅通过受控渠道在目标主机执行。", "A one-time host bootstrap token was issued. Run it on the target host only through a controlled channel."));
    } catch (error) { onNotice((error as Error).message); } finally { setBusy(false); }
  };
  const activateBootstrap = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    setBusy(true);
    try {
      await api(`/api/platform/agent-pool/onboardings/${encodeURIComponent(String(form.get("onboarding_id") || ""))}/activate`, { method: "POST", body: JSON.stringify({ reason: String(form.get("reason") || "") }) });
      formElement.reset();
      await load();
      onNotice(text("Agent Pool 节点已激活，后续状态由主机心跳更新。", "The Agent Pool node is active; later status is updated by host heartbeats."));
    } catch (error) { onNotice((error as Error).message); } finally { setBusy(false); }
  };
  const rolesOf = (item: Row): string[] => {
    if (Array.isArray(item.role_json)) return item.role_json.map(String).map((value) => value.toUpperCase());
    try { return JSON.parse(String(item.role_json || "[]")).map((value: unknown) => String(value).toUpperCase()); } catch { return []; }
  };
  const nodesFor = (role: string) => (data.nodes || []).filter((item: Row) => rolesOf(item).includes(role));
  const storageFor = (purpose: string) => (data.storage || []).filter((item: Row) => String(item.storage_purpose || "").toUpperCase() === purpose);
  const storageRegistration = (purpose: "AGENT_POOL_RUNTIME" | "AGENT_POOL_AGENT_RUNTIME") => {
    const agentInfo = purpose === "AGENT_POOL_AGENT_RUNTIME";
    if (agentInfo) return null;
    return <form className="compact-form pool-config-block" onSubmit={(event) => { event.preventDefault(); void post("/api/platform/shared-storage", event.currentTarget, text("Agent Pool 目录已登记", "Agent Pool directory profile registered")); }}>
      <strong>{text(agentInfo ? "Agent Pool Agent 基本信息目录" : "Agent Pool 运行时共享目录", agentInfo ? "Agent Pool Agent information root" : "Agent Pool runtime shared directory")}</strong>
      <p className="cx-form-hint">{text(agentInfo ? "统一配置 Agent Pool 节点放置 Agent 基本信息和本地运行文件的根目录。运行时应在根目录下按 Agent ID 创建独立子目录，禁止 Agent 之间互相读取。该目录不是跨节点共享状态目录。" : "跨 Agent Pool 节点共享空闲 Agent 与运行时状态，避免不同时段访问到不同节点造成状态不一致。此目录不承载 Agent 本地文件或 Admin Agent 平台运行信息。", agentInfo ? "Configures the root directory for Agent metadata and local runtime files on Agent Pool nodes. The runtime must create a separate subdirectory per Agent ID and prevent cross-Agent reads. This is not the cross-node shared-state directory." : "Shares idle Agents and runtime state across Pool nodes so time-window changes do not create inconsistent instances. It does not store Agent-local files or Admin Agent platform runtime information.")}</p>
      <input type="hidden" name="storage_purpose" value={purpose} />
      <ConfigField label={text("配置名称", "Profile name")} hint={text("用于后续目录绑定和审计识别。", "Used by later bindings and audit records.")}><input name="storage_key" required /></ConfigField>
      <ConfigField label={text("存储类型", "Storage type")} hint={text("选择实际由基础设施提供的共享方式。", "Choose the sharing method supplied by the infrastructure.")}><select name="backend_kind" defaultValue="LOCAL_PATH"><option value="LOCAL_PATH">{text("目录或挂载点", "Directory or mount point")}</option><option value="NFS">NFS</option><option value="OBJECT_STORAGE">{text("对象存储", "Object storage")}</option><option value="UNIFIED_STORAGE">{text("统一存储", "Unified storage")}</option></select></ConfigField>
      <ConfigField label={text("路径或位置", "Path or location")} hint={text("填写共享存储的统一逻辑位置；节点本地实际挂载路径在目录绑定中填写。", "Enter the shared logical location; node-local mount paths are set in the directory binding.")}><input name="location_ref" required /></ConfigField>
      <ConfigField label={text("配置原因", "Configuration reason")} hint={text("必填并写入审计。", "Required and audited.")}><input name="reason" required /></ConfigField>
      <ConfigField label={text("操作", "Action")} hint={text("登记后将其绑定给对应的 Pool 节点。", "Bind it to the corresponding Pool nodes after registration.")} action><button className="small-button" disabled={busy}><Check size={14} />{text("登记目录", "Register directory")}</button></ConfigField>
    </form>;
  };
  const bindingPanel = (purpose: "AGENT_POOL_RUNTIME" | "AGENT_POOL_AGENT_RUNTIME") => {
    const role = "AGENT_POOL";
    const nodes = nodesFor(role);
    const storage = storageFor(purpose);
    const agentInfo = purpose === "AGENT_POOL_AGENT_RUNTIME";
    if (agentInfo) return null;
    return <InfoPanel title={text(agentInfo ? "Agent Pool Agent 信息目录绑定" : "Agent Pool 运行时共享目录绑定", agentInfo ? "Agent Pool Agent information directory binding" : "Agent Pool runtime shared-directory binding")} text={text}>
      <p className="cx-form-hint">{text(agentInfo ? "绑定 Agent Pool 节点上的 Agent 信息根目录。每个 Agent 必须使用独立子目录，目录内容不代表数据库授权。" : "将 Agent Pool 节点绑定到跨节点运行时共享目录，用于空闲 Agent 复用和一致性控制。", agentInfo ? "Bind the Agent information root on each Agent Pool node. Every Agent must use a separate subdirectory; directory contents never represent database authorization." : "Bind Agent Pool nodes to the cross-node runtime shared directory used for idle-Agent reuse and consistency.")}</p>
      <form className="configuration-form compact-configuration-form node-storage-binding-form" onSubmit={(event) => { event.preventDefault(); void post("/api/platform/node-storage-bindings", event.currentTarget, text("共享目录绑定已保存", "Shared-directory binding saved")); }}>
        <ConfigField label={text("运行节点", "Runtime node")} hint={nodes.length ? text("只显示已登记为对应角色的节点。", "Only nodes registered for this role are shown.") : text("暂无可选节点，请先登记并在节点角色中包含对应角色。", "No selectable node. Register a node with this role first.")}><select name="node_id" required><option value="">{text("请选择节点", "Select node")}</option>{nodes.map((item: Row) => <option key={String(item.node_id)} value={String(item.node_id)}>{String(item.node_key)} · {String(item.host_reference)}</option>)}</select></ConfigField>
        <ConfigField label={text(agentInfo ? "Agent 信息目录" : "专用共享存储", agentInfo ? "Agent information directory" : "Dedicated shared storage")} hint={storage.length ? text("只显示本能力登记的目录。", "Only storage registered for this capability is shown.") : text("暂无可选目录，请先登记本能力的目录。", "No selectable directory. Register one for this capability first.")}><select name="storage_id" required><option value="">{text("请选择目录", "Select directory")}</option>{storage.map((item: Row) => <option key={String(item.storage_id)} value={String(item.storage_id)}>{String(item.storage_key)} · {displayRowValue(lang, item.backend_kind)}</option>)}</select></ConfigField>
<ConfigField label={text("节点实际挂载路径", "Node mount path")} hint={text("填写该运行节点上实际可访问的目录或挂载点。共享存储登记的是统一位置，不同节点的本地路径可能不同；平台不会自动执行挂载。", "Enter the directory or mount point visible on this runtime node. The storage profile is the shared logical location; each node may expose a different local path. The platform does not mount it automatically.")}><input name="mount_reference" required /></ConfigField>
        <input type="hidden" name="role_scope" value={role} />
        <ConfigField label={text("绑定原因", "Binding reason")} hint={text("必填并写入审计。", "Required and audited.")}><input name="reason" required /></ConfigField>
        <ConfigField label={text("操作", "Action")} hint={text("绑定只记录运行节点和存储关系，不扩大数据授权。", "Binding records a runtime-node/storage relation; it does not expand data authorization.")} action><button className="small-button" disabled={busy}><Check size={14} />{text("绑定目录", "Bind directory")}</button></ConfigField>
      </form>
      <DataTable headers={[text("节点", "Node"), text("存储", "Storage"), text("挂载引用", "Mount reference"), text("状态", "Status")]} rows={(data.bindings || []).filter((item: Row) => String(item.role_scope || "").toUpperCase() === role).map((item: Row) => [item.node_key, item.storage_key, item.mount_reference, displayRowValue(lang, item.status)])} empty={text("暂无绑定", "No bindings")} text={text} />
    </InfoPanel>;
  };
  const allowed = new Set<string>(data.policy?.allowed_profile_ids || []);
  const poolNodes = nodesFor("AGENT_POOL");
  const checkedIn = (data.onboardings || []).filter((item: Row) => String(item.status || "").toUpperCase() === "CHECKED_IN");
  const bootstrapCommand = bootstrap ? `python3.14 scripts/agent_pool_node.py --platform-url ${window.location.origin} --onboarding-id ${bootstrap.onboarding_id} --token ${bootstrap.bootstrap_token} --shared-path <pool-shared-path> --agent-info-path <agent-info-root> --heartbeat-seconds 60` : "";
  return <div className="agent-pool-page"><InfoPanel title={text("Agent Pool 配置", "Agent Pool configuration")} text={text}>
    <p className="cx-form-hint">{text("按照主机方式接入时，必须完成登记、连通性验证、一次性引导回执、Agent Pool 运行时共享目录绑定、Agent 信息根目录绑定和管理员激活。每个 Agent 的本地文件必须位于其独立子目录，不能把目录内容当作授权。MaaS、SaaS、虚拟化等场景通过部署适配器接入；当前页面只提供适配器边界，不虚构通用自动部署。", "For host onboarding, complete registration, reachability validation, one-time bootstrap receipt, bindings for both the Agent Pool shared runtime directory and the Agent information root, and administrator activation. Each Agent's local files must stay in its own subdirectory; directory contents never grant authority. MaaS, SaaS, and virtualization connect through deployment adapters; this page exposes the adapter boundary and does not claim generic automatic deployment.")}</p>
    <form className="pool-config-block pool-llm-policy-form" onSubmit={savePolicy}><strong>{text("Portal Agent Pool LLM 允许列表", "Portal Agent Pool LLM allowlist")}</strong><p className="cx-form-hint">{text("Portal 只能切换到下方允许的 LLM。默认配置必须在允许列表中。", "Portal can switch only to LLMs allowed below. The default must be allowlisted.")}</p><div className="pool-llm-allowlist">{(data.profiles || []).length ? (data.profiles || []).map((item: Row) => <label className="checkbox-field" key={String(item.profile_id)}><input type="checkbox" name={`profile_${item.profile_id}`} defaultChecked={allowed.has(String(item.profile_id))} />{String(item.profile_key)} · {String(item.model_id)} · {String(item.health_state || "UNKNOWN")}</label>) : <p className="cx-form-hint">{text("请先在部署与模型中配置并测试 LLM。", "Configure and test an LLM in Deployment & models first.")}</p>}</div><div className="pool-policy-fields"><ConfigField label={text("默认 LLM", "Default LLM")} hint={text("只能选择已允许的配置。", "Choose an allowlisted profile.")}><select name="default_profile_id" defaultValue={String(data.policy?.policy?.default_profile_id || "")} required><option value="">{text("请选择", "Select")}</option>{(data.profiles || []).map((item: Row) => <option key={String(item.profile_id)} value={String(item.profile_id)}>{String(item.profile_key)}</option>)}</select></ConfigField><ConfigField label={text("变更原因", "Change reason")} hint={text("至少三个字符并写入审计。", "At least three characters and audited.")}><input name="reason" required /></ConfigField><ConfigField label={text("操作", "Action")} hint={text("保存后立即应用。", "Applied after saving.")} action><button className="small-button" disabled={busy}><Check size={14} />{text("保存策略", "Save policy")}</button></ConfigField></div></form>
    <InfoPanel title={text("主机节点登记", "Host node registration")} text={text}><form className="configuration-form compact-configuration-form" onSubmit={(event) => { event.preventDefault(); void post("/api/platform/managed-nodes", event.currentTarget, text("Agent Pool 主机节点已登记，请继续验证可达性。", "Agent Pool host node registered. Validate reachability next.")); }}>
      <ConfigField label={text("节点名称", "Node name")} hint={text("用于节点清单、回执和审计。", "Used for inventory, receipts, and audit.")}><input name="node_key" required /></ConfigField>
      <ConfigField label={text("主机或 IP", "Host or IP")} hint={text("平台用于进行有界 TCP 连通性验证。", "Used by the platform for bounded TCP reachability validation.")}><input name="host_reference" required /></ConfigField>
      <ConfigField label={text("SSH 端口", "SSH port")} hint={text("默认 22；仅记录连接目标，不保存密码。", "Defaults to 22; records the target only and never stores a password.")}><input name="ssh_port" type="number" min="1" max="65535" defaultValue="22" required /></ConfigField>
      <ConfigField label={text("操作系统用户", "Operating-system user")} hint={text("用于受控的主机侧安装与运行记录。", "Used by controlled host-side installation and runtime records.")}><input name="os_user" required /></ConfigField>
      <ConfigField label={text("连接方式", "Connection mode")} hint={text("当前由目标主机用一次性引导令牌回连；SSH 密码不进入平台。", "The target host checks in using a one-time bootstrap token; SSH passwords never enter the platform.")}><select name="trust_mode" defaultValue="MUTUAL_TRUST"><option value="MUTUAL_TRUST">{text("已配置 SSH 互信", "SSH mutual trust configured")}</option><option value="ONE_USE_PASSWORD">{text("一次性主机验证", "One-use host verification")}</option></select></ConfigField>
      <ConfigField label={text("故障域", "Failure domain")} hint={text("生产环境用来避免 Pool 节点集中在同一风险域。", "Prevents Pool nodes from concentrating in one production failure domain.")}><input name="failure_domain" required /></ConfigField>
      <LocalAgentPathField text={text} />
      <input type="hidden" name="roles" value="AGENT_POOL" />
      <ConfigField label={text("登记原因", "Registration reason")} hint={text("必填并写入审计。", "Required and audited.")}><input name="reason" required /></ConfigField>
      <ConfigField label={text("操作", "Action")} hint={text("登记后先验证可达性，再签发一次性主机引导令牌。", "After registration, validate reachability before issuing a one-time host bootstrap token.")} action><button className="small-button" disabled={busy}><Check size={14} />{text("登记节点", "Register node")}</button></ConfigField>
    </form></InfoPanel>
    <InfoPanel title={text("主机引导与激活", "Host bootstrap and activation")} text={text}><form className="configuration-form compact-configuration-form" onSubmit={startBootstrap}>
      <ConfigField label={text("已验证节点", "Validated node")} hint={text("仅可为已通过可达性检查的 Agent Pool 节点签发令牌。", "Only reachable Agent Pool nodes can receive a token.")}><select name="node_id" required><option value="">{text("请选择节点", "Select node")}</option>{poolNodes.filter((item: Row) => ["REACHABLE", "ONLINE"].includes(String(item.validation_state || "").toUpperCase())).map((item: Row) => <option key={String(item.node_id)} value={String(item.node_id)}>{String(item.node_key)} · {String(item.host_reference)}</option>)}</select></ConfigField>
      <ConfigField label={text("令牌有效期（秒）", "Token lifetime (seconds)")} hint={text("令牌只显示一次，到期后必须重新签发。", "The token is shown once; issue a new token after expiry.")}><input name="expires_seconds" type="number" min="300" max="86400" defaultValue="1800" required /></ConfigField>
      <ConfigField label={text("引导原因", "Bootstrap reason")} hint={text("必填并写入审计。", "Required and audited.")}><input name="reason" required /></ConfigField>
      <ConfigField label={text("操作", "Action")} hint={text("平台只保存令牌摘要，原始令牌不会再次显示。", "The platform stores only a token digest; the raw token is never shown again.")} action><button className="small-button" disabled={busy}><PlayCircle size={14} />{text("生成一次性引导", "Issue one-time bootstrap")}</button></ConfigField>
    </form>
    {bootstrap && <div className="pool-bootstrap-command"><strong>{text("仅显示一次的主机执行命令", "Host command shown once")}</strong><p className="cx-form-hint">{text("在目标主机上执行，将 <pool-shared-path> 替换为 Agent Pool 共享运行目录；Agent 信息根目录已经在节点登记时配置。完成回执后绑定共享运行目录并激活节点。", "Run this on the target host. Replace <pool-shared-path> with the shared Agent Pool runtime directory; the local Agent information directory was configured during node registration. Bind the shared runtime directory and activate the node after check-in.")}</p><code>{bootstrapCommand}</code></div>}
    <form className="configuration-form compact-configuration-form" onSubmit={activateBootstrap}>
      <ConfigField label={text("已回执节点", "Checked-in node")} hint={text("必须先在目标主机完成一次性引导回执。", "The target host must complete the one-time bootstrap receipt first.")}><select name="onboarding_id" required><option value="">{text("请选择回执", "Select receipt")}</option>{checkedIn.map((item: Row) => <option key={String(item.onboarding_id)} value={String(item.onboarding_id)}>{String(item.node_key)} · {displayRowValue(lang, item.status)}</option>)}</select></ConfigField>
      <ConfigField label={text("激活原因", "Activation reason")} hint={text("确认本地 Agent 信息目录已在节点登记，并且共享运行目录已绑定。", "Confirm that the local Agent information directory was registered and the shared runtime directory is bound.")}><input name="reason" required /></ConfigField>
      <ConfigField label={text("操作", "Action")} hint={text("激活要求共享 Agent Pool 运行目录已绑定。", "Activation requires the shared Agent Pool runtime directory binding.")} action><button className="small-button" disabled={busy}><Check size={14} />{text("激活节点", "Activate node")}</button></ConfigField>
    </form>
    <DataTable headers={[text("节点", "Node"), text("接入方式", "Integration"), text("状态", "Status"), text("最后心跳", "Last heartbeat"), text("运行时版本", "Runtime version")]} rows={(data.onboardings || []).map((item: Row) => [item.node_key, displayRowValue(lang, item.integration_kind), displayRowValue(lang, item.status), displayRowValue(lang, item.last_heartbeat_at) || "-", item.runtime_version || "-"])} empty={text("暂无主机接入记录", "No host onboarding records")} text={text} />
    </InfoPanel>
    <div className="pool-config-stack"><InfoPanel title={text("Agent Pool 目录配置", "Agent Pool directory configuration")} text={text}><div className="pool-config-stack">{storageRegistration("AGENT_POOL_RUNTIME")}{storageRegistration("AGENT_POOL_AGENT_RUNTIME")}</div></InfoPanel></div>
    {bindingPanel("AGENT_POOL_RUNTIME")}
    {bindingPanel("AGENT_POOL_AGENT_RUNTIME")}
    <div className="data-summary"><strong>{text("当前登记", "Registered")}</strong> · {text("Pool 节点", "Pool nodes")} {nodesFor("AGENT_POOL").length} · {text("共享目录", "Shared directories")} {storageFor("AGENT_POOL_RUNTIME").length} · {text("本地信息目录", "Local information directories")} {nodesFor("AGENT_POOL").filter((item: Row) => Boolean(item.agent_info_path)).length} · {text("绑定", "Bindings")} {data.bindings?.filter((item: Row) => String(item.role_scope || "").toUpperCase() === "AGENT_POOL").length || 0}</div>
  </InfoPanel></div>;
}

function ExternalRegistrationPolicyPanel({
  lang, text, onNotice,
}: {
  lang: Lang; text: (zh: string, en: string) => string; onNotice: (value: string) => void;
}) {
  const [policy, setPolicy] = useState<Row>({});
  const [state, setState] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const load = async () => {
    try {
      const value = await api<Row>("/api/platform/external-agent-registration");
      setPolicy(value);
      setState(String(value.state || "DISABLED").toUpperCase());
      setLoaded(true);
    }
    catch (error) { onNotice((error as Error).message); }
  };
  useEffect(() => { void load(); }, []);
  return <InfoPanel title={text("外部智能体注册", "External Agent registration")} text={text}>
    <p className="cx-form-hint">{text("此处控制是否允许新的外部 Skill-first 智能体注册。该策略只影响新注册；既有智能体不会被删除，变更原因会进入审计。", "This controls whether new external Skill-first Agents may register. It affects new registrations only; existing Agents are retained and the reason is audited.")}</p>
    <form className="configuration-form compact-configuration-form" onSubmit={async (event) => { event.preventDefault(); const form = new FormData(event.currentTarget); setBusy(true); try { await api("/api/platform/external-agent-registration", { method: "PUT", body: JSON.stringify({ state: String(form.get("state") || "DISABLED"), expected_version: Number(policy.version || 1), reason: String(form.get("reason") || "") }) }); await load(); onNotice(text("外部智能体注册策略已更新并记录审计。", "External Agent registration policy was updated and audited.")); } catch (error) { onNotice((error as Error).message); } finally { setBusy(false); } }}>
      <ConfigField label={text("注册策略", "Registration policy")} hint={text("关闭后拒绝新的外部注册令牌兑换。读取完成后才显示当前状态。", "Disabled rejects new external enrollment-token redemption. The current state is shown only after loading completes.")}><select name="state" value={state} disabled={!loaded} onChange={(event) => setState(event.target.value)}><option value="" disabled>{text("读取中", "Loading")}</option><option value="ENABLED">{text("允许", "Enabled")}</option><option value="APPROVAL_ONLY">{text("仅审批", "Approval only")}</option><option value="DISABLED">{text("关闭", "Disabled")}</option></select></ConfigField>
      <ConfigField label={text("变更原因", "Change reason")} hint={text("至少三个字符，写入审计。", "At least three characters; written to audit.")}><input name="reason" required /></ConfigField>
      <ConfigField label={text("操作", "Action")} hint={text("保存后立即用于新的注册请求。", "Applies immediately to new registration requests.")} action><button type="submit" className="small-button" disabled={busy}><Check size={15} />{text("保存策略", "Save policy")}</button></ConfigField>
    </form>
  </InfoPanel>;
}

function AdminAgentStoragePanel({
  lang, text, onNotice,
}: { lang: Lang; text: (zh: string, en: string) => string; onNotice: (value: string) => void }) {
  const [nodes, setNodes] = useState<Row[]>([]);
  const [storage, setStorage] = useState<Row[]>([]);
  const [bindings, setBindings] = useState<Row[]>([]);
  const [busy, setBusy] = useState(false);
  const load = async () => {
    try {
      const [nodeResult, storageResult, bindingResult] = await Promise.all([api<Row>("/api/platform/managed-nodes"), api<Row>("/api/platform/shared-storage"), api<Row>("/api/platform/node-storage-bindings")]);
      setNodes(listPayload(nodeResult, ["items"])); setStorage(listPayload(storageResult, ["items"])); setBindings(listPayload(bindingResult, ["items"]));
    } catch (error) { onNotice((error as Error).message); }
  };
  useEffect(() => { void load(); }, []);
  const post = async (url: string, form: HTMLFormElement, message: string) => {
    const values: Row = Object.fromEntries(new FormData(form).entries());
    if (typeof values.roles === "string") values.roles = values.roles.split(",").map((item: string) => item.trim()).filter(Boolean);
    setBusy(true);
    try { await api(url, { method: "POST", body: JSON.stringify(values) }); form.reset(); await load(); onNotice(message); }
    catch (error) { onNotice((error as Error).message); } finally { setBusy(false); }
  };
  const adminNodes = nodes.filter((item) => String(item.role_json || "").toUpperCase().includes("ADMIN_AGENT"));
  const adminStorage = storage.filter((item) => String(item.storage_purpose || "ADMIN_RUNTIME").toUpperCase() === "ADMIN_RUNTIME");
  const adminLocalStorage = storage.filter((item) => String(item.storage_purpose || "").toUpperCase() === "ADMIN_AGENT_RUNTIME");
  const registerAdminNode = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const formElement = event.currentTarget;
    const values: Row = Object.fromEntries(new FormData(formElement).entries());
    values.roles = ["ADMIN_AGENT"];
    setBusy(true);
    try { await api("/api/platform/managed-nodes", { method: "POST", body: JSON.stringify(values) }); formElement.reset(); await load(); onNotice(text("Admin Agent 节点已登记", "Admin Agent node registered")); }
    catch (error) { onNotice((error as Error).message); } finally { setBusy(false); }
  };
  return <InfoPanel title={text("Admin Agent 运行节点", "Admin Agent runtime nodes")} text={text}>
    <p className="cx-form-hint">{text("Admin Agent 本地运行目录必须在添加节点时配置。它只属于该节点，不是共享存储；平台不将本地目录转换为 NFS、对象存储或其他类型。平台运行信息的跨节点共享目录仍在平台配置的独立共享区域登记。", "Configure the Admin Agent local runtime directory when adding the node. It belongs only to that node and is not shared storage; the platform does not convert it to NFS, object storage, or another backend. The cross-node platform runtime directory remains a separate shared-storage profile.")}</p>
    <form className="configuration-form compact-configuration-form pool-config-block" onSubmit={registerAdminNode}>
      <strong>{text("添加 Admin Agent 运行节点", "Add Admin Agent runtime node")}</strong>
      <ConfigField label={text("节点名称", "Node name")} hint={text("用于节点清单和审计。", "Used in inventory and audit.")}><input name="node_key" required /></ConfigField>
      <ConfigField label={text("主机或 IP", "Host or IP")} hint={text("用于有界连通性验证。", "Used for bounded reachability checks.")}><input name="host_reference" required /></ConfigField>
      <ConfigField label={text("操作系统用户", "Operating-system user")} hint={text("用于受控节点运行。", "Used for controlled node operation.")}><input name="os_user" /></ConfigField>
      <LocalAgentPathField text={text} />
      <ConfigField label={text("连接方式", "Connection mode")} hint={text("仅记录受信方式，不保存可复用密码。", "Records the trust mode; reusable passwords are not stored.")}><select name="trust_mode" defaultValue="MUTUAL_TRUST"><option value="MUTUAL_TRUST">{text("SSH 互信", "SSH mutual trust")}</option><option value="ONE_USE_PASSWORD">{text("一次性密码验证", "One-use password")}</option></select></ConfigField>
      <ConfigField label={text("故障域", "Failure domain")} hint={text("用于区分部署风险域。", "Separates deployment failure domains.")}><input name="failure_domain" /></ConfigField>
      <ConfigField label={text("登记原因", "Registration reason")} hint={text("必填并写入审计。", "Required and audited.")}><input name="reason" required /></ConfigField>
      <ConfigField label={text("操作", "Action")} hint={text("登记后由平台完成节点验证。", "The platform validates the node after registration.")} action><button className="small-button" disabled={busy}><Check size={14} />{text("登记节点", "Register node")}</button></ConfigField>
    </form>
    <DataTable headers={[text("节点", "Node"), text("主机", "Host"), text("本地 Agent 信息目录", "Local Agent information directory"), text("状态", "Status")]} rows={adminNodes.map((item) => [item.node_key, item.host_reference, item.agent_info_path || text("未配置", "Not configured"), displayRowValue(lang, item.status)])} empty={text("暂无 Admin Agent 节点", "No Admin Agent nodes")} text={text} />
  </InfoPanel>;
  /* The legacy shared-storage form below is retained in source only for migration compatibility. */
  return <InfoPanel title={text("Admin Agent 平台运行信息共享目录", "Admin Agent platform runtime-information shared directory")} text={text}>
    <p className="cx-form-hint">{text("这是平台管理能力的共享存储配置，不属于 Agent Pool。用于保存 Admin Agent 的运行状态、协作信息和恢复所需文件。运行节点由平台启动或 Admin Agent 部署自动采集，不需要手工登记。它不授予数据库、Skill、Tool、频道或业务数据权限。", "This shared storage belongs to platform management, not Agent Pool. It stores Admin Agent runtime state, coordination information, and recovery files. Runtime nodes are collected automatically at platform startup or Admin Agent deployment; manual registration is not required. It grants no database, Skill, Tool, Channel, or business-data permission.")}</p>
    <div className="pool-config-stack"><form className="compact-form pool-config-block" onSubmit={(event) => { event.preventDefault(); void post("/api/platform/managed-nodes", event.currentTarget, text("Admin Agent 受管节点已登记", "Admin Agent managed node registered")); }}><strong>{text("Admin Agent 运行节点登记", "Admin Agent runtime node registration")}</strong><p className="cx-form-hint">{text("只登记用于运行平台管理 Agent 的节点。", "Register only nodes used by platform-management Agents.")}</p><input name="node_key" placeholder={text("节点名称", "Node name")} required /><input name="host_reference" placeholder={text("主机或 IP", "Host or IP")} required /><input name="os_user" placeholder={text("操作系统用户", "OS user")} /><input type="hidden" name="roles" value="ADMIN_AGENT" /><select name="trust_mode" defaultValue="MUTUAL_TRUST"><option value="MUTUAL_TRUST">{text("SSH 互信", "SSH mutual trust")}</option><option value="ONE_USE_PASSWORD">{text("一次性密码验证", "One-use password")}</option></select><input name="failure_domain" placeholder={text("故障域", "Failure domain")} /><input name="reason" placeholder={text("登记原因", "Registration reason")} required /><button className="small-button" disabled={busy}>{text("登记 Admin Agent 节点", "Register Admin Agent node")}</button></form><form className="compact-form pool-config-block" onSubmit={(event) => { event.preventDefault(); void post("/api/platform/shared-storage", event.currentTarget, text("Admin Agent 共享目录已登记", "Admin Agent shared directory registered")); }}><strong>{text("Admin Agent 运行信息共享目录登记", "Register Admin Agent runtime-information directory")}</strong><p className="cx-form-hint">{text("可使用本地目录、挂载点、NFS、对象存储或统一存储适配器。", "Supports a local directory, mount point, NFS, object storage, or unified-storage adapter.")}</p><input type="hidden" name="storage_purpose" value="ADMIN_RUNTIME" /><input name="storage_key" placeholder={text("配置名称", "Profile name")} required /><select name="backend_kind" defaultValue="LOCAL_PATH"><option value="LOCAL_PATH">{text("目录或挂载点", "Directory or mount point")}</option><option value="NFS">NFS</option><option value="OBJECT_STORAGE">{text("对象存储", "Object storage")}</option><option value="UNIFIED_STORAGE">{text("统一存储", "Unified storage")}</option></select><input name="location_ref" placeholder={text("路径或位置", "Path or location")} required /><input name="reason" placeholder={text("配置原因", "Configuration reason")} required /><button className="small-button" disabled={busy}>{text("登记共享目录", "Register shared directory")}</button></form><form className="configuration-form compact-configuration-form" onSubmit={(event) => { event.preventDefault(); void post("/api/platform/shared-storage", event.currentTarget, text("Admin Agent 本地信息目录已登记", "Admin Agent local information directory registered")); }}><input type="hidden" name="storage_purpose" value="ADMIN_AGENT_RUNTIME" /><ConfigField label={text("Admin Agent 本地信息目录名称", "Admin Agent local information profile")} hint={text("每个 Admin Agent 节点独立使用，不作为跨节点共享目录。", "Used independently by each Admin Agent node; it is not cross-node shared storage.")}><input name="storage_key" required /></ConfigField><ConfigField label={text("存储类型", "Storage type")} hint={text("填写本节点实际可访问的目录或挂载点。", "Use a directory or mount point accessible on the node.")}><select name="backend_kind" defaultValue="LOCAL_PATH"><option value="LOCAL_PATH">{text("目录或挂载点", "Directory or mount point")}</option><option value="NFS">NFS</option><option value="OBJECT_STORAGE">{text("对象存储", "Object storage")}</option><option value="UNIFIED_STORAGE">{text("统一存储", "Unified storage")}</option></select></ConfigField><ConfigField label={text("位置", "Location")} hint={text("平台仅记录逻辑位置，不自动挂载。", "The platform records the logical location and does not mount it automatically.")}><input name="location_ref" required /></ConfigField><ConfigField label={text("登记原因", "Registration reason")} hint={text("必填并写入审计。", "Required and audited.")}><input name="reason" required /></ConfigField><ConfigField label={text("操作", "Action")} hint={text("登记后绑定到指定 Admin Agent 节点。", "Bind it to a specific Admin Agent node after registration.")} action><button className="small-button" disabled={busy}><Check size={14} />{text("登记本地目录", "Register local directory")}</button></ConfigField></form></div>
    <form className="configuration-form compact-configuration-form node-storage-binding-form" onSubmit={(event) => { event.preventDefault(); void post("/api/platform/node-storage-bindings", event.currentTarget, text("Admin Agent 运行信息目录绑定已保存", "Admin Agent runtime-information binding saved")); }}><ConfigField label={text("Admin Agent 运行节点", "Admin Agent runtime node")} hint={adminNodes.length ? text("只显示 Admin Agent 节点。", "Only Admin Agent nodes are shown.") : text("暂无节点，请先登记 Admin Agent 运行节点。", "No node available; register an Admin Agent runtime node first.")}><select name="node_id" required><option value="">{text("请选择节点", "Select node")}</option>{adminNodes.map((item) => <option key={String(item.node_id)} value={String(item.node_id)}>{String(item.node_key)} · {String(item.host_reference)}</option>)}</select></ConfigField><ConfigField label={text("Admin Agent 共享目录", "Admin Agent shared directory")} hint={adminStorage.length ? text("只显示 Admin Agent 运行信息用途的存储。", "Only Admin Agent runtime-information storage is shown.") : text("暂无存储，请先登记 Admin Agent 共享目录。", "No storage available; register an Admin Agent directory first.")}><select name="storage_id" required><option value="">{text("请选择存储", "Select storage")}</option>{adminStorage.map((item) => <option key={String(item.storage_id)} value={String(item.storage_id)}>{String(item.storage_key)} · {displayRowValue(lang, item.backend_kind)}</option>)}</select></ConfigField><ConfigField label={text("节点实际挂载路径", "Node mount path")} hint={text("填写该运行节点上实际可访问的目录或挂载点。共享存储登记的是统一位置，不同节点的本地路径可能不同；平台不会自动执行挂载。", "Enter the directory or mount point visible on this runtime node. The storage profile is the shared logical location; each node may expose a different local path. The platform does not mount it automatically.")}><input name="mount_reference" required /></ConfigField><input type="hidden" name="role_scope" value="ADMIN_AGENT" /><ConfigField label={text("绑定原因", "Binding reason")} hint={text("必填并写入审计。", "Required and audited.")}><input name="reason" required /></ConfigField><ConfigField label={text("操作", "Action")} hint={text("只绑定平台运行信息目录，不改变平台权限。", "Binds runtime-information storage only; it does not change platform permissions.")} action><button className="small-button" disabled={busy}><Check size={14} />{text("绑定 Admin Agent 目录", "Bind Admin Agent directory")}</button></ConfigField></form>
    <form className="configuration-form compact-configuration-form node-storage-binding-form" onSubmit={(event) => { event.preventDefault(); void post("/api/platform/node-storage-bindings", event.currentTarget, text("Admin Agent 本地信息目录绑定已保存", "Admin Agent local information binding saved")); }}><ConfigField label={text("Admin Agent 节点", "Admin Agent node")} hint={text("每个节点独立选择自己的本地信息目录。", "Choose the local information directory independently for each node.")}><select name="node_id" required><option value="">{text("请选择节点", "Select node")}</option>{adminNodes.map((item) => <option key={String(item.node_id)} value={String(item.node_id)}>{String(item.node_key)} · {String(item.host_reference)}</option>)}</select></ConfigField><ConfigField label={text("本地信息目录", "Local information directory")} hint={adminLocalStorage.length ? text("只显示 Admin Agent 本地信息用途目录。", "Only Admin Agent local-information profiles are shown.") : text("暂无目录，请先登记。", "No directory is registered yet.")}><select name="storage_id" required><option value="">{text("请选择目录", "Select directory")}</option>{adminLocalStorage.map((item) => <option key={String(item.storage_id)} value={String(item.storage_id)}>{String(item.storage_key)} · {displayRowValue(lang, item.backend_kind)}</option>)}</select></ConfigField><ConfigField label={text("节点挂载路径", "Node mount path")} hint={text("Agent 在该路径下按 Agent ID 使用独立子目录。", "Agents use separate Agent-ID subdirectories below this path.")}><input name="mount_reference" required /></ConfigField><input type="hidden" name="role_scope" value="ADMIN_AGENT" /><ConfigField label={text("绑定原因", "Binding reason")} hint={text("必填并写入审计。", "Required and audited.")}><input name="reason" required /></ConfigField><ConfigField label={text("操作", "Action")} hint={text("只绑定本地 Agent 信息目录，不改变平台权限。", "Binds local Agent information storage only; it does not change platform permissions.")} action><button className="small-button" disabled={busy}><Check size={14} />{text("绑定本地目录", "Bind local directory")}</button></ConfigField></form>
    <DataTable headers={[text("节点", "Node"), text("存储", "Storage"), text("挂载引用", "Mount reference"), text("状态", "Status")]} rows={bindings.filter((item) => String(item.role_scope || "").toUpperCase() === "ADMIN_AGENT").map((item) => [item.node_key, item.storage_key, item.mount_reference, displayRowValue(lang, item.status)])} empty={text("暂无 Admin Agent 目录绑定", "No Admin Agent directory binding")} text={text} />
  </InfoPanel>;
}

function LLMProviderProfilesPanel({ lang, capabilities, text, onNotice }: {
  lang: Lang;
  capabilities: Row | null;
  text: (zh: string, en: string) => string;
  onNotice: (value: string) => void;
}) {
  const [profiles, setProfiles] = useState<Row[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [testing, setTesting] = useState(false);
  const [draftVersion, setDraftVersion] = useState(0);
  const [testedVersion, setTestedVersion] = useState<number | null>(null);
  const [feedback, setFeedback] = useState("");
  const formRef = useRef<HTMLFormElement>(null);
  const canManage = canAction(capabilities, "platform.manage") || canAction(capabilities, "agents.manage");
  const load = async () => {
    setLoading(true);
    try {
      const value = await api<Row>("/api/llm-provider-profiles?limit=100");
      setProfiles(listPayload(value, ["items"]));
    } catch (error) { onNotice((error as Error).message); }
    finally { setLoading(false); }
  };
  useEffect(() => { void load(); }, []);
  const draftBody = () => {
    const form = new FormData(formRef.current!);
    return { profile_key: String(form.get("profile_key") || ""), provider_url: String(form.get("provider_url") || ""), model_id: String(form.get("model_id") || ""), api_key: String(form.get("api_key") || "") };
  };
  const testProfile = async () => {
    if (!formRef.current) return;
    setTesting(true);
    try {
      const result = await api<Row>("/api/llm-provider-profiles/probe-draft", { method: "POST", body: JSON.stringify(draftBody()) });
      if (String(result.status || "").toUpperCase() !== "VERIFIED") throw new Error(text("LLM 服务测试未通过，请检查地址、模型 ID 和 API Key。", "LLM test did not pass. Check the URL, model ID, and API key."));
      setTestedVersion(draftVersion);
      const message = text(`LLM 服务测试通过，延迟 ${result.latency_ms ?? "-"} ms。`, `LLM service test passed in ${result.latency_ms ?? "-"} ms.`);
      setFeedback(message); onNotice(message);
    } catch (error) { setTestedVersion(null); setFeedback((error as Error).message); onNotice((error as Error).message); }
    finally { setTesting(false); }
  };
  const saveProfile = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (testedVersion !== draftVersion) { onNotice(text("请先测试当前 LLM 配置。", "Test the current LLM configuration first.")); return; }
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    setBusy(true);
    try {
      const saved = await api<Row>("/api/llm-provider-profiles", { method: "POST", body: JSON.stringify({ ...draftBody(), approved_for: [], reason: String(form.get("reason") || "") }) });
      await api<Row>(`/api/llm-provider-profiles/${encodeURIComponent(String(saved.profile_id || ""))}/probe`, { method: "POST", body: "{}" });
      formElement.reset(); setDraftVersion((value) => value + 1); setTestedVersion(null); await load();
      const message = text("LLM 配置已加密保存并完成探活。", "LLM profile was encrypted, saved, and probed."); setFeedback(message); onNotice(message);
    } catch (error) { setFeedback((error as Error).message); onNotice((error as Error).message); }
    finally { setBusy(false); }
  };
  const probe = async (profileId: string) => { setBusy(true); try { await api(`/api/llm-provider-profiles/${encodeURIComponent(profileId)}/probe`, { method: "POST", body: "{}" }); await load(); } catch (error) { onNotice((error as Error).message); } finally { setBusy(false); } };
  const retire = async (item: Row) => {
    const reason = window.prompt(text(`请输入移除“${item.profile_key}”的原因（至少三个字符）`, `Enter a reason to retire “${item.profile_key}” (at least 3 characters)`), "");
    if (!reason || reason.trim().length < 3) return;
    setBusy(true); try { await api(`/api/llm-provider-profiles/${encodeURIComponent(String(item.profile_id))}`, { method: "DELETE", body: JSON.stringify({ reason: reason.trim() }) }); await load(); } catch (error) { onNotice((error as Error).message); } finally { setBusy(false); }
  };
  return <InfoPanel title={text("LLM 服务商配置", "LLM Provider Profiles")} text={text}>
    <p className="cx-form-hint">{text("模型服务只提供推理能力，不构成授权边界。当前填写内容必须先测试再保存；API Key 仅以密文保存且不会回显。", "Model services provide reasoning only and never define authorization. Test the current draft before saving; API keys are encrypted and never returned.")}</p>
    {feedback && <p className="operation-feedback" role="status">{feedback}</p>}
    {canManage && <form ref={formRef} className="configuration-form native-profile-form" onChange={() => { setDraftVersion((value) => value + 1); setTestedVersion(null); setFeedback(""); }} onSubmit={saveProfile}>
      <ConfigField label={text("配置键", "Profile key")} hint={text("平台内唯一标识。", "Unique platform identifier.")}><input name="profile_key" required /></ConfigField>
      <ConfigField label={text("服务地址", "Provider URL")} hint={text("受控的 OpenAI 兼容服务根地址。", "Approved OpenAI-compatible service root.")}><input name="provider_url" type="url" required /></ConfigField>
      <ConfigField label={text("模型 ID", "Model ID")} hint={text("服务端发布的模型标识。", "Model identifier exposed by the provider.")}><input name="model_id" required /></ConfigField>
      <ConfigField label={text("API Key", "API key")} hint={text("可留空；填写后仅保存密文。", "Optional; stored only as ciphertext.")}><input name="api_key" type="password" autoComplete="new-password" /></ConfigField>
      <ConfigField label={text("保存原因", "Save reason")} hint={text("至少三个字符并写入审计。", "At least three characters and audited.")}><input name="reason" required /></ConfigField>
      <ConfigField label={text("测试与保存", "Test and save")} hint={testedVersion === draftVersion ? text("测试通过，可以保存。", "Test passed; saving is enabled.") : text("修改任一字段后需重新测试。", "Retest after changing any field.")} action><div className="action-button-row"><button type="button" className="small-button" disabled={busy || testing} onClick={() => void testProfile()}><Activity className={testing ? "spin" : ""} size={14} />{text("测试", "Test")}</button><button className="primary-button" disabled={busy || testedVersion !== draftVersion}><Plus size={14} />{text("保存", "Save")}</button></div></ConfigField>
    </form>}
    {loading ? <PageLoading text={text} /> : <DataTable headers={[text("配置", "Profile"), text("模型", "Model"), text("密钥", "Secret"), text("健康", "Health"), text("操作", "Action")]} rows={profiles.map((item) => [item.profile_key, item.model_id, item.secret_present ? text("已加密", "Encrypted") : text("未设置", "Not set"), displayRowValue(lang, item.health_state), canManage && String(item.status || "").toUpperCase() !== "RETIRED" ? <span className="actions-row"><button className="small-button" disabled={busy} onClick={() => void probe(String(item.profile_id))}>{text("探活", "Probe")}</button><button className="small-button danger" disabled={busy} onClick={() => void retire(item)}>{text("移除", "Retire")}</button></span> : displayRowValue(lang, item.status)])} empty={text("暂无 LLM 配置", "No LLM profiles")} text={text} />}
  </InfoPanel>;
}

function PlatformOperationsPage({
  lang, capabilities, text, onNotice, activeTab: tab, embedded,
}: {
  lang: Lang; capabilities: Row | null; text: (zh: string, en: string) => string; onNotice: (value: string) => void;
  activeTab: "overview" | "llm-providers" | "admin-management" | "admission" | "agent-pool" | "upgrade" | "containment";
  embedded?: boolean;
}) {
  const [payload, setPayload] = useState<Row>({});
  const [enrollments, setEnrollments] = useState<Row[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [path, setPath] = useState("PLATFORM_DEPLOYED");
  const [trustMode, setTrustMode] = useState("MUTUAL_TRUST");
  const [upgradeFile, setUpgradeFile] = useState<File | null>(null);
  const [governanceGraph, setGovernanceGraph] = useState<Row>({});
  const [governanceInterval, setGovernanceInterval] = useState(3);
  const load = async () => {
    setLoading(true);
    try {
      const [management, enrollmentState] = await Promise.all([
        api<Row>("/api/platform/administration"), api<Row>("/api/platform/admin-enrollments?limit=100"),
      ]);
      setPayload(management); setEnrollments(enrollmentState.items || []);
    } catch (error) { onNotice((error as Error).message); }
    finally { setLoading(false); }
  };
  useEffect(() => { void load(); }, []);
  useEffect(() => {
    if (tab !== "overview") return;
    let cancelled = false;
    const fetchGraph = async () => {
      try {
        const value = await api<Row>(`/api/platform/governance-graph?refresh_interval_seconds=${governanceInterval}`);
        if (!cancelled) setGovernanceGraph(value);
      } catch (error) {
        if (!cancelled) onNotice((error as Error).message);
      }
    };
    void fetchGraph();
    const timer = window.setInterval(() => { void fetchGraph(); }, governanceInterval * 1000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [tab, governanceInterval]);
  const management = payload || {};
  const group = management.admin_group?.group || {};
  const members = management.admin_group?.members || [];
  const submitEnrollment = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); const formElement = event.currentTarget; const data = new FormData(formElement); setBusy(true);
    try {
      await api("/api/platform/admin-enrollments", { method: "POST", body: JSON.stringify({
        admission_path: path, node_id: String(data.get("node_id") || ""), public_key: path === "EXTERNAL_ADMIN" ? String(data.get("public_key") || "") : "",
        host_reference: path === "PLATFORM_DEPLOYED" ? String(data.get("host_reference") || "") : "",
        ssh_port: Number(data.get("ssh_port") || 22), os_user: path === "PLATFORM_DEPLOYED" ? String(data.get("os_user") || "") : "",
        deployment_target: path === "PLATFORM_DEPLOYED" ? String(data.get("deployment_target") || "") : "",
        agent_info_path: path === "PLATFORM_DEPLOYED" ? String(data.get("agent_info_path") || "") : "",
        ssh_trust_mode: trustMode, ssh_password: path === "PLATFORM_DEPLOYED" && trustMode === "ONE_USE_PASSWORD" ? String(data.get("ssh_password") || "") : "",
        failure_domain: path === "PLATFORM_DEPLOYED" ? String(data.get("failure_domain") || "") : "",
        reason: String(data.get("reason") || ""),
      }) });
      formElement.reset(); setPath("PLATFORM_DEPLOYED"); setTrustMode("MUTUAL_TRUST"); await load();
      onNotice(text("Admin Agent 候选已登记；平台部署节点信息已自动采集并生成受管节点记录，等待受认证适配器完成 SSH 验证。密码仅在本次请求中使用，未写入数据库或审计。", "Admin Agent candidate recorded; deployment-node metadata was collected automatically and a managed-node record was created. An authenticated adapter must complete SSH verification. The password was used only for this request and was not persisted or audited."));
    } catch (error) { onNotice((error as Error).message); } finally { setBusy(false); }
  };
  const submitContainment = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); const formElement = event.currentTarget; const data = new FormData(formElement);
    if (String(data.get("confirmation") || "") !== "CONTAIN") { onNotice(text("请输入 CONTAIN 确认此受保护操作。", "Enter CONTAIN to confirm this protected operation.")); return; }
    setBusy(true); try {
      await api("/api/platform/containment", { method: "POST", body: JSON.stringify({ agent_id: String(data.get("agent_id") || ""), instance_id: String(data.get("instance_id") || ""), requested_state: String(data.get("requested_state") || "DRAIN"), reason: String(data.get("reason") || "") }) });
      formElement.reset(); onNotice(text("平台侧权限已优先隔离；远程终止仍需受认证运行时或基础设施适配器确认。", "Platform authority was isolated first; remote termination still requires a trusted runtime or infrastructure adapter."));
    } catch (error) { onNotice((error as Error).message); } finally { setBusy(false); }
  };
  const uploadUpgrade = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); const formElement = event.currentTarget; const data = new FormData(formElement);
    if (!upgradeFile || String(data.get("reason") || "").trim().length < 3) { onNotice(text("请选择 ZIP 文件并填写至少 3 个字符的升级原因。", "Choose a ZIP file and enter an upgrade reason of at least three characters.")); return; }
    setBusy(true); try {
      const result = await api<Row>(`/api/platform/upgrades/upload?reason=${encodeURIComponent(String(data.get("reason")).trim())}`, { method: "POST", headers: { "X-Upload-Filename": upgradeFile.name }, body: await upgradeFile.arrayBuffer() });
      setUpgradeFile(null); formElement.reset(); await load();
      onNotice(result.automation_state === "WAITING_FOR_TRUSTED_SIGNATURE" ? text("升级包已暂存，正等待受信任签名。", "Package staged and waiting for a trusted signature.") : text("升级包已校验，受控升级与 Skill 分发已自动编排。", "Package verified; controlled upgrade and Skill distribution were scheduled automatically."));
    } catch (error) { onNotice((error as Error).message); } finally { setBusy(false); }
  };
  return <section className={embedded ? "page-stack platform-configuration-subpage" : "page-stack"}>{!embedded && <SectionHeading title={text("平台运行", "Platform operations")} subtitle={text("平台级接入、升级和阻断配置独立于能力开关。所有操作均受保护，并保留数据库审计证据。", "Platform admission, upgrade, and containment settings are separate from capability switches. Every operation is protected and retained as database audit evidence.")} text={text} actions={<PageRefresh loading={loading} onRefresh={load} text={text} />} />}
    {loading ? <PageLoading text={text} /> : <>
      {tab === "llm-providers" && <LLMProviderProfilesPanel lang={lang} capabilities={capabilities} text={text} onNotice={onNotice} />}
      {tab === "overview" && <><InfoPanel title={text("平台管理频道", "Platform Administration Channel")} text={text}><p className="cx-form-hint">{text("仅管理员、平台管理智能体及经审批的 Admin Agent 可加入。聊天仅形成建议；变更必须转换为结构化操作并审计。", "Only administrators, platform management Agents, and approved Admin Agents may join. Chat produces advice only; changes must become structured audited operations.")}</p><div className="metric-grid management-metric-grid"><InfoPanel title={text("频道", "Channel")} text={text}><strong className="metric-value">{management.channel?.channel_name || "-"}</strong></InfoPanel><InfoPanel title={text("高可用状态", "HA readiness")} text={text}><strong className="metric-value">{displayRowValue(lang, management.admin_group?.readiness || "HIGH_AVAILABILITY_NOT_READY")}</strong></InfoPanel><InfoPanel title={text("当前任期", "Current term")} text={text}><strong className="metric-value">{String(group.current_term || 0)}</strong></InfoPanel></div><DataTable headers={[text("成员", "Member"), text("路径", "Path"), text("状态", "State"), text("权重", "Weight"), text("节点", "Node")]} rows={members.map((item: Row) => [item.agent_id, displayRowValue(lang, item.admission_path), displayRowValue(lang, item.status), String(item.weight), item.node_id || "-"])} empty={text("尚无 Admin Agent 成员", "No Admin Agent members")} text={text} /></InfoPanel><InfoPanel title={text("治理影响图", "Governance impact graph")} text={text}><div className="page-toolbar"><label><span>{text("刷新频率", "Refresh interval")}</span><select value={governanceInterval} onChange={(event) => setGovernanceInterval(Number(event.target.value))}><option value={1}>1s</option><option value={3}>3s</option><option value={5}>5s</option><option value={10}>10s</option></select></label><span className="tag">{text("数据时间", "Fresh at")} {String(governanceGraph.fresh_at || "-")}</span></div><div className="metric-grid"><InfoPanel title={text("受管节点", "Managed nodes")} text={text}><strong className="metric-value">{String(governanceGraph.metrics?.managed_nodes ?? "-")}</strong></InfoPanel><InfoPanel title={text("运行任务", "Running executions")} text={text}><strong className="metric-value">{String(governanceGraph.metrics?.runtime_executions ?? "-")}</strong></InfoPanel><InfoPanel title={text("活动 Graph Run", "Active Graph Runs")} text={text}><strong className="metric-value">{String(governanceGraph.metrics?.active_graph_runs ?? "-")}</strong></InfoPanel><InfoPanel title={text("维护任务", "Maintenance tasks")} text={text}><strong className="metric-value">{String(governanceGraph.metrics?.maintenance_tasks ?? "-")}</strong></InfoPanel></div><DataTable headers={[text("依赖", "Dependency"), text("类型", "Type")]} rows={((governanceGraph.nodes || []) as Row[]).map((item) => [item.label, item.group])} empty={text("治理图暂不可用", "Governance graph unavailable")} text={text} /><p className="cx-form-hint">{text("该图是只读影响分析投影，不授予任何执行权限。", "This read-only impact projection never grants execution authority.")}</p></InfoPanel></>}
      {tab === "admin-management" && <AdminAgentStoragePanel lang={lang} text={text} onNotice={onNotice} />}
      {tab === "admission" && <><InfoPanel title={text("登记 Admin Agent 候选", "Register an Admin Agent candidate")} text={text}><p className="cx-form-hint">{text("平台部署由现有 Admin Agent 自动完成身份密钥生成、节点登记和接入验证；外部 Admin 使用独立的密钥/接入包路径，不接收基础设施凭证。", "Platform deployment uses the existing Admin Agent to generate identity material, register the node, and complete admission verification. External Admin uses a separate key/package path and never receives infrastructure credentials.")}</p><form className="configuration-form admin-admission-form" onSubmit={submitEnrollment}><ConfigField label={text("接入路径", "Admission path")} hint={text("选择后展示对应的安全字段。", "Shows the appropriate secure fields for the selected path.")}><select value={path} onChange={(event) => setPath(event.target.value)}><option value="PLATFORM_DEPLOYED">{text("平台部署", "Platform deployed")}</option><option value="EXTERNAL_ADMIN">{text("外部 Admin 接入", "External Admin admission")}</option></select></ConfigField><ConfigField label={text("节点名称或 ID", "Node name or ID")} hint={text("用于成员、故障域和审计关联。", "Used for membership, failure-domain, and audit correlation.")}><input name="node_id" required /></ConfigField>{path === "EXTERNAL_ADMIN" && <ConfigField label={text("Admin Agent 身份公钥", "Admin Agent identity public key")} hint={text("外部 Admin 需要提供其身份公钥；不是服务器 SSH 主机公钥，也不是 API Key。平台只保存公钥摘要。", "External Admin must provide its identity public key. This is not the server SSH host key or an API key. The platform stores only its digest.")} multiline><textarea className="config-textarea" name="public_key" required /></ConfigField>}{path === "PLATFORM_DEPLOYED" && <><ConfigField label={text("主机或 IP", "Host or IP")} hint={text("目标节点的可达地址。", "Reachable address of the target node.")}><input name="host_reference" required /></ConfigField><ConfigField label={text("SSH 端口", "SSH port")} hint={text("填写目标节点的 SSH 端口；留空时服务端按 22 处理。", "Enter the target SSH port; the server uses 22 when omitted.")}><input name="ssh_port" type="number" min="1" max="65535" /></ConfigField><ConfigField label={text("系统用户", "Operating-system user")} hint={text("用于部署与节点验证。", "Used for deployment and node verification.")}><input name="os_user" required /></ConfigField><ConfigField label={text("部署目标", "Deployment target")} hint={text("受管运行时、虚拟机或客户适配器目标。", "Managed runtime, virtual machine, or customer-adapter target.")}><input name="deployment_target" required /></ConfigField><ConfigField label={text("SSH 验证方式", "SSH verification mode")} hint={text("互信不传密码；一次性密码只用于当前验证。", "Mutual trust sends no password; a one-use password is used only for this verification.")}><select value={trustMode} onChange={(event) => setTrustMode(event.target.value)}><option value="MUTUAL_TRUST">{text("已配置 SSH 互信", "SSH mutual trust configured")}</option><option value="ONE_USE_PASSWORD">{text("一次性 SSH 密码", "One-use SSH password")}</option></select></ConfigField>{trustMode === "ONE_USE_PASSWORD" && <ConfigField label={text("一次性 SSH 密码", "One-use SSH password")} hint={text("仅用于本次验证，提交后立即丢弃且永不存储。", "Used only for this verification, discarded after submission, and never stored.")}><input name="ssh_password" type="password" autoComplete="new-password" required /></ConfigField>}<ConfigField label={text("故障域", "Failure domain")} hint={text("用于避免高可用成员集中在同一故障域。", "Prevents high-availability members from concentrating in one failure domain.")}><input name="failure_domain" required /></ConfigField></>}<ConfigField label={text("接入原因", "Admission reason")} hint={text("必须说明新增管理节点的原因。", "Explain why this management node is being added.")}><input name="reason" required /></ConfigField><ConfigField label={text("操作", "Action")} hint={text("候选需经过身份验证、观察和批准后才加入投票组。", "The candidate must be verified, observed, and approved before joining the voting group.")} action><button className="primary-button" disabled={busy}><UserPlus size={15} />{text("登记候选", "Register candidate")}</button></ConfigField></form></InfoPanel><InfoPanel title={text("候选状态", "Candidate status")} text={text}><DataTable headers={[text("候选", "Candidate"), text("路径", "Path"), text("节点", "Node"), text("状态", "State")]} rows={enrollments.map((item) => [item.agent_id || "-", displayRowValue(lang, item.admission_path), item.node_id || "-", displayRowValue(lang, item.status)])} empty={text("暂无 Admin Agent 候选", "No Admin Agent candidates")} text={text} /></InfoPanel></>}
      {tab === "agent-pool" && <PlatformPoolGovernancePanel lang={lang} text={text} onNotice={onNotice} />}
      {tab === "upgrade" && <InfoPanel title={text("平台升级与 Skill 自动分发", "Platform upgrade and automatic Skill distribution")} text={text}><p className="cx-form-hint">{text("上传发布流程生成的平台版本 ZIP 包。服务端验证 manifest、摘要、签名、目标数据库、版本和企业版兼容性；通过后自动建立平台维护计划，并向受控智能体分发新版 Skill 通知。运行中的任务只会在安全点切换，不需要逐个智能体人工升级。", "Upload a platform release ZIP produced by the release pipeline. The service validates the manifest, digests, signature, target database, version, and Enterprise compatibility; it then automatically creates the platform maintenance plan and distributes new Skill notices to governed Agents. Running work switches only at a safe point, without per-Agent manual upgrades.")}</p><form className="configuration-form" onSubmit={uploadUpgrade}><ConfigField label={text("平台新版 ZIP 压缩包", "New platform release ZIP")} hint={text("只接受发布流程生成的平台安装包。", "Only accepts a platform installation package generated by the release pipeline.")}><input name="package" type="file" accept=".zip,application/zip" onChange={(event) => setUpgradeFile(event.currentTarget.files?.[0] || null)} required /></ConfigField><ConfigField label={text("升级原因", "Upgrade reason")} hint={text("至少三个字符，写入审计。", "At least three characters; written to audit.")}><input name="reason" required /></ConfigField><ConfigField label={text("操作", "Action")} hint={text("平台不会执行 ZIP 中的任意脚本。", "The platform never executes arbitrary scripts from the ZIP.")} action><button className="primary-button" disabled={busy || !upgradeFile}><Upload size={15} />{text("上传并自动编排平台包", "Upload and schedule platform package")}</button></ConfigField></form><DataTable headers={[text("升级 ID", "Upgrade ID"), text("版本", "Version"), text("状态", "Status")]} rows={(management.upgrades || []).map((item: Row) => [item.upgrade_id, item.package_version, displayRowValue(lang, item.status)])} empty={text("暂无暂存升级包", "No staged upgrade package")} text={text} /></InfoPanel>}
      {tab === "containment" && <InfoPanel title={text("紧急阻断", "Emergency containment")} text={text}><p className="cx-form-hint">{text("先撤销平台授权和任务接收能力，再由受认证运行时或基础设施适配器确认进程级终止。该操作只影响指定实例，不扩大到其他节点。", "Platform authority and work acceptance are removed first. A trusted runtime or infrastructure adapter then confirms process termination. This affects only the specified instance and does not expand to other nodes.")}</p><form className="configuration-form containment-form" onSubmit={submitContainment}><ConfigField label={text("智能体 ID", "Agent ID")} hint={text("要隔离的生产智能体。", "Production Agent to isolate.")}><input name="agent_id" required /></ConfigField><ConfigField label={text("实例 ID", "Instance ID")} hint={text("仅影响指定运行实例。", "Limits containment to the specified runtime instance.")}><input name="instance_id" required /></ConfigField><ConfigField label={text("阻断动作", "Containment action")} hint={text("按风险选择排空、隔离或请求终止。", "Choose drain, quarantine, or termination based on risk.")}><select name="requested_state" defaultValue="DRAIN"><option value="DRAIN">{text("排空新任务", "Drain new work")}</option><option value="QUARANTINE">{text("隔离", "Quarantine")}</option><option value="TERMINATE">{text("请求终止", "Request termination")}</option><option value="INFRA_TERMINATE">{text("请求基础设施终止", "Request infrastructure termination")}</option></select></ConfigField><ConfigField label={text("阻断原因", "Containment reason")} hint={text("必须填写影响判断依据。", "Required impact rationale.")}><input name="reason" required /></ConfigField><ConfigField label={text("确认文本", "Confirmation text")} hint={text("输入 CONTAIN 以确认此受保护操作。", "Enter CONTAIN to confirm this protected operation.")}><input name="confirmation" required /></ConfigField><ConfigField label={text("操作", "Action")} hint={text("操作和影响范围均写入审计。", "The operation and impact scope are written to audit.")} action><button className="small-button danger" disabled={busy}><StopCircle size={15} />{text("提交阻断", "Issue containment")}</button></ConfigField></form></InfoPanel>}
    </>}
  </section>;
}

function DeploymentModelsPage({
  lang,
  capabilities,
  text,
  onNotice,
  embedded = false,
}: {
  lang: Lang;
  capabilities: Row | null;
  text: (zh: string, en: string) => string;
  onNotice: (value: string) => void;
  embedded?: boolean;
}) {
  const [payload, setPayload] = useState<Row>({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [testing, setTesting] = useState(false);
  const [observedDimension, setObservedDimension] = useState<number | null>(null);
  const [draftVersion, setDraftVersion] = useState(0);
  const [testedDraftVersion, setTestedDraftVersion] = useState<number | null>(null);
  const profileFormRef = useRef<HTMLFormElement>(null);
  const canManage = canAction(capabilities, "platform.manage");
  const load = async () => {
    setLoading(true);
    try {
      const [runs, readiness, profiles, contracts, spaces, bindings, jobs] = await Promise.all([
        api<Row>("/api/deployment-runs?limit=20"), api<Row>("/api/embedding/readiness"),
        api<Row>("/api/embedding/profiles?limit=100"), api<Row>("/api/embedding/contracts?limit=100"),
        api<Row>("/api/embedding/spaces?limit=100"), api<Row>("/api/embedding/bindings?limit=100"),
        api<Row>("/api/embedding/jobs?limit=100"),
      ]);
      setPayload({ runs, readiness, profiles, contracts, spaces, bindings, jobs });
    } catch (error) {
      onNotice((error as Error).message);
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { void load(); }, []);
  const profileBody = (form: FormData): Row => ({
    profile_key: String(form.get("profile_key") || ""),
    provider_url: String(form.get("provider_url") || ""),
    model_id: String(form.get("model_id") || ""),
    execution_mode: String(form.get("execution_mode") || "PLATFORM_MANAGED"),
    dimension: Number(form.get("dimension") || 0),
    distance_metric: String(form.get("distance_metric") || "COSINE"),
    normalize_vectors: true,
    api_key: String(form.get("api_key") || ""),
    secret_reference: String(form.get("secret_reference") || ""),
    reason: String(form.get("reason") || ""),
  });
  const testProfile = async () => {
    if (!profileFormRef.current) return;
    setTesting(true);
    try {
      const draft = profileBody(new FormData(profileFormRef.current));
      if (!String(draft.reason || "").trim())
        throw new Error(text("请填写变更原因。", "Enter a change reason."));
      if (String(draft.reason || "").trim().length < 3)
        throw new Error(text("变更原因至少需要 3 个字符。", "The change reason must contain at least 3 characters."));
      const result = await api<Row>("/api/embedding/profiles/probe-draft", {
        method: "POST", body: JSON.stringify(draft),
      });
      if (String(result.status || "").toUpperCase() !== "VERIFIED")
        throw new Error(text("Embedding 测试未通过，请检查模型地址、模型 ID 和向量维度。", "Embedding test did not pass. Check the URL, model ID, and vector dimension."));
      const detectedDimension = Number(result.result?.observed_dimension || draft.dimension || 0);
      if (detectedDimension > 0) {
        setObservedDimension(detectedDimension);
        draft.dimension = detectedDimension;
      }
      // A successful probe is bound to the current form revision. A stale
      // result must never activate a changed Embedding profile.
      if (testedDraftVersion !== draftVersion && testedDraftVersion !== null) {
        throw new Error(text("配置已发生变化，请重新测试。", "The configuration changed; run the probe again."));
      }
      setTestedDraftVersion(draftVersion);
      setBusy(true);
      await api("/api/embedding/platform/activate", { method: "POST", body: JSON.stringify(draft) });
      await load();
      onNotice(text("Embedding 测试通过，平台已自动完成统一配置、契约、默认空间和绑定。", "Embedding test passed; the platform automatically completed the unified profile, Contract, default Space, and binding."));
    } catch (error) {
      setTestedDraftVersion(null);
      onNotice((error as Error).message);
    } finally {
      setBusy(false);
      setTesting(false);
    }
  };
  const probeSavedProfile = async (item: Row) => {
    setBusy(true);
    try {
      const result = await api<Row>(`/api/llm-provider-profiles/${encodeURIComponent(String(item.profile_id))}/probe`, { method: "POST", body: "{}" });
      await load();
      onNotice(String(result.health_state || "").toUpperCase() === "HEALTHY"
        ? text("LLM 服务探活成功，状态已更新为健康。", "LLM provider probe passed; health state is Healthy.")
        : text("LLM 服务探活未通过，状态已更新为降级。", "LLM provider probe failed; health state is Degraded."));
    } catch (error) { onNotice((error as Error).message); } finally { setBusy(false); }
  };
  const profiles = listPayload(payload.profiles, ["items"]);
  const contracts = listPayload(payload.contracts, ["items"]);
  const spaces = listPayload(payload.spaces, ["items"]);
  const bindings = listPayload(payload.bindings, ["items"]);
  const jobs = listPayload(payload.jobs, ["items"]);
  const runs = listPayload(payload.runs, ["items"]);
  const readiness = payload.readiness?.readiness || {};
  const embeddingDeployed = Boolean(readiness.platform_deployed);
  return <section className={embedded ? "page-stack platform-configuration-subpage" : "page-stack"}>
    {!embedded && <SectionHeading title={text("部署与模型", "Deployment & models")} subtitle={text("Bootstrap Deployment Agent 仅在本地执行受校验安装；此处管理部署证据、LLM/Embedding 契约与重嵌入队列。", "The Bootstrap Deployment Agent runs verified installation locally; this view governs deployment evidence, LLM/Embedding Contracts, and re-embedding jobs.")} text={text} actions={<PageRefresh loading={loading} onRefresh={load} text={text} />} />}
    {embedded && <div className="embedded-page-heading"><h2>{text("模型与部署", "Models & deployment")}</h2><p>{text("统一管理 Embedding、LLM 契约、默认空间和受控部署结果。", "Manage Embedding, LLM Contracts, the default Space, and governed deployment results.")}</p></div>}
    {loading ? <PageLoading text={text} /> : <>
      <div className="metric-grid">
        <InfoPanel title={text("向量就绪状态", "Embedding readiness")} text={text}><strong className="metric-value">{displayRowValue(lang, readiness.state || "UNCONFIGURED")}</strong><p className="cx-form-hint">{text("只有已验证且可写的空间可以写入和参与向量检索。", "Only verified writable spaces can accept vectors or participate in vector retrieval.")}</p></InfoPanel>
        <InfoPanel title={text("默认空间", "Default space")} text={text}><strong className="metric-value metric-identifier">{String(readiness.space_key || "-")}</strong><p className="cx-form-hint metric-metadata">{text("配置", "Profile")}: {String(readiness.profile_key || "-")} · {text("维度", "Dimension")}: {String(readiness.dimension || "-")}<br />{text("空间 ID", "Space ID")}: <code>{String(readiness.space_id || "-")}</code><br />{text("契约 ID", "Contract ID")}: <code>{String(readiness.contract_id || "-")}</code></p></InfoPanel>
        <InfoPanel title={text("队列", "Queue")} text={text}><strong className="metric-value">{String(payload.readiness?.queue?.pending || 0)}</strong><p className="cx-form-hint">{text("待处理或已租约的重嵌入任务。", "Pending or leased re-embedding jobs.")}</p></InfoPanel>
      </div>
      {canManage && !embeddingDeployed && <InfoPanel title={text("配置统一 Embedding", "Configure platform Embedding")} text={text}>
        <div className="automation-boundary" role="status"><ShieldCheck size={14} />{text("标准流程：测试成功后自动识别维度并完成配置；不存在后续手工创建契约、空间、绑定或迁移任务的步骤。", "Standard flow: a successful test discovers the dimension and completes activation automatically; there is no later manual Contract, Space, Binding, or migration step.")}</div>
        <p className="cx-form-hint">{text("距离度量决定检索相似度的计算方式。除非模型服务明确要求其他度量，否则使用余弦距离；归一化为平台统一契约的强制规则。测试成功后平台自动维护配置、契约、默认空间、绑定和必要迁移任务。", "Distance metric defines similarity calculation. Use cosine unless the model service requires another metric; normalization is mandatory for the platform-wide Contract. After a successful test, the platform automatically maintains the Profile, Contract, default Space, binding, and required migration jobs.")}</p>
        <form ref={profileFormRef} className="configuration-form compact-configuration-form" onChange={() => { setDraftVersion((value) => value + 1); setTestedDraftVersion(null); setObservedDimension(null); }} onSubmit={(event) => event.preventDefault()}>
          <ConfigField label={text("配置键", "Profile key")} hint={text("平台内唯一、可读的标识。", "Unique, readable platform identifier.")}><input name="profile_key" required /></ConfigField>
          <ConfigField label={text("接入模式", "Execution mode")} hint={text("决定由谁调用模型服务。", "Determines who calls the model service.")}><select name="execution_mode" defaultValue="PLATFORM_MANAGED"><option value="PLATFORM_MANAGED">{text("平台托管", "Platform managed")}</option><option value="ENTERPRISE_DIRECT">{text("企业直连", "Enterprise direct")}</option><option value="ENTERPRISE_PROXY">{text("企业代理", "Enterprise proxy")}</option><option value="PRECOMPUTED_IMPORT">{text("预计算导入", "Precomputed import")}</option><option value="NONE">{text("不使用向量", "No vectors")}</option></select></ConfigField>
          <ConfigField label={text("模型服务地址", "Provider URL")} hint={text("填写服务根地址；探测时会使用 /embeddings。", "Enter the service root; probing uses /embeddings.")}><input name="provider_url" /></ConfigField>
          <ConfigField label={text("模型 ID", "Model ID")} hint={text("必须与所有写入该空间的智能体一致。", "Must match every Agent writing this space.")}><input name="model_id" /></ConfigField>
          <ConfigField label={text("向量维度", "Vector dimension")} hint={observedDimension ? text("已由模型测试自动识别；不可手工修改。", "Discovered by the provider test; cannot be edited manually.") : text("点击测试后由模型服务自动识别；不可手工填写。", "Discovered automatically by the provider test; do not enter it manually.")}><output className="derived-value" aria-live="polite">{observedDimension || text("待测试", "Pending test")}</output></ConfigField>
          <ConfigField label={text("距离度量", "Distance metric")} hint={text("推荐余弦距离；仅在服务要求时选择其他项。", "Cosine is recommended; choose another only when required.")}><select name="distance_metric" defaultValue="COSINE"><option value="COSINE">{text("余弦距离（推荐）", "Cosine (recommended)")}</option><option value="EUCLIDEAN">{text("欧氏距离", "Euclidean")}</option><option value="DOT_PRODUCT">{text("点积", "Dot product")}</option></select></ConfigField>
          <ConfigField label={text("向量归一化", "Normalize vectors")} hint={text("平台统一契约强制启用，所有写入同一空间的智能体使用一致规则；这不代表不同智能体会产生相同向量。", "The platform Contract enforces one rule for every Agent writing to the Space; this does not make Agents produce identical vectors.")}><output className="derived-value enforced-value">{text("平台强制启用", "Enforced by platform")}</output></ConfigField>
          <ConfigField label={text("API Key", "API key")} hint={text("如填写，仅以加密密文保存且不会回显；留空即按无 API Key 测试和保存。", "When provided, stored only as ciphertext and never returned; leave empty to test and save without an API key.")}><input name="api_key" type="password" autoComplete="new-password" /></ConfigField>
          <ConfigField label={text("企业密钥引用", "Enterprise secret reference")} hint={text("可替代直接保存密钥的企业密管引用。", "Enterprise secret-manager reference instead of a direct key.")}><input name="secret_reference" /></ConfigField>
          <ConfigField label={text("变更原因", "Change reason")} hint={text("写入审计记录，至少三个字符。", "Written to audit; at least three characters.")}><input name="reason" required /></ConfigField>
          <ConfigField label={text("自动测试并配置", "Test and configure automatically")} hint={testedDraftVersion === draftVersion ? text("已完成测试并自动维护统一契约、默认空间和平台绑定。", "The test passed and the unified Contract, default Space, and platform binding were maintained automatically.") : text("点击后先测试模型服务；成功后自动识别维度并完成平台配置。", "The provider is tested first; on success the dimension is discovered and platform configuration is completed automatically.")} action><button type="button" className="primary-button" disabled={busy || testing} onClick={() => void testProfile()}><Activity className={testing ? "spin" : ""} size={15} />{testing ? text("测试并配置中", "Testing and configuring") : text("测试并自动配置", "Test and configure")}</button></ConfigField>
        </form>
      </InfoPanel>}
      {canManage && embeddingDeployed && <InfoPanel title={text("统一 Embedding 已完成配置", "Platform Embedding configured")} text={text}>
        <div className="automation-boundary" role="status"><ShieldCheck size={14} />{text("统一 Embedding 契约已部署并绑定到平台默认空间。为保证所有智能体写入的向量一致，运行期不提供修改入口。", "The unified Embedding Contract is deployed and bound to the platform default Space. Runtime edits are unavailable to keep vector writes consistent for every Agent.")}</div>
        <p className="cx-form-hint">{text("如需更换模型、接入模式、距离度量或密钥引用，请使用新版平台包重新部署。重新部署会按受控流程建立新的契约、空间和绑定，不会在运行期改写当前统一契约。", "To change the model, execution mode, distance metric, or secret reference, redeploy with a new platform package. Redeployment creates a new governed Contract, Space, and binding instead of changing the active unified Contract at runtime.")}</p>
      </InfoPanel>}
      <InfoPanel title={text("自动化结果", "Automated results")} text={text}><p className="cx-form-hint">{text("配置、契约、默认空间、平台绑定和迁移任务均由上方的自动化流程维护。以下为只读状态，不提供手工创建、修改或补偿入口。", "The configuration, Contract, default Space, platform binding, and migration jobs are maintained by the automated workflow above. These are read-only results; no manual create, update, or compensation path is available here.")}</p><DataTable headers={[text("配置", "Profile"), text("模式", "Mode"), text("模型", "Model"), text("维度", "Dimension"), text("密钥", "Secret"), text("状态", "State")]} rows={profiles.map((item) => [item.profile_key, displayRowValue(lang, item.execution_mode), item.model_id || "-", item.dimension, item.secret_present ? text("已加密", "Encrypted") : "-", displayRowValue(lang, item.health_state)])} empty={text("尚未配置 Embedding", "No Embedding configured")} text={text} /><DataTable headers={[text("契约", "Contract"), text("模型", "Model"), text("维度", "Dimension"), text("模式", "Mode"), text("状态", "State")]} rows={contracts.map((item) => [item.contract_id, item.model_id || "-", item.dimension, displayRowValue(lang, item.execution_mode), displayRowValue(lang, item.status)])} empty={text("尚未创建契约", "No Contract created")} text={text} /><DataTable headers={[text("空间", "Space"), text("契约", "Contract"), text("验证", "Validation"), text("默认", "Default"), text("可写", "Writable")]} rows={spaces.map((item) => [item.space_key, item.contract_id || "-", displayRowValue(lang, item.validation_state), item.is_default, item.write_enabled])} empty={text("尚未创建空间", "No Space created")} text={text} />
      <DataTable headers={[text("范围", "Scope"), text("主体", "Subject"), text("配置", "Profile"), text("空间", "Space"), text("版本", "Version")]} rows={bindings.map((item) => [displayRowValue(lang, item.binding_scope), item.binding_subject_id, item.profile_key || item.profile_id, item.space_key || item.space_id, item.version])} empty={text("平台默认绑定尚未建立", "No platform default binding")} text={text} /><DataTable headers={[text("任务", "Job"), text("类型", "Kind"), text("状态", "State"), text("目标空间", "Target space"), text("时间", "Time")]} rows={jobs.map((item) => [item.job_id, displayRowValue(lang, item.job_kind), displayRowValue(lang, item.status), item.target_space_id, displayRowValue(lang, item.created_at)])} empty={text("没有自动迁移任务", "No automated migration jobs")} text={text} /></InfoPanel>
      <InfoPanel title={text("部署证据", "Deployment evidence")} text={text}><DataTable headers={[text("运行", "Run"), text("数据库", "Database"), text("版本", "Version"), text("状态", "State"), text("当前步骤", "Current step"), text("时间", "Time")]} rows={runs.map((item) => [item.run_id, item.database_dialect, item.package_version, displayRowValue(lang, item.status), item.current_step || "-", displayRowValue(lang, item.updated_at)])} empty={text("当前数据库没有部署证据", "No deployment evidence in this database")} text={text} /></InfoPanel>
    </>}
  </section>;
}

function NativeAgentsPage({
  lang,
  me,
  capabilities,
  text,
  onNotice,
  embedded = false,
}: {
  lang: Lang;
  me: Row;
  capabilities: Row | null;
  text: (zh: string, en: string) => string;
  onNotice: (value: string) => void;
  embedded?: boolean;
}) {
  const [data, setData] = useState<Row>({ agents: [], templates: [], manifests: [], profiles: [], requests: [], targets: [], bootstrap: null });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [bootstrapFeedback, setBootstrapFeedback] = useState("");
  const [selected, setSelected] = useState<Row | null>(null);
  const [configuringAgent, setConfiguringAgent] = useState<Row | null>(null);
  const [pageSize, setPageSize] = useState(20);
  const [cursorHistory, setCursorHistory] = useState<string[]>([""]);
  const [nextCursor, setNextCursor] = useState("");
  const [totalItems, setTotalItems] = useState<number | undefined>(undefined);
  const canManage = canAction(capabilities, "platform.manage") || canAction(capabilities, "agents.manage");
  const canEnroll = canAction(capabilities, "agents.enroll");
  const canDecide = canAction(capabilities, "agents.manage");
  const refreshProfileHealth = async (profilePayload: Row) => {
    const items = listPayload(profilePayload, ["items"]);
    const active = items.filter((item) => String(item.status || "ACTIVE").toUpperCase() === "ACTIVE");
    if (!active.length) return;
    const results = await Promise.all(active.map(async (item) => {
      try {
        const probe = await api<Row>(`/api/llm-provider-profiles/${encodeURIComponent(String(item.profile_id))}/probe`, { method: "POST", body: "{}" });
        return [String(item.profile_id), String(probe.health_state || "HEALTHY").toUpperCase()] as const;
      } catch {
        return [String(item.profile_id), "DEGRADED"] as const;
      }
    }));
    setData((current) => {
      const currentProfiles = current.profiles;
      const updatedItems = listPayload(currentProfiles, ["items"]).map((item) => {
        const result = results.find(([profileId]) => profileId === String(item.profile_id));
        return result ? { ...item, health_state: result[1] } : item;
      });
      return { ...current, profiles: Array.isArray(currentProfiles) ? updatedItems : { ...currentProfiles, items: updatedItems } };
    });
  };
  const load = async (cursor = cursorHistory[cursorHistory.length - 1] || "", size = pageSize) => {
    setLoading(true);
    try {
      const [bootstrap, agents, templates, manifests, profiles, requests, targets] = await Promise.all([
        api<Row>("/api/platform/native-bootstrap"),
        api<Row>(`/api/native-agents?page_size=${size}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`),
        api<Row>("/api/agent-templates?limit=100"),
        api<Row>("/api/native-manifests?limit=100"),
        api<Row>("/api/llm-provider-profiles?limit=100"),
        api<Row>("/api/agent-provision-requests?limit=100"),
        api<Row>("/api/deployment-targets?limit=100"),
      ]);
      setData({ bootstrap, agents, templates, manifests, profiles, requests, targets });
      void refreshProfileHealth(profiles);
      setNextCursor(String(agents.next_cursor || ""));
      setTotalItems(typeof agents.total_items === "number" ? agents.total_items : undefined);
    } catch (error) {
      onNotice((error as Error).message);
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { void load(); }, []);
  const changePageSize = (value: number) => {
    setPageSize(value); setCursorHistory([""]); setNextCursor(""); void load("", value);
  };
  const nextPage = () => {
    if (!nextCursor) return;
    const history = [...cursorHistory, nextCursor];
    setCursorHistory(history); void load(nextCursor);
  };
  const previousPage = () => {
    if (cursorHistory.length <= 1) return;
    const history = cursorHistory.slice(0, -1);
    setCursorHistory(history); void load(history[history.length - 1]);
  };
  const agents = listPayload(data.agents, ["items"]);
  const templates = listPayload(data.templates, ["items"]);
  const manifests = listPayload(data.manifests, ["items"]);
  const profiles = listPayload(data.profiles, ["items"]);
  const requests = listPayload(data.requests, ["items"]);
  const targets = listPayload(data.targets, ["items"]);
  const referenceAdapters = listPayload(data.targets, ["reference_adapters"]);
  const submitRequest = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    setBusy(true);
    try {
      await api("/api/agent-provision-requests", { method: "POST", body: JSON.stringify({
        agent_name: String(form.get("agent_name") || ""), owner_principal_id: String(form.get("owner_principal_id") || me.principal_id || ""),
        template_key: String(form.get("template_key") || ""), provider_profile_id: String(form.get("provider_profile_id") || ""),
        deployment_target_id: String(form.get("deployment_target_id") || "DT_LOCAL_MANAGED"), isolation_level: String(form.get("isolation_level") || "DOMAIN_ISOLATED"),
        classification: String(form.get("classification") || "INTERNAL"), purpose: String(form.get("purpose") || ""), reason: String(form.get("reason") || ""),
      }) });
      formElement.reset(); await load(); onNotice(text("业务智能体申请已提交，等待职责分离审批", "Business Agent request submitted for separated approval"));
    } catch (error) { onNotice((error as Error).message); } finally { setBusy(false); }
  };
  const decide = async (request: Row, decision: string) => {
    const why = window.prompt(text("请输入审批原因", "Enter the decision reason")) || "";
    if (why.trim().length < 3) return;
    setBusy(true);
    try {
      await api(`/api/agent-provision-requests/${encodeURIComponent(String(request.request_id))}/decision`, { method: "POST", body: JSON.stringify({ decision, reason: why.trim() }) });
      await load(); onNotice(text("申请状态已更新并记录审计", "Request state was updated and audited"));
    } catch (error) { onNotice((error as Error).message); } finally { setBusy(false); }
  };
  const activate = async (agent: Row, profileId = String(profiles[0]?.profile_id || "")) => {
    if (!profileId) { onNotice(text("请先配置一个 LLM 服务商配置", "Configure an LLM Provider Profile first")); return; }
    const why = window.prompt(text("请输入激活原因", "Enter the activation reason")) || "";
    if (why.trim().length < 3) return;
    setBusy(true);
    try {
      await api(`/api/native-agents/${encodeURIComponent(String(agent.agent_id))}/activate`, { method: "POST", body: JSON.stringify({ llm_profile_id: profileId, reason: why.trim() }) });
      await load(); onNotice(text("智能体已激活", "Agent activated"));
    } catch (error) { onNotice((error as Error).message); } finally { setBusy(false); }
  };
  const statusLabel = (value: unknown) => displayRowValue(lang, value || "-");
  const bootstrapStatusLabel = (value: unknown) => {
    const state = String(value || "").toUpperCase();
    if (state === "READY") return text("初始化已就绪", "Bootstrap ready");
    if (state === "MIGRATION_PENDING") return text("等待数据库迁移", "Waiting for database migration");
    return statusLabel(state || "-");
  };
  return <>
    {!embedded && <SectionHeading title={text("原生智能体", "Native Agents")} subtitle={text("平台原生管理智能体不依赖外部 Agent；业务智能体通过申请、审批、部署和激活形成可审计生命周期。LLM 只提供推理能力，不是安全边界。", "Platform-native management Agents bootstrap without an external Agent; business Agents follow an auditable request, approval, deployment, and activation lifecycle. An LLM provides reasoning only and is never a security boundary.")} text={text} actions={<PageRefresh loading={loading} onRefresh={load} text={text} />} />}
    {loading ? <PageLoading text={text} /> : <>
      <div className="metric-grid native-summary-grid">
        <InfoPanel title={text("初始化状态", "Bootstrap status")} text={text}><strong className="metric-value">{bootstrapStatusLabel(data.bootstrap?.status)}</strong><p className="cx-form-hint">{text("初始化只创建和校验平台管理智能体，不调用模型。智能体是否可执行由下方“状态”和“模型配置”决定。", "Bootstrap only creates and verifies platform management Agents; it makes no model call. Execution readiness is determined by each Agent's status and model profile below.")}</p>{bootstrapFeedback && <p className="operation-feedback" role="status">{bootstrapFeedback}</p>}{canManage && <button type="button" className="primary-button" disabled={busy} onClick={async () => { setBusy(true); setBootstrapFeedback(text("正在检查并初始化平台原生智能体...", "Checking and initializing platform-native Agents...")); try { const result = await api<Row>("/api/platform/native-bootstrap", { method: "POST", body: "{}" }); await load(); const completed = ["READY", "COMPLETED"].includes(String(result.status || "").toUpperCase()); const message = completed ? text("平台原生智能体初始化已完成；当前状态已刷新。", "Platform-native Agent initialization is complete and the current status was refreshed.") : text(`初始化已处理，当前状态：${bootstrapStatusLabel(result.status)}。`, `Initialization was processed. Current status: ${bootstrapStatusLabel(result.status)}.`); setBootstrapFeedback(message); onNotice(message); } catch (error) { const message = (error as Error).message; setBootstrapFeedback(message); onNotice(message); } finally { setBusy(false); } }}><Bot className={busy ? "spin" : ""} size={15} />{busy ? text("处理中", "Working") : text("初始化或刷新状态", "Initialize or refresh status")}</button>}</InfoPanel>
      </div>
        <InfoPanel title={text("平台内置管理智能体", "Built-in management Agents")} text={text}><p className="cx-form-hint">{text("内置管理智能体必须先绑定已批准的 LLM 服务商配置，配置和激活均写入审计。", "Built-in management Agents require an approved LLM Provider Profile; configuration and activation are audited.")}</p><CursorPager pageSize={pageSize} page={cursorHistory.length} totalItems={totalItems} hasMore={Boolean(nextCursor)} loading={loading} onPageSize={changePageSize} onPrevious={previousPage} onNext={nextPage} text={text} /><DataTable headers={[text("智能体", "Agent"), text("来源", "Source"), text("状态", "Status"), text("模型配置", "LLM profile"), text("操作", "Action")]} rows={agents.map((item) => [<button type="button" className="table-link" onClick={() => setSelected(item)}>{String(item.agent_id)}</button>, statusLabel(item.source), statusLabel(item.status), String(item.llm_profile_id || text("未配置", "Not configured")), canManage ? <span className="actions-row"><button type="button" className="small-button" disabled={busy} onClick={() => setConfiguringAgent(item)}>{text("配置模型", "Configure model")}</button>{String(item.status).toUpperCase() !== "ACTIVE" && <><button type="button" className="small-button" disabled={busy || !profiles.length} onClick={() => void activate(item)} title={!profiles.length ? text("请先创建 LLM 服务商配置", "Create an LLM Provider Profile first") : text("激活智能体", "Activate Agent")}>{text("激活", "Activate")}</button>{!profiles.length && <small className="button-hint">{text("请先配置模型", "Configure a model first")}</small>}</>} </span> : statusLabel(item.activation_state)])} empty={text("暂无可见原生智能体", "No visible native Agents")} text={text} /><CursorPager pageSize={pageSize} page={cursorHistory.length} totalItems={totalItems} hasMore={Boolean(nextCursor)} loading={loading} onPageSize={changePageSize} onPrevious={previousPage} onNext={nextPage} text={text} /></InfoPanel>
      <InfoPanel title={text("业务智能体申请", "Business Agent request")} text={text}><p className="cx-form-hint">{text("申请不会直接创建运行中的智能体；需要经过职责分离审批，随后按目标环境部署和激活。", "A request does not create a running Agent directly. It requires separated approval, then deployment and activation in the target environment.")}</p><form className="configuration-form native-request-form" onSubmit={submitRequest}><ConfigField label={text("智能体名称", "Agent name")} hint={text("面向业务的可读名称。", "Readable business-facing name.")}><input name="agent_name" required /></ConfigField><ConfigField label={text("受管模板", "Managed template")} hint={text("模板是能力倾向、隔离要求和安全基线的受管选项，不会直接授予数据库、网络、Skill 或 Tool 权限。", "A template is a managed option for capability tendencies, isolation requirements, and security baselines; it does not directly grant database, network, Skill, or Tool authority.")}><select name="template_key" required>{templates.filter((item) => String(item.template_kind).toUpperCase() === "BUSINESS").map((item) => <option key={item.template_key} value={item.template_key}>{item.display_name}</option>)}</select></ConfigField><ConfigField label={text("负责人账户", "Owner account")} hint={text("默认当前申请人；填写已存在的用户账号 ID。", "Defaults to the requester; enter an existing user account ID.")}><input name="owner_principal_id" required /></ConfigField><ConfigField label={text("LLM 配置", "LLM profile")} hint={text("可延后配置，但激活前必须绑定已批准配置。", "May be set later, but is mandatory before activation.")}><select name="provider_profile_id" defaultValue=""><option value="">{text("稍后配置", "Configure later")}</option>{profiles.map((item) => <option key={item.profile_id} value={item.profile_id}>{item.profile_key}</option>)}</select></ConfigField><ConfigField label={text("部署目标", "Deployment target")} hint={text("选择受管运行时或已接入的目标。", "Choose a managed runtime or connected target.")}><select name="deployment_target_id" defaultValue="DT_LOCAL_MANAGED">{targets.map((item) => <option key={item.target_id} value={item.target_id}>{item.target_key} · {item.target_type}</option>)}</select></ConfigField><ConfigField label={text("隔离级别", "Isolation level")} hint={text("隔离范围由部署适配器和数据库授权共同执行。", "Enforced by the deployment adapter and database authorization.")}><select name="isolation_level" defaultValue="DOMAIN_ISOLATED"><option value="DOMAIN_ISOLATED">{text("域隔离", "Domain isolated")}</option><option value="DEDICATED_CONTAINER">{text("专用容器", "Dedicated container")}</option><option value="DEDICATED_RUNTIME">{text("专用运行时", "Dedicated runtime")}</option></select></ConfigField><ConfigField label={text("数据分类", "Data classification")} hint={text("用于审批和后续治理策略。", "Used for approval and downstream governance.")}><select name="classification" defaultValue="INTERNAL"><option value="INTERNAL">{text("内部", "Internal")}</option><option value="CONFIDENTIAL">{text("机密", "Confidential")}</option><option value="RESTRICTED">{text("受限", "Restricted")}</option></select></ConfigField><ConfigField label={text("业务目的", "Business purpose")} hint={text("说明预期工作及获准访问范围。", "Describe intended work and approved access scope.")} multiline><textarea name="purpose" required /></ConfigField><ConfigField label={text("申请原因", "Request reason")} hint={text("写入审计记录，至少三个字符。", "Written to audit; at least three characters.")}><input name="reason" required /></ConfigField><ConfigField label={text("操作", "Action")} hint={text("提交后进入职责分离审批队列。", "Submits the request to separated approval.")} action><button className="primary-button" disabled={busy || !canEnroll}><Plus size={15} />{text("提交申请", "Submit request")}</button></ConfigField></form></InfoPanel>
      <InfoPanel title={text("申请与审批", "Requests and approvals")} text={text}><DataTable headers={[text("名称", "Name"), text("模板", "Template"), text("隔离", "Isolation"), text("状态", "Status"), text("操作", "Action")]} rows={requests.map((item) => [String(item.agent_name), String(item.template_key), displayRowValue(lang, item.isolation_level), statusLabel(item.status), String(item.status).toUpperCase() === "APPROVAL_PENDING" && canDecide ? <span className="actions-row"><button className="small-button" disabled={busy} onClick={() => void decide(item, "APPROVE")}>{text("批准", "Approve")}</button><button className="small-button" disabled={busy} onClick={() => void decide(item, "REJECT")}>{text("拒绝", "Reject")}</button></span> : statusLabel(item.decided_by || item.applicant_principal_id)])} empty={text("暂无可见申请", "No visible requests")} text={text} /></InfoPanel>
      <div className="native-contract-panels">
        <InfoPanel title={text("受管 Skill / Tool 清单", "Managed Skill / Tool manifests")} text={text}><p className="cx-form-hint">{text("内置清单按版本和摘要固定，普通读取不暴露私钥；业务 Agent 只能继承已审批清单。", "Built-in manifests are pinned by version and digest; ordinary reads never expose private keys, and business Agents may inherit only approved manifests.")}</p><DataTable headers={[text("清单", "Manifest"), text("类型", "Kind"), text("版本", "Version"), text("校验", "Verification"), text("状态", "Status")]} rows={manifests.map((item) => [item.manifest_key, displayRowValue(lang, item.manifest_kind), item.version, statusLabel(item.signature_status), statusLabel(item.status)])} empty={text("暂无受管清单", "No managed manifests")} text={text} /></InfoPanel>
        <InfoPanel title={text("部署适配器契约", "Deployment adapter contract")} text={text}><p className="cx-form-hint">{text("以下是平台提供的参考生命周期，不代表已经内置客户专属虚拟化、SaaS、MaaS 或 Agent 平台连接器。连接器必须保留数据库授权、隔离、回调校验和审计边界。", "These are reference lifecycle contracts, not built-in customer-specific virtualization, SaaS, MaaS, or Agent connectors. Every connector must preserve database authorization, isolation, callback validation, and audit boundaries.")}</p><DataTable headers={[text("类型", "Type"), text("生命周期", "Lifecycle"), text("网络调用", "Network calls"), text("说明", "Note")]} rows={referenceAdapters.map((item) => [item.target_type, (item.lifecycle || []).join(" · "), item.network_calls ? text("允许", "Allowed") : text("不执行", "None"), item.security_note])} empty={text("暂无适配器契约", "No adapter contracts")} text={text} /></InfoPanel>
      </div>
    </>}
    <DetailDrawer open={Boolean(configuringAgent)} title={text("配置内置智能体模型", "Configure built-in Agent model")} onClose={() => setConfiguringAgent(null)} text={text}>
      {configuringAgent && <form className="cx-form native-agent-activation-form" onSubmit={async (event) => { event.preventDefault(); const form = new FormData(event.currentTarget); const profileId = String(form.get("llm_profile_id") || ""); const why = String(form.get("reason") || "").trim(); if (!profileId || why.length < 3) return; setBusy(true); try { await api(`/api/native-agents/${encodeURIComponent(String(configuringAgent.agent_id))}/activate`, { method: "POST", body: JSON.stringify({ llm_profile_id: profileId, reason: why }) }); await load(); setConfiguringAgent(null); onNotice(text("模型配置已绑定，智能体已激活", "Model profile was bound and the Agent activated")); } catch (error) { onNotice((error as Error).message); } finally { setBusy(false); } }}><p className="cx-form-hint">{text("选择已批准的 LLM 服务商配置。提交会绑定该配置并激活此内置管理智能体；操作可审计。", "Select an approved LLM Provider Profile. Submitting binds it and activates this built-in management Agent; the action is audited.")}</p><ConfigField label={text("LLM 服务商配置", "LLM Provider Profile")} hint={text("只能选择已批准且可用的模型配置。", "Only an approved and available model profile may be selected.")}><select name="llm_profile_id" required defaultValue={String(configuringAgent.llm_profile_id || "")}><option value="" disabled>{text("请选择", "Select a profile")}</option>{profiles.map((item) => <option key={item.profile_id} value={item.profile_id}>{item.profile_key} · {item.model_id}</option>)}</select></ConfigField><ConfigField label={text("配置原因", "Configuration reason")} hint={text("至少三个字符，并写入审计记录。", "At least three characters and written to the audit record.")} multiline><textarea name="reason" required /></ConfigField><ConfigField label={text("操作", "Action")} hint={text("绑定配置后才会激活智能体。", "The Agent is activated only after the profile is bound.")} action><button className="primary-button" disabled={busy || !profiles.length}><Check size={15} />{text("配置并激活", "Configure and activate")}</button></ConfigField>{!profiles.length && <p className="cx-form-hint">{text("请先在本页下方创建 LLM 服务商配置。", "Create an LLM Provider Profile below first.")}</p>}</form>}
    </DetailDrawer>
    <DetailDrawer open={Boolean(selected)} title={text("原生智能体详情", "Native Agent details")} onClose={() => setSelected(null)} text={text}><pre className="decision-box">{selected ? JSON.stringify(selected, null, 2) : ""}</pre></DetailDrawer>
  </>;
}

function MemoryLifecyclePage({
  lang,
  text,
  onNotice,
}: {
  lang: Lang;
  text: (zh: string, en: string) => string;
  onNotice: (value: string) => void;
}) {
  type MemoryView = "overview" | "library" | "chain" | "workbench" | "jobs";
  const [view, setView] = useUrlState<MemoryView>(
    "view",
    ["overview", "library", "chain", "workbench", "jobs"],
    "overview",
  );
  const [payload, setPayload] = useState<Row>({ nodes: [], edges: [] });
  const [jobs, setJobs] = useState<Row[]>([]);
  const [candidates, setCandidates] = useState<Row[]>([]);
  const [policies, setPolicies] = useState<Row[]>([]);
  const [selected, setSelected] = useState<Row | null>(null);
  const [chainData, setChainData] = useState<Row>({ nodes: [], relations: [] });
  const [loading, setLoading] = useState(true);
  const [libraryMode, setLibraryMode] = useUrlState<"list" | "graph">(
    "library",
    ["list", "graph"],
    "list",
  );
  const [libraryItems, setLibraryItems] = useState<Row[]>([]);
  const [libraryPageSize, setLibraryPageSize] = useState(20);
  const [libraryCursorHistory, setLibraryCursorHistory] = useState<string[]>([""]);
  const [libraryNextCursor, setLibraryNextCursor] = useState("");
  const [libraryTotalItems, setLibraryTotalItems] = useState<number | undefined>(undefined);
  const load = async () => {
    setLoading(true);
    try {
      const [memory, jobValue, candidateValue, policyValue] = await Promise.all([
        api<Row>("/api/memory"), api<Row>("/api/memory/jobs"),
        api<Row>("/api/memory/candidates"), api<Row>("/api/memory/policies"),
      ]);
      setPayload(memory);
      setJobs(listPayload(jobValue, ["jobs"]));
      setCandidates(listPayload(candidateValue, ["candidates"]));
      setPolicies(listPayload(policyValue, ["policies"]));
    } catch (error) {
      onNotice(error instanceof Error ? error.message : text("加载记忆生命周期失败", "Memory lifecycle loading failed"));
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { void load(); }, []);
  const loadLibrary = async (cursor = libraryCursorHistory[libraryCursorHistory.length - 1] || "", size = libraryPageSize) => {
    setLoading(true);
    try {
      const value = await api<Row>(`/api/memory/inventory?page_size=${size}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`);
      setLibraryItems(listPayload(value, ["memories", "items"]));
      setLibraryNextCursor(String(value.next_cursor || ""));
      setLibraryTotalItems(typeof value.total_items === "number" ? value.total_items : undefined);
    } catch (error) {
      onNotice(error instanceof Error ? error.message : text("加载记忆库失败", "Memory Library loading failed"));
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    if (view === "library" && libraryMode === "list") void loadLibrary();
  }, [view, libraryMode]);
  const changeLibraryPageSize = (size: number) => {
    setLibraryPageSize(size); setLibraryCursorHistory([""]); setLibraryNextCursor(""); void loadLibrary("", size);
  };
  const nextLibraryPage = () => {
    if (!libraryNextCursor) return;
    const history = [...libraryCursorHistory, libraryNextCursor];
    setLibraryCursorHistory(history); void loadLibrary(libraryNextCursor);
  };
  const previousLibraryPage = () => {
    if (libraryCursorHistory.length <= 1) return;
    const history = libraryCursorHistory.slice(0, -1);
    setLibraryCursorHistory(history); void loadLibrary(history[history.length - 1]);
  };
  const openChain = async (item: Row) => {
    setSelected(item);
    setView("chain");
    if (!item.family_id) return;
    setLoading(true);
    try {
      setChainData(await api<Row>(`/api/memory/${encodeURIComponent(String(item.family_id))}/chain`));
    } catch (error) {
      onNotice(error instanceof Error ? error.message : text("读取记忆链失败", "Memory chain loading failed"));
    } finally { setLoading(false); }
  };
  const startJob = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.currentTarget).entries());
    const reason = String(data.reason || "").trim();
    if (!reason) { onNotice(text("整理作业必须填写原因", "A consolidation reason is required")); return; }
    try {
      await api("/api/memory/x/jobs", { method: "POST", body: JSON.stringify({ job_type: data.job_type, dry_run: data.dry_run === "true", reason, scope: { memory_scope: data.memory_scope || "" } }) });
      onNotice(text("已创建受控整理作业", "Governed consolidation job created"));
      await load();
    } catch (error) { onNotice(error instanceof Error ? error.message : text("作业创建失败", "Job creation failed")); }
  };
  const propose = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selected?.family_id || !selected?.version_id) { onNotice(text("请先从记忆库选择当前版本", "Select a current version from the Library first")); return; }
    const data = Object.fromEntries(new FormData(event.currentTarget).entries());
    const reason = String(data.reason || "").trim();
    if (!reason) { onNotice(text("候选变更必须填写原因", "Candidate changes require a reason")); return; }
    try {
      await api(`/api/memory/${encodeURIComponent(String(selected.family_id))}/candidates`, { method: "POST", body: JSON.stringify({ candidate_type: data.candidate_type, source_version_id: selected.version_id, confidence: Number(data.confidence || 0), reason, proposed: { title: selected.title, note: data.note || "" } }) });
      onNotice(text("候选已提交，语义变更不会直接替换当前记忆", "Candidate submitted; semantic changes do not replace the current memory directly"));
      await load();
    } catch (error) { onNotice(error instanceof Error ? error.message : text("候选提交失败", "Candidate submission failed")); }
  };
  const nodes = payload.nodes || [];
  const tabs: [MemoryView, string, string, typeof Layers3][] = [
    ["overview", "概览", "Overview", Layers3], ["library", "记忆库", "Library", List],
    ["chain", "记忆链", "Chain", Network], ["workbench", "整理工作台", "Consolidation workbench", GitCompareArrows],
    ["jobs", "策略与作业", "Policies and jobs", Activity],
  ];
  return <section>
    <SectionHeading title={text("记忆", "Memory")} subtitle={text("版本化记忆将内容、使用事件和动态效果分离；默认只向运行提供当前且获授权的版本。", "Versioned Memory separates content, usage events, and dynamic effectiveness; only current authorized versions are returned to runtime by default.")} text={text} actions={<PageRefresh loading={loading} onRefresh={load} text={text} />} />
    <div className="hierarchical-tabs-row">
      <ViewToggle className="hierarchical-root-tabs" value={view} options={tabs.map(([key, zh, en, Icon]) => [key, text(zh, en), Icon])} onChange={(value) => setView(value as MemoryView)} />
      {view === "library" && <>
        <span className="hierarchical-tabs-separator" aria-hidden="true" />
        <ViewToggle className="hierarchical-secondary-tabs" value={libraryMode} options={[["list", text("列表", "List"), List], ["graph", text("关系图", "Graph"), Network]]} onChange={(value) => setLibraryMode(value as "list" | "graph")} />
      </>}
    </div>
    {loading && <PageLoading text={text} />}
    {!loading && view === "overview" && <div className="cx-metric-grid">
      <InfoPanel title={text("当前可用版本", "Current usable versions")} text={text}><strong className="metric-value">{nodes.length}</strong><p>{text("不包含已归档、隔离和逻辑不可用版本。", "Archived, quarantined, and logically unavailable versions are excluded.")}</p></InfoPanel>
      <InfoPanel title={text("待复核候选", "Candidates awaiting review")} text={text}><strong className="metric-value">{candidates.filter((item) => item.status === "PENDING").length}</strong><p>{text("语义合并、替换、冲突与范围扩展需要受控复核。", "Semantic merge, replacement, conflict, and scope expansion remain governed.")}</p></InfoPanel>
      <InfoPanel title={text("整理作业", "Consolidation jobs")} text={text}><strong className="metric-value">{jobs.length}</strong><p>{text("先预览影响，再执行受策略约束的整理。", "Preview impact before policy-governed organization work.")}</p></InfoPanel>
    </div>}
    {view === "library" && <>
      {libraryMode === "graph" ? <NetworkGraph nodes={nodes} edges={payload.edges || []} lang={lang} title={text("记忆关系图", "Memory relationship graph")} loading={loading} text={text} onSelect={openChain} showFilters /> : <InfoPanel title={text("当前记忆库", "Current Memory library")} text={text}><p className="cx-form-hint">{text("点击条目查看可授权的版本链与关系；历史内容不会在此预加载。", "Click an item to inspect its authorized version chain and relationships; historical bodies are not preloaded here.")}</p>{!loading && <CursorPager pageSize={libraryPageSize} page={libraryCursorHistory.length} totalItems={libraryTotalItems} hasMore={Boolean(libraryNextCursor)} loading={loading} onPageSize={changeLibraryPageSize} onPrevious={previousLibraryPage} onNext={nextLibraryPage} text={text} />}{loading ? <PageLoading text={text} /> : <DataTable headers={[text("标题", "Title"), text("类型", "Type"), text("范围", "Scope"), text("状态", "State"), text("版本", "Version")]} rows={libraryItems.map((item: Row) => [<button className="text-button" onClick={() => void openChain(item)}>{displayRowValue(lang, item.title || item.label)}</button>, displayRowValue(lang, item.memory_type || item.category), displayRowValue(lang, item.memory_scope), displayRowValue(lang, item.lifecycle_state), item.version_number || "-"])} empty={text("当前权限范围内没有可用记忆", "No usable Memory is visible in the current authorization scope")} text={text} />}{!loading && <CursorPager pageSize={libraryPageSize} page={libraryCursorHistory.length} totalItems={libraryTotalItems} hasMore={Boolean(libraryNextCursor)} loading={loading} onPageSize={changeLibraryPageSize} onPrevious={previousLibraryPage} onNext={nextLibraryPage} text={text} />}</InfoPanel>}
    </>}
    {!loading && view === "chain" && <>
      <InfoPanel title={text("记忆链", "Memory chain")} text={text}><p className="cx-form-hint">{text("链路使用有界关系遍历。推断关系是证据，不构成授权或事实权威。", "Chains use bounded traversal. Inferred relations are evidence, not authority or authorization.")}</p></InfoPanel>
      <NetworkGraph nodes={chainData.nodes || []} edges={(chainData.relations || []).map((item: Row) => ({ from: item.source_version_id, to: item.target_version_id, label: item.relation_type, value: item.confidence || 1 }))} lang={lang} title={selected?.title || text("选择一条记忆", "Select a memory")} loading={false} text={text} onSelect={() => undefined} compact showFilters />
    </>}
    {!loading && view === "workbench" && <div className="cx-memory-workbench">
      <InfoPanel title={text("受控候选", "Governed candidate")} text={text}>
        <p className="cx-form-hint">{text("候选只进入复核队列，不会自动替换当前记忆。置信度仅用于排序，范围为 0 至 1。", "Candidates enter review only and never replace current Memory automatically. Confidence ranks review priority from 0 to 1.")}</p>
        <form className="workbench-form" onSubmit={propose}>
          <label className="workbench-field"><span>{text("候选类型", "Candidate type")}</span><select name="candidate_type" defaultValue="REPLACE"><option value="REPLACE">{text("替换", "Replace")}</option><option value="MERGE">{text("合并", "Merge")}</option><option value="CONFLICT">{text("冲突", "Conflict")}</option><option value="SCOPE_CHANGE">{text("范围调整", "Scope change")}</option></select><small>{text("指定需要复核的变更方式。", "Select the change that requires review.")}</small></label>
          <label className="workbench-field"><span>{text("置信度", "Confidence")}</span><input name="confidence" type="number" min="0" max="1" step="0.01" defaultValue="0.8" title={text("候选与当前记忆的匹配程度，0 最低、1 最高；仅用于复核排序。", "Candidate match level: 0 is lowest and 1 is highest; it is used only for review priority.")} /><small>{text("数值越高，复核排序越靠前。", "Higher values are reviewed earlier.")}</small></label>
          <label className="workbench-field"><span>{text("候选说明", "Candidate note")}</span><input name="note" /><small>{text("记录建议内容，不会覆盖原始记忆。", "Records the proposal without overwriting source Memory.")}</small></label>
          <label className="workbench-field"><span>{text("提交原因", "Submission reason")}</span><input name="reason" required /><small>{text("写入审计记录，说明为何提出变更。", "Written to audit records to explain the request.")}</small></label>
          <div className="workbench-field workbench-action"><span>{text("操作", "Action")}</span><button className="primary-button"><GitCompareArrows size={15} />{text("提交候选", "Submit candidate")}</button><small>{text("仅创建待复核候选。", "Creates a review-pending candidate only.")}</small></div>
        </form>
      </InfoPanel>
      <InfoPanel title={text("受控整理作业", "Governed consolidation job")} text={text}>
        <p className="cx-form-hint">{text("默认创建仅预览作业。创建执行作业只会入队；已注册 Worker 取得租约后，才按策略和审计边界处理，不会在提交时直接覆盖当前记忆。", "The default creates a preview-only job. An execution job is queued first; a registered Worker processes it only after acquiring a lease, under policy and audit boundaries, without overwriting current Memory on submission.")}</p>
        <form className="workbench-form" onSubmit={startJob}>
          <label className="workbench-field"><span>{text("作业类型", "Job type")}</span><select name="job_type" defaultValue="CONSOLIDATE"><option value="CONSOLIDATE">{text("整理", "Consolidate")}</option><option value="ARCHIVE_REVIEW">{text("归档复核", "Archive review")}</option><option value="REPRESENT">{text("生成表示层", "Build representations")}</option><option value="DISCOVER_RELATIONS">{text("发现关系", "Discover relations")}</option></select><small>{text("定义队列项的处理目的。", "Defines the purpose for queued items.")}</small></label>
          <label className="workbench-field"><span>{text("记忆范围", "Memory scope")}</span><select name="memory_scope"><option value="">{text("全部范围", "All scopes")}</option><option value="AGENT_MEMORY">{text("智能体记忆", "Agent memory")}</option><option value="WORKSPACE_MEMORY">{text("工作区记忆", "Workspace memory")}</option></select><small>{text("限制入队对象；服务端仍会校验权限。", "Limits queued subjects; the server still checks authorization.")}</small></label>
          <label className="workbench-field"><span>{text("运行模式", "Run mode")}</span><select name="dry_run" defaultValue="true"><option value="true">{text("仅预览作业", "Preview-only job")}</option><option value="false">{text("创建执行作业", "Queue execution job")}</option></select><small>{text("预览不修改记忆；执行由 Worker 后续处理。", "Preview does not modify Memory; a Worker handles execution later.")}</small></label>
          <label className="workbench-field"><span>{text("作业原因", "Job reason")}</span><input name="reason" required /><small>{text("写入审计记录，说明作业目的。", "Written to audit records to explain the job purpose.")}</small></label>
          <div className="workbench-field workbench-action"><span>{text("操作", "Action")}</span><button className="primary-button"><PlayCircle size={15} />{text("创建作业", "Create job")}</button><small>{text("提交后进入队列，不会立即执行。", "Queues the job; it does not execute immediately.")}</small></div>
        </form>
      </InfoPanel>
    </div>}
    {!loading && view === "jobs" && <><InfoPanel title={text("有效策略", "Effective policies")} text={text}><p className="cx-form-hint">{text("策略版本约束作业的可执行范围；策略本身不直接修改记忆。", "Policy versions constrain job execution scope; a policy does not modify Memory by itself.")}</p><DataTable headers={[text("名称", "Name"), text("版本", "Version"), text("状态", "State")]} rows={policies.map((item) => [item.policy_name, item.policy_version, item.status])} empty={text("没有可见策略", "No policy is visible")} text={text} /></InfoPanel><InfoPanel title={text("作业队列", "Job queue")} text={text}><p className="cx-form-hint">{text("作业先入队，再由持有有效租约的 Worker 处理；状态变化保留在数据库审计链中。", "Jobs queue first, then a Worker with a valid lease processes them; state changes remain in the database audit chain.")}</p><DataTable headers={[text("类型", "Type"), text("状态", "State"), text("模式", "Mode"), text("创建时间", "Created")]} rows={jobs.map((item) => [item.job_type, item.status, ["Y", "TRUE", "1"].includes(String(item.dry_run).toUpperCase()) ? text("仅预览", "Preview-only") : text("执行", "Execution"), displayRowValue(lang, item.created_at)])} empty={text("没有记忆作业", "No Memory jobs")} text={text} /></InfoPanel></>}
  </section>;
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
    endpoint: "/api/knowledge/inventory",
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
  READY: ["已就绪", "Ready"],
  RELEASED: ["已放行", "Released"],
  REJECTED: ["已拒绝", "Rejected"],
  PROPOSED: ["待审批", "Proposed"],
  DISABLED: ["已禁用", "Disabled"],
  PENDING: ["待处理", "Pending"],
  FAILED: ["失败", "Failed"],
  PAUSED: ["已暂停", "Paused"],
  COMPLETED: ["已完成", "Completed"],
  QUARANTINED: ["已隔离", "Quarantined"],
  UNKNOWN: ["未知", "Unknown"],
  COMPLIANT: ["合规", "Compliant"],
  DEGRADED: ["降级", "Degraded"],
  NON_COMPLIANT: ["不合规", "Non-compliant"],
  NORMAL: ["正常", "Normal"],
  PENDING_ACTIVATION: ["待激活", "Pending activation"],
  NEVER_SEEN: ["未观察", "Never observed"],
  ONLINE: ["在线", "Online"],
  IDLE: ["空闲", "Idle"],
  STALE: ["已失效", "Stale"],
  OFFLINE: ["离线", "Offline"],
  BOUNDARY_ONLY: ["仅边界证据", "Boundary only"],
  SIGNED_ADAPTER: ["已签名适配器", "Signed adapter"],
  MANAGED_RUNTIME: ["受管运行时", "Managed runtime"],
  SCOPE_LIMITED: ["范围受限", "Scope limited"],
  REMEDIATING: ["整改中", "Remediating"],
  ACKNOWLEDGED: ["已确认", "Acknowledged"],
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
  DRAFT: ["草稿", "Draft"],
  WORKING_REVISION: ["工作修订", "Working revision"],
  APPROVED_BASELINE: ["已批准基线", "Approved baseline"],
  AMENDMENT: ["修订", "Amendment"],
  SUPERSEDED_BASELINE: ["已替代基线", "Superseded baseline"],
  RETIRED: ["已退役", "Retired"],
  VALID: ["有效", "Valid"],
  ENABLED: ["已启用", "Enabled"],
  APPROVAL_ONLY: ["仅审批", "Approval only"],
  INITIALIZED: ["已初始化", "Initialized"],
  ACTIVATION_PENDING: ["待激活", "Activation pending"],
  CONFIGURED_ONLY: ["仅已配置", "Configured only"],
  VERIFIED: ["已验证", "Verified"],
  AGENT_VERIFIED: ["智能体验证", "Agent verified"],
  GATEWAY_VERIFIED: ["网关验证", "Gateway verified"],
  HIGH_AVAILABILITY_NOT_READY: ["高可用尚未就绪", "High availability not ready"],
  HIGH_AVAILABILITY_READY: ["高可用已就绪", "High availability ready"],
  SYSTEM_PROTECTED: ["系统保护", "System protected"],
  RESTRICTED: ["受限", "Restricted"],
  CANDIDATE: ["候选", "Candidate"],
  OBSERVATION: ["观察中", "Observation"],
  HEALTHY: ["健康", "Healthy"],
  STAGED: ["已暂存", "Staged"],
  PUBLISHED: ["已发布", "Published"],
  NOT_CONFIGURED: ["未配置", "Not configured"],
  NOT_READY: ["未就绪", "Not ready"],
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
  READ: ["只读", "Read"],
  SAFE_MAINTENANCE: ["安全维护", "Safe maintenance"],
  PROPOSED_CHANGE: ["变更提案", "Proposed change"],
  HIGH_RISK_CHANGE: ["高风险变更", "High-risk change"],
  EMERGENCY_CONTAINMENT: ["应急阻断", "Emergency containment"],
  DIRECT_READ: ["直接读取", "Direct read"],
  PROPOSAL_ONLY: ["仅提案", "Proposal only"],
  GOVERNED_EXECUTOR: ["受治理执行", "Governed executor"],
  UNAVAILABLE: ["不可用", "Unavailable"],
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
  PLATFORM_BUILTIN: ["平台内置", "Platform built-in"],
  PLATFORM_CREATED: ["平台创建", "Platform created"],
  PLATFORM_MANAGED: ["平台托管", "Platform managed"],
  ENTERPRISE_DIRECT: ["企业直连", "Enterprise direct"],
  ENTERPRISE_PROXY: ["企业代理", "Enterprise proxy"],
  PRECOMPUTED_IMPORT: ["预计算导入", "Precomputed import"],
  DOMAIN_ISOLATED: ["域隔离", "Domain isolated"],
  DEDICATED_CONTAINER: ["专用容器", "Dedicated container"],
  DEDICATED_RUNTIME: ["专用运行时", "Dedicated runtime"],
  LOCAL_MANAGED: ["本地受管", "Local managed"],
  REEMBED: ["重嵌入", "Re-embed"],
  INGEST: ["写入", "Ingest"],
  VERIFY: ["验证", "Verify"],
  PLATFORM: ["平台", "Platform"],
  TEMPLATE: ["模板", "Template"],
  PLATFORM_ADMINISTRATION: ["平台管理频道", "Platform Administration"],
  PLATFORM_DEPLOYED: ["平台部署", "Platform deployed"],
  EXTERNAL_ADMIN: ["外部 Admin 接入", "External Admin admission"],
  SYSTEM_PROTECTED: ["系统保护", "System protected"],
  PLATFORM_ADMIN: ["平台管理", "Platform administration"],
  HIGH_AVAILABILITY_NOT_READY: ["高可用尚未就绪", "High availability not ready"],
  LOCAL_BOOTSTRAP: ["本地初始化节点", "Local bootstrap node"],
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

function formatDateTime(value: any): string {
  if (!value) return "-";
  const parsed = new Date(String(value));
  return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString();
}

function renderChannelInline(value: string, keyPrefix: string): React.ReactNode[] {
  const parts = value.split(/(`[^`]*`|\*\*[^*]+\*\*|\*[^*]+\*|\[[^\]]+\]\((?:https?:\/\/)[^)\s]+\))/g);
  return parts.filter(Boolean).map((part, index) => {
    const key = `${keyPrefix}-${index}`;
    if (part.startsWith("`") && part.endsWith("`")) return <code key={key}>{part.slice(1, -1)}</code>;
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={key}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("*") && part.endsWith("*")) return <em key={key}>{part.slice(1, -1)}</em>;
    const link = part.match(/^\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)$/);
    if (link) return <a key={key} href={link[2]} target="_blank" rel="noreferrer">{link[1]}</a>;
    return <React.Fragment key={key}>{part}</React.Fragment>;
  });
}

function ChannelMarkdown({ value, streaming, text }: { value: any; streaming: boolean; text: (zh: string, en: string) => string }) {
  const raw = String(value || "");
  const lines = (streaming && raw === "[streaming]" ? "" : raw).replace(/\r/g, "").split("\n");
  const blocks: React.ReactNode[] = [];
  let code: string[] | null = null;
  const flushCode = () => {
    if (code !== null) blocks.push(<pre key={`code-${blocks.length}`}><code>{code.join("\n")}</code></pre>);
    code = null;
  };
  lines.forEach((line, index) => {
    if (line.trimStart().startsWith("```")) { if (code === null) code = []; else flushCode(); return; }
    if (code !== null) { code.push(line); return; }
    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    const list = line.match(/^\s*[-*+]\s+(.+)$/);
    const quote = line.match(/^>\s?(.*)$/);
    if (heading) {
      const level = heading[1].length;
      blocks.push(level === 1 ? <h1 key={`h-${index}`}>{renderChannelInline(heading[2], `h-${index}`)}</h1> : level === 2 ? <h2 key={`h-${index}`}>{renderChannelInline(heading[2], `h-${index}`)}</h2> : <h3 key={`h-${index}`}>{renderChannelInline(heading[2], `h-${index}`)}</h3>);
    } else if (list) blocks.push(<ul key={`ul-${index}`}><li>{renderChannelInline(list[1], `li-${index}`)}</li></ul>);
    else if (quote) blocks.push(<blockquote key={`q-${index}`}>{renderChannelInline(quote[1], `q-${index}`)}</blockquote>);
    else if (line.trim()) blocks.push(<p key={`p-${index}`}>{renderChannelInline(line, `p-${index}`)}</p>);
  });
  flushCode();
  return <div className={`channel-markdown ${streaming ? "is-streaming" : ""}`}>{blocks.length ? blocks : <p className="streaming-placeholder">{text("管理智能体正在生成回复...", "Management Agent is generating a reply...")}</p>}{streaming && <span className="streaming-caret" aria-label={text("正在生成", "Generating")} />}</div>;
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

function enabledFlag(value: unknown): boolean {
  return value === true || ["Y", "YES", "TRUE", "1", "T"].includes(String(value || "").trim().toUpperCase());
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

function CursorPager({
  pageSize, page, totalItems, hasMore, loading, onPageSize, onPrevious, onNext, text,
}: {
  pageSize: number; page: number; totalItems?: number; hasMore: boolean; loading: boolean;
  onPageSize: (value: number) => void; onPrevious: () => void; onNext: () => void;
  text: (zh: string, en: string) => string;
}) {
  const totalPages = totalItems === undefined ? null : Math.max(1, Math.ceil(totalItems / pageSize));
  return <div className="cursor-pager">
    <label className="pager-size-control"><span>{text("每页", "Per page")}</span><select aria-label={text("每页数量", "Items per page")} value={pageSize} disabled={loading} onChange={(event) => onPageSize(Number(event.target.value))}><option value="20">20</option><option value="50">50</option><option value="100">100</option></select></label>
    <span className="pager-page-status" aria-live="polite">{totalPages === null ? text(`${page} / ${page} 页`, `${page} / ${page}`) : text(`${page} / ${totalPages} 页`, `${page} / ${totalPages}`)}</span>
    <button className="small-button" disabled={loading || page <= 1} onClick={onPrevious}>{text("上一页", "Previous")}</button>
    <button className="small-button" disabled={loading || !hasMore} onClick={onNext}>{text("下一页", "Next")}</button>
  </div>;
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

function SddWorkbench({
  lang,
  text,
  onNotice,
}: {
  lang: Lang;
  text: (zh: string, en: string) => string;
  onNotice: (value: string) => void;
}) {
  const [changes, setChanges] = useState<Row[]>([]);
  const [selected, setSelected] = useState<Row | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [title, setTitle] = useState("");
  const [summary, setSummary] = useState("");
  const load = async () => {
    setLoading(true);
    try {
      const payload = await api<Row>("/api/sdd/changes?limit=100");
      setChanges(listPayload(payload, ["changes"]));
      if (selected) setSelected(await api<Row>(`/api/sdd/changes/${selected.change_id}`));
    } catch (error) {
      onNotice(error instanceof Error ? error.message : text("加载规格失败", "Unable to load specifications"));
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { void load(); }, []);
  const createChange = async (event: FormEvent) => {
    event.preventDefault();
    if (!title.trim()) return;
    setBusy(true);
    try {
      await api("/api/sdd/changes", { method: "POST", body: JSON.stringify({ title, summary }) });
      setTitle(""); setSummary(""); await load();
    } catch (error) { onNotice(error instanceof Error ? error.message : text("创建失败", "Creation failed")); }
    finally { setBusy(false); }
  };
  const action = async (path: string, body: Row = {}) => {
    if (!selected?.revision?.revision_id) return;
    setBusy(true);
    try {
      await api(path.replace(":revision", selected.revision.revision_id), { method: "POST", body: JSON.stringify(body) });
      await load();
    } catch (error) { onNotice(error instanceof Error ? error.message : text("操作失败", "Operation failed")); }
    finally { setBusy(false); }
  };
  return (
    <section>
      <SectionHeading
        title={text("规格与交付工作台", "Specification and delivery workbench")}
        subtitle={text("规格在数据库中形成可协作、可审查、可执行的版本基线；OpenSpec 仅作为导入与互操作入口。", "Specifications become collaborative, reviewable and executable database baselines; OpenSpec is only an import and interoperability entry point.")}
        text={text}
      />
      <InfoPanel title={text("新建原生 Change", "Create native Change")} text={text}>
        <form className="workbench-form" onSubmit={createChange}>
          <label className="workbench-field"><span>{text("标题", "Title")}</span><input value={title} onChange={(event) => setTitle(event.target.value)} required /><small>{text("创建后进入工作修订状态。", "Starts as a working revision.")}</small></label>
          <label className="workbench-field"><span>{text("摘要", "Summary")}</span><input value={summary} onChange={(event) => setSummary(event.target.value)} /><small>{text("摘要不会替代结构化条款。", "A summary does not replace structured clauses.")}</small></label>
          <div className="workbench-field workbench-action"><span>{text("操作", "Action")}</span><button className="primary-button" disabled={busy}><Plus size={15} />{text("创建", "Create")}</button></div>
        </form>
      </InfoPanel>
      <div className="cx-two-column">
        <InfoPanel title={text("Change 列表", "Change list")} text={text}>
          {loading ? <div className="cx-empty"><RefreshCw className="spin" size={16} />{text("正在加载", "Loading")}</div> : <DataTable headers={[text("标题", "Title"), text("状态", "Status"), text("更新时间", "Updated")]} rows={changes.map((item) => [<button className="text-button" onClick={() => void api<Row>(`/api/sdd/changes/${item.change_id}`).then(setSelected)}>{String(item.title || item.change_id)}</button>, displayRowValue(lang, item.status), displayRowValue(lang, item.updated_at)])} empty={text("暂无 Change", "No Change yet")} text={text} />}
        </InfoPanel>
        <InfoPanel title={text("选中 Change", "Selected Change")} text={text}>
          {!selected ? <div className="cx-empty">{text("点击列表中的标题查看详情。", "Select a title to inspect its details.")}</div> : <>
            <div className="detail-grid"><span>{text("状态", "Status")}</span><b>{displayRowValue(lang, selected.status)}</b><span>{text("当前修订", "Revision")}</span><b>{displayRowValue(lang, selected.revision?.revision_state)}</b><span>{text("条款", "Clauses")}</span><b>{selected.revision?.clauses?.length || 0}</b><span>{text("证据", "Evidence")}</span><b>{selected.evidence?.length || 0}</b></div>
            <div className="page-toolbar">
              <button className="secondary-button" disabled={busy} onClick={() => void action("/api/sdd/revisions/:revision/working-revision", { reason: text("工作修订", "Working revision") })}><Redo2 size={14} />{text("新建修订", "New revision")}</button>
              <button className="secondary-button" disabled={busy || selected.revision?.revision_state !== "APPROVED_BASELINE"} onClick={() => void action("/api/sdd/revisions/:revision/runs", { budget: {} })}><PlayCircle size={14} />{text("创建 Run", "Create Run")}</button>
              <button className="primary-button" disabled={busy || selected.revision?.revision_state !== "WORKING_REVISION"} onClick={() => void action("/api/sdd/revisions/:revision/baseline", { reason: text("管理员批准基线", "Administrator approved baseline") })}><ShieldCheck size={14} />{text("批准基线", "Approve baseline")}</button>
            </div>
            <p className="cx-form-hint">{text("任务、执行图、Agent/资源、证据、Review、Amendment 和 Release Baseline 均由数据库记录；Agent 的完成声明不会单独关闭验收。", "Tasks, execution graph, Agent/resources, evidence, Review, Amendment and Release Baseline are database records; an Agent completion claim alone never closes acceptance.")}</p>
            <DataTable headers={[text("条款类型", "Clause"), text("标题", "Title"), text("状态", "Status")]} rows={(selected.revision?.clauses || []).map((item: Row) => [displayRowValue(lang, item.clause_kind), item.title, displayRowValue(lang, item.status)])} empty={text("暂无结构化条款", "No structured clauses")} text={text} />
          </>}
        </InfoPanel>
      </div>
    </section>
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
  const [view, setView] = useUrlState<"list" | "graph">(
    "view",
    ["list", "graph"],
    "list",
  );
  const [pageSize, setPageSize] = useState(20);
  const [cursorHistory, setCursorHistory] = useState<string[]>([""]);
  const [nextCursor, setNextCursor] = useState("");
  const [totalItems, setTotalItems] = useState<number | undefined>(undefined);
  const load = async (cursor = cursorHistory[cursorHistory.length - 1] || "", size = pageSize) => {
    setLoading(true);
    try {
      const separator = config.endpoint.includes("?") ? "&" : "?";
      const value = await api<Row>(`${config.endpoint}${separator}page_size=${size}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`);
      setItems(listPayload(value, [...(config.payloadKeys || []), "nodes"]));
      setNextCursor(String(value.next_cursor || ""));
      setTotalItems(typeof value.total_items === "number" ? value.total_items : undefined);
      if (visual) {
        const graph = await api<Row>(page === "knowledge" ? "/api/knowledge?limit=200" : "/api/memory");
        setGraphData({ nodes: graph.nodes || [], edges: graph.edges || [] });
      } else {
        setGraphData({ nodes: value.nodes || [], edges: value.edges || [] });
      }
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
  const changePageSize = (value: number) => {
    setPageSize(value); setCursorHistory([""]); setNextCursor(""); void load("", value);
  };
  const nextPage = () => {
    if (!nextCursor) return;
    const history = [...cursorHistory, nextCursor];
    setCursorHistory(history); void load(nextCursor);
  };
  const previousPage = () => {
    if (cursorHistory.length <= 1) return;
    const history = cursorHistory.slice(0, -1);
    setCursorHistory(history); void load(history[history.length - 1]);
  };
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
            <>
              <CursorPager pageSize={pageSize} page={cursorHistory.length} totalItems={totalItems} hasMore={Boolean(nextCursor)} loading={loading} onPageSize={changePageSize} onPrevious={previousPage} onNext={nextPage} text={text} />
              <DataTable
                headers={config.labels.map((label) => text(label[0], label[1]))}
                rows={rows}
                empty={text(
                  "当前权限范围内没有数据",
                  "No data is visible within the current authorization scope",
                )}
                text={text}
              />
            </>
          )}
          {!loading && <CursorPager pageSize={pageSize} page={cursorHistory.length} totalItems={totalItems} hasMore={Boolean(nextCursor)} loading={loading} onPageSize={changePageSize} onPrevious={previousPage} onNext={nextPage} text={text} />}
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
          label: `${String(node.label || node.title || node.id)}${node.history_node ? ` · ${text("历史谱系", "Historical lineage")}` : ""}`,
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
          <label className="inline-field graph-search-field"><span>{text("搜索节点", "Search nodes")}</span><input value={search} onChange={(event) => setSearch(event.target.value)} /></label>
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
  const [view, setView] = useUrlState(
    "view",
    ["overview", "definitions", "types", "runs", "relationships"] as const,
    "overview",
  );
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
            "当前页面只展示数据库授权且符合 Production 基线的图数据。",
            "This view shows only database-authorized graph data permitted by the Production baseline.",
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
  const [focusId, setFocusId] = useUrlParam("focus");
  const [selected, setSelected] = useState<Row | null>(null);
  const [detail, setDetail] = useState<Row | null>(null);
  const [search, setSearch] = useState("");
  const [searchResults, setSearchResults] = useState<Row[]>([]);
  const [mode, setMode] = useUrlState<OrganizationMode>(
    "view",
    ["organization", "anomalies", "people", "agents"] as const,
    "organization",
  );
  const [orientation, setOrientation] =
    useState<OrganizationOrientation>("UD");
  const [panel, setPanel] = useUrlState(
    "panel",
    ["details", "draft", "impact", "history", "conflicts"] as const,
    "details",
  );
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
        if (firstId) setFocusId(firstId);
        else void loadGraph("", mode);
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
    void loadGraph(focusId, mode);
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
  const [pageSize, setPageSize] = useState(20);
  const [cursorHistory, setCursorHistory] = useState<string[]>([""]);
  const [nextCursor, setNextCursor] = useState("");
  const [totalItems, setTotalItems] = useState<number | undefined>(undefined);
  const [loading, setLoading] = useState(false);
  const load = async (cursor = cursorHistory[cursorHistory.length - 1] || "", status = filter) => {
    setLoading(true);
    try {
      const query = `/api/approvals?page_size=${pageSize}${status !== "ALL" ? `&status=${encodeURIComponent(status)}` : ""}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`;
      const value = await api<Row>(query);
      setItems(listPayload(value, ["approvals"]));
      setNextCursor(String(value.next_cursor || ""));
      setTotalItems(typeof value.total_items === "number" ? value.total_items : undefined);
    } catch (error) {
      onNotice(
        error instanceof Error
          ? error.message
          : text("审批加载失败", "Approvals could not be loaded"),
      );
    } finally { setLoading(false); }
  };
  useEffect(() => {
    setCursorHistory([""]); setNextCursor(""); void load("", filter);
  }, [filter, pageSize]);
  const setPage = (value: number) => { setPageSize(value); setCursorHistory([""]); setNextCursor(""); };
  const nextPage = () => { if (!nextCursor) return; const history = [...cursorHistory, nextCursor]; setCursorHistory(history); void load(nextCursor); };
  const previousPage = () => { if (cursorHistory.length <= 1) return; const history = cursorHistory.slice(0, -1); setCursorHistory(history); void load(history[history.length - 1]); };
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
        <CursorPager pageSize={pageSize} page={cursorHistory.length} totalItems={totalItems} hasMore={Boolean(nextCursor)} loading={loading} onPageSize={setPage} onPrevious={previousPage} onNext={nextPage} text={text} />
        <DataTable
          headers={[
            "ID",
            text("资源/动作", "Resource / action"),
            text("状态", "Status"),
            text("操作", "Actions"),
          ]}
          rows={items.map((row) => {
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
        <CursorPager pageSize={pageSize} page={cursorHistory.length} totalItems={totalItems} hasMore={Boolean(nextCursor)} loading={loading} onPageSize={setPage} onPrevious={previousPage} onNext={nextPage} text={text} />
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
  const [pageSize, setPageSize] = useState(20);
  const [cursorHistory, setCursorHistory] = useState<string[]>([""]);
  const [nextCursor, setNextCursor] = useState("");
  const [totalItems, setTotalItems] = useState<number | undefined>(undefined);
  const [loading, setLoading] = useState(false);
  const load = async (cursor = cursorHistory[cursorHistory.length - 1] || "") => {
    setLoading(true);
    try {
      const value = await api<Row>(`/api/audit?page_size=${pageSize}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`);
      setItems(listPayload(value, ["events", "audit"]));
      setNextCursor(String(value.next_cursor || ""));
      setTotalItems(typeof value.total_items === "number" ? value.total_items : undefined);
    } catch (error) {
      onNotice(
        error instanceof Error
          ? error.message
          : text("审计加载失败", "Audit could not be loaded"),
      );
    } finally { setLoading(false); }
  };
  useEffect(() => {
    setCursorHistory([""]); setNextCursor(""); void load("");
  }, [pageSize]);
  const setPage = (value: number) => { setPageSize(value); setCursorHistory([""]); setNextCursor(""); };
  const nextPage = () => { if (!nextCursor) return; const history = [...cursorHistory, nextCursor]; setCursorHistory(history); void load(nextCursor); };
  const previousPage = () => { if (cursorHistory.length <= 1) return; const history = cursorHistory.slice(0, -1); setCursorHistory(history); void load(history[history.length - 1]); };
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
        <CursorPager pageSize={pageSize} page={cursorHistory.length} totalItems={totalItems} hasMore={Boolean(nextCursor)} loading={loading} onPageSize={setPage} onPrevious={previousPage} onNext={nextPage} text={text} />
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
        <CursorPager pageSize={pageSize} page={cursorHistory.length} totalItems={totalItems} hasMore={Boolean(nextCursor)} loading={loading} onPageSize={setPage} onPrevious={previousPage} onNext={nextPage} text={text} />
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
  const [data, setData] = useState<Row>({});
  const [profile, setProfile] = useState<Row>({});
  const [notifications, setNotifications] = useState<Row[]>([]);
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
        title={text("监控", "Monitor")}
        subtitle={text(
          "查看智能体、会话、任务计划、循环和停滞实例，并确认当前运行配置。",
          "Review Agents, sessions, task plans, Loops, and stalled instances, and confirm the current runtime profile.",
        )}
        text={text}
      />
      {loading ? (
        <PageLoading text={text} />
      ) : (
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
      )}
      {!loading && (
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

function CompliancePage({
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
  const [summary, setSummary] = useState<Row>({ postures: [], open_findings: [] });
  const [findings, setFindings] = useState<Row[]>([]);
  const [profiles, setProfiles] = useState<Row[]>([]);
  const [remediations, setRemediations] = useState<Row[]>([]);
  const [exceptions, setExceptions] = useState<Row[]>([]);
  const [tab, setTab] = useState<"overview" | "findings" | "profiles" | "remediation" | "exceptions" | "controller">("overview");
  const [selected, setSelected] = useState<Row | null>(null);
  const [busy, setBusy] = useState(false);
  const [pageSize, setPageSize] = useState(20);
  const [cursorHistory, setCursorHistory] = useState<string[]>([""]);
  const [nextCursor, setNextCursor] = useState("");
  const [totalItems, setTotalItems] = useState<number | undefined>(undefined);
  const endpointFor = (value: typeof tab) => ({
    findings: "/api/compliance/findings", profiles: "/api/compliance/profiles",
    remediation: "/api/compliance/remediations", exceptions: "/api/compliance/exceptions",
  } as Partial<Record<typeof tab, string>>)[value] || "";
  const load = async (cursor = cursorHistory[cursorHistory.length - 1] || "", currentTab = tab, size = pageSize) => {
    try {
      const endpoint = endpointFor(currentTab);
      const [nextSummary, page] = await Promise.all([
        api<Row>("/api/compliance/summary"),
        endpoint ? api<Row>(`${endpoint}?page_size=${size}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`) : Promise.resolve({}),
      ]);
      setSummary(nextSummary);
      setNextCursor(String(page.next_cursor || ""));
      setTotalItems(typeof page.total_items === "number" ? page.total_items : undefined);
      if (currentTab === "findings") setFindings(page.items || []);
      if (currentTab === "profiles") setProfiles(page.items || []);
      if (currentTab === "remediation") setRemediations(page.items || []);
      if (currentTab === "exceptions") setExceptions(page.items || []);
    } catch (error) {
      onNotice(error instanceof Error ? error.message : text("合规数据加载失败", "Compliance data could not be loaded"));
    }
  };
  useEffect(() => { void load(); }, []);
  const selectTab = (value: typeof tab) => {
    setTab(value); setCursorHistory([""]); setNextCursor(""); void load("", value);
  };
  const changePageSize = (value: number) => {
    setPageSize(value); setCursorHistory([""]); setNextCursor(""); void load("", tab, value);
  };
  const nextPage = () => {
    if (!nextCursor) return;
    const history = [...cursorHistory, nextCursor]; setCursorHistory(history); void load(nextCursor);
  };
  const previousPage = () => {
    if (cursorHistory.length <= 1) return;
    const history = cursorHistory.slice(0, -1); setCursorHistory(history); void load(history[history.length - 1]);
  };
  const decideException = async (decision: "approve" | "reject" | "revoke", reason: string) => {
    if (!selected?.exception_id || !reason.trim()) return;
    setBusy(true);
    try {
      await api(`/api/compliance/exceptions/${encodeURIComponent(String(selected.exception_id))}/${decision}`, {
        method: "POST", body: JSON.stringify({ reason }),
      });
      setSelected(null);
      await load();
      onNotice(text("例外决定已记录。", "Exception decision recorded."));
    } catch (error) {
      onNotice(error instanceof Error ? error.message : text("例外决定失败", "Exception decision failed"));
    } finally { setBusy(false); }
  };
  const createProfile = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const formElement = event.currentTarget;
    const data = Object.fromEntries(new FormData(formElement).entries());
    setBusy(true);
    try {
      await api("/api/compliance/profiles", { method: "POST", body: JSON.stringify({
        profile_key: data.profile_key, display_name: data.display_name, parent_version_id: data.parent_version_id || "", reason: data.reason,
        content: {
          locked_fields: String(data.locked_fields || "").split(",").map((value) => value.trim()).filter(Boolean),
          controls: {
            allowed_skills: String(data.allowed_skills || "").split(",").map((value) => value.trim()).filter(Boolean),
            allowed_tools: String(data.allowed_tools || "").split(",").map((value) => value.trim()).filter(Boolean),
            classification_ceiling: data.classification_ceiling,
            database_access: data.database_access,
            network_egress: data.network_egress,
            approval_policy: data.approval_policy,
            audit_retention: data.audit_retention,
          },
        },
      }) });
      formElement.reset(); await load();
    onNotice(text("合规控制模板草稿已创建，发布前仍可复核。", "Compliance control-template draft created; review it before publication."));
    } catch (error) {
    onNotice(error instanceof Error ? error.message : text("创建合规控制模板失败", "Compliance control-template creation failed"));
    } finally { setBusy(false); }
  };
  const createException = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const formElement = event.currentTarget;
    const data = Object.fromEntries(new FormData(formElement).entries());
    setBusy(true);
    try {
      await api("/api/compliance/exceptions", { method: "POST", body: JSON.stringify({
        policy_key: data.policy_key, agent_id: data.agent_id, environment: data.environment,
        expires_at: data.expires_at, reason: data.reason,
        compensating_controls: { manual_review: "required" },
      }) });
      formElement.reset(); await load();
      onNotice(text("例外请求已提交，申请人与审批人必须分离。", "Exception request submitted; requester and approver must be distinct."));
    } catch (error) {
      onNotice(error instanceof Error ? error.message : text("例外请求失败", "Exception request failed"));
    } finally { setBusy(false); }
  };
  const tabs: Array<[typeof tab, string, string]> = [
    ["overview", "概览", "Overview"], ["findings", "发现", "Findings"], ["profiles", "合规控制模板", "Compliance control templates"],
    ["remediation", "整改", "Remediation"], ["exceptions", "例外", "Exceptions"], ["controller", "控制器", "Controller"],
  ];
  const postureMeaning = (value: unknown) => ({
    COMPLIANT: text("已验证证据满足当前合规控制要求。", "Verified evidence satisfies the current compliance controls."),
    UNKNOWN: text("证据尚不足以形成合规或违规结论，不等同于违规。", "Evidence is insufficient for a compliant or violation conclusion; this is not a violation."),
    DEGRADED: text("已有证据过期或部分控制未达到预期，需要复核。", "Evidence is stale or some controls are below expectation and require review."),
    NON_COMPLIANT: text("确定性规则和已验证证据确认存在违规。", "Deterministic rules and verified evidence confirm a violation."),
  } as Record<string, string>)[String(value || "UNKNOWN").toUpperCase()] || text("当前姿态含义未登记。", "The current posture meaning is not registered.");
  const controlMeaning = (value: unknown) => ({
    NORMAL: text("未施加额外运行限制，仍受既有身份与授权策略约束。", "No additional runtime restriction is applied; existing identity and authorization policies still apply."),
    RESTRICTED: text("仅允许心跳、证据上报、整改和恢复等受限操作。", "Only restricted operations such as heartbeat, evidence, remediation, and recovery are allowed."),
    QUARANTINED: text("Agent 已隔离，仅允许恢复流程，不能继续正常业务执行。", "The Agent is quarantined; only recovery is allowed and normal business execution is blocked."),
    DISABLED: text("Agent 已停用，正常运行和业务操作均被阻止。", "The Agent is disabled; normal runtime and business operations are blocked."),
  } as Record<string, string>)[String(value || "NORMAL").toUpperCase()] || text("当前控制状态含义未登记。", "The current control-state meaning is not registered.");
  const postureGroupTitle = (posture: unknown, control: unknown) => {
    const key = `${String(posture || "UNKNOWN").toUpperCase()}:${String(control || "NORMAL").toUpperCase()}`;
    return ({
      "COMPLIANT:NORMAL": text("健康合规 Agent", "Healthy compliant Agents"),
      "UNKNOWN:NORMAL": text("待评估 Agent", "Agents awaiting assessment"),
      "DEGRADED:NORMAL": text("需要复核的 Agent", "Agents requiring review"),
      "DEGRADED:RESTRICTED": text("已受限的风险 Agent", "Restricted at-risk Agents"),
      "NON_COMPLIANT:QUARANTINED": text("已隔离违规 Agent", "Quarantined non-compliant Agents"),
      "NON_COMPLIANT:DISABLED": text("已停用违规 Agent", "Disabled non-compliant Agents"),
    } as Record<string, string>)[key] || text("其他合规状态 Agent", "Agents in another compliance state");
  };
  return <section className="page-stack">
    <SectionHeading title={text("合规", "Compliance")} subtitle={text("基于已验证证据的智能体姿态、发现和合规控制模板。", "Evidence-based Agent posture, findings, and compliance control templates.")} text={text} />
    <div className="view-toggle compliance-tabs" role="tablist" aria-label={text("合规视图", "Compliance views")}>
      {tabs.map(([key, zh, en]) => (
        <button
          type="button"
          role="tab"
          aria-selected={tab === key}
          key={key}
          className={tab === key ? "active" : ""}
          onClick={() => selectTab(key)}
        >
          {text(zh, en)}
        </button>
      ))}
    </div>
    {tab === "overview" && <>
      <InfoPanel title={text("合规姿态", "Compliance posture")} text={text}>
        <div className="compliance-posture-guide">
          <div><b>{text("证据评估结论", "Evidence assessment")}</b><span>{text("说明 Agent 是否满足当前合规控制要求。", "Whether Agents satisfy the current compliance controls.")}</span></div>
          <div><b>{text("Agent 数量", "Agent count")}</b><span>{text("处于该“姿态 + 控制状态”组合中的 Agent 数量。", "Agents in this posture and control-state combination.")}</span></div>
          <div><b>{text("平台控制措施", "Platform enforcement")}</b><span>{text("说明平台当前是否限制、隔离或停用这些 Agent。", "Whether the platform currently restricts, quarantines, or disables these Agents.")}</span></div>
        </div>
        <div className="metric-grid compliance-posture-grid">{(summary.postures || []).map((item: Row) => <div className="compliance-posture-card" key={`${item.posture_state}-${item.control_state}`}>
          <div className="compliance-posture-card-title">
            <h3>{postureGroupTitle(item.posture_state, item.control_state)}</h3>
            <div><span>{displayRowValue(lang, item.posture_state || "UNKNOWN")}</span><i>+</i><span>{displayRowValue(lang, item.control_state || "NORMAL")}</span></div>
          </div>
          <div className="compliance-posture-fields">
            <div><small>{text("证据评估结论", "Evidence assessment")}</small><strong>{displayRowValue(lang, item.posture_state || "UNKNOWN")}</strong><span>{postureMeaning(item.posture_state)}</span></div>
            <div><small>{text("该组合中的 Agent", "Agents in this combination")}</small><strong>{item.count || 0} {text("个", "")}</strong><span>{text("按当前用户可见范围聚合", "Aggregated within the current user's visible scope")}</span></div>
            <div><small>{text("平台控制措施", "Platform enforcement")}</small><strong>{displayRowValue(lang, item.control_state || "NORMAL")}</strong><span>{controlMeaning(item.control_state)}</span></div>
          </div>
        </div>)}</div>
      </InfoPanel>
      <div className="split-grid">
        <InfoPanel title={text("待处理发现", "Open findings")} text={text}>
          <div className="metric-grid">{(summary.open_findings || []).map((item: Row) => <div className="metric-card" key={String(item.severity)}><small>{displayRowValue(lang, item.severity || "UNKNOWN")}</small><strong>{item.count || 0}</strong></div>)}</div>
          {!(summary.open_findings || []).length && <div className="empty-state">{text("当前范围内没有待处理发现。", "No open findings are visible in the current scope.")}</div>}
        </InfoPanel>
        <InfoPanel title={text("控制器", "Controller")} text={text}><div className="empty-state">{text("状态：", "Status: ")}{displayRowValue(lang, summary.controller || "UNKNOWN")}{summary.scope_limited ? text("。仅显示当前授权范围，不显示全局队列。", ". Only the authorized scope is shown; global queues are hidden.") : ""}</div></InfoPanel>
      </div>
    </>}
    {["findings", "profiles", "remediation", "exceptions"].includes(tab) && <CursorPager pageSize={pageSize} page={cursorHistory.length} totalItems={totalItems} hasMore={Boolean(nextCursor)} loading={busy} onPageSize={changePageSize} onPrevious={previousPage} onNext={nextPage} text={text} />}
    {tab === "findings" && <InfoPanel title={text("发现", "Findings")} text={text}>
      <p className="cx-form-hint">{text("仅确定性规则和已验证证据可以标记为不合规；缺少活动或边界证据不会自动定性为违规。点击条目查看详情。", "Only deterministic rules with verified evidence may mark an Agent non-compliant. Missing activity or boundary evidence is not a violation by itself. Select a row for details.")}</p>
      <DataTable headers={[text("严重性", "Severity"), text("智能体", "Agent"), text("规则", "Rule"), text("状态", "Status"), text("最近观察", "Last observed"), text("", "")]} rows={findings.map((item) => [displayRowValue(lang, item.severity), String(item.agent_id || "-"), String(item.rule_code || "-"), displayRowValue(lang, item.status), String(item.last_observed_at || "-"), <button className="small-button" onClick={() => setSelected({ ...item, kind: "finding" })}>{text("详情", "Details")}</button>])} text={text} empty={text("暂无合规发现", "No compliance findings")} />
      <CursorPager pageSize={pageSize} page={cursorHistory.length} totalItems={totalItems} hasMore={Boolean(nextCursor)} loading={busy} onPageSize={changePageSize} onPrevious={previousPage} onNext={nextPage} text={text} />
    </InfoPanel>}
    {tab === "profiles" && <>
      <InfoPanel title={text("合规控制模板", "Compliance control templates")} text={text}>
        <p className="cx-form-hint">{text("配置限定已有权限，不会授予身份、数据、工具或数据库访问权。发布后的版本不可修改。", "Profiles constrain existing authority; they never grant identity, data, Tool, or database access. Published versions are immutable.")}</p>
        <DataTable headers={[text("键", "Key"), text("名称", "Name"), text("版本", "Version"), text("状态", "Status"), text("摘要", "Digest")]} rows={profiles.map((item) => [String(item.profile_key || "-"), String(item.display_name || "-"), String(item.version_label || "-"), displayRowValue(lang, item.version_status || item.status), String(item.content_digest || "-").slice(0, 16)])} text={text} empty={text("暂无合规控制模板", "No compliance control templates")} />
      </InfoPanel>
      {canAction(capabilities, "agents.manage") && <InfoPanel title={text("创建合规控制模板草稿", "Create Compliance control-template draft")} text={text}><p className="cx-form-hint">{text("控制模板限制既有权限，不能单独授予数据库、网络、技能或工具访问权。逗号分隔的技能、工具与锁定字段将作为结构化策略保存。", "A control template constrains existing authority and cannot independently grant database, network, Skill, or Tool access. Comma-separated Skills, Tools, and locked fields are stored as structured policy.")}</p><form className="configuration-form compliance-template-form" onSubmit={createProfile}><ConfigField label={text("配置键", "Profile key")} hint={text("平台内唯一且可读的模板标识。", "A unique, readable template identifier.")}><input name="profile_key" required /></ConfigField><ConfigField label={text("显示名称", "Display name")} hint={text("用于审批、分配与审计显示。", "Shown in approval, assignment, and audit.")}><input name="display_name" required /></ConfigField><ConfigField label={text("父版本 ID", "Parent version ID")} hint={text("可选；父版本必须已发布。", "Optional; the parent version must be published.")}><input name="parent_version_id" /></ConfigField><ConfigField label={text("允许的技能", "Allowed Skills")} hint={text("用逗号分隔；留空表示不在此模板中额外限定。", "Comma separated; blank means this template adds no Skill restriction.")}><input name="allowed_skills" /></ConfigField><ConfigField label={text("允许的工具", "Allowed Tools")} hint={text("用逗号分隔；实际授权仍由身份策略决定。", "Comma separated; effective grants are still decided by identity policy.")}><input name="allowed_tools" /></ConfigField><ConfigField label={text("数据分类上限", "Data classification ceiling")} hint={text("限制此模板可处理的最高数据分类。", "Caps the highest data classification this template can handle.")}><select name="classification_ceiling" defaultValue="INTERNAL"><option value="INTERNAL">{text("内部", "Internal")}</option><option value="CONFIDENTIAL">{text("机密", "Confidential")}</option><option value="RESTRICTED">{text("受限", "Restricted")}</option></select></ConfigField><ConfigField label={text("数据库访问方式", "Database access mode")} hint={text("数据库授权仍由账号、Schema 与网关执行。", "Database grants are still enforced by accounts, schemas, and the gateway.")}><select name="database_access" defaultValue="GATEWAY_ONLY"><option value="GATEWAY_ONLY">{text("仅网关", "Gateway only")}</option><option value="READ_SCOPED">{text("范围内只读", "Scoped read")}</option><option value="LEAST_PRIVILEGE">{text("最小权限", "Least privilege")}</option><option value="DENY">{text("禁止", "Deny")}</option></select></ConfigField><ConfigField label={text("网络出口策略", "Network egress policy")} hint={text("网络访问还需满足运行时与基础设施控制。", "Network access also remains subject to runtime and infrastructure controls.")}><select name="network_egress" defaultValue="ALLOWLIST"><option value="ALLOWLIST">{text("白名单", "Allowlist")}</option><option value="ISOLATED">{text("隔离", "Isolated")}</option><option value="DENY">{text("禁止", "Deny")}</option></select></ConfigField><ConfigField label={text("审批策略", "Approval policy")} hint={text("定义高风险操作的审批要求。", "Defines approval requirements for high-risk actions.")}><select name="approval_policy" defaultValue="REQUIRED"><option value="REQUIRED">{text("必须审批", "Required")}</option><option value="RISK_BASED">{text("按风险审批", "Risk based")}</option><option value="NONE">{text("无需审批", "None")}</option></select></ConfigField><ConfigField label={text("审计与留存策略", "Audit and retention policy")} hint={text("定义审计证据的最低留存要求。", "Defines the minimum retention requirement for audit evidence.")}><select name="audit_retention" defaultValue="EVIDENCE_REQUIRED"><option value="EVIDENCE_REQUIRED">{text("必须保留证据", "Evidence required")}</option><option value="STANDARD">{text("标准留存", "Standard")}</option><option value="EXTENDED">{text("延长留存", "Extended")}</option></select></ConfigField><ConfigField label={text("锁定字段", "Locked fields")} hint={text("用逗号分隔；子模板不可改写父模板同名锁定内容。", "Comma separated; child templates cannot override same-named locked parent content.")}><input name="locked_fields" /></ConfigField><ConfigField label={text("创建原因", "Creation reason")} hint={text("至少三个字符，写入审计。", "At least three characters; written to audit.")}><input name="reason" required /></ConfigField><ConfigField label={text("操作", "Action")} hint={text("创建后为草稿，发布前仍可复核。", "Created as a draft and remains reviewable before publication.")} action><button className="primary-button" disabled={busy}><Plus size={15} />{text("创建草稿", "Create draft")}</button></ConfigField></form></InfoPanel>}
    </>}
    {tab === "remediation" && <InfoPanel title={text("整改", "Remediation")} text={text}>
      <p className="cx-form-hint">{text("整改必须通过受认证网关提交结构化证据；普通频道聊天不会关闭整改。", "Remediation requires structured evidence through the authenticated Gateway; ordinary Channel chat never closes a case.")}</p>
      <DataTable headers={[text("编号", "Case"), text("智能体", "Agent"), text("要求", "Required action"), text("状态", "Status"), text("期限", "Deadline"), text("", "")]} rows={remediations.map((item) => [String(item.case_id || "-"), String(item.agent_id || "-"), String(item.required_action || "-"), displayRowValue(lang, item.status), String(item.deadline_at || "-"), <button className="small-button" onClick={() => setSelected({ ...item, kind: "remediation" })}>{text("详情", "Details")}</button>])} text={text} empty={text("暂无整改任务", "No remediation cases")} />
    </InfoPanel>}
    {tab === "exceptions" && <>
      <InfoPanel title={text("例外", "Exceptions")} text={text}>
        <p className="cx-form-hint">{text("例外必须包含补偿控制、原因和失效时间；申请人不能审批自己的请求，到期后控制器会重新评估。", "Exceptions require compensating controls, a reason, and an expiry. Requesters cannot approve their own request; the Controller reevaluates expiry.")}</p>
        <DataTable headers={[text("策略", "Policy"), text("智能体", "Agent"), text("状态", "Status"), text("失效时间", "Expiry"), text("申请人", "Requester"), text("", "")]} rows={exceptions.map((item) => [String(item.policy_key || "-"), String(item.agent_id || "-") , displayRowValue(lang, item.status), String(item.expires_at || "-"), String(item.requested_by || "-"), <button className="small-button" onClick={() => setSelected({ ...item, kind: "exception" })}>{text("详情", "Details")}</button>])} text={text} empty={text("暂无合规例外", "No compliance exceptions")} />
      </InfoPanel>
      {canAction(capabilities, "agents.manage") && <InfoPanel title={text("请求例外", "Request exception")} text={text}><form className="configuration-form compact-configuration-form" onSubmit={createException}><ConfigField label={text("策略或字段", "Policy or field")} hint={text("要请求临时例外的策略键或字段。", "Policy key or field for the temporary exception.")}><input name="policy_key" required /></ConfigField><ConfigField label={text("智能体 ID", "Agent ID")} hint={text("可选；留空表示不绑定特定智能体。", "Optional; leave blank when not bound to one Agent.")}><input name="agent_id" /></ConfigField><ConfigField label={text("环境", "Environment")} hint={text("例外生效的目标环境。", "Target environment where the exception applies.")}><input name="environment" /></ConfigField><ConfigField label={text("失效时间", "Expiry")} hint={text("到期后控制器会重新评估。", "The controller reevaluates after expiry.")}><input name="expires_at" type="datetime-local" required /></ConfigField><ConfigField label={text("业务原因", "Business reason")} hint={text("必须说明为何需要该例外。", "Explain why this exception is needed.")}><input name="reason" required /></ConfigField><ConfigField label={text("操作", "Action")} hint={text("申请人与审批人必须分离。", "Requester and approver must be separate.")} action><button className="primary-button" disabled={busy}><Plus size={15} />{text("提交请求", "Submit request")}</button></ConfigField></form></InfoPanel>}
    </>}
    {tab === "controller" && <InfoPanel title={text("控制器诊断", "Controller diagnostics")} text={text}>
      <DataTable headers={[text("状态", "Status"), text("数量", "Count")]} rows={(summary.jobs || []).map((item: Row) => [displayRowValue(lang, item.status), String(item.count || 0)])} text={text} empty={text("当前账户无权查看全局控制器队列，或暂无控制器任务。", "This account cannot view the global Controller queue, or no Controller jobs exist.")} />
      <div className="empty-state">{text("最近租约节点：", "Last lease owner: ")}{summary.lease_owner || text("暂无", "None")}</div>
    </InfoPanel>}
    <DetailDrawer open={Boolean(selected)} title={text("合规详情", "Compliance details")} onClose={() => setSelected(null)} text={text} wide>
      {selected && <><pre className="decision-box">{JSON.stringify(selected, null, 2)}</pre>{selected.kind === "exception" && canAction(capabilities, "agents.manage") && <form className="cx-form" onSubmit={(event) => { event.preventDefault(); const reason = String(new FormData(event.currentTarget).get("reason") || ""); void decideException("approve", reason); }}><label>{text("决定原因", "Decision reason")}<input name="reason" required /></label><div className="actions-row"><button className="primary-button" disabled={busy}>{text("批准", "Approve")}</button><button type="button" className="small-button" disabled={busy} onClick={() => { const reason = window.prompt(text("拒绝原因", "Rejection reason")) || ""; void decideException("reject", reason); }}>{text("拒绝", "Reject")}</button><button type="button" className="small-button" disabled={busy} onClick={() => { const reason = window.prompt(text("撤销原因", "Revocation reason")) || ""; void decideException("revoke", reason); }}>{text("撤销", "Revoke")}</button></div></form>}</>}
    </DetailDrawer>
  </section>;
}

function AgentsPage({
  lang,
  me,
  capabilities,
  text,
  onNotice,
  initialView = "registered",
}: {
  lang: Lang;
  me: Row;
  capabilities: Row | null;
  text: (zh: string, en: string) => string;
  onNotice: (value: string) => void;
  initialView?: "registered" | "native";
}) {
  const [view, setView] = useUrlState<"registered" | "external" | "native">(
    "view",
    ["registered", "external", "native"],
    initialView === "native" ? "native" : "registered",
  );
  const [agents, setAgents] = useState<Row[]>([]);
  const [grants, setGrants] = useState<Row[]>([]);
  const [externalPolicy, setExternalPolicy] = useState<Row>({});
  const [token, setToken] = useState<Row | null>(null);
  const [agentSearch, setAgentSearch] = useState("");
  const [agentSourceFilter, setAgentSourceFilter] = useState("ALL");
  const [agentStatusFilter, setAgentStatusFilter] = useState("ALL");
  const [pageSize, setPageSize] = useState(20);
  const [cursorHistory, setCursorHistory] = useState<string[]>([""]);
  const [nextCursor, setNextCursor] = useState("");
  const [totalItems, setTotalItems] = useState<number | undefined>(undefined);
  const [loading, setLoading] = useState(false);
  const load = async (cursor = cursorHistory[cursorHistory.length - 1] || "") => {
    setLoading(true);
    try {
      const [registered, grantData, policyData] = await Promise.all([
        api<Row>(`/api/agents?page_size=${pageSize}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`),
        api<Row>("/api/enrollment/grants"),
        api<Row>("/api/platform/external-agent-registration"),
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
            .map((item: Row) => ({ ...item, inventory_source: "LEGACY", agent_source: "EXTERNAL_SKILL" })),
        );
      }
      setAgents(governed);
      setGrants(grantData.items || []);
      setExternalPolicy(policyData);
      setNextCursor(String(registered.next_cursor || ""));
      setTotalItems(typeof registered.total_items === "number" ? registered.total_items : undefined);
    } catch (error) {
      onNotice(
        error instanceof Error
          ? error.message
          : text("智能体清单加载失败", "Agent inventory loading failed"),
      );
    } finally { setLoading(false); }
  };
  useEffect(() => {
    void load();
  }, [pageSize]);
  const setPage = (value: number) => { setPageSize(value); setCursorHistory([""]); setNextCursor(""); };
  const nextPage = () => { if (!nextCursor) return; const history = [...cursorHistory, nextCursor]; setCursorHistory(history); void load(nextCursor); };
  const previousPage = () => { if (cursorHistory.length <= 1) return; const history = cursorHistory.slice(0, -1); setCursorHistory(history); void load(history[history.length - 1]); };
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
          ...(String(body.ttl_seconds || "").trim()
            ? { ttl_seconds: Number(body.ttl_seconds) }
            : {}),
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
  const sourceCategory = (item: Row) => String(item.agent_source || "EXTERNAL_SKILL").toUpperCase().startsWith("PLATFORM_") ? "PLATFORM" : "EXTERNAL";
  const visibleAgents = agents.filter((item) => {
    const query = agentSearch.trim().toLowerCase();
    return (!query || String(item.agent_id || "").toLowerCase().includes(query) || String(item.agent_name || "").toLowerCase().includes(query))
      && (agentSourceFilter === "ALL" || sourceCategory(item) === agentSourceFilter)
      && (agentStatusFilter === "ALL" || String(item.status || "UNKNOWN").toUpperCase() === agentStatusFilter);
  });
  const agentStatuses = Array.from(new Set(agents.map((item) => String(item.status || "UNKNOWN").toUpperCase()))).sort();
  const agentRows = visibleAgents.map((item) => {
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
      sourceCategory(item) === "PLATFORM" ? text("平台生成", "Platform-generated") : text("外部注册", "External"),
      displayRowValue(lang, item.status),
      displayRowValue(lang, item.relationship_role || item.db_status || "-"),
      controls,
    ];
  });
  const agentViews: [string, string, React.ComponentType<{ size?: number }>?][] = [
    ["registered", text("已注册智能体", "Registered Agents"), Users],
    ["external", text("外部智能体注册", "External Agent registration"), UserPlus],
    ["native", text("平台原生智能体生成", "Platform-native Agent provisioning"), Bot],
  ];
  const externalRegistration = <>
    <InfoPanel title={text("外部注册策略", "External registration policy")} text={text}>
      <div className="external-registration-status"><span className="cx-form-hint">{text("注册策略", "Registration policy")}</span><span className={`compact-status ${String(externalPolicy.state || "").toLowerCase()}`}>{externalPolicy.state ? displayRowValue(lang, externalPolicy.state) : text("读取中", "Loading")}</span><p className="cx-form-hint">{text("这里只显示新外部智能体的注册策略，不显示或预填运行时。创建令牌时必须填写 Agent 名称；既有智能体不会被删除。配置位置：平台配置 → 能力与策略 → 外部智能体注册。", "This shows only the registration policy for new external Agents; runtime is neither shown nor prefilled. An Agent name is required when creating a Token; existing Agents are not deleted. Configure it in Platform configuration → Capabilities & policies → External Agent registration.")}</p></div>
    </InfoPanel>
    <InfoPanel title={text("生成注册令牌", "Create Enrollment Token")} text={text}>
      <p className="cx-form-hint">{text("外部智能体必须携带一次性令牌通过 Skill-first 注册。令牌只显示一次，并确定智能体归属、环境和风险范围。", "An external Agent must present a one-time Token for Skill-first registration. The Token is shown once and fixes ownership, environment, and risk scope.")}</p>
      <form className="external-registration-form" onSubmit={createGrant}>
        <label>{text("智能体名称", "Agent name")}<input name="agent_name" autoComplete="off" required /></label>
        <label>{text("环境", "Environment")}<select name="environment"><option value="development">{text("开发", "Development")}</option><option value="production">{text("生产", "Production")}</option></select></label>
        <label>{text("风险等级", "Risk tier")}<select name="risk_tier"><option value="LOW">{text("低", "Low")}</option><option value="STANDARD">{text("标准", "Standard")}</option><option value="RESTRICTED">{text("受限", "Restricted")}</option></select></label>
        <label>{text("有效秒数", "TTL seconds")}<input name="ttl_seconds" type="number" min="60" max="3600" /></label>
        <button className="primary-button" type="submit"><Plus size={16} />{text("生成并仅显示一次", "Create and show once")}</button>
      </form>
      {token && <div className="one-time-token"><b>{text("请立即保存令牌", "Save this Token now")}</b><code>{token.token}</code><small>{text("平台只保存摘要，不会再次显示明文。", "Only a digest is stored; plaintext will not be shown again.")}</small></div>}
    </InfoPanel>
      <InfoPanel title={text("外部注册边界", "External registration boundary")} text={text}>
      <p>{text("外部注册不会直接获得平台管理权限。注册后仍需经过身份、归属、安全域、Skill、Tool 和审批策略检查。管理员可以在平台配置的能力与策略中关闭新的外部注册。", "External registration never grants platform-management authority. Identity, ownership, Security Domain, Skill, Tool, and approval policies are still checked after registration. Administrators can disable new external registration under Platform configuration → Capabilities & policies.")}</p>
    </InfoPanel>
    <InfoPanel title={text("注册历史", "Enrollment history")} text={text}>
      <DataTable headers={[text("令牌记录", "Grant"), text("智能体名称", "Agent name"), text("环境", "Environment"), text("使用次数", "Usage"), text("状态", "Status")]} rows={grants.map((item) => [item.grant_id, item.agent_name || "-", displayRowValue(lang, item.environment), `${item.used_count || 0}/${item.max_uses || 1}`, displayRowValue(lang, item.status)])} empty={text("暂无外部注册记录", "No external registration records")} text={text} />
    </InfoPanel>
  </>;
  if (view === "native") {
    return <section><SectionHeading title={text("智能体管理", "Agent management")} subtitle={text("平台原生管理智能体、业务智能体申请与外部 Skill-first 注册彼此分开显示，但共享同一数据库安全边界。", "Platform-native management Agents, business Agent requests, and external Skill-first registration are shown separately while sharing one database security boundary.")} text={text} /><ViewToggle value={view} onChange={(value) => setView(value as "registered" | "external" | "native")} options={agentViews} /><NativeAgentsPage lang={lang} me={me} capabilities={capabilities} text={text} onNotice={onNotice} embedded /></section>;
  }
  if (view === "external") {
    return <section><SectionHeading title={text("智能体管理", "Agent management")} subtitle={text("外部智能体通过一次性注册令牌接入，适用于 OpenClaw、Hermes 等 Skill-first Agent。", "External Agents join with a one-time enrollment Token, including Skill-first Agents such as OpenClaw and Hermes.")} text={text} /><ViewToggle value={view} onChange={(value) => setView(value as "registered" | "external" | "native")} options={agentViews} />{externalRegistration}</section>;
  }
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
      <ViewToggle value={view} onChange={(value) => setView(value as "registered" | "external" | "native")} options={agentViews} />
      <InfoPanel
          title={text("已注册智能体", "Registered Agents")}
          text={text}
        >
          <div className="filter-row agent-inventory-filters">
            <label className="filter-field"><span>{text("搜索", "Search")}</span><input value={agentSearch} onChange={(event) => setAgentSearch(event.target.value)} placeholder={text("智能体 ID 或名称", "Agent ID or name")} /></label>
            <label className="filter-field"><span>{text("来源", "Source")}</span><select value={agentSourceFilter} onChange={(event) => setAgentSourceFilter(event.target.value)}><option value="ALL">{text("全部来源", "All sources")}</option><option value="PLATFORM">{text("平台生成", "Platform-generated")}</option><option value="EXTERNAL">{text("外部注册", "External")}</option></select></label>
            <label className="filter-field"><span>{text("状态", "Status")}</span><select value={agentStatusFilter} onChange={(event) => setAgentStatusFilter(event.target.value)}><option value="ALL">{text("全部状态", "All statuses")}</option>{agentStatuses.map((status) => <option key={status} value={status}>{displayRowValue(lang, status)}</option>)}</select></label>
            <span className="filter-result-count">{text("当前结果", "Results")} {visibleAgents.length}</span>
          </div>
          <CursorPager pageSize={pageSize} page={cursorHistory.length} totalItems={totalItems} hasMore={Boolean(nextCursor)} loading={loading} onPageSize={setPage} onPrevious={previousPage} onNext={nextPage} text={text} />
          <DataTable
            headers={[
              text("智能体 ID", "Agent ID"),
              text("来源", "Source"),
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
          <CursorPager pageSize={pageSize} page={cursorHistory.length} totalItems={totalItems} hasMore={Boolean(nextCursor)} loading={loading} onPageSize={setPage} onPrevious={previousPage} onNext={nextPage} text={text} />
      </InfoPanel>
      <InfoPanel
        title={text("Enrollment 历史", "Enrollment history")}
        text={text}
      >
        <DataTable
          headers={[
            text("Grant", "Grant"),
            text("智能体名称", "Agent name"),
            text("环境", "Environment"),
            text("使用", "Usage"),
            text("状态", "Status"),
          ]}
          rows={grants.map((item) => [
            item.grant_id,
            item.agent_name || "-",
            displayRowValue(lang, item.environment),
            `${item.used_count || 0}/${item.max_uses || 1}`,
            displayRowValue(lang, item.status),
          ])}
          empty={text("暂无记录", "No records")}
          text={text}
        />
          <CursorPager pageSize={pageSize} page={cursorHistory.length} totalItems={totalItems} hasMore={Boolean(nextCursor)} loading={loading} onPageSize={setPage} onPrevious={previousPage} onNext={nextPage} text={text} />
      </InfoPanel>
    </section>
  );
}

function SecurityDomainsPage({
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
  const [domains, setDomains] = useState<Row[]>([]);
  const [principals, setPrincipals] = useState<Row[]>([]);
  const [groups, setGroups] = useState<Row[]>([]);
  const [selected, setSelected] = useState<Row | null>(null);
  const [members, setMembers] = useState<Row[]>([]);
  const [bindings, setBindings] = useState<Row[]>([]);
  const [draft, setDraft] = useState<Row | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const loadSelected = async (domain: Row) => {
    const id = encodeURIComponent(String(domain.security_domain_id));
    const [memberValue, bindingValue] = await Promise.all([
      api<Row>(`/api/security-domains/${id}/members`),
      api<Row>(`/api/security-domains/${id}/bindings`),
    ]);
    setMembers(memberValue.items || []);
    setBindings(bindingValue.items || []);
  };
  const load = async () => {
    setLoading(true);
    try {
      const [domainValue, candidateValue, groupValue] = await Promise.all([
        api<Row>("/api/security-domains?limit=300&include_inactive=true"),
        api<Row>("/api/security-domains/candidates?limit=300"),
        api<Row>("/api/security-domains/collaboration-groups?limit=300"),
      ]);
      const next = domainValue.items || [];
      setDomains(next); setPrincipals(candidateValue.items || []); setGroups(groupValue.items || []);
      if (!selected && next[0]) setSelected(next[0]);
    } catch (error) {
      onNotice(error instanceof Error ? error.message : text("安全域数据加载失败", "Security Domain data could not be loaded"));
    } finally { setLoading(false); }
  };
  useEffect(() => { void load(); }, []);
  useEffect(() => { if (selected) void loadSelected(selected); }, [selected]);
  const refresh = async () => { await load(); if (selected) await loadSelected(selected); };
  const createDomain = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setBusy(true);
    const form = event.currentTarget;
    try {
      const created = await api<Row>("/api/security-domains", { method: "POST", body: JSON.stringify(Object.fromEntries(new FormData(form).entries())) });
      form.reset(); await load(); setSelected(created);
      onNotice(text("安全域已创建。请先确认成员，再创建频道或绑定协作组。", "Security Domain created. Confirm members before creating Channels or binding a collaboration group."));
    } catch (error) { onNotice(error instanceof Error ? error.message : text("安全域创建失败", "Security Domain creation failed")); }
    finally { setBusy(false); }
  };
  const updateMember = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); if (!selected) return; setBusy(true);
    try {
      await api(`/api/security-domains/${encodeURIComponent(String(selected.security_domain_id))}/members`, { method: "POST", body: JSON.stringify(Object.fromEntries(new FormData(event.currentTarget).entries())) });
      await loadSelected(selected); onNotice(text("安全域成员已更新，后续频道准入将重新校验。", "Security Domain member updated; Channel admission will revalidate it."));
    } catch (error) { onNotice(error instanceof Error ? error.message : text("成员更新失败", "Member update failed")); }
    finally { setBusy(false); }
  };
  const bindGroup = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); if (!selected) return; setBusy(true);
    try {
      const data = Object.fromEntries(new FormData(event.currentTarget).entries());
      await api(`/api/security-domains/${encodeURIComponent(String(selected.security_domain_id))}/bindings`, { method: "POST", body: JSON.stringify({ ...data, binding_type: "LEGACY_COLLAB_GROUP" }) });
      await loadSelected(selected); await load(); onNotice(text("协作组已完成受控绑定，历史成员和共享策略未被转换为权限。", "Collaboration group bound under governance; historic members and sharing policy were not converted into authority."));
    } catch (error) { onNotice(error instanceof Error ? error.message : text("协作组绑定失败", "Collaboration group binding failed")); }
    finally { setBusy(false); }
  };
  const createDraft = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setBusy(true);
    try {
      const created = await api<Row>("/api/security-domains/conversion-drafts", { method: "POST", body: JSON.stringify(Object.fromEntries(new FormData(event.currentTarget).entries())) });
      const value = await api<Row>(`/api/security-domains/conversion-drafts/${encodeURIComponent(String(created.draft_id))}`);
      setDraft(value); onNotice(text("转换草稿已创建。请逐项确认候选成员，未确认成员不会入域。", "Conversion draft created. Confirm candidates individually; unconfirmed candidates never enter the Domain."));
    } catch (error) { onNotice(error instanceof Error ? error.message : text("转换草稿创建失败", "Conversion draft creation failed")); }
    finally { setBusy(false); }
  };
  const reviewDraftMember = async (item: Row, decision: "CONFIRMED" | "REJECTED") => {
    if (!draft) return;
    const reason = askReason(text, text("复核安全域候选成员", "Review Security Domain candidate"));
    if (!reason) return;
    setBusy(true);
    try {
      await api(`/api/security-domains/conversion-drafts/${encodeURIComponent(String(draft.draft_id))}/members/${encodeURIComponent(String(item.principal_id))}`, { method: "POST", body: JSON.stringify({ decision, membership_tier: item.membership_tier || "MEMBER", reason }) });
      setDraft(await api<Row>(`/api/security-domains/conversion-drafts/${encodeURIComponent(String(draft.draft_id))}`));
    } catch (error) { onNotice(error instanceof Error ? error.message : text("候选成员复核失败", "Candidate review failed")); }
    finally { setBusy(false); }
  };
  const applyDraft = async () => {
    if (!draft) return;
    const reason = askReason(text, text("应用安全域转换草稿", "Apply Security Domain conversion draft"));
    if (!reason) return;
    setBusy(true);
    try {
      const result = await api<Row>(`/api/security-domains/conversion-drafts/${encodeURIComponent(String(draft.draft_id))}/apply`, { method: "POST", body: JSON.stringify({ reason }) });
      await load(); setDraft(await api<Row>(`/api/security-domains/conversion-drafts/${encodeURIComponent(String(draft.draft_id))}`));
      onNotice(text(`转换已应用，已确认 ${result.confirmed_members || 0} 位主体。`, `Conversion applied with ${result.confirmed_members || 0} confirmed Principal(s).`));
    } catch (error) { onNotice(error instanceof Error ? error.message : text("转换草稿应用失败", "Conversion draft could not be applied")); }
    finally { setBusy(false); }
  };
  if (loading) return <section><SectionHeading title={text("安全域", "Security Domains")} subtitle={text("定义人、智能体、频道与协作组的零信任边界。", "Define zero-trust boundaries for Humans, Agents, Channels, and collaboration groups.")} text={text} /><PageLoading text={text} /></section>;
  return <section>
    <SectionHeading title={text("安全域", "Security Domains")} subtitle={text("安全域是授权边界；频道与协作组只在该边界内协作，不能由消息、提示词或历史成员关系扩大权限。", "A Security Domain is the authorization boundary. Channels and collaboration groups work inside it; messages, prompts, and historical membership never expand authority.")} text={text} />
    <div className="domain-page-grid">
      <InfoPanel title={text("安全域清单", "Security Domain inventory")} text={text}>
        <div className="domain-list">{domains.map((item) => <button key={item.security_domain_id} className={`list-row ${selected?.security_domain_id === item.security_domain_id ? "active" : ""}`} onClick={() => setSelected(item)}><span><b>{item.domain_name}</b><small>{item.security_domain_id} · {displayRowValue(lang, item.classification)} · {displayRowValue(lang, item.status)}</small></span><span className="tag">{item.member_count ?? 0}</span></button>)}</div>
      </InfoPanel>
      <InfoPanel title={text("创建项目安全域", "Create project Security Domain")} text={text}>
        <p className="cx-form-hint">{text("先定义项目用途、数据分级和责任人。创建时仅将责任人加入安全域；其他人员和智能体需单独确认。", "Define purpose, classification, and accountable owner first. Creation adds only the owner; all other Humans and Agents require explicit confirmation.")}</p>
        <form className="domain-form" onSubmit={createDomain}>
          <label className="inline-field"><span>{text("安全域 ID", "Security Domain ID")}</span><input name="security_domain_id" required /><small>{text("建议使用项目型标识，例如 SD_CODING_PROJECT_A。", "Use a project identifier, for example SD_CODING_PROJECT_A.")}</small></label>
          <label className="inline-field"><span>{text("名称", "Name")}</span><input name="domain_name" required /></label>
          <label className="inline-field"><span>{text("数据分级", "Classification")}</span><select name="classification" defaultValue="INTERNAL"><option value="INTERNAL">{text("内部", "Internal")}</option><option value="CONFIDENTIAL">{text("机密", "Confidential")}</option><option value="RESTRICTED">{text("受限", "Restricted")}</option></select></label>
          <label className="inline-field"><span>{text("责任人", "Accountable owner")}</span><select name="owner_principal_id" required defaultValue=""><option value="" disabled>{text("请选择平台用户", "Select a platform user")}</option>{principals.filter((item) => String(item.principal_type) === "HUMAN").map((item) => <option key={item.principal_id} value={item.principal_id}>{item.display_name} · {item.principal_id}</option>)}</select></label>
          <label className="inline-field full"><span>{text("业务用途", "Purpose")}</span><textarea name="purpose" required /></label>
          <label className="inline-field full"><span>{text("创建原因", "Reason")}</span><textarea name="reason" required /></label>
          <button className="primary-button" disabled={busy || !canAction(capabilities, "domains.manage")}><Plus size={15} />{text("创建安全域", "Create Security Domain")}</button>
        </form>
      </InfoPanel>
    </div>
    {selected && <div className="domain-detail-grid">
      <InfoPanel title={`${text("成员与有效期", "Members and validity")} · ${selected.domain_name}`} text={text}>
        <p className="cx-form-hint">{text("主体必须先成为安全域成员，才能被加入频道或以该安全域运行。暂停或撤销会在下一次受保护操作时阻断访问。", "A Principal must enter the Security Domain before Channel admission or runtime use. Suspension or revocation blocks access at the next guarded operation.")}</p>
        <div className="member-list">{members.map((item) => <div className="member-row" key={item.membership_id}><span><b>{item.display_name || item.principal_id}</b><small>{displayRowValue(lang, item.principal_type)} · {displayRowValue(lang, item.membership_tier)} · {displayRowValue(lang, item.status)}</small></span><span className="tag">{item.valid_until ? String(item.valid_until) : text("长期", "No expiry")}</span></div>)}</div>
        <form className="domain-inline-form domain-member-form" onSubmit={updateMember}>
          <label className="inline-field"><span>{text("平台主体", "Platform Principal")}</span><select name="principal_id" required defaultValue=""><option value="" disabled>{text("选择人员或智能体", "Select a Human or Agent")}</option>{principals.map((item) => <option key={item.principal_id} value={item.principal_id}>{item.display_name} · {displayRowValue(lang, item.principal_type)}</option>)}</select></label>
          <label className="inline-field"><span>{text("成员级别", "Membership tier")}</span><select name="membership_tier" defaultValue="MEMBER"><option value="MEMBER">{text("成员", "Member")}</option><option value="ADMIN">{text("管理员", "Admin")}</option><option value="VIEWER">{text("查看者", "Viewer")}</option></select></label>
          <label className="inline-field"><span>{text("有效期", "Valid until")}</span><input name="valid_until" type="datetime-local" /><small>{text("留空表示不设置到期时间。", "Leave blank for no expiry.")}</small></label>
          <label className="inline-field"><span>{text("更新原因", "Reason")}</span><input name="reason" required /></label>
          <button className="small-button" disabled={busy}><UserPlus size={14} />{text("确认成员", "Confirm member")}</button>
        </form>
      </InfoPanel>
      <InfoPanel title={text("频道与协作组绑定", "Channel and collaboration bindings")} text={text}>
        <p className="cx-form-hint">{text("绑定仅建立可追溯关系，不会将协作组的历史成员、共享工作区或共享策略转换为安全域权限。一个协作组初版只能有一个活动安全域绑定。", "A binding is traceability only. It never converts historic group members, shared workspaces, or sharing policy into Domain authority. One group initially has only one active Domain binding.")}</p>
        <div className="mini-list">{bindings.map((item) => <div className="governance-row" key={item.binding_id}><span><b>{displayRowValue(lang, item.binding_type)}</b><small>{item.target_id} · {displayRowValue(lang, item.status)}</small></span></div>)}{!bindings.length && <p className="empty-text">{text("暂无绑定", "No bindings")}</p>}</div>
        <form className="domain-inline-form domain-binding-form" onSubmit={bindGroup}>
          <label className="inline-field"><span>{text("协作组", "Collaboration group")}</span><select name="target_id" required defaultValue=""><option value="" disabled>{text("选择未绑定协作组", "Select an unbound collaboration group")}</option>{groups.filter((item) => !item.bound_security_domain_id).map((item) => <option key={item.group_id} value={item.group_id}>{item.group_name} · {item.member_count || 0} {text("个智能体", "Agents")}</option>)}</select></label>
          <label className="inline-field"><span>{text("绑定原因", "Binding reason")}</span><input name="reason" required /></label>
          <button className="small-button" disabled={busy}><ShieldCheck size={14} />{text("受控绑定", "Governed bind")}</button>
        </form>
      </InfoPanel>
    </div>}
    <InfoPanel title={text("从旧协作组创建转换草稿", "Create conversion draft from legacy collaboration group")} text={text}>
      <p className="cx-form-hint">{text("适用于已有协作组。系统仅带入智能体候选清单，不会自动加入任何智能体或人员；选择责任人并逐项确认后才能应用。", "For existing groups, the system imports only Agent candidates. It never automatically admits an Agent or Human; select an owner and review each candidate before applying.")}</p>
      <form className="domain-form domain-draft-form" onSubmit={createDraft}>
        <label className="inline-field"><span>{text("来源协作组", "Source collaboration group")}</span><select name="source_group_id" required defaultValue=""><option value="" disabled>{text("选择未绑定协作组", "Select an unbound collaboration group")}</option>{groups.filter((item) => !item.bound_security_domain_id).map((item) => <option key={item.group_id} value={item.group_id}>{item.group_name}</option>)}</select></label>
        <label className="inline-field"><span>{text("新安全域 ID", "New Security Domain ID")}</span><input name="security_domain_id" required /></label>
        <label className="inline-field"><span>{text("安全域名称", "Security Domain name")}</span><input name="domain_name" required /></label>
        <label className="inline-field"><span>{text("数据分级", "Classification")}</span><select name="classification" defaultValue="INTERNAL"><option value="INTERNAL">{text("内部", "Internal")}</option><option value="CONFIDENTIAL">{text("机密", "Confidential")}</option><option value="RESTRICTED">{text("受限", "Restricted")}</option></select></label>
        <label className="inline-field"><span>{text("责任人", "Accountable owner")}</span><select name="owner_principal_id" required defaultValue=""><option value="" disabled>{text("选择平台用户", "Select a platform user")}</option>{principals.filter((item) => String(item.principal_type) === "HUMAN").map((item) => <option key={item.principal_id} value={item.principal_id}>{item.display_name}</option>)}</select></label>
        <label className="inline-field full"><span>{text("业务用途", "Purpose")}</span><textarea name="purpose" required /></label>
        <label className="inline-field full"><span>{text("创建原因", "Reason")}</span><textarea name="reason" required /></label>
        <button className="small-button" disabled={busy}><Plus size={14} />{text("创建转换草稿", "Create conversion draft")}</button>
      </form>
      {draft && <div className="conversion-draft"><div className="subhead"><b>{text("当前转换草稿", "Current conversion draft")}</b><span className="tag">{displayRowValue(lang, draft.status)}</span></div><p className="cx-form-hint">{draft.proposed_domain_id} · {draft.domain_name} · {text("只有“已确认”成员会被写入安全域。", "Only confirmed members are written to the Security Domain.")}</p><div className="member-list">{(draft.members || []).map((item: Row) => <div className="member-row" key={item.draft_member_id}><span><b>{item.display_name || item.principal_id}</b><small>{displayRowValue(lang, item.principal_type)} · {displayRowValue(lang, item.membership_tier)} · {displayRowValue(lang, item.decision)}</small></span>{String(item.decision) === "PENDING" ? <div className="row-actions"><button className="small-button" disabled={busy} onClick={() => void reviewDraftMember(item, "CONFIRMED")}>{text("确认", "Confirm")}</button><button className="small-button danger" disabled={busy} onClick={() => void reviewDraftMember(item, "REJECTED")}>{text("拒绝", "Reject")}</button></div> : null}</div>)}</div><button className="primary-button" disabled={busy || !["DRAFT", "REVIEW", "APPROVED"].includes(String(draft.status))} onClick={() => void applyDraft()}><Check size={15} />{text("应用已复核草稿", "Apply reviewed draft")}</button></div>}
    </InfoPanel>
  </section>;
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
  const [securityDomains, setSecurityDomains] = useState<Row[]>([]);
  const [channelTotal, setChannelTotal] = useState<number | undefined>(undefined);
  const [selected, setSelected] = useState<Row | null>(null);
  const [selectedChannelId, setSelectedChannelId] = useUrlParam("channel");
  const [messages, setMessages] = useState<Row[]>([]);
  const [members, setMembers] = useState<Row[]>([]);
  const [threads, setThreads] = useState<Row[]>([]);
  const [summary, setSummary] = useState<Row>({});
  const [actions, setActions] = useState<Row[]>([]);
  const [candidates, setCandidates] = useState<Row[]>([]);
  const [bridges, setBridges] = useState<Row[]>([]);
  const [body, setBody] = useState("");
  const [selectedMessagePrincipal, setSelectedMessagePrincipal] = useState<Row | null>(null);
  const [threadId, setThreadId] = useState("");
  const [view, setView] = useUrlState("view", ["chat", "manage"] as const, "chat");
  const [pageSize, setPageSize] = useState(20);
  const [cursorHistory, setCursorHistory] = useState<string[]>([""]);
  const [nextCursor, setNextCursor] = useState("");
  const [totalItems, setTotalItems] = useState<number | undefined>(undefined);
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [messageFeedback, setMessageFeedback] = useState("");
  const [commandCatalog, setCommandCatalog] = useState<Row[]>([]);
  const [showCommandPanel, setShowCommandPanel] = useState(false);
  const messageStreamRef = useRef<HTMLDivElement>(null);
  const followLatestRef = useRef(false);
  const feedbackTimerRef = useRef<number | null>(null);
  const showTransientFeedback = (value: string, duration = 5000) => {
    if (feedbackTimerRef.current) window.clearTimeout(feedbackTimerRef.current);
    setMessageFeedback(value);
    feedbackTimerRef.current = window.setTimeout(() => setMessageFeedback(""), duration);
  };
  const load = async (cursor = cursorHistory[cursorHistory.length - 1] || "") => {
    setLoading(true);
    try {
      const [value, domainValue] = await Promise.all([
        api<Row>(`/api/channels?page_size=${pageSize}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`),
        api<Row>("/api/security-domains?limit=200"),
      ]);
      const list = value.items || [];
      setChannels(list);
      setNextCursor(String(value.next_cursor || ""));
      setChannelTotal(typeof value.total_items === "number" ? value.total_items : undefined);
      setSecurityDomains(domainValue.items || []);
      const requested = selectedChannelId
        ? list.find((item: Row) => String(item.channel_id) === selectedChannelId)
        : null;
      if (requested) setSelected(requested);
      else if (!selected && list[0]) {
        setSelected(list[0]);
        setSelectedChannelId(String(list[0].channel_id));
      } else if (selectedChannelId && !list.some((item: Row) => String(item.channel_id) === selectedChannelId)) {
        setSelected(null);
        setSelectedChannelId("");
        onNotice(text("频道不存在或当前无权访问，已返回频道列表。", "The Channel is unavailable or unauthorized; returned to the Channel list."));
      }
    } catch (error) {
      onNotice(
        error instanceof Error
          ? error.message
          : text("频道加载失败", "Channel loading failed"),
      );
    } finally { setLoading(false); }
  };
  const selectChannel = (channel: Row | null) => {
    setSelected(channel);
    setSelectedChannelId(channel ? String(channel.channel_id) : "");
    setCommandCatalog([]);
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
    if (String(channel.channel_id) === "CH_PLATFORM_ADMINISTRATION") {
      try {
        const commandValue = await api<Row>(`/api/platform/admin-commands/catalog?channel_id=${encodeURIComponent(String(channel.channel_id))}`);
        setCommandCatalog(commandValue.items || []);
      } catch {
        setCommandCatalog([]);
      }
    }
  };
  const loadIncremental = async (channel: Row) => {
    try {
      // Streaming responses update one existing message in place. Filtering
      // by created_at would miss those updates because the row timestamp does
      // not change between chunks; refresh the bounded recent window instead.
      const value = await api<Row>(`/api/channels/${encodeURIComponent(String(channel.channel_id))}/messages?limit=100`);
      const incoming = ((value.items || []) as Row[]);
      if (!incoming.length) return;
      setMessages((current) => {
        const byId = new Map(current.map((item) => [String(item.message_id), item]));
        incoming.forEach((item) => byId.set(String(item.message_id), item));
        return Array.from(byId.values()).sort((a, b) => String(a.created_at).localeCompare(String(b.created_at)));
      });
    } catch {
      // The full load remains the recovery path on the next channel selection.
    }
  };
  useEffect(() => {
    void load();
  }, [pageSize]);
  useEffect(() => {
    if (selected) {
      setThreadId("");
      // Opening a Channel is an inbox action: show its most recent activity,
      // while later manual scrolling is still respected by the normal stream
      // follow logic.
      followLatestRef.current = true;
      void loadSelected(selected);
    }
  }, [selected]);
  useEffect(() => {
    if (!selected || !messages.some((item) => String(item.message_type || "").toUpperCase() === "AGENT_RESPONSE_STREAMING")) return;
    const timer = window.setInterval(() => {
      if (document.visibilityState === "hidden") return;
      void loadIncremental(selected);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [selected, messages]);
  useEffect(() => {
    const stream = messageStreamRef.current;
    if (!stream) return;
    if (followLatestRef.current) {
      window.requestAnimationFrame(() => { stream.scrollTop = stream.scrollHeight; });
    }
    if (!messages.some((item) => String(item.message_type || "").toUpperCase() === "AGENT_RESPONSE_STREAMING")) followLatestRef.current = false;
  }, [messages]);
  const handleMessageScroll = () => {
    const stream = messageStreamRef.current;
    if (!stream) return;
    // Background streaming refreshes may update the message data, but the
    // reader controls whether those updates follow the newest message.
    followLatestRef.current = stream.scrollHeight - stream.scrollTop - stream.clientHeight < 72;
  };
  const refresh = async () => {
    await load();
    if (selected) await loadSelected(selected);
  };
  const pageChange = (value: number) => { setPageSize(value); setCursorHistory([""]); setNextCursor(""); };
  const nextPage = () => { if (!nextCursor) return; const history = [...cursorHistory, nextCursor]; setCursorHistory(history); void load(nextCursor); };
  const previousPage = () => { if (cursorHistory.length <= 1) return; const history = cursorHistory.slice(0, -1); setCursorHistory(history); void load(history[history.length - 1]); };
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
      selectChannel(created);
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
  const send = async (event?: FormEvent) => {
    event?.preventDefault();
    if (!selected || !body.trim()) return;
    followLatestRef.current = true;
    const mentions = members.flatMap((member) => {
      const displayName = String(member.display_name || "").trim();
      return displayName && body.includes(`@${displayName}`) ? [String(member.principal_id)] : [];
    });
    setSending(true);
    setMessageFeedback("");
    try {
      const result = await api<Row>(
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
            references: mentions.length ? { mentions } : {},
            response_language: lang,
          }),
        },
      );
      setBody("");
      // Keep the Channel visible immediately after the durable POST. Refreshing
      // the full Channel surface can be slower than sending, and the bounded
      // polling below already picks up Agent responses.
      void loadSelected(selected);
      const dispatches = Array.isArray(result.agent_dispatches) ? result.agent_dispatches : [];
      const dispatchErrors = Array.isArray(result.agent_dispatch_errors) ? result.agent_dispatch_errors : [];
      const message = dispatches.length
        ? text(`消息已发送，已派发给 ${dispatches.length} 个管理智能体，正在等待回复。`, `Message sent and dispatched to ${dispatches.length} management Agent(s); awaiting responses.`)
        : dispatchErrors.length
        ? text(`消息已写入审计，但管理智能体暂未派发：${String(dispatchErrors[0]?.reason || "未就绪")}`, `Message was recorded, but management Agent dispatch is unavailable: ${String(dispatchErrors[0]?.reason || "not ready")}`)
        : mentions.length
        ? text(`消息已发送，已提及 ${mentions.length} 位频道成员。`, `Message sent; mentioned ${mentions.length} Channel member(s).`)
        : text("消息已发送并已写入审计。", "Message sent and recorded in audit.");
      showTransientFeedback(message);
      onNotice(message);
      if (dispatches.length) {
        // A model invocation can legitimately outlive a single HTTP refresh.
        // Bounded polling keeps the Channel current without creating a stream
        // or polling indefinitely when an upstream model is unavailable.
        [3000, 6000, 10000, 15000, 21000, 28000, 36000].forEach((delay) => {
          window.setTimeout(() => { void loadSelected(selected); }, delay);
        });
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : text("发送失败", "Send failed");
      showTransientFeedback(message, 8000); onNotice(message);
    } finally { setSending(false); }
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
  const pinChannel = async (enabled: boolean) => {
    if (!selected) return;
    const reason = askReason(
      text,
      enabled ? text("置顶频道", "Pin Channel") : text("取消置顶频道", "Unpin Channel"),
      enabled ? text("提高频道处理优先级", "Raise Channel handling priority") : text("恢复按最新消息排序", "Return to latest-message ordering"),
    );
    if (!reason) return;
    try {
      await api(`/api/channels/${encodeURIComponent(String(selected.channel_id))}/pin`, {
        method: "POST",
        body: JSON.stringify({ decision: enabled ? "ENABLE" : "DISABLE", reason }),
      });
      setSelected({ ...selected, pinned: enabled });
      setChannels((items) => items.map((item) => (
        String(item.channel_id) === String(selected.channel_id)
          ? { ...item, pinned: enabled }
          : item
      )));
      await refresh();
      onNotice(enabled ? text("频道已置顶，并按置顶频道内最新消息排序。", "Channel pinned and ordered by newest message within pinned Channels.") : text("频道已取消置顶。", "Channel unpinned."));
    } catch (error) {
      onNotice(error instanceof Error ? error.message : text("频道置顶操作失败", "Channel pin operation failed"));
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
          "频道必须选择已授权的活动安全域。安全域先定义人员与智能体边界，再创建频道；频道不会扩大数据、API、工具或技能权限。",
          "A Channel must select an authorized active Security Domain. Define Human and Agent boundaries in the Domain before creating a Channel; a Channel never widens data, API, Tool, or Skill authority.",
        )}
      </p>
      <form className="channel-create-form" onSubmit={createChannel}>
        <div className="channel-create-fields">
          <label className="inline-field"><span>{text("频道名称", "Channel name")}</span><input name="channel_name" required /></label>
          <label className="inline-field"><span>{text("安全域", "Security Domain")}</span><select name="security_domain_id" required defaultValue="">
            <option value="" disabled>{text("请选择已授权的安全域", "Select an authorized Security Domain")}</option>
            {securityDomains.map((item) => <option key={item.security_domain_id} value={item.security_domain_id}>{item.domain_name} · {item.security_domain_id} · {displayRowValue(lang, item.classification)}</option>)}
          </select><small>{text("未列出的安全域不可用于创建频道。", "Domains not listed here cannot be used to create a Channel.")}</small></label>
          <label className="inline-field"><span>{text("数据分级", "Classification")}</span><select name="classification" defaultValue="INTERNAL">
            <option value="INTERNAL">{text("内部", "Internal")}</option>
            <option value="CONFIDENTIAL">{text("机密", "Confidential")}</option>
            <option value="RESTRICTED">{text("受限", "Restricted")}</option>
          </select></label>
          <label className="inline-field"><span>{text("频道类型", "Channel type")}</span><select name="channel_type" defaultValue="TEAM">
            <option value="TEAM">{text("团队", "Team")}</option>
            <option value="WORKFLOW">{text("工作流", "Workflow")}</option>
          </select></label>
        </div>
        <button
          className="primary-button"
          disabled={!canAction(capabilities, "channels.create")}
        >
          <Plus size={15} />
          {text("创建频道", "Create Channel")}
        </button>
        <p className="channel-create-note">
          {securityDomains.some((item) => String(item.security_domain_id) === "DEFAULT")
            ? text("DEFAULT 仅用于初始化或受限 PoC；生产项目应选择专属安全域。", "DEFAULT is for bootstrap or constrained PoC use; production projects should use a dedicated Security Domain.")
            : text("请先在“安全域”页面创建项目安全域并确认成员。", "Create a project Security Domain and confirm its members in the Security Domains page first.")}
        </p>
      </form>
    </InfoPanel>
  );
  if (loading && !selected)
    return <section><SectionHeading title={text("频道", "Channels")} subtitle={text("人和智能体在受安全域约束的频道中协作。", "Humans and Agents collaborate inside Security Domain-bound Channels.")} text={text} /><PageLoading text={text} /></section>;
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
  const mentionMatch = body.match(/(?:^|\s)@([^\s@]*)$/);
  const mentionQuery = mentionMatch ? mentionMatch[1].toLowerCase() : "";
  const mentionCandidates = mentionMatch ? members.filter((item) => {
    const name = String(item.display_name || item.principal_id || "").toLowerCase();
    const agentAlias = ["管理", "智能体", "agent", "admin"].some((alias) => mentionQuery.includes(alias))
      && String(item.principal_type || "").toUpperCase() === "AGENT";
    return name.includes(mentionQuery) || agentAlias;
  }).slice(0, 8) : [];
  const insertMention = (member: Row) => {
    const name = String(member.display_name || member.principal_id || "").trim();
    if (!name || !mentionMatch) return;
    setBody((value) => value.replace(/(?:^|\s)@([^\s@]*)$/, (matched) => `${matched.startsWith(" ") ? " " : ""}@${name} `));
    showTransientFeedback(text(`已添加对 @${name} 的提及；发送消息后将写入频道审计。`, `Mention for @${name} added; it will be recorded in Channel audit when sent.`), 4000);
  };
  const isAdministrationChannel = String(selected.channel_id) === "CH_PLATFORM_ADMINISTRATION";
  const commandPrefixMatch = body === "/" || body.toLowerCase().startsWith("/p") || body.toLowerCase().startsWith("/platform");
  const commandTokenMatch = body.match(/^\/platform(?:\s+([A-Z0-9_]*))?$/i);
  const commandQuery = commandTokenMatch ? String(commandTokenMatch[1] || "").toUpperCase() : "";
  const commandCandidates = isAdministrationChannel && commandPrefixMatch
    ? (commandCatalog || []).filter((item) => !commandQuery || String(item.command_key).startsWith(commandQuery)).slice(0, 10)
    : [];
  const insertCommand = (item: Row) => {
    setBody(String(item.example || `/platform ${item.command_key}`));
    showTransientFeedback(text("已插入命令模板。请替换尖括号参数后再发送。", "Command template inserted. Replace angle-bracket placeholders before sending."), 4000);
  };
  const insertHelp = () => {
    setBody("/platform HELP");
    showTransientFeedback(text("已插入平台命令帮助。", "Platform command help inserted."), 4000);
  };
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
            <CursorPager pageSize={pageSize} page={cursorHistory.length} totalItems={channelTotal} hasMore={Boolean(nextCursor)} loading={loading} onPageSize={pageChange} onPrevious={previousPage} onNext={nextPage} text={text} />
            {channels.map((item) => (
              <button
                key={item.channel_id}
                className={`channel-item ${selected.channel_id === item.channel_id ? "active" : ""}`}
                onClick={() => selectChannel(item)}
              >
                <MessageSquare size={15} />
                <span>
                  <strong>{enabledFlag(item.pinned) ? <><Pin className="channel-pin" size={12} />{item.channel_name}</> : item.channel_name}</strong>
                  <small>
                    {displayRowValue(lang, item.classification)} ·{" "}
                    {displayRowValue(lang, item.member_role)}
                  </small>
                </span>
              </button>
            ))}
            <CursorPager pageSize={pageSize} page={cursorHistory.length} totalItems={channelTotal} hasMore={Boolean(nextCursor)} loading={loading} onPageSize={pageChange} onPrevious={previousPage} onNext={nextPage} text={text} />
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
              <div className="channel-title-actions">
                {enabledFlag(selected.pinned) && <span className="tag"><Pin size={12} />{text("已置顶", "Pinned")}</span>}
                <ShieldCheck size={18} />
              </div>
            </div>
            {isAdministrationChannel && (
              <div className="platform-command-toolbar">
                <button type="button" className="small-button" onClick={() => setShowCommandPanel((value) => !value)}>
                  <CircleHelp size={14} />{text("平台命令", "Platform commands")}
                </button>
                <button type="button" className="small-button" onClick={insertHelp}>
                  {text("命令帮助", "Command help")}
                </button>
              </div>
            )}
            <DetailDrawer
              open={isAdministrationChannel && showCommandPanel}
              title={text("平台命令", "Platform commands")}
              onClose={() => setShowCommandPanel(false)}
              text={text}
            >
              <div className="platform-command-panel">
                <div className="subhead"><b>{text("可用平台命令", "Available platform commands")}</b></div>
                {(commandCatalog || []).map((item) => (
                  <button type="button" key={String(item.command_id)} onClick={() => insertCommand(item)}>
                    <span>
                      <b>{item.command_key}</b>
                      <small>{String(item.metadata?.[lang === "zh" ? "name_zh" : "name_en"] || "")}</small>
                      <small className="platform-command-summary">{String(item.metadata?.[lang === "zh" ? "summary_zh" : "summary_en"] || "")}</small>
                      <code>{String(item.example || `/platform ${item.command_key}`)}</code>
                    </span>
                    <small className="platform-command-state">{displayRowValue(lang, item.risk_level)} · {displayRowValue(lang, item.execution_mode)} · {String(item.executor_state || "UNAVAILABLE")}</small>
                  </button>
                ))}
                {!commandCatalog.length && <p className="cx-form-hint">{text("命令注册表暂不可用或当前没有可发现命令。", "The command registry is unavailable or no commands are discoverable.")}</p>}
              </div>
            </DetailDrawer>
            <div className="message-stream" ref={messageStreamRef} onScroll={handleMessageScroll}>
              {messages.map((item) => (
                <article className="message" key={item.message_id}>
                  <button className="message-avatar" type="button" onClick={() => setSelectedMessagePrincipal(members.find((member) => String(member.principal_id) === String(item.principal_id)) || { principal_id: item.principal_id, display_name: item.sender_display_name, principal_type: item.sender_principal_type, principal_status: item.sender_status })} title={text("查看主体信息", "View principal details")}>
                    {String(item.sender_principal_type || "").toUpperCase() === "HUMAN" ? <User size={15} /> : <Bot size={15} />}
                  </button>
                  <div>
                    <div className="message-meta">
                      <b>{item.sender_display_name || text("未命名主体", "Unnamed principal")}</b>
                      <span>{item.created_at || ""}</span>
                    </div>
                    <ChannelMarkdown value={item.body_text} streaming={String(item.message_type || "").toUpperCase() === "AGENT_RESPONSE_STREAMING"} text={text} />
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
              <label className="message-input-field"><span>{text("消息内容", "Message")}</span><textarea value={body} onChange={(event) => { const value = event.target.value; setBody(value); const match = value.match(/(?:^|\s)@([^\s@]*)$/); if (match && match[1].trim() && !members.some((member) => { const name = String(member.display_name || member.principal_id || "").toLowerCase(); const query = match[1].toLowerCase(); const agentAlias = ["管理", "智能体", "agent", "admin"].some((alias) => query.includes(alias)) && String(member.principal_type || "").toUpperCase() === "AGENT"; return name.includes(query) || agentAlias; })) { setMessageFeedback(text("当前频道没有匹配的可提及成员；提及不会扩大频道或数据访问范围。", "No matching mentionable member exists in this Channel; mentions never expand Channel or data access.")); } else { setMessageFeedback(""); } }} onKeyDown={(event) => { if (event.key === "Escape" && commandCandidates.length) { event.preventDefault(); setBody(""); } else if (commandCandidates.length && ["ArrowDown", "ArrowUp", "Tab"].includes(event.key)) { event.preventDefault(); if (event.key === "Tab") insertCommand(commandCandidates[0]); } else if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); if (commandCandidates.length && commandQuery) insertCommand(commandCandidates[0]); else void send(); } }} /><small>{text("按 Enter 发送，Shift+Enter 换行。输入 @ 可提及当前频道成员；在管理频道输入 / 可补全平台命令。提及与命令都不会自动获得额外权限。", "Press Enter to send and Shift+Enter for a new line. Type @ to mention a Channel member or / in the Administration Channel for platform commands. Mentions and commands never add authority by themselves.")}</small>{messageFeedback && <small className="operation-feedback" role="status">{messageFeedback}</small>}{commandCandidates.length > 0 && <div className="mention-menu platform-command-menu" role="listbox" aria-label={text("平台命令", "Platform commands")}>{commandCandidates.map((item) => <button type="button" role="option" key={String(item.command_id)} onClick={() => insertCommand(item)}><span>{item.command_key}<small>{String(item.metadata?.[lang === "zh" ? "name_zh" : "name_en"] || "")}</small></span><small>{displayRowValue(lang, item.risk_level)} · {displayRowValue(lang, item.execution_mode)}</small></button>)}</div>}{mentionCandidates.length > 0 && <div className="mention-menu" role="listbox" aria-label={text("提及成员", "Mention member")}>{mentionCandidates.map((member) => <button type="button" role="option" key={String(member.principal_id)} onClick={() => insertMention(member)}><span>{member.display_name || text("未命名主体", "Unnamed principal")}</span><small>{displayRowValue(lang, member.principal_type)}</small></button>)}</div>}</label>
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
                <button className="primary-button" disabled={!body.trim() || sending}>
                  <ChevronRight className={sending ? "spin" : ""} size={16} />
                  {sending ? text("发送中", "Sending") : text("发送", "Send")}
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
              title={text("讨论线程与频道成员", "Discussion Threads and Channel Members")}
              text={text}
            >
              <p className="cx-form-hint">
                {text(
                  "讨论线程用于组织频道内的消息上下文；成员才是可被邀请的人、智能体或服务主体。创建线程不会增加任何成员、数据、工具或技能权限。",
                  "Discussion threads organize message context inside a Channel. Members are the people, Agents, or service principals that can be invited. Creating a thread never adds members or grants data, Tool, or Skill authority.",
                )}
              </p>
              <form className="channel-thread-form" onSubmit={createThread}>
                <label className="inline-field">
                  <span>{text("讨论上下文类型", "Discussion context type")}</span>
                  <select name="thread_type">
                    <option value="CHANNEL">{text("频道", "Channel")}</option>
                    <option value="TASK">{text("任务", "Task")}</option>
                    <option value="RUN">{text("运行", "Run")}</option>
                    <option value="PRIVATE">{text("私有", "Private")}</option>
                    <option value="DIRECT">{text("直接", "Direct")}</option>
                  </select>
                </label>
                <label className="inline-field">
                  <span>{text(
                    "参与者主体 ID（私有/直接必填）",
                    "Participant Principal IDs (required for private/direct)",
                  )}</span>
                  <input name="participants" aria-label={text("参与者主体 ID", "Participant Principal IDs")} />
                </label>
                <button className="small-button">
                  <Plus size={14} />
                  {text("创建讨论线程", "Create discussion thread")}
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
                      <b>{item.display_name || item.principal_id}</b>
                      <small>
                        {displayRowValue(lang, item.principal_type)} ·{" "}
                        {displayRowValue(lang, item.member_role)}
                        {String(selected.channel_id) === "CH_PLATFORM_ADMINISTRATION" && String(item.principal_type).toUpperCase() === "AGENT" && ` · ${text("平台受保护", "Platform protected")}`}
                      </small>
                    </span>
                    {String(selected.channel_id) === "CH_PLATFORM_ADMINISTRATION" && String(item.principal_type).toUpperCase() === "AGENT" ? (
                      <span className="tag"><ShieldCheck size={12} />{text("不可移除", "Non-removable")}</span>
                    ) : item.member_role !== "OWNER" &&
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
              <form className="channel-member-form" onSubmit={memberAdd}>
                <label className="inline-field"><span>{text("成员主体 ID", "Member Principal ID")}</span><input name="principal_id" required /></label>
                <label className="inline-field"><span>{text("频道角色", "Channel role")}</span><select name="member_role">
                  <option value="MEMBER">{text("成员", "Member")}</option>
                  <option value="OPERATOR">{text("操作员", "Operator")}</option>
                  <option value="REVIEWER">{text("复核者", "Reviewer")}</option>
                </select></label>
                <label className="inline-field"><span>{text("加入原因", "Addition reason")}</span><input name="reason" required /></label>
                <button
                  className="small-button"
                  disabled={!canAction(capabilities, "channels.manage_members")}
                >
                  <UserPlus size={14} />
                  {text("添加", "Add")}
                </button>
              </form>
            </InfoPanel>
            <InfoPanel title={text("频道优先级", "Channel priority")} text={text}>
              <p className="cx-form-hint">
                {text(
                  "置顶只调整频道列表的处理优先级。多个置顶频道按最新消息活动排序；不会改变频道成员、消息、数据、工具、技能或安全域权限。",
                  "Pinning only changes Channel list priority. Multiple pinned Channels are ordered by their newest message activity; it never changes members, messages, data, Tools, Skills, or Security Domain authority.",
                )}
              </p>
              <div className="row-actions">
                <button
                  className="small-button"
                  disabled={!canAction(capabilities, "channels.lifecycle")}
                  onClick={() => void pinChannel(!enabledFlag(selected.pinned))}
                >
                  <Pin size={14} />
                  {enabledFlag(selected.pinned) ? text("取消置顶", "Unpin") : text("置顶频道", "Pin Channel")}
                </button>
                <span className="tag">{enabledFlag(selected.pinned) ? text("当前已置顶", "Currently pinned") : text("按消息活动排序", "Ordered by message activity")}</span>
              </div>
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
      <DetailDrawer open={Boolean(selectedMessagePrincipal)} title={text("频道消息主体", "Channel message principal")} onClose={() => setSelectedMessagePrincipal(null)} text={text}>
        {selectedMessagePrincipal && <div className="detail-record"><p><strong>{text("显示名称", "Display name")}</strong><span>{selectedMessagePrincipal.display_name || text("未命名主体", "Unnamed principal")}</span></p><p><strong>{text("主体类型", "Principal type")}</strong><span>{displayRowValue(lang, selectedMessagePrincipal.principal_type || "-")}</span></p><p><strong>{text("状态", "Status")}</strong><span>{displayRowValue(lang, selectedMessagePrincipal.principal_status || "-")}</span></p><p><strong>{text("主体 ID", "Principal ID")}</strong><code>{selectedMessagePrincipal.principal_id}</code></p></div>}
      </DetailDrawer>
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

function RegistrationGovernancePanel({
  capabilities,
  text,
  onNotice,
}: {
  capabilities: Row | null;
  text: (zh: string, en: string) => string;
  onNotice: (value: string) => void;
}) {
  const [policy, setPolicy] = useState<Row | null>(null);
  const [tokens, setTokens] = useState<Row[]>([]);
  const [issuedToken, setIssuedToken] = useState<Row | null>(null);
  const [busy, setBusy] = useState(false);
  const load = async () => {
    try {
      const [policyValue, tokenValue] = await Promise.all([
        api<Row>("/api/registration/policy?context=SELF"),
        api<Row>("/api/registration/tokens"),
      ]);
      setPolicy(policyValue);
      setTokens(tokenValue.items || []);
    } catch (error) {
      onNotice(error instanceof Error ? error.message : text("注册策略加载失败", "Unable to load registration policy"));
    }
  };
  useEffect(() => { void load(); }, []);
  const updateField = async (fieldKey: string, fieldState: string, version: number) => {
    const reason = window.prompt(text("请输入注册字段策略变更原因", "Enter a registration-field policy reason"));
    if (!reason?.trim()) return;
    setBusy(true);
    try {
      await api(`/api/registration/policy/SELF/${encodeURIComponent(fieldKey)}`, {
        method: "PUT", body: JSON.stringify({ field_state: fieldState, expected_version: version, reason }),
      });
      await load();
      onNotice(text("注册字段策略已更新", "Registration field policy updated"));
    } catch (error) { onNotice((error as Error).message); } finally { setBusy(false); }
  };
  const updateTokenPolicy = async () => {
    if (!policy) return;
    const reason = window.prompt(text("请输入一次性注册令牌策略变更原因", "Enter a one-time registration Token policy reason"));
    if (!reason?.trim()) return;
    setBusy(true);
    try {
      await api("/api/registration/token-policy", { method: "PUT", body: JSON.stringify({
        required: !Boolean(policy.token_required), expected_version: Number(policy.token_policy_version || 0), reason,
      }) });
      await load();
      onNotice(text("一次性注册令牌策略已更新", "One-time registration Token policy updated"));
    } catch (error) { onNotice((error as Error).message); } finally { setBusy(false); }
  };
  const issueToken = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const reason = String(data.get("reason") || "").trim();
    setBusy(true);
    try {
      const value = await api<Row>("/api/registration/tokens", { method: "POST", body: JSON.stringify({ expires_in_seconds: Number(data.get("expires_in_seconds") || 3600), reason }) });
      setIssuedToken(value);
      form.reset();
      await load();
      onNotice(text("一次性注册令牌已签发，明文仅在当前页面显示一次。", "One-time registration Token issued; plaintext is shown only on this page."));
    } catch (error) { onNotice((error as Error).message); } finally { setBusy(false); }
  };
  const revokeToken = async (tokenId: string) => {
    const reason = window.prompt(text("请输入撤销原因", "Enter a revocation reason"));
    if (!reason?.trim()) return;
    setBusy(true);
    try {
      await api(`/api/registration/tokens/${encodeURIComponent(tokenId)}`, { method: "DELETE", body: JSON.stringify({ reason }) });
      await load();
      onNotice(text("注册令牌已撤销", "Registration Token revoked"));
    } catch (error) { onNotice((error as Error).message); } finally { setBusy(false); }
  };
  const fields = policy?.fields || {};
  return <InfoPanel title={text("人员注册策略", "Human registration policy")} text={text}>
    <p className="cx-form-hint">{text("Portal 与 Dashboard 使用同一个注册页面；服务端按当前数据库策略校验姓名、邮箱、手机号和一次性令牌。", "Portal and Dashboard share one registration page. The server enforces current database policy for name, email, mobile, and one-time Tokens.")}</p>
    <div className="governance-list">
      {["display_name", "email", "mobile"].map((key) => {
        const item = fields[key] || {};
        const labels: Record<string, string> = { display_name: text("姓名", "Name"), email: text("邮箱", "Email"), mobile: text("手机号", "Mobile") };
        return <div className="governance-row" key={key}><span><b>{labels[key]}</b><small>{text("策略版本", "Policy version")} v{item.version || 0}</small></span><select aria-label={labels[key]} value={String(item.field_state || "OPTIONAL")} disabled={busy || !canAction(capabilities, "users.permissions.manage")} onChange={(event) => void updateField(key, event.target.value, Number(item.version || 0))}><option value="REQUIRED">{text("必填", "Required")}</option><option value="OPTIONAL">{text("选填", "Optional")}</option><option value="DISABLED">{text("不采集", "Disabled")}</option></select></div>;
      })}
      <div className="governance-row"><span><b>{text("一次性人员注册令牌", "One-time Human Registration Token")}</b><small>{policy?.token_required ? text("注册时必须提供", "Required during registration") : text("当前不要求", "Currently optional")}</small></span><button className="small-button" disabled={busy || !canAction(capabilities, "users.permissions.manage")} onClick={() => void updateTokenPolicy()}>{policy?.token_required ? text("关闭要求", "Disable requirement") : text("开启要求", "Require Token")}</button></div>
    </div>
    <div className="panel-toolbar"><strong>{text("注册令牌", "Registration Tokens")}</strong></div>
    <form className="registration-token-form" onSubmit={issueToken}>
      <ConfigField label={text("有效时间", "Validity")} hint={text("令牌到期后不能注册；建议按邀请窗口设置。", "Registration is denied after expiry; match the invitation window.")}><select name="expires_in_seconds" defaultValue="3600"><option value="1800">30 {text("分钟", "minutes")}</option><option value="3600">1 {text("小时", "hour")}</option><option value="14400">4 {text("小时", "hours")}</option><option value="86400">24 {text("小时", "hours")}</option></select></ConfigField>
      <ConfigField label={text("签发原因", "Issuance reason")} hint={text("说明邀请对象或业务用途，写入审计。", "Identify the invitee or purpose; written to audit.")}><input name="reason" required minLength={3} /></ConfigField>
      <ConfigField label={text("操作", "Action")} hint={text("每个令牌只能使用一次，平台仅保存摘要。", "Each Token is single-use; the platform stores only its digest.")} action><button className="small-button" disabled={busy || !canAction(capabilities, "users.approve")}><Plus size={14} />{text("签发一次性令牌", "Issue one-time Token")}</button></ConfigField>
    </form>
    {issuedToken && <div className="one-time-token"><b>{text("令牌明文仅显示一次", "Token plaintext is shown once")}</b><code>{String(issuedToken.token || "")}</code><small>{text("请通过受控渠道交付；离开页面后无法再次读取。", "Deliver it through a controlled channel; it cannot be retrieved after leaving this page.")}</small></div>}
    <DataTable headers={[text("令牌 ID", "Token ID"), text("签发人", "Issued by"), text("签发原因", "Reason"), text("创建时间", "Created"), text("到期时间", "Expires"), text("状态", "State"), text("操作", "Action")]} rows={tokens.map((item) => [item.token_id, item.sponsor_principal_id || "-", item.reason || "-", formatDateTime(item.created_at), formatDateTime(item.expires_at), item.revoked_at ? text("已撤销", "Revoked") : Number(item.used_count || 0) > 0 ? text("已使用", "Used") : text("可用", "Available"), !item.revoked_at && Number(item.used_count || 0) === 0 ? <button className="small-button danger" disabled={busy} onClick={() => void revokeToken(String(item.token_id))}>{text("撤销", "Revoke")}</button> : "-"])} empty={text("暂无注册令牌", "No registration Tokens")} text={text} />
  </InfoPanel>;
}

function ExternalIdentityProviderPanel({ lang, capabilities, text, onNotice }: { lang: Lang; capabilities: Row | null; text: (zh: string, en: string) => string; onNotice: (value: string) => void }) {
  const [items, setItems] = useState<Row[]>([]);
  const [busy, setBusy] = useState(false);
  const load = async () => { try { const value = await api<Row>("/api/identity/providers"); setItems(value.items || []); } catch (error) { onNotice((error as Error).message); } };
  useEffect(() => { void load(); }, []);
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); const form = event.currentTarget; const data = new FormData(form); setBusy(true);
    try {
      await api("/api/identity/providers", { method: "PUT", body: JSON.stringify({
        provider_key: data.get("provider_key"), adapter_type: data.get("adapter_type"), protocol_type: data.get("protocol_type"), issuer: data.get("issuer"), tenant_reference: data.get("tenant_reference"), redirect_allowlist: String(data.get("redirect_allowlist") || "").split("\n").map((value) => value.trim()).filter(Boolean), credential_reference: data.get("credential_reference"), registration_policy: data.get("registration_policy"), status: "DISABLED", expected_version: 0, reason: data.get("reason"),
      }) }); form.reset(); await load(); onNotice(text("身份提供方配置已保存；经适配器验证前保持不可用。", "Identity provider configuration saved; it remains unavailable until adapter validation."));
    } catch (error) { onNotice((error as Error).message); } finally { setBusy(false); }
  };
  const testProvider = async (providerId: string) => { const reason = window.prompt(text("请输入测试原因", "Enter a test reason")); if (!reason?.trim()) return; setBusy(true); try { const value = await api<Row>(`/api/identity/providers/${encodeURIComponent(providerId)}/test`, { method: "POST", body: JSON.stringify({ reason }) }); onNotice(String(value.message || text("测试完成", "Test completed"))); } catch (error) { onNotice((error as Error).message); } finally { setBusy(false); } };
  const deleteProvider = async (providerId: string) => { const reason = window.prompt(text("请输入删除原因", "Enter a deletion reason")); if (!reason?.trim()) return; setBusy(true); try { await api(`/api/identity/providers/${encodeURIComponent(providerId)}`, { method: "DELETE", body: JSON.stringify({ reason }) }); await load(); onNotice(text("身份提供方配置已删除", "Identity provider profile deleted")); } catch (error) { onNotice((error as Error).message); } finally { setBusy(false); } };
  return <InfoPanel title={text("企业身份与扫码登录", "Enterprise identity and QR login")} text={text}>
    <p className="cx-form-hint">{text("使用通用 OIDC、OAuth 2.0、SAML 2.0 或企业扫码适配器契约。仅保存配置不会启用登录，必须通过单独的适配器验证和发布证据门禁。", "Uses a provider-neutral OIDC, OAuth 2.0, SAML 2.0, or enterprise QR adapter contract. Saving configuration does not enable login; a separately validated adapter and release evidence are required.")}</p>
    <form className="configuration-form compact-configuration-form" onSubmit={submit}>
      <ConfigField label={text("配置标识", "Profile key")} hint={text("企业内唯一的稳定标识。", "A stable key unique within the installation.")}><input name="provider_key" required /></ConfigField>
      <ConfigField label={text("适配器类型", "Adapter type")} hint={text("实际落地时由经过验证的适配器提供。", "Supplied by a validated adapter during deployment.")}><input name="adapter_type" required /></ConfigField>
      <ConfigField label={text("协议", "Protocol")} hint={text("选择企业身份系统支持的标准协议。", "Choose the standard supported by the enterprise identity system.")}><select name="protocol_type" defaultValue="OIDC"><option>OIDC</option><option>OAUTH2</option><option>SAML2</option><option>ENTERPRISE_QR</option></select></ConfigField>
      <ConfigField label={text("签发方地址", "Issuer")} hint={text("OIDC/SAML 签发方；不在浏览器中保存密钥。", "OIDC/SAML issuer; secrets are not stored in the browser.")}><input name="issuer" /></ConfigField>
      <ConfigField label={text("企业租户标识", "Tenant reference")} hint={text("可选，不用于直接授予平台权限。", "Optional and never grants platform authority directly.")}><input name="tenant_reference" /></ConfigField>
      <ConfigField label={text("允许的回调地址", "Allowed redirect URIs")} hint={text("每行一个精确地址。", "One exact URI per line.")} multiline><textarea className="config-textarea" name="redirect_allowlist" rows={3} /></ConfigField>
      <ConfigField label={text("密钥引用", "Credential reference")} hint={text("填写外部密钥管理系统中的引用，不填写明文密钥。", "Use an external secret-manager reference, never a plaintext secret.")}><input name="credential_reference" /></ConfigField>
      <ConfigField label={text("首次登录策略", "First-login policy")} hint={text("外部身份不能直接授予平台权限。", "External identity cannot directly grant platform authority.")}><select name="registration_policy" defaultValue="APPROVAL"><option value="APPROVAL">{text("审批", "Approval")}</option><option value="INVITE_ONLY">{text("仅邀请", "Invite only")}</option><option value="DIRECTORY">{text("企业目录", "Directory")}</option><option value="CLOSED">{text("关闭", "Closed")}</option></select></ConfigField>
      <ConfigField label={text("变更原因", "Reason")} hint={text("必填并记录审计。", "Required and audited.")}><input name="reason" required /></ConfigField>
      <ConfigField label={text("操作", "Action")} hint={text("新配置默认关闭。", "New profiles are disabled by default.")} action><button className="small-button" disabled={busy || !canAction(capabilities, "users.security.manage")}><Plus size={14} />{text("保存配置", "Save profile")}</button></ConfigField>
    </form>
    <DataTable headers={[text("配置", "Profile"), text("协议", "Protocol"), text("能力状态", "Capability"), text("启用状态", "Status"), text("操作", "Action")]} rows={items.map((item) => [item.provider_key, item.protocol_type, displayRowValue(lang, item.capability_status), displayRowValue(lang, item.status), <span className="row-actions"><button className="small-button" disabled={busy || !canAction(capabilities, "users.security.manage")} onClick={() => void testProvider(String(item.provider_id))}>{text("测试适配器", "Test adapter")}</button><button className="small-button danger" disabled={busy || !canAction(capabilities, "users.security.manage") || String(item.status).toUpperCase() !== "DISABLED"} onClick={() => void deleteProvider(String(item.provider_id))}>{text("删除", "Delete")}</button></span>])} empty={text("暂无外部身份配置", "No external identity profiles")} text={text} />
  </InfoPanel>;
}

function PortalConnectionPanel({ principalId, capabilities, text, onNotice }: { principalId: string; capabilities: Row | null; text: (zh: string, en: string) => string; onNotice: (value: string) => void }) {
  const [value, setValue] = useState<Row | null>(null); const [busy, setBusy] = useState(false);
  const load = async () => { try { setValue(await api<Row>(`/api/users/${encodeURIComponent(principalId)}/portal-connections`)); } catch (error) { onNotice((error as Error).message); } };
  useEffect(() => { void load(); }, [principalId]);
  const policy = value?.policy || {}; const items = value?.items || [];
  const update = async (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); const data = new FormData(event.currentTarget); setBusy(true); try { await api(`/api/users/${encodeURIComponent(principalId)}/portal-connections/policy`, { method: "PUT", body: JSON.stringify({ max_connections: Number(data.get("max_connections")), expected_version: Number(policy.version || 0), reason: data.get("reason") }) }); await load(); onNotice(text("Portal 连接上限已更新", "Portal connection limit updated")); } catch (error) { onNotice((error as Error).message); } finally { setBusy(false); } };
  const release = async (connectionId: string) => { const reason = window.prompt(text("请输入终止连接的原因", "Enter a connection termination reason")); if (!reason?.trim()) return; setBusy(true); try { await api(`/api/users/${encodeURIComponent(principalId)}/portal-connections/${encodeURIComponent(connectionId)}`, { method: "DELETE", body: JSON.stringify({ reason }) }); await load(); onNotice(text("Portal 连接已终止", "Portal connection terminated")); } catch (error) { onNotice((error as Error).message); } finally { setBusy(false); } };
  return <InfoPanel title={text("Portal 连接控制", "Portal connection control")} text={text}>
    <div className="metric-grid three-up">{[[text("配置上限", "Configured limit"), policy.configured_limit ?? "-"], [text("实际生效上限", "Effective limit"), policy.effective_limit ?? "-"], [text("当前活动连接", "Active connections"), policy.active_connections ?? "-"]].map(([label, metric]) => <div className="metric-card" key={String(label)}><small>{label}</small><strong>{metric}</strong></div>)}</div>
    <form className="inline-form" onSubmit={update}><label className="inline-field"><span>{text("每用户 Portal 连接数", "Portal connections per user")}</span><input name="max_connections" type="number" min="1" max="8" defaultValue={Number(policy.configured_limit || 1)} required /></label><label className="inline-field"><span>{text("变更原因", "Reason")}</span><input name="reason" required /></label><button className="small-button" disabled={busy || !canAction(capabilities, "users.permissions.manage")}>{text("更新上限", "Update limit")}</button></form>
    <DataTable headers={[text("连接", "Connection"), text("节点", "Node"), text("状态", "State"), text("最近心跳", "Last heartbeat"), text("操作", "Action")]} rows={items.map((item: Row) => [item.connection_id, item.node_id, displayRowValue("zh", item.status), formatDateTime(item.last_heartbeat_at), String(item.status).toUpperCase() === "ACTIVE" ? <button className="small-button danger" disabled={busy || !canAction(capabilities, "sessions.revoke")} onClick={() => void release(String(item.connection_id))}>{text("终止", "Terminate")}</button> : "-"])} empty={text("暂无 Portal 连接", "No Portal connections")} text={text} />
  </InfoPanel>;
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
  const [section, setSection] = useUrlState<"accounts" | "registration" | "identity">(
    "section",
    ["accounts", "registration", "identity"],
    "accounts",
  );
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
  const [pageSize, setPageSize] = useState(20);
  const [cursorHistory, setCursorHistory] = useState<string[]>([""]);
  const [nextCursor, setNextCursor] = useState("");
  const [totalItems, setTotalItems] = useState<number | undefined>(undefined);
  const [loading, setLoading] = useState(false);
  const userRequest = useRef(0);

  const load = (cursor = cursorHistory[cursorHistory.length - 1] || "") => {
    setLoading(true);
    return Promise.all([
      api<Row>(`/api/users?page_size=${pageSize}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`),
      api<Row>("/api/registration/requests?status=PENDING"),
      api<Row>("/api/organization/options"),
    ])
      .then(([userResponse, requestResponse, organizationResponse]) => {
        const pending = requestResponse.items || [];
        const options = organizationResponse.items || [];
        setUsers(userResponse.items || []);
        setNextCursor(String(userResponse.next_cursor || ""));
        setTotalItems(typeof userResponse.total_items === "number" ? userResponse.total_items : undefined);
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
      ).finally(() => setLoading(false));
  };

  useEffect(() => {
    void load();
  }, [pageSize]);
  const pageChange = (value: number) => { setPageSize(value); setCursorHistory([""]); setNextCursor(""); };
  const nextPage = () => { if (!nextCursor) return; const history = [...cursorHistory, nextCursor]; setCursorHistory(history); void load(nextCursor); };
  const previousPage = () => { if (cursorHistory.length <= 1) return; const history = cursorHistory.slice(0, -1); setCursorHistory(history); void load(history[history.length - 1]); };

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
    const formElement = event.currentTarget;
    const data = Object.fromEntries(
      new FormData(formElement).entries(),
    );
    const value = await run(
      api(
        `/api/users/${encodeURIComponent(String(selected.principal_id))}/roles`,
        { method: "POST", body: JSON.stringify(data) },
      ),
      text("角色已分配", "Role assigned"),
    );
    if (value) {
      formElement.reset();
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
    const formElement = event.currentTarget;
    const data = Object.fromEntries(
      new FormData(formElement).entries(),
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
      formElement.reset();
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
    const formElement = event.currentTarget;
    const data = Object.fromEntries(
      new FormData(formElement).entries(),
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
      formElement.reset();
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
      <ViewToggle value={section} onChange={(value) => setSection(value as typeof section)} options={[
        ["accounts", text("注册用户与用户清单", "Registration & users"), Users],
        ["registration", text("人员注册策略", "Human registration policy"), ShieldCheck],
        ["identity", text("企业身份与扫码登录", "Enterprise identity & QR login"), UserPlus],
      ]} />
      <div className="nested-tabs-separator" aria-hidden="true" />
      {section === "registration" && <RegistrationGovernancePanel capabilities={capabilities} text={text} onNotice={onNotice} />}
      {section === "identity" && <ExternalIdentityProviderPanel lang={lang} capabilities={capabilities} text={text} onNotice={onNotice} />}
      {section === "accounts" && <>
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
          <CursorPager pageSize={pageSize} page={cursorHistory.length} totalItems={totalItems} hasMore={Boolean(nextCursor)} loading={loading} onPageSize={pageChange} onPrevious={previousPage} onNext={nextPage} text={text} />
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
          <CursorPager pageSize={pageSize} page={cursorHistory.length} totalItems={totalItems} hasMore={Boolean(nextCursor)} loading={loading} onPageSize={pageChange} onPrevious={previousPage} onNext={nextPage} text={text} />
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
          <PortalConnectionPanel principalId={String(selected.principal_id)} capabilities={capabilities} text={text} onNotice={onNotice} />
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
              <label className="inline-field"><span>{text("变更原因", "Change reason")}</span><input name="reason" required /></label>
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
                <label className="inline-field"><span>{text("权限动作", "Permission action")}</span><input name="action" required /></label>
                <span></span>
                <button
                  className="primary-button"
                  disabled={busy || !canAction(capabilities, "users.read")}
                >
                  <ShieldCheck size={15} />
                  {text("模拟", "Simulate")}
                </button>
              </form>
              <p className="inline-form-note">{text("例如 agents.read。", "For example, agents.read.")}</p>
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
                <label className="inline-field"><span>{text("提供方", "Provider")}</span><input name="provider" required /></label>
                <label className="inline-field"><span>{text("不可变主体 ID", "Immutable subject ID")}</span><input name="subject_key" required /></label>
                <label className="inline-field"><span>{text("绑定原因", "Link reason")}</span><input name="reason" required /></label>
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
                <label className="inline-field"><span>{text("受让人主体 ID", "Grantee Principal ID")}</span><input name="grantee_principal_id" required /></label>
                <label className="inline-field"><span>{text("权限", "Permissions")}</span><input name="permissions" required /></label>
                <label className="inline-field"><span>{text("数据范围", "Data scope")}</span><select name="data_scope" defaultValue="ASSIGNED">
                  <option value="ASSIGNED">
                    {text("分配范围", "Assigned")}
                  </option>
                  <option value="OWNED">{text("所有者范围", "Owned")}</option>
                  <option value="ORG_SUBTREE">
                    {text("组织子树", "Organization subtree")}
                  </option>
                </select></label>
                <label className="inline-field"><span>{text("有效期", "Valid until")}</span><input name="valid_until" /></label>
                <label className="inline-field"><span>{text("委派原因", "Delegation reason")}</span><input name="reason" required /></label>
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
              <p className="inline-form-note">{text("多个权限使用逗号分隔；有效期可选，填写 ISO 时间。", "Separate multiple permissions with commas. Valid until is optional and uses an ISO timestamp.")}</p>
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
      </>}
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
  const [pageSize, setPageSize] = useState(20);
  const [cursorHistory, setCursorHistory] = useState<string[]>([""]);
  const [nextCursor, setNextCursor] = useState("");
  const [totalItems, setTotalItems] = useState<number | undefined>(undefined);
  const load = async (cursor = cursorHistory[cursorHistory.length - 1] || "") => {
    setLoading(true);
    try {
      const [agentData, metricData] = await Promise.all([
        api<Row>(`/api/monitor/agents-page?page_size=${pageSize}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`),
        api<Row>("/api/monitor/metrics"),
      ]);
      setAgents(listPayload(agentData, ["agents"]));
      setNextCursor(String(agentData.next_cursor || ""));
      setTotalItems(typeof agentData.total_items === "number" ? agentData.total_items : undefined);
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
    setCursorHistory([""]); setNextCursor(""); void load("");
    const timer = window.setInterval(() => void load(), 30000);
    return () => window.clearInterval(timer);
  }, [pageSize]);
  const setPage = (value: number) => { setPageSize(value); setCursorHistory([""]); setNextCursor(""); };
  const nextPage = () => { if (!nextCursor) return; const history = [...cursorHistory, nextCursor]; setCursorHistory(history); void load(nextCursor); };
  const previousPage = () => { if (cursorHistory.length <= 1) return; const history = cursorHistory.slice(0, -1); setCursorHistory(history); void load(history[history.length - 1]); };
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
        <CursorPager pageSize={pageSize} page={cursorHistory.length} totalItems={totalItems} hasMore={Boolean(nextCursor)} loading={loading} onPageSize={setPage} onPrevious={previousPage} onNext={nextPage} text={text} />
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
        <CursorPager pageSize={pageSize} page={cursorHistory.length} totalItems={totalItems} hasMore={Boolean(nextCursor)} loading={loading} onPageSize={setPage} onPrevious={previousPage} onNext={nextPage} text={text} />
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
      const formElement = event.currentTarget;
      const form = new FormData(formElement);
      try {
        await api("/api/skill/create", { method: "POST", body: form });
        formElement.reset();
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
      const formElement = event.currentTarget;
      const form = new FormData(formElement);
      try {
        await api(`/api/skill/${encodeURIComponent(selected)}/upload`, {
          method: "POST",
          body: form,
        });
        formElement.reset();
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
                  defaultValue=""
                  required
                />
              </label>
              <label>
                {text("版本", "Version")}
                <input
                  name="skill_version"
                  defaultValue=""
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
      const formElement = event.currentTarget;
      const body = Object.fromEntries(
        new FormData(formElement).entries(),
      );
      await run("/api/branch/fork", body);
      formElement.reset();
    };
    const target = items.find((item) => String(item.branch_id) === selected);
    return (
      <InfoPanel title={text("分支操作", "Branch operations")} text={text}>
        <p className="cx-form-hint">{text("创建分支只建立独立上下文与归属记录，不会合并、执行或覆盖源上下文。后续暂停、恢复和废弃均保留审计轨迹。", "Creating a Branch establishes isolated context and ownership only; it does not merge, execute, or overwrite the source context. Later pause, resume, and abandonment actions remain auditable.")}</p>
        <form className="operation-explainer-form" onSubmit={fork}>
          <label className="workbench-field"><span>{text("工作区 ID", "Workspace ID")}</span><input name="workspace_id" required /><small>{text("指定新分支所属的工作区。", "Sets the workspace that owns the new Branch.")}</small></label>
          <label className="workbench-field"><span>{text("起始上下文 ID", "Fork context ID")}</span><input name="fork_context_id" /><small>{text("可选；指定从哪一条上下文开始分叉。", "Optional; identifies the context from which to fork.")}</small></label>
          <label className="workbench-field"><span>{text("分支名称", "Branch name")}</span><input name="branch_name" required /><small>{text("用于列表和审计中的可读标识。", "A readable identifier for lists and audit.")}</small></label>
          <label className="workbench-field"><span>{text("分支类型", "Branch type")}</span><select name="branch_type" defaultValue="EXPERIMENT"><option value="EXPERIMENT">{text("实验", "Experiment")}</option><option value="HANDOFF">{text("移交", "Handoff")}</option><option value="PARALLEL">{text("并行", "Parallel")}</option></select><small>{text("说明分支的协作意图，不授予额外权限。", "Records collaboration intent; it grants no extra authority.")}</small></label>
          <label className="workbench-field"><span>{text("目标智能体 ID", "Target Agent ID")}</span><input name="agent_id" required /><small>{text("指定承载该分支的智能体。", "Sets the Agent responsible for this Branch.")}</small></label>
          <label className="workbench-field"><span>{text("源智能体 ID", "Source Agent ID")}</span><input name="source_agent_id" /><small>{text("可选；记录来源智能体，便于交接追溯。", "Optional; records the source Agent for handoff traceability.")}</small></label>
          <label className="workbench-field"><span>{text("分支目的", "Branch purpose")}</span><input name="purpose" required /><small>{text("写入审计记录，说明为何需要该分支。", "Written to audit records to explain the Branch.")}</small></label>
          <div className="workbench-field workbench-action"><span>{text("操作", "Action")}</span><button className="primary-button" disabled={!canAction(capabilities, "branches.write")}><GitBranch size={15} />{text("创建分支", "Create Branch")}</button><small>{text("仅创建分支定义，不会启动执行。", "Creates the Branch definition only; it does not start execution.")}</small></div>
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
    const formElement = event.currentTarget;
    const data = Object.fromEntries(
      new FormData(formElement).entries(),
    );
    await run("/api/loops/create", {
      title: data.title,
      summary: data.summary,
      visibility: data.visibility,
      goal_definition: { goal: data.goal || data.title },
      stop_conditions: { max_iterations: Number(data.max_iterations || 10) },
      evaluation_config: { eval_type: "MANUAL" },
    });
    formElement.reset();
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
      <p className="cx-form-hint">{text("创建循环只保存定义与停止条件，不会自动启动运行。请从下方选定循环后明确点击“启动运行”；暂停、恢复和停止均由运行状态机处理。", "Creating a Loop stores its definition and stop condition only; it never starts a run automatically. Select the Loop below and explicitly start it; pause, resume, and stop use the run state machine.")}</p>
      <form className="operation-explainer-form" onSubmit={createLoop}>
        <label className="workbench-field"><span>{text("循环标题", "Loop title")}</span><input name="title" required /><small>{text("用于识别该循环定义。", "Identifies this Loop definition.")}</small></label>
        <label className="workbench-field"><span>{text("目标", "Goal")}</span><input name="goal" required /><small>{text("定义每次迭代要达成的结果。", "Defines the result each iteration works toward.")}</small></label>
        <label className="workbench-field"><span>{text("摘要", "Summary")}</span><input name="summary" /><small>{text("可选；为操作人员提供简短背景说明。", "Optional; provides brief context for operators.")}</small></label>
        <label className="workbench-field"><span>{text("最大迭代次数", "Maximum iterations")}</span><input name="max_iterations" type="number" min="1" defaultValue="10" /><small>{text("达到上限后循环停止，防止无限运行。", "Stops the Loop at this limit to prevent unbounded runs.")}</small></label>
        <label className="workbench-field"><span>{text("可见性", "Visibility")}</span><select name="visibility" defaultValue="PRIVATE"><option value="PRIVATE">{text("私有", "Private")}</option><option value="SHARED">{text("共享", "Shared")}</option></select><small>{text("控制定义的可见范围，不替代数据授权。", "Controls definition visibility; it does not replace data authorization.")}</small></label>
        <div className="workbench-field workbench-action"><span>{text("操作", "Action")}</span><button className="primary-button" disabled={!canAction(capabilities, "loops.write")}><Plus size={15} />{text("创建循环", "Create Loop")}</button><small>{text("仅创建定义；运行需单独启动。", "Creates the definition only; start a run separately.")}</small></div>
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
  actions,
}: {
  title: string;
  subtitle: string;
  text: (zh: string, en: string) => string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="section-heading">
      <div className="section-heading-main">
        <h1>{title}</h1>
        <p>{subtitle}</p>
      </div>
      <div className="section-heading-actions">
        {actions}
        <span className="secure-badge">
          <ShieldCheck size={15} />
          {text("数据库授权", "DB governed")}
        </span>
      </div>
    </div>
  );
}
function PageRefresh({
  loading,
  onRefresh,
  text,
}: {
  loading: boolean;
  onRefresh: () => void | Promise<void>;
  text: (zh: string, en: string) => string;
}) {
  return <button className="icon-button" onClick={() => void onRefresh()} title={text("刷新", "Refresh")}><RefreshCw className={loading ? "spin" : ""} size={15} />{text("刷新", "Refresh")}</button>;
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
  protectedView = false,
}: {
  title: string;
  children: React.ReactNode;
  text: (zh: string, en: string) => string;
  protectedView?: boolean;
}) {
  return (
    <section className="info-panel">
      <div className="panel-title">
        <h2>{title}</h2>
        {protectedView && <span>{text("受保护视图", "Protected view")}</span>}
      </div>
      {children}
    </section>
  );
}
function ConfigField({
  label,
  hint,
  children,
  action = false,
  multiline = false,
}: {
  label: string;
  hint: string;
  children: React.ReactNode;
  action?: boolean;
  multiline?: boolean;
}) {
  return (
    <div className={`config-field${action ? " config-action" : ""}${multiline ? " config-multiline" : ""}`}>
      <span>{label}</span>
      {children}
      <small>{hint}</small>
    </div>
  );
}
function LocalAgentPathField({ text }: { text: (zh: string, en: string) => string }) {
  const [basePath, setBasePath] = useState("");
  const normalized = basePath.trim().replace(/\/+$/, "");
  const finalPath = normalized
    ? (normalized.endsWith("/AI-Agent-Infra-with-DB") ? normalized : `${normalized}/AI-Agent-Infra-with-DB`)
    : "";
  return (
    <div className="config-field local-agent-path-field">
      <span>{text("本地目录的父目录", "Local directory parent")}</span>
      <input name="agent_info_path" value={basePath} onChange={(event) => setBasePath(event.target.value)} required />
      <small>{finalPath
        ? `${text("实际存储目录", "Resolved storage directory")}: ${finalPath}`
        : text("必须填写绝对路径，例如 /root；平台将自动追加 AI-Agent-Infra-with-DB。", "Enter an absolute path such as /root; the platform appends AI-Agent-Infra-with-DB.")}</small>
    </div>
  );
}
function ViewToggle({
  value,
  options,
  onChange,
  className = "",
}: {
  value: string;
  options: [string, string, React.ComponentType<{ size?: number }>?][];
  onChange: (value: string) => void;
  className?: string;
}) {
  return (
    <div className={`view-toggle${className ? ` ${className}` : ""}`} role="tablist">
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
