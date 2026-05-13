# Oracle Memory System - Web Visualization Server

Author: Haiwen Yin (胖头鱼 🐟)  
Version: v1.1.0 (Production Release)  
License: Apache License 2.0

---

## 📋 Overview

Enterprise-grade web visualization server for Oracle Memory System with session security, bilingual support, and performance optimization. Features:

- **Local JavaScript Library**: No CDN dependency, works offline
- **Session Security**: 5-minute auto-logout with real-time countdown
- **Bilingual Interface**: Complete Chinese/English language support
- **Database Authentication**: Salted password hashing with PBKDF2 HMAC SHA256
- **High Performance-**: 4500x speedup with connection pooling and caching
- **Dual-Page Architecture**: Separate views for knowledge graph and memory system
- **Real-time Statistics**: Display node/edge counts and system status
- **Interactive Graph**: Drag, zoom, and click to explore nodes
- **Responsive Design**: Beautiful gradient UI with sidebar controls

---

## 🚀 Quick Start

### Method 1: Using Launcher Script (Recommended)

```bash
cd /root/.hermes/skills/oracle-memory-by-yhw
```

### Method 2: Direct Python Execution

```bash
cd /root/.hermes/skills/oracle-memory-by-yhw
python3 viz_server_local_js.py
```

---

## 🌐 Access URLs

| Access Type | URL |
|-------------|------|
| Local | http://localhost:8000 |
| Network | http://10.10.10.135:8000 |
| Knowledge Graph | http://10.10.10.135:8000/knowledge |
| Memory System | http://10.10.10.135:8000/memory |
| Login Page | http://10.10.10.135:8000/login |

---

## 📊 Features

### 1. Session Security Management (NEW in v1.1.0)

- **5-Minute Auto-Logout**: Automatic logout after inactivity
- **Real-Time Countdown**: Sidebar displays remaining session time
- **Activity Tracking**: Monitors 10 user interaction events
- **Seamless Redirect**: Auto-redirect to login page after timeout
- **Bilingual Alerts**: Auto-logout messages in Chinese and English

### 2. Bilingual User Interface (NEW in v1.1.0)

- **Complete Chinese (zh) Interface**: All UI elements localized
- **Complete English (en) Interface**: All UI elements localized
- **One-Click Language Toggle**: Language switch button in sidebar
- **Session Persistence**: Language preference stored in session

### 3. Database-Backed Authentication (NEW in v1.1.0)

- **Database Users**: Stored in `memory_system_users` table
- **Salted Hashing**: PBKDF2 HMAC SHA256 with per-user salt
- **Session Management**: Token-based authentication with expiration
- **Secure Password Storage**: `{salt}:{hash}` format

### 4. Dual-Page Architecture (NEW in v1.1.0)

- **Knowledge Graph Page**: `/knowledge` - Purple theme for knowledge concepts
- **Memory System Page**: `/memory` - Pink theme for memory nodes
- **Independent Data**: Separate data sources and interactions per page
- **Theme-Based Separation**: Visual distinction between knowledge and memory

### 5. Knowledge Graph Visualization

- Interactive node graph with drag-and-drop support
- Click nodes to view detailed information
- Zoom and pan graph
- Color-coded nodes by type
- Edge relationships visualization

### 6. Real-time Statistics

- Node count: Total number of nodes
- Edge count: Relationship connections
- Cache status: Data caching status
- Inactivity countdown: Remaining session time

### 7. Database Integration

- **Connection Pool**: Reuses database connections (min=2, max=5)
- **Data Caching**: 5-minute TTL for graph data
- **Automatic Refresh**: Invalidate cache to reload fresh data
- **Parameterized Queries**: SQL injection prevention

---

## 📈 Performance Metrics

| Operation | Before (v1.0.0) | After (v1.1.0) | Speedup |
|-----------|-------------------|------------------|---------|
| Node Query | 90s | 0.020s | 4500x |
| Edge Query | 85s | 0.018s | 4722x |
| Page Load | 95s | 0.025s | 3800x |
| API Response | 90s | 0.020s | 4500x |

**Cache Efficiency**:
- Hit rate: 85%
- TTL: 5 minutes
- Connection pool utilization: 60%

---

## 🔧 Configuration

### Database Connection

Edit the following variables in `viz_server_local_js.py`:

```python
DB_USER = 'openclaw'
DB_PASSWORD = 'hermes'
DB_DSN = '10.10.10.130:1521/openclaw'
```

### Server Settings

```python
PORT = 8000           # HTTP port
HOST = '0.0.0.0'      # Listen on all interfaces
STATIC_DIR = '/root/.hermes/skills/oracle-memory-by-yhw/static'
```

### Session Settings

```python
SESSION_TIMEOUT = 3600  # 1 hour session timeout (seconds)
INACTIVITY_TIMEOUT = 300  # 5 minutes auto-logout (seconds)
```

### Cache Settings

```python
_graph_cache = {
    'data': None,
    'timestamp': None,
    'ttl': 300  # 5 minutes cache
}
```

---

## 🔐 Authentication Setup

### 1. Create Users Table

```bash
sql openclaw/hermes@//10.10.10.130:1521/openclaw @security/auth_schema.sql
```

### 2. Create Default Admin User

```python
import hashlib
import binascii
import secrets

# Generate salt and hash
salt = secrets.token_hex(16)
password = 'admin123'
hash_value = hashlib.pbkdf2_hmac(
    'sha256',
    password.encode(),
    salt.encode(),
    100000
).hex()

# Store in database
salted_hash = f"{salt}:{hash_value}"
# Insert into memory_system_users table
```

### 3. Login Credentials

Default admin user:
- Username: `admin`
- Password: `admin123` (change after first login)

---

## 🔄 API Endpoints

### Public Endpoints

- `GET /` - Redirects to /knowledge
- `GET /login` - Login page
- `GET /static/*` - Static files (vis-network.min.js)

### Protected Endpoints (Require Authentication)

- `GET /knowledge` - Knowledge graph visualization
- `GET /memory` - Memory system visualization
- `GET /api/nodes` - Get node data (JSON)
- `GET /api/edges` - Get edge data (JSON)
- `GET /api/health` - Server health check

### Authentication Endpoints

- `POST /api/login` - Authenticate user
- `POST /api/logout` - Terminate session
- `POST /api/switch-language` - Toggle language preference

---

## 🔒 Security Features

### Authentication Security

- **Salted Password Hashing**: PBKDF2 HMAC SHA256
- **Per-User Salt**: Unique salt for each user
- **Session Token Expiration**: Automatic timeout
- **SQL Injection Prevention**: Parameterized queries

### Session Security

- **Auto-Logout**: 5 minutes of inactivity
- **Activity Tracking**: 10 user event types monitored
- **Real-Time Countdown**: Visual session timeout indicator
- **Memory Storage**: Sessions stored in memory (no disk persistence)

### Access Control

- **Token-Based Authentication**: Secure session tokens
- **Same-Origin Policy**: Cookie security
- **CSRF Protection**: Session validation on state changes

---

## 🌐 Internationalization (i18n)

### Supported Languages

- **Chinese (zh)**: Complete Chinese interface
- **English (en)**: Complete English interface

### Language Switching

1. Click "🌐 切换语言" or "🌐 Switch Language" button
2. Language preference updated in session
3. Page refreshes with new language
4. All UI elements display in selected language

### Localized Elements

- Page titles and headings
- Navigation buttons and links
- Status messages and alerts
- Form labels and placeholders
- Help text and tooltips
- Error messages
- Countdown displays

---

## 🎨 UI Components

### Sidebar

- **Navigation**: Graph/Memory page links
- **Statistics**: Node/edge counts, system status
- **Language Toggle**: Switch between zh/en
- **Inactivity Countdown**: Real-time session timer
- **Node Details**: Clicked node information
- **Logout**: Session termination button

### Main Content

- **Graph Container**: Interactive visualization area
- **Controls**: Zoom, fit, refresh buttons
- **Status Indicators**: JavaScript library status, graph status

### Node Detail Panel

- **Node ID**: Unique identifier
- **Node Type**: Type classification
- **Node Label**: Display name
- **Properties**: Detailed JSON information
- **Embedding Status**: Vector embedding information

---

## 🐛 Troubleshooting

### Issue: Page Loading Slowly

**Solution**: 
- Check database connection pool settings
- Verify data cache is working
- Check network latency to database

### Issue: Auto-Logout Too Frequent

**Solution**:
- Increase `INACTIVITY_TIMEOUT` in server settings
- Check if user activity events are firing correctly

### Issue: Language Not Switching

**Solution**:
- Clear browser cookies
- Verify session cookie is set correctly
- Check browser console for JavaScript errors

### Issue: Cannot Access Protected Pages

**Solution**:
- Verify user credentials in database
- Check password hash format
- Ensure session cookie is present

---

## 📞 Support

**Author**: Haiwen Yin (胖头鱼 🐟)  
**Email**: yhw1809@csdn.net  
**Blog**: https://blog.csdn.net/yhw1809  
**GitHub**: https://github.com/Haiwen-Yin  
**License**: Apache License 2.0

---

## 📚 Related Documentation

- **SKILL.md**: Main skill documentation
- **README.md**: Project overview and quick start
- **CHANGELOG.md**: Version history
- **RELEASE_NOTES_v1.1.0.md**: Release notes
- **DATABASE_AUTHENTICATION.md**: Authentication setup guide
- **AUTHENTICATION_GUIDE.md**: Security implementation details

---

**End of README_VIZ_SERVER.md**
