# Web Visualization - Oracle Memory System v2.0.0

## Server

`viz_server_local_js.py` provides a web interface for browsing entities, relationships, agents, and task plans.

## Pages

| Page | Route | Description |
|------|-------|-------------|
| Knowledge Graph | `/knowledge` | Interactive vis.js graph of KNOWLEDGE entities and edges |
| Memory Content | `/memory` | Interactive vis.js graph of MEMORY entities and edges |
| Agent Collaboration | `/agents` | 3-tab dashboard: Agent Registry, Active Sessions, Collaboration Requests |
| Task Plans | `/tasks` | Status filter, keyword search, accordion plan list with expandable step tables |

All pages share: bilingual UI (zh/en), session auth with auto-logout timer, `/api/stats` sidebar.

## API Routes

| Route | Method | Description |
|-------|--------|-------------|
| `/api/health` | GET | Health check (no auth required) |
| `/api/knowledge` | GET | Knowledge graph JSON (nodes + edges) |
| `/api/knowledge/refresh` | GET | Force refresh knowledge cache |
| `/api/memory` | GET | Memory graph JSON (nodes + edges) |
| `/api/memory/refresh` | GET | Force refresh memory cache |
| `/api/agents` | GET | Agent registry, sessions, collaborations JSON |
| `/api/tasks` | GET | Task plans + steps JSON (query params: `status`, `keyword`) |
| `/api/stats` | GET | Entity counts by type + edge count |
| `/api/login` | POST | Authenticate (form: username + password) |
| `/api/logout` | GET | Clear session cookie, redirect to login |

## Agent Collaboration Page

Three tabbed sections:

- **Agent Registry** — Table with Agent ID, Name, Type, Status (colored badge), Permission Level (badge), Active Sessions count, Access Count, Created timestamp
- **Active Sessions** — Recent 50 sessions with Session ID (truncated), Agent Name, Active (Y/N badge), Start Time, Last Activity
- **Collaboration Requests** — Recent 50 requests with From/To agent names, Reason, Status (PENDING/ACCEPTED/REJECTED/EXPIRED badges), Created timestamp

Status badges: ACTIVE=green, DISABLED=red, SUSPENDED=orange. Permission badges: READ_ONLY=blue, READ_WRITE=green, ADMIN=purple.

## Task Plans Page

- **Top bar**: Status filter dropdown (ALL/PENDING/RUNNING/SUCCESS/FAILED/CANCELLED/BLOCKED), keyword search input, summary stat badges
- **Plan list**: Accordion-style cards showing Plan Name, Status badge, Type, Priority, Progress bar (done_steps/total_steps), Created, Completed timestamps
- **Step details**: Click a plan to expand its step table — Order, Step Name, Action, Status badge, Started, Completed, Error message

## UTF-8 Encoding Fix

oracledb thin mode returns Chinese characters from AL32UTF8 databases with double-encoding (UTF-8 bytes interpreted as Latin-1 code points). The `_fix_encoding()` function auto-detects this:

1. If string contains CJK characters (`ord >= 0x4E00`) → already correct, skip
2. If string contains Latin-1 range chars (`0x80-0xFF`) but no CJK → apply `bytes([ord(c)]).decode('utf-8')` fix
3. Fallback: `encode('latin-1', errors='replace').decode('utf-8', errors='replace')`

Applied in `_q()`, `load_entity_data()`, `load_db_stats()`.

## Quick Start

```bash
# Control script (recommended)
./start_web_server.sh start    # Start (daemon mode)
./start_web_server.sh status    # Show status + config
./start_web_server.sh stop      # Stop server
./start_web_server.sh restart   # Restart server
./start_web_server.sh config    # Show full configuration
./start_web_server.sh log       # View last 50 log lines

# Or run directly
python3.14 viz_server_local_js.py

# Open http://localhost:8000 in browser
# Login: admin / admin123
```

## Configuration

Via `config.json` or environment variables:
- `MEMORY_SERVER_HOST` (default: 0.0.0.0)
- `MEMORY_SERVER_PORT` (default: 8000)
- `MEMORY_SESSION_TIMEOUT` (default: 300 seconds)
