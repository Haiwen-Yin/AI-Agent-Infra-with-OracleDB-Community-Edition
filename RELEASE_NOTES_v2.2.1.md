# Oracle Memory System v2.2.1 Release Notes

**Release Date**: 2026-05-23  
**Author**: Haiwen Yin  
**License**: Apache License 2.0

---

## Overview

v2.2.1 is a **visualization-only update** with no schema or API changes. It replaces the monolithic single-file visualization (`viz_server_local_js.py`, 963 lines) with a template-based architecture (`scripts/visualization/server.py`, 519 lines + 7 HTML templates + static assets), delivering a modern dark-themed UI with sidebar navigation, bilingual persistence, and richer page layouts.

**Fully compatible with v2.2.0 database** — no migration needed.

---

## What Changed

### Architecture: Template-Based Visualization

| Before (v2.2.0) | After (v2.2.1) |
|-----------------|----------------|
| `viz_server_local_js.py` (963 lines, single file) | `scripts/visualization/server.py` (519 lines) + templates + static |
| Inline JS/CSS embedded in Python strings | Separate HTML templates + `style.css` + `vis-network.min.js` |
| Top button navigation bar | Left fixed sidebar with icons, language toggle, auto-logout timer |
| Simple table views for all pages | Rich layouts: tabs, accordions, expandable details, dual views |
| Language resets on page navigation | Language persisted in `localStorage` across pages |
| No auto-logout countdown | 5-min countdown with 60s color warning, 30s title flash |

### New File Structure

```
scripts/visualization/
  server.py                 # HTTP server (BaseHTTPRequestHandler, oracledb, session auth)
  templates/
    login.html              # Card-style login with gradient background
    knowledge.html          # List/Graph dual view, detail panel, domain coloring
    memory.html             # List/Graph dual view, category filter
    agents.html             # Bootstrap tabs: Registry / Sessions / Collaborations
    tasks.html              # Accordion with step details, tool input/output
    workspaces.html         # Expandable rows: context timeline + linked tasks
    graph.html              # Stats cards, search, vis-network graph, detail panel
  static/
    style.css               # Dark theme CSS variables, sidebar styles
    vis-network.min.js      # Vis.js network library
```

### UI Features

| Feature | Description |
|---------|-------------|
| Sidebar Navigation | Fixed 220px sidebar with 6 page links, Oracle Memory branding, language toggle |
| Login Page | Card-style form with gradient background, error feedback |
| Knowledge/Memory | List + Graph toggle with domain/category color grouping, detail panel |
| Agents | 3 Bootstrap tabs: Registry (status badges, cap tags), Sessions, Collaborations |
| Tasks | Accordion panels with step-by-step detail, status badges (PENDING/RUNNING/SUCCESS/FAILED) |
| Workspaces | Click-to-expand rows: context timeline + linked tasks table |
| Graph Explorer | Vertex/Edge/Degree stats cards, search+type filter, vis-network, node detail |
| Bilingual | `data-zh`/`data-en` attribute toggle, persisted in `localStorage` |
| Auto-Logout | 5-min countdown in sidebar, warning color at 60s, title flash at 30s |

### API Enhancements

- `/api/workspaces` now returns `context_chain`, `linked_tasks`, `task_count` per workspace
- `Decimal` sanitization in `_clean_row()` for oracledb thin mode compatibility

### Data Seeding

- 21 task steps seeded across 6 plans with mixed statuses (SUCCESS 14, RUNNING 4, FAILED 1, PENDING 2)

---

## Compatibility

| Aspect | v2.2.0 → v2.2.1 |
|--------|-----------------|
| Database schema | **No changes** — same 22 tables, 4 JRD views |
| PL/SQL packages | **No changes** — same 5 packages |
| Python API layer | **No changes** — same 10 modules, 80+ functions |
| Scheduler jobs | **No changes** — same 9 jobs |
| Test suite | **No changes** — 61/61 tests pass |
| Visualization | **Replaced** — template-based architecture |

---

## Upgrade from v2.2.0

No migration needed. Simply replace the visualization files:

1. Stop the web server: `./start_web_server.sh stop`
2. Remove old file: `rm viz_server_local_js.py vis-network.min.js`
3. Copy new `scripts/visualization/` directory
4. Update `start_web_server.sh` (points to `scripts/visualization/server.py`)
5. Start: `./start_web_server.sh start`

---

## Test Results

```
Oracle Memory System v2.2.1 - Full Test Suite

Connection: PASS (6 tests)
Memory:     PASS (8 tests)
Knowledge:  PASS (8 tests)
Agent:      PASS (8 tests)
Security:   PASS (5 tests)
Harness:    PASS (6 tests)
Graph:      PASS (8 tests)
Workspace:  PASS (12 tests)

Overall: ALL PASSED (61/61)
```

---

## Known Issues

- oracledb thin mode returns `decimal.Decimal` for NUMBER columns in JSON — handled by `_clean_row()` sanitization
- `JSON_MERGEPATCH` produces OSON v2 unsupported by oracledb thin — use `JSON_TRANSFORM` instead
- SYSTEM_USERS authentication uses SHA256 placeholder hash — production deployments should use proper password hashing

---

## Credits

- Vis.js Network: [vis-network.js](https://github.com/visjs/vis-network)
- Bootstrap 5.3.3: [getbootstrap.com](https://getbootstrap.com/)
