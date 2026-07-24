/* Chuanxu UI behavior is local and framework-free. */
(function () {
  "use strict";
  var root = document.documentElement;
  var build = root.dataset || {};
  function readPreference() {
    try { return window.localStorage; } catch (_) { return null; }
  }
  var storage = readPreference();
  var query = new URLSearchParams(window.location.search);
  var queryLang = query.get("cx_lang");
  var queryTheme = query.get("cx_theme");
  var savedLang = queryLang || (storage && (storage.getItem("cx-lang") || storage.getItem("lang")));
  var savedTheme = queryTheme || (storage && (storage.getItem("cx-theme") || storage.getItem("theme")));
  var lang = savedLang === "en" ? "en" : "zh";
  var theme = savedTheme === "dark" ? "dark" : "light";
  var valueLabels = {
    ONLINE: ["在线", "Online"], BUSY: ["忙碌", "Busy"], IDLE: ["空闲", "Idle"],
    DORMANT: ["休眠", "Dormant"], STALLED: ["停滞", "Stalled"],
    PENDING: ["待处理", "Pending"], RUNNING: ["运行中", "Running"], BLOCKED: ["已阻塞", "Blocked"],
    SUCCESS: ["成功", "Success"], SUCCEEDED: ["成功", "Succeeded"], FAILED: ["失败", "Failed"],
    CANCELLED: ["已取消", "Cancelled"], COMPLETED: ["已完成", "Completed"], PARTIAL: ["部分完成", "Partial"],
    ACTIVE: ["启用", "Active"], INACTIVE: ["未启用", "Inactive"], DISABLED: ["已禁用", "Disabled"],
    DEPRECATED: ["已弃用", "Deprecated"], APPROVED: ["已批准", "Approved"], REJECTED: ["已拒绝", "Rejected"],
    REVIEW_REQUIRED: ["待复核", "Post-review"], EXPIRED: ["已过期", "Expired"],
    PAUSED: ["已暂停", "Paused"], STOPPED: ["已停止", "Stopped"], TIMEOUT: ["已超时", "Timed out"],
    ARCHIVED: ["已归档", "Archived"], IMPLEMENTED: ["已实现", "Implemented"],
    DECOMMISSIONED: ["已退役", "Decommissioned"], REMOVED: ["已移除", "Removed"],
    SUSPENDED: ["已挂起", "Suspended"], REVOKED: ["已撤销", "Revoked"], POOL: ["池中", "Pooled"],
    DUPLICATE_CONFLICT: ["重复冲突", "Duplicate conflict"], DRAFT: ["草稿", "Draft"], REVIEWED: ["已复核", "Reviewed"],
    ALLOW: ["允许", "Allow"], DENY: ["拒绝", "Deny"], APPROVAL_REQUIRED: ["需要审批", "Approval required"],
    METADATA: ["元数据", "Metadata"], BOUNDED: ["有限详情", "Bounded"], HASHED: ["哈希", "Hashed"],
    ENCRYPTED_REFERENCE: ["加密引用", "Encrypted reference"],
    READ: ["读取", "Read"], WRITE: ["写入", "Write"], SEARCH: ["搜索", "Search"], CALL: ["调用", "Call"],
    RUN: ["运行", "Run"], EXPORT: ["导出", "Export"], DELETE: ["删除", "Delete"],
    AUDIT_RETENTION: ["审计留存", "Audit retention"], EMERGENCY_DISABLE: ["应急禁用", "Emergency disable"],
    GRANT_REVOKE: ["撤销授权", "Grant revoke"], VALIDATION_AUDIT: ["验证审计", "Validation audit"],
    APPROVAL_DECISION: ["审批决策", "Approval decision"], GRANT_CREATE: ["创建授权", "Grant creation"],
    POLICY_CREATE: ["创建策略", "Policy creation"], RESOURCE_REGISTER: ["注册资源", "Resource registration"],
    APPROVAL_REQUEST: ["发起审批", "Approval request"], RETENTION_FIXTURE: ["留存验证", "Retention validation"],
    RECORDED: ["已记录", "Recorded"], DECISION_RECORDED: ["已记录决策", "Decision recorded"],
    RETENTION_APPLIED: ["已应用留存", "Retention applied"], EMERGENCY_COMPLETED: ["应急操作完成", "Emergency completed"],
    GRANT_REVOKED: ["授权已撤销", "Grant revoked"], EMERGENCY_PARTIAL: ["应急操作部分完成", "Emergency partial"],
    VALIDATION: ["验证", "Validation"], APPROVAL_RECORDED: ["审批已记录", "Approval recorded"],
    POLICY_AND_GRANT_MATCH: ["策略与授权匹配", "Policy and grant match"], GRANT_ISSUED: ["授权已签发", "Grant issued"],
    POLICY_REGISTERED: ["策略已注册", "Policy registered"], RESOURCE_REGISTERED: ["资源已注册", "Resource registered"],
    APPROVAL_CREATED: ["审批已创建", "Approval created"], POLICY_MATCH: ["策略匹配", "Policy match"],
    APPROVAL_EXPIRED: ["审批已过期", "Approval expired"], APPROVER_INELIGIBLE: ["审批人不符合条件", "Approver ineligible"],
    SEPARATION_OF_DUTIES: ["职责分离", "Separation of duties"], GRANT_EXPIRED: ["授权已过期", "Grant expired"],
    AGENT_NOT_REGISTERED: ["智能体未注册", "Agent not registered"], EXPLICIT_POLICY_REQUIRED: ["需要显式策略", "Explicit policy required"],
    FIXTURE: ["验证数据", "Fixture"], GRANT_POLICY_MISMATCH: ["授权与策略不匹配", "Grant and policy mismatch"],
    MEMORY: ["记忆", "Memory"], KNOWLEDGE: ["知识", "Knowledge"], TASK_OUTPUT: ["任务输出", "Task output"],
    EXPERIENCE: ["经验", "Experience"], HARNESS_TEMPLATE: ["模板", "Harness template"], SPEC: ["规格", "Spec"],
    SKILL: ["技能", "Skill"], LOOP_DEFINITION: ["循环定义", "Loop definition"],
    DATABASE_DATA: ["数据库数据", "Database data"], API: ["API", "API"], TOOL: ["工具", "Tool"],
    WORKSPACE: ["工作区", "Workspace"], DATA_EXTRACT: ["数据转储", "Data extract"],
    INTERNAL: ["内部", "Internal"], SENSITIVE: ["敏感", "Sensitive"], RESTRICTED: ["受限", "Restricted"],
    UNKNOWN: ["未知", "Unknown"], NEVER: ["从未", "Never"], PRODUCTION: ["生产", "Production"],
    CUSTOM: ["自定义", "Custom"], BUILTIN: ["内置", "Built-in"], TEMPLATE: ["模板", "Template"],
    WORKFLOW: ["工作流", "Workflow"], TEXT: ["文本", "Text"], SCRIPT: ["脚本", "Script"], HYBRID: ["混合", "Hybrid"],
    PYTHON: ["Python", "Python"], BASH: ["Bash", "Bash"], NODE: ["Node.js", "Node.js"], OTHER: ["其他", "Other"],
    CANCEL_WORK: ["取消任务", "Cancel work"], DISABLE_AGENT: ["禁用智能体", "Disable Agent"],
    RELEASE_POOL: ["释放池分配", "Release pool assignment"], REVOKE_GRANTS: ["撤销授权", "Revoke grants"],
    ROTATE_CREDENTIALS: ["轮换凭证", "Rotate credentials"], TERMINATE_SESSIONS: ["终止会话", "Terminate sessions"],
    BUSINESS: ["业务", "Business"], WORKER: ["执行", "Worker"], COORDINATOR: ["协调", "Coordinator"],
    SYSTEM: ["系统", "System"], TEST: ["测试", "Test"], GENERIC: ["通用", "Generic"],
    "GENERIC-SKILL": ["通用技能", "Generic Skill"], PLATFORM: ["平台", "Platform"], MANAGED: ["托管", "Managed"],
    SHARING: ["分享", "Sharing"], COORDINATION: ["协调", "Coordination"], DATA_SHARING: ["数据共享", "Data sharing"],
    KNOWLEDGE_SHARE: ["知识共享", "Knowledge sharing"], KNOWLEDGE_TRANSFER: ["知识移交", "Knowledge transfer"],
    TASK_DELEGATION: ["任务委派", "Task delegation"], TASK_HANDOFF: ["任务交接", "Task handoff"],
    CONVERSATION: ["会话", "Conversation"], AUTONOMOUS: ["自主", "Autonomous"], COLLAB_GROUP: ["协作组", "Collaboration group"],
    PERSONAL_IN_GROUP: ["组内个人", "Personal in group"], TASK_CHAIN: ["任务链", "Task chain"],
    ISOLATED: ["隔离", "Isolated"], SHARED: ["共享", "Shared"], PUBLIC: ["公开", "Public"],
    HIGH: ["高", "High"], MEDIUM: ["中", "Medium"], LOW: ["低", "Low"], CRITICAL: ["关键", "Critical"],
    ENTITY: ["实体", "Entity"], GLOBAL: ["全局", "Global"], PROCESSING: ["处理", "Processing"],
    SECURITY: ["安全", "Security"], STORAGE: ["存储", "Storage"],
    MERGED: ["已合并", "Merged"], ABANDONED: ["已废弃", "Abandoned"], EXPLORATION: ["探索", "Exploration"],
    HANDOFF: ["交接", "Handoff"], PARALLEL: ["并行", "Parallel"], ROLLBACK: ["回滚", "Rollback"],
    FAST_FORWARD: ["快进合并", "Fast-forward"], THREE_WAY: ["三方合并", "Three-way"], SQUASH: ["压缩合并", "Squash"],
    MISTAKE: ["错误", "Mistake"], INSIGHT: ["洞察", "Insight"], ALTERNATIVE: ["替代方案", "Alternative"],
    AD_HOC: ["临时", "Ad hoc"], PROJECT: ["项目", "Project"], TEAM: ["团队", "Team"], PIPELINE: ["流水线", "Pipeline"],
    MODERATED: ["受控", "Moderated"], OPEN: ["开放", "Open"],
    LEAD: ["负责人", "Lead"], CONTRIBUTOR: ["贡献者", "Contributor"], MEMBER: ["成员", "Member"],
    OBSERVER: ["观察者", "Observer"], LEFT: ["已离开", "Left"], PRIVATE: ["私有", "Private"],
    MANUAL: ["手动评估", "Manual"], SCHEDULE: ["定时触发", "Schedule"], EVENT: ["事件触发", "Event"], HOOK: ["钩子触发", "Hook"],
    DIFF: ["差异评估", "Diff"], LLM_JUDGE: ["模型评判", "LLM judge"],
    SPEC_VALIDATION: ["规格验证", "Spec validation"], AGGREGATE: ["聚合评估", "Aggregate"],
    PASS: ["通过", "Pass"], FAIL: ["未通过", "Fail"]
  };
  root.setAttribute("data-lang", lang);
  root.setAttribute("data-theme", theme);
  root.setAttribute("lang", lang === "zh" ? "zh-CN" : "en");

  function valueLabel(value, requestedLang) {
    if (value === null || value === undefined || value === "") return "";
    var raw = String(value);
    var labels = valueLabels[raw.trim().toUpperCase()];
    if (!labels) return raw;
    return (requestedLang || lang) === "en" ? labels[1] : labels[0];
  }
  function valueList(value, requestedLang) {
    var items = value;
    if (typeof items === "string") {
      try { items = JSON.parse(items); } catch (_) { items = items.split(","); }
    }
    if (!Array.isArray(items)) return valueLabel(value, requestedLang);
    return items.map(function (item) { return valueLabel(item, requestedLang); }).join(", ");
  }

  function asset(name) { return "/static/brand/" + name; }
  function icon(name) {
    return '<svg aria-hidden="true"><use href="/static/chuanxu-icons.svg#' + name + '"></use></svg>';
  }
  function chosenLogo(onDark) {
    if (onDark || theme === "dark") return asset(lang === "zh" ? "chuanxu-logo-zh-on-dark.svg" : "chuanxu-logo-en-on-dark.svg");
    return asset(lang === "zh" ? "chuanxu-logo-zh.svg" : "chuanxu-logo-en.svg");
  }
  function syncLogos() {
    document.querySelectorAll(".cx-lockup, .cx-auth-lockup").forEach(function (img) {
      img.src = chosenLogo(!!img.closest(".sidebar"));
    });
  }
  function applyLanguage(next) {
    lang = next === "en" ? "en" : "zh";
    root.setAttribute("data-lang", lang);
    root.setAttribute("lang", lang === "zh" ? "zh-CN" : "en");
    try { if (storage) { storage.setItem("cx-lang", lang); storage.setItem("lang", lang); } } catch (_) {}
    document.querySelectorAll("[data-zh]").forEach(function (el) { el.hidden = lang !== "zh"; });
    document.querySelectorAll("[data-en]").forEach(function (el) { el.hidden = lang !== "en"; });
    document.querySelectorAll("[data-ph-zh]").forEach(function (el) {
      el.placeholder = lang === "zh" ? el.getAttribute("data-ph-zh") : el.getAttribute("data-ph-en") || "";
    });
    document.querySelectorAll("option[data-label-zh]").forEach(function (option) {
      option.textContent = lang === "zh" ? option.getAttribute("data-label-zh") : option.getAttribute("data-label-en") || option.getAttribute("data-label-zh");
    });
    syncLogos();
    document.querySelectorAll(".cx-theme-toggle").forEach(function (button) {
      button.title = theme === "dark" ? (lang === "zh" ? "切换亮色" : "Use light theme") : (lang === "zh" ? "切换暗色" : "Use dark theme");
      button.setAttribute("aria-label", button.title);
    });
    try { window.dispatchEvent(new CustomEvent("chuanxu-language-change", { detail: { lang: lang } })); } catch (_) {}
  }
  function applyTheme(next) {
    theme = next === "dark" ? "dark" : "light";
    root.setAttribute("data-theme", theme);
    try { window.dispatchEvent(new CustomEvent("chuanxu-theme-change", { detail: { theme: theme } })); } catch (_) {}
    try { if (storage) { storage.setItem("cx-theme", theme); storage.setItem("theme", theme); } } catch (_) {}
    syncLogos();
    document.querySelectorAll(".cx-theme-toggle").forEach(function (button) {
      var label = theme === "dark" ? (lang === "zh" ? "亮色" : "Light") : (lang === "zh" ? "暗色" : "Dark");
      button.innerHTML = icon(theme === "dark" ? "sun" : "moon") + "<span class=\"cx-theme-label\">" + label + "</span>";
      button.title = theme === "dark" ? (lang === "zh" ? "切换亮色" : "Use light theme") : (lang === "zh" ? "切换暗色" : "Use dark theme");
      button.setAttribute("aria-label", button.title);
    });
  }
  function addLogo() {
    var sidebar = document.querySelector(".sidebar-brand");
    if (sidebar && !sidebar.querySelector(".cx-lockup")) {
      var image = document.createElement("img");
      image.className = "cx-lockup";
      image.alt = "Chuanxu";
      image.src = chosenLogo(true);
      sidebar.insertBefore(image, sidebar.firstChild);
    }
    var auth = document.querySelector(".login-card h2, .portal-card h2");
    if (auth && !auth.querySelector(".cx-auth-lockup")) {
      var authLogo = document.createElement("img");
      authLogo.className = "cx-auth-lockup";
      authLogo.alt = "Chuanxu";
      authLogo.src = chosenLogo(false);
      // Keep the localized product name rendered by the template below the logo.
      auth.insertBefore(authLogo, auth.firstChild);
    }
  }
  function addBuildMeta() {
    var bar = document.querySelector(".main-content .top-bar, body > .top-bar");
    if (!bar || bar.querySelector(".cx-build-meta")) return;
    var meta = document.createElement("span");
    meta.className = "cx-build-meta";
    var db = build.cxDb || "Chuanxu";
    var tier = build.cxTier || "";
    var version = build.cxVersion || "";
    meta.textContent = [db, tier, version ? "v" + version : ""].filter(Boolean).join(" / ");
    bar.appendChild(meta);
  }
  function addPlatformName() {
    var brand = document.querySelector(".sidebar-brand");
    if (!brand || brand.querySelector(".cx-sidebar-platform-name")) return;
    var name = document.createElement("span");
    name.className = "cx-sidebar-platform-name";
    name.innerHTML = '<span data-zh>AI Agent 管理平台</span><span data-en>AI Agent Management Platform</span>';
    brand.appendChild(name);
  }
  function addThemeToggle() {
    if (document.querySelector(".cx-theme-toggle")) return;
    var button = document.createElement("button");
    button.type = "button";
    button.className = "cx-theme-toggle";
    button.addEventListener("click", function () { applyTheme(theme === "dark" ? "light" : "dark"); });
    var bar = document.querySelector(".main-content .top-bar, body > .top-bar");
    if (bar) bar.appendChild(button);
    else {
      var footer = document.querySelector(".sidebar-footer");
      if (footer) footer.insertBefore(button, footer.querySelector(".lang-toggle") || footer.firstChild);
      else {
        var card = document.querySelector(".login-card, .portal-card");
        if (card) { var toolbar = document.createElement("div"); toolbar.className = "cx-card-toolbar"; toolbar.appendChild(button); card.insertBefore(toolbar, card.firstChild); }
        else document.body.appendChild(button);
      }
    }
    applyTheme(theme);
  }
  function updateBrand() { addLogo(); addPlatformName(); addBuildMeta(); addThemeToggle(); applyLanguage(lang); applyTheme(theme); }

  function graphPalette() {
    var styles = getComputedStyle(root);
    var dark = root.getAttribute("data-theme") === "dark";
    return {
      labelBackground: styles.getPropertyValue("--cx-surface-strong").trim() || (dark ? "#172033" : "#f4f6f8"),
      text: styles.getPropertyValue("--cx-text").trim() || "#102033",
      muted: styles.getPropertyValue("--cx-text-secondary").trim() || "#465a73",
      edge: dark ? "#8296b5" : "#6d8096"
    };
  }
  function nodeTextColor(background) {
    var hex = String(background || "").replace("#", "");
    if (hex.length !== 6) return "#fff";
    var rgb = [0, 2, 4].map(function (index) { return parseInt(hex.substring(index, index + 2), 16) / 255; });
    rgb = rgb.map(function (value) { return value <= .03928 ? value / 12.92 : Math.pow((value + .055) / 1.055, 2.4); });
    return .2126 * rgb[0] + .7152 * rgb[1] + .0722 * rgb[2] > .36 ? "#102033" : "#fff";
  }
  function graphFont(size, background, foreground) {
    var palette = graphPalette();
    var labelBackground = background || palette.labelBackground;
    return { color: foreground || palette.text, background: labelBackground, size: size, strokeWidth: 5, strokeColor: labelBackground };
  }
  window.ChuanxuGraph = {
    palette: graphPalette,
    nodeFont: function (background, size) { return graphFont(size || 11, background, nodeTextColor(background)); },
    edgeFont: function (size) { return graphFont(size || 9); },
    nodeTextColor: nodeTextColor
  };
  window.ChuanxuUI = {
    applyLanguage: applyLanguage,
    applyTheme: applyTheme,
    valueLabel: valueLabel,
    valueList: valueList
  };
  document.addEventListener("DOMContentLoaded", function () {
    window.toggleLang = function () { applyLanguage(lang === "zh" ? "en" : "zh"); };
    window.applyLang = function (next) { applyLanguage(next); };
    document.querySelectorAll(".lang-toggle").forEach(function (button) {
      button.setAttribute("aria-label", "Switch language");
    });
    updateBrand();
  });
}());
