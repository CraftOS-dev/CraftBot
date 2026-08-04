/**
 * Drag-to-reorder preset.
 *
 *   <SortableList
 *     items={cards}
 *     renderItem={(card) => <CardFace card={card} />}
 *     onReorder={async (items) => {
 *       await reorderAndSave('cards', items);
 *       refresh();
 *     }}
 *   />
 *
 * `reorderAndSave(collection, items)` persists the new order into each item's
 * `position` field (pair with sort: 'position' in useCollection).
 */
import { useState } from 'react';
import type { ReactNode } from 'react';
import { cn } from '../lib/cn.ts';
import { getPbClient } from '../pb/client.ts';

export async function reorderAndSave<T extends { id: string }>(
  collection: string,
  items: ReadonlyArray<T>,
  positionField = 'position',
): Promise<void> {
  const client = getPbClient();
  await Promise.all(
    items.map((item, index) =>
      client.call((pb) => pb.collection(collection).update(item.id, { [positionField]: index })),
    ),
  );
}

export interface SortableListProps<T extends { id: string }> {
  items: ReadonlyArray<T>;
  renderItem: (item: T) => ReactNode;
  /** Receives the full list in its NEW order after a drop. */
  onReorder: (items: T[]) => void;
  direction?: 'vertical' | 'horizontal' | undefined;
  className?: string | undefined;
}

export function SortableList<T extends { id: string }>({
  items,
  renderItem,
  onReorder,
  direction = 'vertical',
  className,
}: SortableListProps<T>): React.JSX.Element {
  const [dragId, setDragId] = useState<string | null>(null);
  const [overId, setOverId] = useState<string | null>(null);

  const drop = (): void => {
    if (dragId === null || overId === null || dragId === overId) {
      setDragId(null);
      setOverId(null);
      return;
    }
    const next = [...items];
    const from = next.findIndex((i) => i.id === dragId);
    const to = next.findIndex((i) => i.id === overId);
    if (from !== -1 && to !== -1) {
      const [moved] = next.splice(from, 1);
      if (moved !== undefined) {
        next.splice(to, 0, moved);
        onReorder(next);
      }
    }
    setDragId(null);
    setOverId(null);
  };

  return (
    <div className={cn('flex gap-2', direction === 'vertical' ? 'flex-col' : 'flex-row', className)}>
      {items.map((item) => (
        <div
          key={item.id}
          draggable
          onDragStart={() => setDragId(item.id)}
          onDragOver={(e) => {
            e.preventDefault();
            if (item.id !== overId) setOverId(item.id);
          }}
          onDrop={drop}
          onDragEnd={() => {
            setDragId(null);
            setOverId(null);
          }}
          className={cn(
            'cursor-grab transition-opacity active:cursor-grabbing',
            dragId === item.id && 'opacity-40',
            overId === item.id &&
              dragId !== null &&
              dragId !== item.id &&
              'rounded-[var(--lui-radius)] outline outline-1 outline-[var(--lui-accent)]',
          )}
        >
          {renderItem(item)}
        </div>
      ))}
    </div>
  );
}
