# UI Rules

The UI layer is **100% standard shadcn/ui**, installed from shadcn's
registry by shadcn's own installer at project setup (46 components in
`frontend/components/ui/` — plain readable source) + Tailwind +
lucide-react icons + `sonner` toasts. Write ordinary shadcn code; import
per file: `import { Button } from '@/components/ui/button'`.

Installed: accordion, alert, alert-dialog, aspect-ratio, avatar, badge,
breadcrumb, button, calendar, card, carousel, chart, checkbox,
collapsible, command, context-menu, date-picker, dialog, drawer,
dropdown-menu, form, hover-card, input, input-otp, label, menubar,
navigation-menu, pagination, popover, progress, radio-group, resizable,
scroll-area, select, separator, sheet, skeleton, slider, sonner, switch,
table, tabs, textarea, toggle, toggle-group, tooltip.

**Excluded on purpose**: `sidebar` (build page structure with plain
Tailwind), `toast` (toasts are `sonner`). Anything else genuinely
missing: `npx shadcn@latest add <name> --yes` from the project root
(components.json is configured) — never hand-write a fake component,
never overwrite existing files.

**Packages that DO NOT EXIST** (never import): `@livingui/*`,
`@/lib/api`, `'./ui'`, `@/components/platform`. The ONLY data client is
the generated `api.gen` (plus `services/data`); the ONLY UI source is
`@/components/ui/<name>`.

## Styling rules

- Tailwind utilities with the **semantic colors** — they follow the
  user's live theme and style pack: `bg-background bg-card bg-muted
text-foreground text-muted-foreground border-border bg-primary
text-primary-foreground bg-destructive` (+ `success`, `warning`,
  `info`). NEVER pick arbitrary hex colors.
- Opacity suffixes do NOT work on the semantic colors (they are CSS
  variables): use the provided shades (`bg-primary-hover`,
  `bg-muted-subtle`) or a palette color (`bg-indigo-500/20`).
- `rounded-sm/md/lg/xl` are token-driven (style packs reshape them).
- Page structure is plain Tailwind: a padded `<main>`, an `mx-auto
max-w-6xl` container, one `<section>` per region with a heading and a
  `flex flex-col gap-*` body. Nothing may overflow horizontally
  (`min-w-0`, `truncate`, `overflow-x-auto` on wide tables).
- Wireframes (Phase 1.5) use shadcn `<Skeleton>` sized with Tailwind —
  no DIY shimmer divs, no `<style>` blocks, no px page widths.
- No hand-rolled `<style>` blocks where utilities suffice.

## Forms, tables, data

- Forms: react-hook-form + zod + `@/components/ui/form`, typed against
  the generated entity types (`import type { Card } from '../types.gen'`).
- Tables: `@/components/ui/table` composition; wide tables scroll inside
  `overflow-x-auto`.
- Dates: `<DatePicker date={d} onSelect={setD} />` (also accepts
  `value`/`onChange`) or a native `<Input type="date">`; the backend
  wire format is ISO-8601 strings.
- Confirmation: `<AlertDialog>` — NEVER browser `confirm()`/`alert()`/
  `prompt()`.
- Data access: `import { api, useEntities } from '../api.gen'`;
  `useEntities(name)` → `{items, loading, error, refresh, create, update,
remove}` (react-query aliases `data`/`isLoading`/`refetch` also work);
  typed client `api.<name>.getFullList/getList/getOne/create/update/
delete`. Never hand-write fetch calls for entities; `ApiService.request`
  is ONLY for `/api/custom/*` pb_hooks endpoints. File fields: pass a
  `File` in `create`/`update`; URLs via `pb.files.getURL(record, name)`.

## Toasts

`import { toast } from 'sonner'` → `toast.success/error/warning/info`.
The `<Toaster />` is mounted in App.tsx — never mount another.

## Accent Discipline

The accent (`bg-primary`) is reserved for: ONE `variant="default"` Button
per view, the active Tab/nav state, and focus rings. Everything else is
neutral (`outline`/`secondary`/`ghost`) + semantic colors. On dashboards,
give each stat tile/chart a different semantic color.

## Style Packs (multi-theme)

Four design languages as token overrides in `frontend/styles/themes.css`
(system-managed — never edit): default (dark charcoal, orange accent),
modern (airy indigo), glass (aurora glassmorphism), classic (flat warm
amber). Each has its own palette and follows light/dark — colors come
from the semantic classes. **The HOST owns theming** — NEVER render a
theme picker or dark-mode toggle inside the app (an app may declare its
intended look ONCE via `setDefaultStyle('glass')` from '@/lib/theme' at
the top of App.tsx; the user's choice always wins).
