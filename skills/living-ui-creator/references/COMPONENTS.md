# UI Component Reference

**Use these preset components by default** instead of custom styles.

```typescript
import { Button, Input, Textarea, Select, Checkbox, Toggle, Card, Container, Divider,
         Alert, Badge, EmptyState, Table, List, ListItem, Modal, Tabs, TabList, Tab, TabPanel } from './components/ui'
```

---

## Exact Props Cheat-Sheet (check BEFORE writing any component)

**EXACT prop names (do NOT guess — wrong props fail the TS build at validation):**

| Component | Props |
|---|---|
| `Button` | `variant`('primary'\|'secondary'\|'danger'\|'ghost' — DEFAULT is 'secondary'; use 'primary' for THE one main action per view), `size`, `loading`, `fullWidth`, `icon`, `disabled`, `onClick` |
| `Input` | `label?`, `error?`, `hint?` + native input props (`value`, `onChange`, `placeholder`, ...) |
| `Select` | `label?`, `error?`, `hint?`, `options: {value,label}[]`, `placeholder?` |
| `Toggle` | `checked`, `onChange:(checked)=>void`, `label?`, `disabled?` |
| `Card` | `children`, `padding?`('none'\|'sm'\|'md'\|'lg') — NO `title` prop; put headings in children |
| `Alert` | `variant`, `title?`, `children`, `onClose?` |
| `Badge` | `children`, `variant?`, `size?`, `dot?` |
| `Modal` | `open` (NOT `isOpen`), `onClose`, `title?`, `children`, `footer?`, `size?` |
| `Table` | `columns: TableColumn[]`, `data`, `emptyMessage?`, `onRowClick?`, `rowKey?` |
| `EmptyState` | `icon?`, `title?`, `message` (NOT `description`), `action?` (one ReactNode) |
| `Tabs` | `children`, `defaultTab?`, `onChange?` |
| `AppShell` | `sidebar?`, `children`, `maxWidth?` — NO header prop |
| `Section` | `title?`, `meta?`, `actions?`, `children` |
| `CardGrid` | `children`, `minWidth?` |
| `SkeletonBox` | `count?`, `ratio?` (width/height proportion, e.g. 3 = strip, 1 = square) — the generic wireframe rectangle, adaptive width |
| `SkeletonCircle` | `count?`, `size?`('sm'\|'md'\|'lg') — avatar/icon spots |
| `SkeletonText` | `lines?` — paragraph placeholder (staggered widths) |
| `SkeletonChip` | `count?` — filter/tag pill row |
| `SkeletonCard` | `count?`, `lines?`, `media?` — content card placeholder (NO px sizing; media is aspect-ratio) |
| `SkeletonRow` | `count?` — list/table row placeholders |
| `SkeletonStack` | `children` — stacks mixed skeleton shapes with consistent spacing |
| `Collapsible` | `title`, `children`, `defaultOpen?` — expandable group (settings sections, FAQ) |
| `Toolbar` | `children`, `end?` (right-aligned group) — one row of controls |
| `IconBadge` | `icon` (lucide element), `color?`, `size?` — colored icon holder |
| `StatCard` | `icon?`, `value`, `label`, `color?` — icon + big number + label |
| `SplitView` | `children` (main), `aside`, `asideWidth?` — main + side column |
| `EntityForm` | `entity` (schema name e.g. "Card"), `initial?` (edit mode), `defaults?`, `exclude?`, `onSaved?`, `onCancel?` — WHOLE create/edit form generated from the schema (right input per type, required validation, ref dropdowns) |
| `EntityTable` | `entity`, `filters?`, `columns?`, `onRowClick?`, `actions?`, `allowDelete?`, `searchable?` (adds a ?q= search box), `pageSize?` (server-side paging) — sortable data table bound to the generated API, delete confirmation included |
| `ConfirmDialog` / `useConfirm()` | `const [el, confirm] = useConfirm()`; `if (await confirm('Delete?'))` … render `{el}` — NEVER browser confirm() |
| `NumberInput` | `value: number\|null`, `onValue`, `label?` |
| `DateInput` | `value: string\|null` (ISO), `onValue`, `label?`, `dateOnly?` — for datetime fields |
| `SearchInput` | `onSearch(query)` (debounced), `placeholder?` — pair with the list endpoint's `q` param |
| `TagInput` | `value: string[]`, `onChange`, `label?` — for json array fields |
| `SortableList` | `items`, `renderItem`, `onReorder(newItems)` + `reorderAndSave(plural, items)` persists `position` |
| `useHotkey` / `useDebounce` | `useHotkey('ctrl+k', fn)` global shortcut; `useDebounce(value, ms)` |
| `toast` | `toast.success('Saved')` / `.error(msg)` / `.info(msg)` — action feedback; AppShell hosts it (else render `<ToastHost/>` once). ALWAYS confirm mutations with a toast |
| `DropdownMenu` | `trigger` (element), `items: {label, icon?, danger?, disabled?, onSelect}[]`, `align?` — the row-actions "..." menu |
| `Drawer` | `open`, `onClose`, `title?`, `children`, `footer?`, `side?`, `width?` — slide-over panel for detail/edit views |
| `Tooltip` | `content`, `children`, `side?` — explain icon-only controls |
| `SegmentedControl` | `options: {value,label}[]`, `value`, `onChange`, `size?` — THE filter control for enum fields |
| `Pagination` | `page` (0-based), `onPage`, `hasNext`, `total?`, `pageSize?` — or just set `pageSize` on EntityTable |
| `Sparkline` / `MiniBarChart` | `values: number[]` / `data: {label, value, color?}[]` — dependency-free charts for `/_stats` results |
| `ProgressBar` | `value`, `max?`, `color?`, `height?` |
| `Spinner` / `Kbd` / `Avatar` | `Spinner` `size?`, `color?`; `Kbd` shortcut hint (pairs with useHotkey); `Avatar` `name`, `src?`, `size?` |
| `FileUpload` | `onUploaded(file)`, `accept?`, `label?` — drop zone + browse, uploads via the system file API; store `file.url` (string) in a schema field |
| `ImageInput` | `value: string\|null` (stored file url), `onValue`, `label?` — image field with upload + preview; render elsewhere with `fileUrl(url)` from services/data |

---

## Layout Kit (the page comes from HERE — never hand-roll page scaffolding)

`AppShell`, `Section`, `CardGrid` and the Skeleton shape set
(`SkeletonBox`, `SkeletonCircle`, `SkeletonText`, `SkeletonChip`,
`SkeletonCard`, `SkeletonRow`, `SkeletonStack`)
own page structure: gutters, max-width, viewport height, section spacing,
overflow discipline, responsive collapse, and shimmer placeholders. All
skeletons are ADAPTIVE — they size from their container (aspect ratios and
em units, never px props), cannot overflow, and space themselves; the
wireframe phase uses ONLY them (hand-made shimmer divs / inline styles /
px sizes in MainView are flagged at write time). Build
every page as a kit assembly; your own `<style>` blocks cover only what is
INTERNAL to a component.

```tsx
import { AppShell, Section, CardGrid, SkeletonCard, EmptyState, Button } from './components/ui'

<AppShell>
  <Section title="Categories">…category tabs…</Section>
  <Section title="Articles" meta="124 articles">
    <CardGrid>
      {loading ? <SkeletonCard count={6} /> :
       articles.length === 0 ? <EmptyState title="No articles yet" message="Refresh to load the latest news." /> :
       articles.map(a => <ArticleCard key={a.id} article={a} />)}
    </CardGrid>
  </Section>
</AppShell>
```

- `AppShell` props: `sidebar?` (240px sticky column), `children`, `maxWidth?` — NO page header: pages start with their content Sections
- `Section` props: `title?`, `meta?` (counts/hints), `actions?`, `children`
- `CardGrid` props: `minWidth?` (px, default 260) — responsive auto-fill grid
- `SkeletonCard` props: `count?`, `height?` | `SkeletonRow` props: `count?` — wireframe placeholders (Phase 1.5) and loading states
- `Toolbar` props: `children`, `end?` — one horizontal row of controls (filters + a right-aligned action)
- `IconBadge` props: `icon` (lucide element), `color?`, `size?` — colored icon holder; the cheapest way to stop a UI being all text
- `StatCard` props: `icon?`, `value`, `label`, `color?` — icon + big number + label, for dashboard strips (`<CardGrid minWidth={200}>` of StatCards)
- `SplitView` props: `children` (main), `aside`, `asideWidth?` — main content + side column, collapses on mobile

---

## Forms

### Button
`variant`: `'primary'` | `'secondary'` | `'danger'` | `'ghost'` (default: `'primary'`)
`size`: `'sm'` | `'md'` | `'lg'` (default: `'md'`)
`loading`, `fullWidth`, `disabled`: boolean | `icon`: ReactNode | `iconPosition`: `'left'` | `'right'`

```tsx
<Button variant="primary">Save</Button>
<Button variant="danger">Delete</Button>
<Button variant="ghost" size="sm">Cancel</Button>
<Button loading>Saving...</Button>
```

### Input
`label`, `error`, `hint`, `placeholder`: string | `type`: `'text'` | `'email'` | `'password'` | `'number'`

```tsx
<Input label="Email" type="email" placeholder="you@example.com" />
<Input label="Username" error="Required" />
```

### Textarea
`label`, `error`, `hint`: string | `rows`: number (default: 4)

```tsx
<Textarea label="Description" rows={6} />
```

### Select
`label`, `error`, `hint`, `placeholder`: string | `options`: `{ value: string, label: string, disabled?: boolean }[]` (required)

```tsx
<Select label="Country" options={[{ value: 'us', label: 'US' }, { value: 'uk', label: 'UK' }]} />
```

### Checkbox
`label`: string | `checked`, `disabled`: boolean

```tsx
<Checkbox label="I agree to the terms" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} />
```

### Toggle
`checked`: boolean (required) | `onChange`: `(checked: boolean) => void` (required) | `label`: string | `disabled`: boolean

```tsx
<Toggle checked={enabled} onChange={setEnabled} label="Dark Mode" />
```

---

## Layout

### Card
`padding`: `'none'` | `'sm'` | `'md'` | `'lg'` (default: `'md'`)

```tsx
<Card><h3>Title</h3><p>Content</p></Card>
<Card padding="lg"><form>...</form></Card>
```

### Container
`maxWidth`: `'sm'` (640px) | `'md'` (768px) | `'lg'` (1024px) | `'xl'` (1280px) | `'full'` (default: `'lg'`)
`padding`: boolean (default: true)

```tsx
<Container maxWidth="sm"><form>Narrow form</form></Container>
```

### Divider
`orientation`: `'horizontal'` | `'vertical'` (default: `'horizontal'`) | `spacing`: `'sm'` | `'md'` | `'lg'`

```tsx
<Divider />
<Divider orientation="vertical" />
```

---

## Feedback

### Alert
`variant`: `'info'` | `'success'` | `'warning'` | `'error'` (required) | `title`: string | `onClose`: `() => void`

```tsx
<Alert variant="success" title="Saved!">Changes saved.</Alert>
<Alert variant="error">Something went wrong.</Alert>
```

### Badge
`variant`: `'default'` | `'primary'` | `'success'` | `'warning'` | `'error'` | `'info'` | `size`: `'sm'` | `'md'` | `dot`: boolean

```tsx
<Badge variant="success">Active</Badge>
<Badge variant="error" dot>Offline</Badge>
```

### EmptyState
`message`: string (required) | `title`: string | `icon`: ReactNode | `action`: ReactNode

```tsx
<EmptyState title="No tasks" message="Create your first task" action={<Button>Create</Button>} />
```

---

## Data

### Table
`columns`: `TableColumn[]` (required) | `data`: `T[]` (required) | `emptyMessage`: string | `onRowClick`: `(item, index) => void` | `rowKey`: `(item, index) => string | number`

```typescript
interface TableColumn<T> {
  key: string; header: string; render?: (item: T, index: number) => ReactNode; width?: string; align?: 'left' | 'center' | 'right'
}
```

```tsx
<Table
  columns={[
    { key: 'name', header: 'Name' },
    { key: 'status', header: 'Status', render: (item) => <Badge variant={item.active ? 'success' : 'default'}>{item.status}</Badge> }
  ]}
  data={users}
/>
```

### List & ListItem
**List**: `dividers`: boolean (default: true)
**ListItem**: `onClick`: `() => void` | `active`: boolean

```tsx
<List>
  {items.map(item => <ListItem key={item.id} onClick={() => select(item)} active={selected === item.id}>{item.name}</ListItem>)}
</List>
```

---

## Overlays

### Modal
`open`: boolean (required) | `onClose`: `() => void` (required) | `title`: string | `footer`: ReactNode | `size`: `'sm'` (320px) | `'md'` (420px) | `'lg'` (560px)

```tsx
<Modal open={show} onClose={() => setShow(false)} title="Confirm" footer={<><Button variant="ghost" onClick={() => setShow(false)}>Cancel</Button><Button variant="danger">Delete</Button></>}>
  Are you sure?
</Modal>
```

### Tabs
**Tabs**: `defaultTab`: string | `onChange`: `(tabId: string) => void`
**Tab**: `id`: string (required)
**TabPanel**: `id`: string (required, matches Tab id)

```tsx
<Tabs defaultTab="details">
  <TabList>
    <Tab id="details">Details</Tab>
    <Tab id="settings">Settings</Tab>
  </TabList>
  <TabPanel id="details">Details content</TabPanel>
  <TabPanel id="settings">Settings content</TabPanel>
</Tabs>
```

---

## Styling with Tailwind Token Classes

**Styling inside components: token-mapped Tailwind utilities FIRST.**
Tailwind is integrated utilities-only (no preflight — it never fights the
kit). Colors map to the design tokens, so these classes follow the active
theme automatically:

| Class family | Maps to |
|---|---|
| `bg-page` / `bg-surface` / `bg-raised` | `--bg-primary/secondary/tertiary` |
| `text-ink` / `text-ink-secondary` / `text-ink-muted` | `--text-*` tokens |
| `border-line` | `--border-primary` |
| `bg-primary`, `text-primary`, `bg-primary-light`, ... | `--color-primary*` |
| `bg-success/warning/error/info` (+`-light`) | status tokens |
| `rounded-token` | `--radius-md` |

Plus the full standard utility set (flex, grid, gap-*, p-*, m-*, w-*,
truncate, ...). Use a scoped `<style>` block ONLY for what utilities can't
express (keyframes, complex selectors).

## Design Tokens

| Category | Tokens |
|----------|--------|
| **Colors** | `--color-primary` (#FF4F18), `--color-success` (#22C55E), `--color-warning` (#EAB308), `--color-error` (#EF4444), `--color-info` (#3B82F6) |
| **Backgrounds** | `--bg-primary`, `--bg-secondary`, `--bg-tertiary` |
| **Text** | `--text-primary`, `--text-secondary`, `--text-muted` |
| **Spacing** | `--space-1` to `--space-12` (4px to 48px) |
| **Radius** | `--radius-sm` (4px), `--radius-md` (6px), `--radius-lg` (8px), `--radius-full` (9999px) |

---

## Accessibility

- Always provide `label` for form inputs
- Use `aria-label` for icon-only buttons
- Keyboard: Tab, Enter, Space, Escape supported

---

## Icons (lucide-react)

Use `lucide-react` for icons — it's pre-installed. Tree-shakeable, only imports what you use.

```tsx
import { Search, Plus, Trash2, Edit, Settings, ChevronRight } from 'lucide-react'

<Search size={16} />
<Button icon={<Plus size={14} />}>Add Item</Button>
```

Browse icons at https://lucide.dev/icons. NEVER use emoji for UI icons — use lucide-react instead.

---

## Toast Notifications

Use THE preset toast from './components/ui' (AppShell hosts it — no
container to add; render `<ToastHost/>` once only on pages without
AppShell). Do NOT install or import react-toastify.

```tsx
import { toast } from './components/ui'

toast.success('Card created')
toast.error('Failed to save changes')
toast.info('Export started')
```

**Use toasts for:** CRUD feedback, API errors, important state changes.
**Don't use toasts for:** Validation errors (show inline), loading states (use spinners/skeletons).

## Schema-Aware Presets (use these FIRST)

Generated from `config/schema.json` metadata — one line replaces a whole
hand-rolled component:

```tsx
import { EntityForm, EntityTable, useConfirm, SortableList, reorderAndSave,
         SearchInput, DateInput, NumberInput, TagInput,
         useHotkey, useDebounce } from './components/ui'
```

**EntityForm** — the create/edit form for any entity. Field types map to
the right inputs automatically (enum→Select, boolean→Toggle,
datetime→DateInput, json→TagInput, ref→dropdown of the parent entity,
loaded live). Required fields validate; server errors (409 unique, 422)
display inline.

```tsx
<Modal open={adding} onClose={close} title="New card">
  <EntityForm entity="Card" defaults={{ columnId: col.id }}
              onSaved={() => { close(); cards.refresh() }} onCancel={close} />
</Modal>
<EntityForm entity="Card" initial={card} onSaved={onSaved} />  // edit mode
```

**EntityTable** — sortable table over the generated API with row actions
and confirmed deletes:

```tsx
<EntityTable<Card> entity="Card" filters={{ columnId: col.id }}
  columns={['title', 'dueDate', 'status']} onRowClick={open} allowDelete />
```

**useConfirm** — NEVER browser confirm():

```tsx
const [confirmEl, confirm] = useConfirm()
// in a handler:  if (await confirm('Delete this card?')) await cards.remove(id)
// in the JSX:    {confirmEl}
```

**SortableList + reorderAndSave** — drag-to-reorder persisting `position`:

```tsx
<SortableList items={cards.items} renderItem={c => <CardFace card={c} />}
  onReorder={async next => { await reorderAndSave('cards', next); await cards.refresh() }} />
```

**Form inputs** — `NumberInput` (number|null), `DateInput` (ISO string —
datetime fields), `TagInput` (string[] — json array fields), `SearchInput`
(debounced; pair with the list endpoint's `?q=` search:
`useEntities<Card>('cards', { q: query })`).

**Hooks** — `useHotkey('ctrl+k', openSearch)` (global shortcut, ignores
typing for plain keys), `useDebounce(value, ms)`.

## Feedback, Overlays, and Dashboard Presets

```tsx
import { toast, DropdownMenu, Drawer, Tooltip, SegmentedControl,
         Pagination, Sparkline, MiniBarChart, ProgressBar, Spinner,
         Kbd, Avatar } from './components/ui'
```

**toast** — confirm every mutation. No wiring needed when the page uses
`AppShell` (it hosts the toasts); otherwise render `<ToastHost />` once.

```tsx
await cards.create(values); toast.success('Card created')
try { await runExport() } catch (e) { toast.error(String(e)) }
```

**DropdownMenu** — the "…" row-actions pattern:

```tsx
<DropdownMenu
  trigger={<Button size="sm" variant="ghost" icon={<MoreHorizontal size={14} />} />}
  items={[
    { label: 'Edit', icon: <Pencil size={14} />, onSelect: () => setEditing(card) },
    { label: 'Delete', danger: true, onSelect: () => removeCard(card) },
  ]}
/>
```

**Drawer** — slide-over detail/edit panel (larger than Modal, keeps the
page visible): `open`, `onClose`, `title?`, `footer?`, `side?`, `width?`.
Pairs perfectly with `<EntityForm initial={selected}>` for edit flows.

**SegmentedControl** — exclusive filter, ideal for enum fields:

```tsx
<SegmentedControl value={status} onChange={setStatus}
  options={[{ value: 'all', label: 'All' }, { value: 'todo', label: 'To do' },
            { value: 'done', label: 'Done' }]} />
```

**Charts** — visualize `/_stats` without a chart library:

```tsx
const stats = await ApiService.request('GET', '/cards/_stats?groupBy=status')
<MiniBarChart data={stats.map(s => ({ label: s.group, value: s.value }))} />
<Sparkline values={weeklyCounts} color="var(--color-success)" />
```

**Pagination** — usually implicit: `<EntityTable pageSize={25} />` pages
server-side. Standalone: `page` (0-based), `onPage`, `hasNext`
(`items.length === pageSize`), `total?`, `pageSize?`.

**Tooltip / Spinner / ProgressBar / Kbd / Avatar** — `Tooltip` explains
icon-only buttons; `Spinner` (`size`, `color`) for inline loading
(skeletons for whole regions); `ProgressBar` (`value`, `max`) for
determinate progress; `<Kbd>Ctrl+K</Kbd>` renders shortcut hints;
`Avatar` (`name`, `src?`) shows initials with a deterministic color.

## Accent Discipline

The orange accent is reserved for: ONE primary Button per view, the active
Tab/ListItem/SegmentedControl state, and focus rings. Everything else is
neutral surfaces + semantic colors. `Button` defaults to `secondary` and
`IconBadge` to neutral gray on purpose — opt INTO the accent deliberately,
never blanket-apply it. On dashboards, give each StatCard/chart a different
semantic color (`--color-info`, `--color-success`, `--color-warning`,
`--color-error`).

## Style Packs (multi-theme)

Beyond light/dark mode, the app has four DESIGN LANGUAGES defined as token
overrides in `frontend/styles/themes.css` (system-managed — never edit):

| Pack | Look |
|---|---|
| `default` | The CraftBot baseline |
| `modern` | Larger radii, deeper soft shadows, roomier spacing |
| `glass` | Translucent blurred surfaces over a tinted page backdrop |
| `classic` | Near-square corners, flat borders, dense spacing |

**The HOST owns theming.** Users pick a THEME from the Living UI top
bar's theme picker in CraftBot — each theme bundles a style pack with a
palette (CraftBot/Modern/Glass/Classic follow light/dark mode; color
themes pin a palette on the default style). NEVER render a theme picker,
style switcher, or dark-mode toggle inside the app — theming controls in
the app are a defect the design review flags.

```tsx
import { setDefaultStyle, getStyle } from './components/ui'

setDefaultStyle('glass')    // the app's intended look — once, at the top
                            // of App.tsx; yields to the user's own choice
getStyle()                  // current pack, if you need to branch on it
```

Selection arrives via the host's `craftbot-theme` messages and lives on
`<html data-style="...">` (+ `data-theme` for mode); the boot script in
index.html restores the last host-sent value before React mounts (no
flash). Because packs are token overrides, they restyle every preset
automatically — which is also why components must NEVER hardcode radius,
shadow, blur, or spacing values: always use tokens/utility classes so all
four packs keep working.

## File Uploads

Backed by the system file API — never write multipart code.

```tsx
import { FileUpload, ImageInput } from './components/ui'
import { files, fileUrl, uploadFile } from '../services/data'

// Attachments: store the returned url in a schema string field
<FileUpload accept=".csv" onUploaded={f =>
  attachments.create({ taskId: task.id, name: f.name, fileUrl: f.url })} />

// Image field with preview (value is the stored url string)
<ImageInput label="Cover" value={coverUrl} onValue={setCoverUrl} />

// Render a stored image / link anywhere
<img src={fileUrl(card.coverUrl)} />

// Programmatic: uploadFile(file), files.list(), files.remove(id)
```

Declare the field that holds it as a plain `string` in schema.json.

