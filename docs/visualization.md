# Web Visualization - AI Agent Infra with DB v4.1.0

> This is a technical document for **Chuanxu (川序)**, the **AI Agent
> Management Platform**. `AI Agent Infra with DB` is the unified technical project
> name; database-specific package names identify the adapter and edition.

## Server

`viz_server_local_js.py` provides a web interface for browsing entities, relationships, agents, task plans, and graph data.

## Pages

| Page | Route | Description |
|------|-------|-------------|
| Knowledge Graph | `/knowledge` | Interactive vis.js graph of KNOWLEDGE entities and edges |
| Memory Content | `/memory` | Interactive vis.js graph of MEMORY entities and edges |
| Agent Collaboration | `/agents` | 3-tab dashboard: Agent Registry, Active Sessions, Collaboration Requests |
| Task Plans | `/tasks` | Status filter, keyword search, accordion plan list with expandable step tables |
| Property Graph | `/graph` | Graph API explorer for entity context, paths, and communities |

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
| `/api/graph/neighbors` | GET | Graph neighbors for entity (param: `entity_id`, `direction`) |
| `/api/graph/path` | GET | Shortest path between entities (params: `source_id`, `target_id`) |
| `/api/graph/context` | GET | Entity context with grouped neighbors (param: `entity_id`) |
| `/api/graph/stats` | GET | Graph statistics (vertex/edge counts, distributions) |
| `/api/graph/search` | GET | Graph-aware search (params: `keyword`, `entity_type`, `category`) |
| `/api/graph/subgraph` | GET | Subgraph extraction (param: `entity_ids`, `include_intermediate`) |
| `/api/graph/communities` | GET | Community detection (params: `entity_type`, `min_connections`) |

## Graph API Endpoints

The `/api/graph/*` endpoints wrap `graph_api.py` functions, providing Property Graph visualization and analysis:

- **Neighbors**: One-hop adjacency with direction filtering and edge type/strength constraints
- **Path**: Shortest path between two entities (up to 6 hops) using GRAPH_TABLE
- **Context**: Full entity view with neighbors grouped by type and edge type
- **Stats**: Graph-wide statistics including vertex/edge counts, type distributions, average degree
- **Search**: Graph-aware entity search with importance filtering
- **Subgraph**: Extract a subgraph by entity ID list, optionally including intermediate nodes
- **Communities**: Find highly-connected entity clusters

## UI Column Updates (v3.4.0)

v3.4.0 renamed several columns visible in the UI:

| v2.0 UI Label | v2.1 UI Label | Field |
|---------------|---------------|-------|
| Name | Title | ENTITIES.TITLE |
| Priority | Importance | ENTITIES.IMPORTANCE (1-10) |
| Tags (JSON) | Tags (table) | TAGS.TAG_NAME via ENTITY_TAGS |
| Metadata | *(removed)* | No longer displayed |
| Accessible To | *(removed)* | Replaced by visibility badge |

New columns displayed:
- **Summary**: Entity summary text
- **Source Agent**: Creating agent ID
- **Retrieval Count**: Access counter
- **Execution Mode**: On harness templates (SEQUENTIAL/PARALLEL/CONDITIONAL)

## Agent Collaboration Page

Three tabbed sections:

- **Agent Registry** — Table with Agent ID, Name, Type, Status (colored badge), Active Sessions count, Last Seen, Created timestamp
- **Active Sessions** — Recent 50 sessions with Session ID (truncated), Agent Name, Active (Y/N badge), Start Time
- **Collaboration Requests** — Recent 50 requests with From/To agent names, Type, Entity ID, Strength, Created timestamp

Status badges: ACTIVE=green, INACTIVE=gray, SUSPENDED=orange, DECOMMISSIONED=red.

## Task Plans Page

- **Top bar**: Status filter dropdown (ALL/PENDING/RUNNING/SUCCESS/FAILED/CANCELLED/BLOCKED), keyword search input, summary stat badges
- **Plan list**: Accordion-style cards showing Plan Name, Status badge, Goal, Priority, Progress, Created, Completed timestamps
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

# Open http://localhost:18090 in browser
# Login: admin / <config.security.admin_password>
```

## Configuration

Via `config.json` or environment variables:
- `MEMORY_SERVER_HOST` (default: 0.0.0.0)
- `MEMORY_SERVER_PORT` (default: 8000)
- `MEMORY_SESSION_TIMEOUT` (default: 300 seconds)
