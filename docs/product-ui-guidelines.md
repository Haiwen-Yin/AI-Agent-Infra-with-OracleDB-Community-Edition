# Chuanxu Product UI Guidelines v4.4.9

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

## Verification and published screenshots

Release verification covers Chinese and English, light and dark, desktop and
mobile layouts. Screenshots and bounding-box assertions verify headings,
actions, and metric cards. Website and presentation screenshots are captured
from the final package of the current release after loading completes; old
versions, loading placeholders, errors, and overlaps are rejected.
