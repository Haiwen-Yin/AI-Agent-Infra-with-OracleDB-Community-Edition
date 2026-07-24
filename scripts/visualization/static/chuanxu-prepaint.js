/* Resolve explicit product preferences before the first paint. */
(function () {
  "use strict";
  var root = document.documentElement;
  var lang = "zh";
  var theme = "light";
  try {
    var query = new URLSearchParams(window.location.search);
    var queryLang = query.get("cx_lang");
    var queryTheme = query.get("cx_theme");
    var storage = window.localStorage;
    var preferenceVersion = root.getAttribute("data-cx-version") || "4.1.0";
    if (storage.getItem("cx-ui-preferences-version") !== preferenceVersion) {
      // Reset legacy preferences once so a version upgrade keeps the product
      // default (Chinese and light) instead of inheriting stale UI state.
      storage.setItem("cx-ui-preferences-version", preferenceVersion);
      storage.setItem("cx-lang", "zh");
      storage.setItem("lang", "zh");
      storage.setItem("cx-theme", "light");
      storage.setItem("theme", "light");
    }
    var savedLang = storage.getItem("cx-lang") || storage.getItem("lang");
    var savedTheme = storage.getItem("cx-theme") || storage.getItem("theme");
    if (savedLang === "en") lang = "en";
    if (savedTheme === "dark") theme = "dark";
    if (queryLang === "en" || queryLang === "zh") lang = queryLang;
    if (queryTheme === "dark" || queryTheme === "light") theme = queryTheme;
  } catch (_) {}
  root.setAttribute("data-lang", lang);
  root.setAttribute("data-theme", theme);
  root.setAttribute("lang", lang === "zh" ? "zh-CN" : "en");
}());
