# Oracle Memory System v2.3.2 Release Notes

**Release Date**: 2026-05-27
**Version**: v2.3.2
**Compatibility**: Backward compatible with v2.3.1 database schema

## Summary

**Web UI Optimization** — Client-side pagination (PAGE_SIZE=30), sticky table headers with shadow, viewport height fixes, table spacing improvements, and login language persistence across all 7 data pages.

## Changes

### Web Visualization Improvements

| Change | Description |
|--------|-------------|
| **Client-side pagination** | PAGE_SIZE=30 with Prev/Next + page number buttons for all data tables. Knowledge, Memory, Tasks, Workspaces, Specs, Collab pages use single pagination; Agents page uses triple pagination (registry/sessions/collabs tabs). |
| **Sticky table headers** | `position:sticky;top:0;z-index:2` with `background` and `box-shadow` for visual separation when scrolling. Applied to all data tables across 7 pages. |
| **Viewport height fix** | `body` changed from `min-height:100vh` to `height:100vh`; `content-area`/`listView` given `min-height:0` and `height:calc(100vh - 120px)` to prevent layout overflow. |
| **Table spacing** | `border-collapse:collapse` → `border-collapse:separate;border-spacing:0` for consistent cell rendering. |
| **Text color** | Table body cells use explicit `color:#fff`; info-card divs use `color:#fff` instead of `var(--text-primary)` for consistent dark-theme rendering. |
| **Login language persistence** | Language preference saved to `localStorage` on toggle; restored on page load with `document.documentElement.lang` set for screen readers. |
| **Graph page** | Language persistence fix applied; no pagination needed (vis-network canvas). |

### Files Changed

- `scripts/visualization/templates/knowledge.html` — pagination, sticky header, viewport fix
- `scripts/visualization/templates/memory.html` — pagination, sticky header, viewport fix
- `scripts/visualization/templates/agents.html` — triple pagination, sticky header, viewport fix
- `scripts/visualization/templates/tasks.html` — pagination, sticky header, viewport fix
- `scripts/visualization/templates/workspaces.html` — pagination, sticky header, viewport fix
- `scripts/visualization/templates/specs.html` — pagination, sticky header, viewport fix
- `scripts/visualization/templates/collab.html` — pagination, sticky header, viewport fix
- `scripts/visualization/templates/graph.html` — language persistence, viewport fix
- `scripts/visualization/templates/login.html` — language persistence

### No Database or API Changes

v2.3.2 is a pure front-end optimization release. No schema changes, no new Python API functions, no new PL/SQL. All 183 tests from v2.3.1 continue to pass.

## Upgrade from v2.3.1

No database migration needed. Simply update the HTML templates and restart the web server:

```bash
./start_web_server.sh restart
```
