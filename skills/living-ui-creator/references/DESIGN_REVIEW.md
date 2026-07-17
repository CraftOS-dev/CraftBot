# Design Quality Reference

Apply this WHILE building each region — design is part of the feature, not
a later phase. There is no separate reviewer: you check your own screens
with the browser tools as you go.

## Foundations (already set up — build on them)

- **shadcn components** from `components/ui/` for every control — Button,
  Card, Dialog, Select, Skeleton, Badge, Tabs, sonner toasts... Never
  hand-roll one that exists.
- **Design tokens, not hex.** Every color/space/radius comes from
  `styles/global.css` (system-managed), and `styles/themes.css` style
  packs restyle the whole app by overriding tokens. Use the token-mapped
  Tailwind classes — `bg-background` / `bg-surface` / `bg-page`,
  `text-foreground` / `text-muted-foreground` / `text-ink-secondary`,
  `border-line` / `border-border`, `bg-primary text-primary-foreground`,
  `text-destructive` — and both themes plus all style packs follow
  automatically. A hardcoded `#333` or `bg-gray-800` breaks them.
- **Dark mode is the DEFAULT**; light is `[data-theme="light"]` on
  `<html>`, applied by the host. You never write theme toggles — you just
  never hardcode colors.
- Tailwind is utilities-only (preflight disabled); style with utility
  classes, not hand-written `<style>` blocks.

## Standards checklist (per region)

- **Hierarchy**: one clear primary element per region; headings sized
  `text-xl/2xl`, metadata muted (`text-muted-foreground text-sm`). Not a
  wall of same-weight text.
- **Spacing rhythm**: consistent gaps from the 4px scale (`gap-2/4/6`,
  `p-4/6`); content in Cards/sections, max-width containers — nothing
  welded into a corner over a void.
- **Empty states communicate**: no data yet → an explicit message + the
  action that creates the first item (icon + "No tasks yet — add one
  above"), never blank space or a bare table header.
- **Loading**: `<Skeleton>` while fetching (`useEntities().loading`), not
  a flash of empty.
- **Feedback**: hover/focus states (shadcn gives them — don't strip
  them), toast or visible change after every action, inline error text on
  failure.
- **Consistency**: same element types look identical everywhere — one
  Button variant vocabulary, one Card pattern, one date format.
- **Responsive**: grids collapse (`grid-cols-1 sm:grid-cols-2
lg:grid-cols-3`), no horizontal overflow, long text truncates or wraps
  deliberately.

## Self-check in the browser (do this after each region)

The app URL hot-reloads on save. Look at your own work:

```
mcp_playwright-mcp_browser_navigate      → the app URL
mcp_playwright-mcp_browser_take_screenshot   (NO filename — image arrives inline)
mcp_playwright-mcp_browser_snapshot          (NO filename — structure/text/refs inline)
```

The screenshot is the pixels — judge it like a design reviewer. The
snapshot is the accessibility tree — good for catching missing labels,
duplicated regions, and unrendered content.

**Defect vs design decision.** Before "fixing" something, ask: is this a
bug, or a choice a competent designer plausibly made? Muted secondary
styling, whitespace, restrained palettes, and empty states in an app with
no data yet are NOT defects. DO fix: text clipped/overlapping; elements
colliding or misaligned; sections rendering raw/unstyled; unreadable
contrast; controls that look dead or misplaced; inconsistent siblings;
unexplained dead space (empty is fine only when it says why); an
unstructured wall of text.

Fix the CSS/layout, let the dev server hot-reload, re-screenshot. Repeat
until the resting page reads as a designed application. Also check
`mcp_playwright-mcp_browser_console_messages` — a styled page that logs
runtime errors is still broken (see VERIFY.md).
