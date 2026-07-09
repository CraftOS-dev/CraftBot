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
| Custom behavior endpoints (only beyond CRUD) | `backend/routes.py` |
| Ops for those endpoints | `config/operations.json` |
| Tests for those endpoints | `backend/tests/test_*.py` |
| Documentation | `LIVING_UI.md` |

Everything else — models, CRUD API, entity TypeScript types
(`frontend/types.gen.ts`), the data client/hook, system routes, test
runner — already exists or is generated.

## 1. Declare entities — `config/schema.json`

```json
{
  "entities": {
    "BoardColumn": {
      "description": "A lane on the board",
      "fields": {
        "title": {"type": "string", "required": true},
        "position": {"type": "integer", "default": 0}
      }
    },
    "Card": {
      "description": "A card inside a column",
      "fields": {
        "title": {"type": "string", "required": true},
        "notes": {"type": "text"},
        "position": {"type": "integer", "default": 0},
        "dueDate": {"type": "datetime"},
        "labels": {"type": "json", "default": []},
        "columnId": {"type": "ref", "entity": "BoardColumn", "required": true}
      }
    }
  }
}
```

This alone creates the tables, the REST API (`/api/board_columns`,
`/api/cards` + `/bulk` + filters/ordering), auto CRUD tests, AND
`frontend/types.gen.ts` with `BoardColumn` and `Card` interfaces.
Never declare `id`, `createdAt`, `updatedAt` — they are automatic.

## 2. The one-line form and table (reach for these FIRST)

```tsx
import { EntityForm, EntityTable, Modal, toast } from './ui'

// Create/edit form — generated from the schema (validation, ref dropdowns):
<Modal open={adding} onClose={close} title="New card">
  <EntityForm entity="Card" defaults={{ columnId: col.id }}
              onSaved={() => { close(); cards.refresh(); toast.success('Card created') }}
              onCancel={close} />
</Modal>

// Sortable, searchable, paged data table with confirmed deletes:
<EntityTable entity="Card" filters={{ columnId: col.id }}
             columns={['title', 'dueDate']} allowDelete searchable pageSize={25} />
```

## 2b. Custom layout — generated types + `useEntities`

```tsx
import { useState } from 'react'
import { Button, Input, Modal, EmptyState, Section } from './ui'
import { useEntities } from '../services/data'
import type { Card, BoardColumn } from '../types.gen'

export function ColumnView({ column }: { column: BoardColumn }) {
  const cards = useEntities<Card>('cards', {
    columnId: column.id,
    orderBy: 'position',
  })
  const [adding, setAdding] = useState(false)
  const [title, setTitle] = useState('')

  const addCard = async () => {
    await cards.create({ title, columnId: column.id, position: cards.items.length })
    setTitle('')
    setAdding(false)
  }

  return (
    <Section
      title={column.title}
      actions={<Button size="sm" onClick={() => setAdding(true)}>Add card</Button>}
    >
      {cards.items.length === 0 ? (
        <EmptyState message="No cards yet — add the first one." />
      ) : (
        <div className="flex flex-col gap-2">
          {cards.items.map(card => (
            <div key={card.id} className="bg-raised border-line rounded-token p-3 text-ink">
              {card.title}
              <Button size="sm" variant="ghost" onClick={() => cards.remove(card.id)}>
                Delete
              </Button>
            </div>
          ))}
        </div>
      )}
      <Modal open={adding} onClose={() => setAdding(false)} title="New card">
        <Input label="Title" value={title} onChange={e => setTitle(e.target.value)} />
        <Button onClick={addCard} disabled={!title.trim()}>Create</Button>
      </Modal>
    </Section>
  )
}
```

Notes: real `Modal` (never `prompt()`), Tailwind token classes for
internals (`bg-raised`, `border-line`, `text-ink`, `rounded-token`),
`useEntities` handles fetch/create/remove/refresh — no ApiService edits,
no AppController plumbing, no hand-written entity types.

## 3. Custom behavior endpoint — `backend/routes.py` (only beyond CRUD)

```python
class ArchiveDoneRequest(BaseModel):
    """Body for POST /cards/archive-done."""
    columnId: int


@router.post("/cards/archive-done")
def archive_done(req: ArchiveDoneRequest, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Archive every done card in a column (single transaction)."""
    from models import Card
    n = (
        db.query(Card)
        .filter(Card.column_id == req.columnId, Card.done == True)  # noqa: E712
        .update({"archived": True})
    )
    db.commit()
    return {"archived": n}
```

Rules: Pydantic body (never a bare Dict — smoke tests probe the OpenAPI
schema), path WITHOUT `/api`, one-line docstring, absolute imports.
`from models import Card` works for every schema entity (columns are
snake_case in Python: `Card.column_id`).

For routes that accept LISTS (imports, bulk ops), validate the ITEMS with
a Pydantic model too — smoke tests probe with minimal payloads, and an
unvalidated `List[dict]` turns missing fields into a 500 instead of a
clean 422:

```python
class ImportCard(BaseModel):
    """One card in an import payload."""
    title: str
    columnId: int
    notes: Optional[str] = None


class ImportRequest(BaseModel):
    """Body for POST /cards/import."""
    cards: List[ImportCard]


@router.post("/cards/import")
def import_cards(req: ImportRequest, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Bulk-import cards (validated per item; one transaction)."""
    from models import Card
    rows = [Card(title=c.title, column_id=c.columnId, notes=c.notes) for c in req.cards]
    db.add_all(rows)
    db.commit()
    return {"imported": len(rows)}
```

Any unhandled exception in a custom route returns a 500 whose body carries
the REAL error (`{"detail": "IntegrityError: ... [at routes.py:42]"}`) —
read it from the validation/smoke output instead of guessing.

Then declare the op in `config/operations.json`:

```json
"archive_done": {
  "description": "Archive every done card in a column. Use for cleanup requests.",
  "params": {"columnId": "int"},
  "executor": {"type": "http", "method": "POST", "path": "/api/cards/archive-done"},
  "mode": "sync"
}
```

And test it — `backend/tests/test_archive.py`:

```python
def test_archive_done(client):
    col = client.post("/api/board_columns", json={"title": "T"}).json()
    client.post("/api/cards", json={"title": "a", "columnId": col["id"], "done": True})
    r = client.post("/api/cards/archive-done", json={"columnId": col["id"]})
    assert r.status_code == 200 and r.json()["archived"] == 1
```

The `client` fixture (conftest, system-managed) gives you a fresh in-memory
DB per run. Call paths WITH `/api`. Never seed fake data outside tests.

## 4. One-off data calls outside components

```ts
import { data } from '../services/data'
import type { Card } from '../types.gen'

const all = await data.list<Card>('cards', { orderBy: 'createdAt', order: 'desc' })
await data.bulkCreate<Card>('cards', rows)   // one transaction
```

Custom endpoints still go through ApiService:

```ts
await ApiService.request('POST', '/cards/archive-done', { columnId: 3 })
```
