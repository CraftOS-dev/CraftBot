# UI Component Reference

**Use these preset components by default** instead of custom styles.

```typescript
import { Button, Input, Textarea, Select, Checkbox, Toggle, Card, Container, Divider,
         Alert, Badge, EmptyState, Table, List, ListItem, Modal, Tabs, TabList, Tab, TabPanel } from './components/ui'
```

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

## Toast Notifications (react-toastify)

Use `react-toastify` for user feedback — it's pre-installed and the `<ToastContainer />` is already in `App.tsx`.

```tsx
import { toast } from 'react-toastify'

toast.success('Item created successfully')
toast.error('Failed to save changes')
toast.info('Changes saved')
toast.warn('This action cannot be undone')
```

**Use toasts for:** CRUD feedback, API errors, important state changes.
**Don't use toasts for:** Validation errors (show inline), loading states (use spinners).
