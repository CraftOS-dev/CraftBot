# Living UI Code Examples

Complete examples for the schema-driven architecture. The backend data
layer is DECLARED — you never write models or CRUD routes. Entity types
and the frontend data plumbing are provided — you never write those
either.

## What you hand-write (the complete list)

| Artifact | File |
|---|---|
| Entity declarations | `config/schema.json` |
| React components | `frontend/components/*.tsx` |
| Custom behavior endpoints (only beyond CRUD) | `pb_hooks/main.pb.js` |
| Ops for those endpoints | `config/operations.json` |
| Documentation | `LIVING_UI.md` |

Everything else — models, CRUD API, entity TypeScript types
(`frontend/types.gen.ts`), the data client/hook, system routes — already
exists or is generated. Custom endpoints are proven with a live curl
against the running backend, not with a test suite.

## 1. Declare collections — `config/schema.json` (PocketBase format)

```json
{
  "collections": [
    {
      "name": "boardColumns", "type": "base",
      "listRule": "", "viewRule": "", "createRule": "", "updateRule": "", "deleteRule": "",
      "fields": [
        {"name": "title", "type": "text", "required": true},
        {"name": "position", "type": "number"}
      ]
    },
    {
      "name": "cards", "type": "base",
      "listRule": "", "viewRule": "", "createRule": "", "updateRule": "", "deleteRule": "",
      "fields": [
        {"name": "title", "type": "text", "required": true},
        {"name": "notes", "type": "text"},
        {"name": "position", "type": "number"},
        {"name": "dueDate", "type": "date"},
        {"name": "labels", "type": "json"},
        {"name": "columnId", "type": "relation", "collectionName": "boardColumns",
         "cascadeDelete": true, "maxSelect": 1}
      ]
    }
  ]
}
```

This alone gives full CRUD from PocketBase itself
(`/api/collections/cards/records` + filters/sort/realtime), and
regenerates `frontend/types.gen.ts` (`BoardColumn`, `Card`) +
`api.gen.ts`. Ids are strings; `created`/`updated` are automatic — never
declare them.

## 2. A typed form (react-hook-form + zod + generated types)

```tsx
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { zodResolver } from '@hookform/resolvers/zod'
import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { toast } from 'sonner'
import { api } from '../api.gen'

const schema = z.object({ title: z.string().min(1, 'Required') })

export function NewCardForm({ columnId, onDone }: { columnId: string; onDone: () => void }) {
  const form = useForm<z.infer<typeof schema>>({ resolver: zodResolver(schema), defaultValues: { title: '' } })
  const submit = form.handleSubmit(async values => {
    await api.cards.create({ ...values, columnId })   // typed against types.gen
    toast.success('Card created')
    onDone()
  })
  return (
    <Form {...form}>
      <form onSubmit={submit} className="flex flex-col gap-3">
        <FormField control={form.control} name="title" render={({ field }) => (
          <FormItem>
            <FormLabel>Title</FormLabel>
            <FormControl><Input placeholder="Card title" {...field} /></FormControl>
            <FormMessage />
          </FormItem>
        )} />
        <Button type="submit" disabled={form.formState.isSubmitting}>Create</Button>
      </form>
    </Form>
  )
}
```

`api.cards.create` refreshes every mounted `useEntities('cards')` list
automatically — no manual refetch wiring.

## 2b. Custom layout — generated types + `useEntities`

```tsx
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useEntities } from '../api.gen'
import type { BoardColumn } from '../types.gen'

export function ColumnView({ column }: { column: BoardColumn }) {
  const cards = useEntities('cards', {   // typed Card[] — no type argument needed
    filter: `columnId = '${column.id}'`,
    sort: 'position',
  })
  const [adding, setAdding] = useState(false)
  const [title, setTitle] = useState('')

  const addCard = async () => {
    await cards.create({ title, columnId: column.id, position: cards.items.length })
    setTitle('')
    setAdding(false)
  }

  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">{column.title}</h2>
        <Button size="sm" onClick={() => setAdding(true)}>Add card</Button>
      </div>
      {cards.items.length === 0 ? (
        <p className="py-8 text-center text-sm text-muted-foreground">No cards yet — add the first one.</p>
      ) : (
        <div className="flex flex-col gap-2">
          {cards.items.map(card => (
            <div key={card.id} className="bg-muted border border-border rounded-md p-3">
              {card.title}
              <Button size="sm" variant="ghost" onClick={() => cards.remove(card.id)}>
                Delete
              </Button>
            </div>
          ))}
        </div>
      )}
      <Dialog open={adding} onOpenChange={setAdding}>
        <DialogContent>
          <DialogHeader><DialogTitle>New card</DialogTitle></DialogHeader>
          <Input placeholder="Title" value={title} onChange={e => setTitle(e.target.value)} />
          <Button onClick={addCard} disabled={!title.trim()}>Create</Button>
        </DialogContent>
      </Dialog>
    </section>
  )
}
```

Notes: real `Dialog` (never `prompt()`), Tailwind semantic classes for
internals (`bg-muted`, `border-border`, `rounded-md`),
`useEntities` handles fetch/create/remove/refresh — no ApiService edits,
no AppController plumbing, no hand-written entity types. Mutations
propagate to EVERY mounted `useEntities` list automatically (a create in a
form component appears instantly in a sibling list component) — never lift
entity state to "sync" components, and never keep entity rows in local
`useState`.

## 3. Custom behavior endpoint — `pb_hooks/main.pb.js` (only beyond CRUD)

```js
routerAdd("POST", "/api/custom/archive-done", (e) => {
  const body = e.requestInfo().body            // { columnId: "..." }
  if (!body.columnId) return e.json(422, { error: "columnId is required" })
  const done = $app.findRecordsByFilter(
    "cards", `columnId = '${body.columnId}' && done = true`, "-created", 500, 0)
  done.forEach((c) => { c.set("archived", true); $app.save(c) })
  return e.json(200, { archived: done.length })
})
```

Rules: plain JavaScript in PocketBase's embedded VM — NO npm imports, NO
node APIs; use `$app`/`$os`/`$http` (ambient API: `pb_data/types.d.ts`).
Paths under `/api/custom/...`. Validate inputs and return a clean 422 —
never let a missing field become a 500. Restart the backend after hook
edits (`livingui <id> restart`), then PROVE the route with curl against
the running api URL.

## 4. One-off data calls outside components

```ts
import { api } from '../api.gen'

const all = await api.cards.getFullList({ sort: '-created' })
await api.cards.create({ title: 'Hi', columnId: col.id })
```

Custom pb_hooks endpoints (`/api/custom/...`) go through ApiService —
pass the path WITHOUT the `/api` prefix:

```ts
import { ApiService } from '../services/ApiService'

await ApiService.request('POST', '/custom/archive-done', { columnId: 'abc123' })
```
