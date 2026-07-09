/**
 * Drag-to-reorder preset (SYSTEM-MANAGED — do not edit)
 *
 *   <SortableList
 *     items={cards.items}
 *     renderItem={card => <CardFace card={card} />}
 *     onReorder={async items => { await reorderAndSave('cards', items); await cards.refresh() }}
 *   />
 *
 * `reorderAndSave(plural, items)` persists the new order into each item's
 * `position` field (the standard ordering convention — pair with
 * `orderBy: 'position'` in useEntities).
 */

import React, { useState } from 'react'
import { data } from '../../services/data'

export async function reorderAndSave<T extends { id: number }>(
  plural: string,
  items: T[],
  positionField = 'position',
): Promise<void> {
  await Promise.all(
    items.map((item, index) =>
      data.update(plural, item.id, { [positionField]: index } as Partial<T>),
    ),
  )
}

export interface SortableListProps<T extends { id: number }> {
  items: T[]
  renderItem: (item: T) => React.ReactNode
  /** Receives the full list in its NEW order after a drop. */
  onReorder: (items: T[]) => void
  direction?: 'vertical' | 'horizontal'
  className?: string
}

export function SortableList<T extends { id: number }>({
  items,
  renderItem,
  onReorder,
  direction = 'vertical',
  className,
}: SortableListProps<T>) {
  const [dragId, setDragId] = useState<number | null>(null)
  const [overId, setOverId] = useState<number | null>(null)

  const drop = () => {
    if (dragId === null || overId === null || dragId === overId) {
      setDragId(null)
      setOverId(null)
      return
    }
    const next = [...items]
    const from = next.findIndex(i => i.id === dragId)
    const to = next.findIndex(i => i.id === overId)
    if (from !== -1 && to !== -1) {
      const [moved] = next.splice(from, 1)
      next.splice(to, 0, moved)
      onReorder(next)
    }
    setDragId(null)
    setOverId(null)
  }

  return (
    <div
      className={`flex ${direction === 'vertical' ? 'flex-col' : 'flex-row'} gap-2 ${className ?? ''}`}
    >
      {items.map(item => (
        <div
          key={item.id}
          draggable
          onDragStart={() => setDragId(item.id)}
          onDragOver={e => {
            e.preventDefault()
            if (item.id !== overId) setOverId(item.id)
          }}
          onDrop={drop}
          onDragEnd={() => {
            setDragId(null)
            setOverId(null)
          }}
          className={
            'cursor-grab active:cursor-grabbing transition-opacity ' +
            (dragId === item.id ? 'opacity-40 ' : '') +
            (overId === item.id && dragId !== null && dragId !== item.id
              ? 'outline outline-1 outline-primary rounded-token '
              : '')
          }
        >
          {renderItem(item)}
        </div>
      ))}
    </div>
  )
}
