/**
 * AGENT-OWNED starter (spec A1). Replace this with the real app.
 * It demonstrates the kit's core loop: realtime data via useCollection,
 * CRUD through the PB client seam, preset components, toast feedback,
 * and a confirmation dialog for destructive actions.
 */
import { useState } from 'react';
import type { RecordModel } from 'pocketbase';
import {
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Dialog,
  Input,
  Table,
  getPbClient,
  toast,
  useCollection,
} from '../kit/index.ts';

interface Item extends RecordModel {
  title: string;
  done: boolean;
}

export function App(): React.JSX.Element {
  const { records, loading, error } = useCollection<Item>('items', { sort: '-created' });
  const [title, setTitle] = useState('');
  const [busy, setBusy] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<Item | null>(null);

  const addItem = async (): Promise<void> => {
    const trimmed = title.trim();
    if (trimmed === '') return;
    setBusy(true);
    try {
      await getPbClient().call((pb) => pb.collection('items').create({ title: trimmed, done: false }));
      setTitle('');
      toast.success('Item added');
    } catch {
      /* PB errors already surface via the shell's toast handler */
    } finally {
      setBusy(false);
    }
  };

  const toggleDone = async (item: Item): Promise<void> => {
    try {
      await getPbClient().call((pb) => pb.collection('items').update(item.id, { done: !item.done }));
    } catch {
      /* surfaced by shell */
    }
  };

  const confirmDelete = async (): Promise<void> => {
    if (pendingDelete === null) return;
    try {
      await getPbClient().call((pb) => pb.collection('items').delete(pendingDelete.id));
      toast.success('Item deleted');
    } catch {
      /* surfaced by shell */
    } finally {
      setPendingDelete(null);
    }
  };

  return (
    <main className="mx-auto max-w-2xl px-4 py-10">
      <Card>
        <CardHeader>
          <CardTitle>Items</CardTitle>
        </CardHeader>
        <CardContent className="flex gap-2">
          <Input
            placeholder="What needs doing?"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') void addItem();
            }}
          />
          <Button loading={busy} onClick={() => void addItem()}>
            Add
          </Button>
        </CardContent>
        <CardContent className="p-0">
          {loading ? (
            <p className="px-6 py-10 text-center text-sm text-[var(--lui-muted)]">Loading…</p>
          ) : error !== null ? (
            <p className="px-6 py-10 text-center text-sm text-red-500">{error}</p>
          ) : (
            <Table<Item>
              rows={records}
              rowKey={(r) => r.id}
              emptyMessage="No items yet — add your first one above."
              columns={[
                {
                  key: 'done',
                  header: '',
                  className: 'w-10',
                  render: (r) => (
                    <input
                      type="checkbox"
                      checked={r.done}
                      onChange={() => void toggleDone(r)}
                      aria-label={`Mark "${r.title}" ${r.done ? 'not done' : 'done'}`}
                    />
                  ),
                },
                {
                  key: 'title',
                  header: 'Title',
                  render: (r) => (
                    <span className={r.done ? 'line-through opacity-60' : undefined}>{r.title}</span>
                  ),
                },
                {
                  key: 'actions',
                  header: '',
                  className: 'w-20 text-right',
                  render: (r) => (
                    <Button variant="ghost" size="sm" onClick={() => setPendingDelete(r)}>
                      Delete
                    </Button>
                  ),
                },
              ]}
            />
          )}
        </CardContent>
      </Card>

      <Dialog
        open={pendingDelete !== null}
        onOpenChange={(open) => {
          if (!open) setPendingDelete(null);
        }}
        title="Delete item?"
        description={pendingDelete !== null ? `"${pendingDelete.title}" will be permanently removed.` : undefined}
        footer={
          <>
            <Button variant="secondary" onClick={() => setPendingDelete(null)}>
              Cancel
            </Button>
            <Button variant="danger" onClick={() => void confirmDelete()}>
              Delete
            </Button>
          </>
        }
      >
        <span />
      </Dialog>
    </main>
  );
}
