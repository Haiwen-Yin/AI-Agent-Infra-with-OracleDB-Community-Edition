# i18n Localization Pattern — Pure Language Display

## User Requirement
User explicitly rejected bilingual display ("中文 / English" mixed text).要求纯中文或纯英文，不能混用。

## Pattern: localStorage + getLang()

### 1. i18n Dictionary (Pure Strings)
```javascript
const i18n = {
    zh: {
        title_zh: '知识图谱', title_en: '记忆内容',
        instructions: '操作指南',  // NOT '操作指南 / Instructions'
        graphBtn: '知识图谱',
        memoryBtn: '记忆内容',
        logout: '退出登录',
    },
    en: {
        title_zh: 'Knowledge Graph', title_en: 'Memory Content',
        instructions: 'Instructions',  // NOT 'Instructions / 操作指南'
        graphBtn: 'Knowledge',
        memoryBtn: 'Memory',
        logout: 'Logout',
    }
};
```

### 2. Dynamic Language Reading (NOT const)
```javascript
// WRONG: const curLang = localStorage.getItem('lang') || 'zh';
// This freezes at page load, doesn't update when toggleLang() is called

// CORRECT: function that reads dynamically
function getLang() { return localStorage.getItem('lang') || 'zh'; }
```

### 3. Toggle + Persist
```javascript
function toggleLang(lang) {
    localStorage.setItem('lang', lang);
    applyLang(lang);
}
```

### 4. Apply on Page Load
```javascript
applyLang(getLang());  // Reads from localStorage each time
```

### 5. Navigation Buttons (Preserve Language)
```javascript
// Don't need to manually save language — localStorage already has it
document.getElementById('btn-graph').onclick = function() {
    window.location.href = '/knowledge';
};
```

## Why Not Bilingual?
- User find "操作指南 / Instructions" ugly and cluttered
- User wants clean, professional display in one language
- Language switch should be instant, no page reload needed
- localStorage persists across page navigation automatically

## Common Mistake
Using `const curLang = localStorage.getItem('lang')` at page top — this value is frozen.
When user clicks English, `toggleLang('en')` updates localStorage and DOM, but
clicking a nav button triggers page reload, and `curLang` still holds the OLD value
from when the page first loaded. Use `getLang()` function instead.
