# Web Visualization Server Bilingual Support Guide

**Author**: Haiwen Yin (胖头鱼 🐟)  
**Feature Version**: v1.5.0  
**Date**: 2026-05-12

---

## Overview

The Web Visualization Server now supports **Chinese/English bilingual interface**, allowing users to dynamically switch between languages without page reload limitations or separate language builds.

---

## Architecture

### Backend Enhancements

#### 1. i18n Dictionary Structure
```python
_i18n = {
    'zh': {
        'oracle_memory_system': 'Oracle Memory System',
        'knowledge_graph': '知识图谱',
        'memory_content': '记忆内容',
        'knowledge_graph_viz': '知识图谱可视化',
        'memory_content_viz': '记忆内容可视化',
        'operation_guide': '操作指南：',
        'drag_nodes': '• 拖拽：移动节点',
        'scroll_zoom': '• 滚轮：缩放视图',
        'click_details': '• 点击：查看详情',
        'statistics': '统计信息：',
        'nodes_count': '节点数',
        'edges_count': '边数',
        'status': '状态：',
        'js_checking': 'JavaScript: 检查中...',
        'js_ok': 'JavaScript: 加载成功',
        'js_error': 'JavaScript: 加载失败',
        'vis_checking': 'vis-network: 检查中...',
        'vis_ok': 'vis-network: 加载成功',
        'vis_error': 'vis-network: 加载失败',
        'node_details': '节点详情',
        'node_id': 'ID',
        'node_type': '类型',
        'node_label': '名称',
        'detailed_info': '详细信息：',
        'click_to_load': '点击节点加载...',
        'switch_lang': '切换语言',
        'login_title': '登录 - Oracle Memory System',
        'login_subtitle': 'Web Visualization Server',
        'login_prompt': '请登录以访问可视化界面',
        'username': '用户名',
        'password': '密码',
        'login_btn': '登录',
        'login_failed': '登录失败',
        'login_success': '登录成功',
        'welcome': '欢迎',
    },
    'en': {
        'oracle_memory_system': 'Oracle Memory System',
        'knowledge_graph': 'Knowledge Graph',
        'memory_content': 'Memory Content',
        'knowledge_graph_viz': 'Knowledge Graph Visualization',
        'memory_content_viz': 'Memory Content Visualization',
        'operation_guide': 'Operation Guide:',
        'drag_nodes': '• Drag: Move nodes',
        'scroll_zoom': '• Scroll: Zoom view',
        'click_details': '• Click: View details',
        'statistics': 'Statistics:',
        'nodes_count': 'Nodes',
        'edges_count': 'Edges',
        'status': 'Status:',
        'js_checking': 'JavaScript: Checking...',
        'js_ok': 'JavaScript: Loaded',
        'js_error': 'JavaScript: Failed',
        'vis_checking': 'vis-network: Checking...',
        'vis_ok': 'vis-network: Loaded',
        'vis_error': 'vis-network: Failed',
        'node_details': 'Node Details',
        'node_id': 'ID',
        'node_type': 'Type',
        'node_label': 'Label',
        'detailed_info': 'Details:',
        'click_to_load': 'Click node to load...',
        'switch_lang': 'Switch Language',
        'login_title': 'Login - Oracle Memory System',
        'login_subtitle': 'Web Visualization Server',
        'login_prompt': 'Please login to access visualization',
        'username': 'Username',
        'password': 'Password',
        'login_btn': 'Login',
        'login_failed': 'Login failed',
        'login_success': 'Login successful',
        'welcome': 'Welcome',
    }
}
```

#### 2. Session Data Structure Enhancement
```python
# BEFORE (v1.4.0)
_sessions = {}  # session_token: {username, created_at, expires_at, role}

# AFTER (v1.5.0)
_sessions = {}  # session_token: {username, created_at, expires_at, role, language}
```

**Changes**:
- Added `language` field to session dictionary
- Default language: `zh` (Chinese)
- Language stored at session creation and updated on switch

#### 3. Language Switch API Endpoint
```python
def handle_switch_language(self):
    """Handle language switch request"""
    # 1. Validate session (authentication required)
    token = self.get_session_token()
    if not token:
        self.send_401()
        return
    
    session = validate_session(token)
    if not session:
        self.send_401()
        return
    
    # 2. Parse POST data
    content_length = int(self.headers.get('Content-Length', 0))
    post_data = self.rfile.read(content_length).decode('utf-8')
    
    params = {}
    for pair in post_data.split('&'):
        if '=' in pair:
            key, value = pair.split('=', 1)
            params[key] = value
    
    new_lang = params.get('language', 'zh')
    
    # 3. Validate language (only zh/en allowed)
    if new_lang not in ('zh', 'en'):
        new_lang = 'zh'
    
    # 4. Update session language
    with _sessions_lock:
        if token in _sessions:
            _sessions[token]['language'] = new_lang
    
    # 5. Send success response
    self.send_response(200)
    self.send_header('Content-Type', 'application/json')
    self.send_cors_headers()
    self.end_headers()
    self.wfile.write(json.dumps({'success': True, 'language': new_lang}).encode('utf-8'))
```

### Frontend Enhancements

#### 1. Language Switch Button
```html
<a href="#" class="lang-switch" onclick="switchLanguage()">
    🌐 {t['switch_lang']} ({'English' if language == 'zh' else '中文'})
</a>
```

**Button Styling**:
```css
.lang-switch {
    display: inline-block;
    margin: 10px 0;
    padding: 8px 15px;
    background: rgba(255,255,255,0.3);
    border: 2px solid rgba(255,255,255,0.5);
    border-radius: 5px;
    color: white;
    text-decoration: none;
    transition: all 0.3s;
    cursor: pointer;
}
.lang-switch:hover {
    background: rgba(255,255,255,0.4);
    border-color: rgba(255,255,255,0.8);
}
```

#### 2. JavaScript i18n Integration
```javascript
// Backend injects i18n dictionaries
var i18nText = {
    'zh': { /* Chinese text mappings */ },
    'en': { /* English text mappings */ }
};

var currentLanguage = 'zh';  // Set by backend

// Language switch function
function switchLanguage() {
    var newLang = currentLanguage === 'zh' ? 'en' : 'zh';
    fetch('/api/switch-language', {
        method: 'POST',
        headers: {'Content-Type': 'application/x-www-form-urlencoded'},
        body: 'language=' + newLang,
        credentials: 'same-origin'
    }).then(response => {
        if (response.ok) {
            location.reload();  // Refresh page with new language
        }
    });
}
```

#### 3. Dynamic UI Text Updates
```javascript
// Status messages with i18n
function handleLoadError() {
    var t = i18nText[currentLanguage];
    document.getElementById('js-status').innerHTML = 
        'JavaScript: <span class="error">✗ ' + 
        (currentLanguage === 'zh' ? '加载失败' : 'Failed') + 
        '</span>';
    alert(
        currentLanguage === 'zh' ? 
        '无法加载 vis-network.js，请检查服务器配置' : 
        'Cannot load vis-network.js, please check server configuration'
    );
}

window.onload = function() {
    if (typeof vis !== 'undefined') {
        var t = i18nText[currentLanguage];
        document.getElementById('js-status').innerHTML = 
            'JavaScript: <span class="success">✓ ' + 
            (currentLanguage === 'zh' ? '已加载' : 'Loaded') + 
            '</span>';
        initGraph();
    }
};
```

---

## Usage Guide

### 1. Start the Server
```bash
cd /root/.hermes/skills/oracle-memory-by-yhw
python3 viz_server_local_js.py
```

**Output**:
```
======================================================================
         Oracle Memory System - Web Visualization Server
         (Local JavaScript - No CDN Dependency)
======================================================================
✅ Starting server on http://0.0.0.0:8000
   Local:   http://localhost:8000
   Network: http://10.10.10.135:8000
```

### 2. Login to the System
- **URL**: http://10.10.10.135:8000/login
- **Default Credentials**:
  - Username: `admin`
  - Password: `admin123`

### 3. Switch Language
- **Method 1**: Click the language switch button in the sidebar
  - Button text: "🌐 切换语言"
  - Target language shown: "🌐 Switch Language"

- **Method 2**: Use the API programmatically
```bash
# Switch to English
curl -b /tmp/cookies.txt -X POST \
  -d "language=en" \
  http://10.10.10.135:8000/api/switch-language

# Switch to Chinese
curl -b /tmp/cookies.txt -X POST \
  -d "language=zh" \
  http://10.10.10.135:8000/api/switch-language
```

### 4. Verify Language Switch
After clicking the switch button:
1. **API Response**: `{success: true, language: 'en'}`
2. **Page Reload**: Browser refreshes automatically
3. **UI Update**: All interface text changes to selected language
4. **Session Update**: Language preference stored in session

---

## Testing Checklist

### Backend Testing
```bash
# 1. Login and get session
curl -c /tmp/cookies.txt -X POST \
  -d "username=admin&password=admin123" \
  http://10.10.10.135:8000/api/login

# 2. Switch to English
curl -b /tmp/cookies.txt -X POST \
  -d "language=en" \
  http://10.10.10.135:8000/api/switch-language
# Expected: {"success": true, "language": "en"}

# 3. Switch to Chinese
curl -b /tmp/cookies.txt -X POST \
  -d "language=zh" \
  http://10.10.10.135:8000/api/switch-language
# Expected: {"success": true, "language": "zh"}

# 4. Access page with new language
curl -b /tmp/cookies.txt http://10.10.10.135:8000/graph | grep "Knowledge Graph"
# Should find English text after switching to 'en'
```

### Frontend Testing
- [ ] Login page displays correctly in default language (Chinese)
- [ ] Language switch button is visible in sidebar
- [ ] Clicking switch button toggles between zh/en
- [ ] Page reloads automatically after language switch
- [ ] All UI elements update with new language
- [ ] JavaScript status messages update correctly
- [ ] Node details panel text updates correctly
- [ ] Navigation buttons text updates correctly
- [ ] Statistics section text updates correctly

---

## Implementation Notes

### Key Decisions

1. **Session-Scoped Language Preference**
   - Language stored in session, not in database
   - Resets when session expires (1 hour default)
   - No additional database tables required

2. **Default Language: Chinese (zh)**
   - Matches user preference for Chinese interface
   - Consistent with existing Chinese documentation

3. **Full Coverage**
   - All user-facing text elements covered
   - Error messages in both languages
   - Status messages in both languages
   - Form labels and buttons in both languages

4. **Atomic Switching**
   - Language change happens instantly
   - Page reload ensures complete UI update
   - No partial text updates (avoids inconsistencies)

### Performance Considerations

- **Minimal Overhead**: Language switch requires one API call and one page reload
- **No Database Query**: Session update is in-memory operation
- **Caching Still Works**: Graph data cache unaffected by language changes
- **JavaScript Payload**: i18n dictionaries add ~5KB to HTML (negligible)

### Security Considerations

- **Authentication Required**: Language switch protected by session validation
- **No CSRF**: Simple implementation (acceptable for internal tool)
- **Input Validation**: Only accepts `zh` or `en`, rejects other values
- **Session Isolation**: Language preference scoped to user session only

---

## Troubleshooting

### Issue: Language doesn't change after clicking button
**Diagnosis**:
```bash
# Check if API call succeeds
curl -b /tmp/cookies.txt -X POST \
  -d "language=en" \
  -v http://10.10.10.135:8000/api/switch-language

# Expected: HTTP/1.0 200 OK + JSON response
```

**Solutions**:
1. Check browser console for JavaScript errors
2. Verify session cookie is valid (not expired)
3. Check server logs for error messages

### Issue: Some text still in Chinese after switching to English
**Diagnosis**:
```bash
# Check HTML contains both language mappings
curl -b /tmp/cookies.txt http://10.10.10.135:8000/graph | grep "i18nText"
# Should find: 'zh': {...}, 'en': {...}
```

**Solutions**:
1. Check if all text elements use `t['key']` pattern
2. Verify page reload completed (not interrupted)
3. Check browser cache (force refresh with Ctrl+F5)

### Issue: Language resets to default after session expiry
**Diagnosis**:
```bash
# Check session timeout setting
# grep SESSION_TIMEOUT viz_server_local_js.py
# Default: 3600 seconds (1 hour)
```

**Solution**: This is expected behavior. Language preference is session-scoped.

---

## Future Enhancements

### Planned Improvements

1. **Persistent Language Preference**
   - Store language choice in localStorage
   - Load from localStorage on page load
   - Fallback to session if localStorage empty

2. **Browser Language Detection**
   - Detect browser language on first visit
   - Auto-set to user's preferred language
   - Example: `navigator.language` or `navigator.userLanguage`

3. **Additional Languages**
   - Add Japanese (ja)
   - Add Korean (ko)
   - Add other regional languages as needed

4. **Language-Specific Routing**
   - Support URL-based language selection
   - Example: `/graph/en`, `/graph/zh`
   - Enables direct language selection via URL

---

## Related Files

- `viz_server_local_js.py` - Main server with bilingual support
- `references/web-visualization-server-authentication-integration.md` - Authentication integration guide
- `references/web-visualization-dual-page-architecture.md` - Dual-page architecture documentation

---

## References

- MDN Web Docs: Best Practices for i18n - https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Intl
- W3C i18n Standards: https://www.w3.org/International/
- Flask-Babel: Python i18n library reference - https://python-babel.readthedocs.io/
