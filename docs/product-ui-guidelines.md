# Chuanxu Product UI Guidelines v4.4.10

These reusable rules apply to authenticated Dashboard pages in every edition.

## Heading actions

Page-level controls use the shared `SectionHeading` action area. Refresh stays
on the same row as the database-authorization badge when space permits. Actions
remain in normal document flow and may wrap below the heading on narrow
viewports. Negative margins, overlays, and overlapping controls are prohibited.

## Summary metrics

Summary cards fill the available width according to their actual count. One
card fills the row, three cards form equal thirds, and four cards form equal
quarters. The shared desktop grid uses
`repeat(auto-fit, minmax(240px, 1fr))`; it becomes two columns at 780 pixels or
below and one column at 430 pixels or below. Page-specific fixed columns must
not reserve unused space.

## Hierarchical tabs

Pages with first-level and context-dependent second-level tabs render both
groups in one horizontal navigation row on desktop. The complete first-level
group comes first; child tabs follow after a visible vertical separator and use
smaller, subordinate styling. Child tabs never split or reorder first-level
destinations. Each level uses a separate allowlisted URL parameter so refresh,
history navigation, direct links, and re-login restore the same view.

At narrow widths, each tab group may wrap as a complete group. The two levels
must not interleave, overlap, clip labels, or add a second-level separator to a
page that has only one tab level. Browser checks compare group bounding boxes
and verify URL restoration in both Chinese and English.

## Login and cache behavior

After successful password or MFA login, the client persists session and CSRF
state and reloads the current page shell. The HTML shell and static
control-plane assets use `Cache-Control: no-store` so a platform upgrade cannot
leave an older SPA bundle active.

Authentication errors distinguish credential admission from Session expiry.
A `401` from `/api/auth/login` is shown as invalid credentials or a temporary
account lock; a `401` from an authenticated API is shown as an expired login.
A rejected password must never be described as an expired Session.

## Streaming message updates

A streaming Channel response owns one stable message row. While its message
type remains `AGENT_RESPONSE_STREAMING`, the client reloads a bounded recent
window and merges by message ID; a creation-time cursor alone cannot observe an
in-place body update. The response expands as chunks arrive, respects manual
scroll position, pauses while the page is hidden, and stops refreshing after
the terminal message type.

## Platform command presentation

The command catalog uses the available drawer height and presents each command
as one scan-friendly item containing name, localized summary, syntax, risk,
execution mode, and executor state. Command help and result messages preserve
the same hierarchy. A proposal must visibly distinguish Action Card creation
from approved execution.

## Compliance posture presentation

Compliance aggregate cards must have a business title and show the underlying
posture/control pair as secondary state labels. Each card separately explains
the evidence assessment, visible Agent count, and platform enforcement. Known
combinations use stable titles such as healthy compliant, awaiting assessment,
and quarantined non-compliant Agents. Mobile layouts stack these dimensions;
labels and explanatory text must not overlap or be truncated.

## Model routing presentation

Model routing belongs on the corresponding LLM Provider Profile row. Direct
and platform-gateway choices use compact independent checkboxes because both
may be enabled. The confirmation action stays on the same row, is gray and
disabled when unchanged, and becomes highlighted when a draft differs. Saving
requires a compliance reason. The platform-generated forwarding address is
read-only and must remain legible without expanding the table unpredictably.

## Executive wallboard presentation

The wallboard is an operational overview, not a Token table. It combines stable
runtime metrics with separate 14-day Token and cost curves, bounded usage
detail, coverage, and freshness. It contains no mutation controls. Loading,
empty, stale, error, and current states keep the same layout dimensions so
refresh cannot shift or overlap surrounding content.

## Verification and published screenshots

Release verification covers Chinese and English, light and dark, desktop and
mobile layouts. Screenshots and bounding-box assertions verify headings,
actions, and metric cards. Website and presentation screenshots are captured
from the final package of the current release after loading completes; old
versions, loading placeholders, errors, and overlaps are rejected.

## Governed record details

Normal detail drawers use up to 640 CSS pixels. Dense governed details such as
Knowledge visibility and Branch relationships use the 960-pixel wide treatment
on desktop. At 780 pixels or below, drawers use the available viewport width,
multi-field rows collapse to one column, and content scrolls vertically.
Inputs, selects, textareas, buttons, panels, and structured output must remain
inside the drawer; hiding horizontal overflow is not sufficient evidence.
Browser gates assert both drawer `scrollWidth` and every control bounding box.
