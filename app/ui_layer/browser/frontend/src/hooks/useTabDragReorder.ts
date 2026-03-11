import { useState, useCallback } from 'react'

interface TabDragState {
  dragIndex: number | null
  dragOverIndex: number | null
  handleDragStart: (e: React.DragEvent, index: number) => void
  handleDragOver: (e: React.DragEvent, index: number) => void
  handleDragEnd: () => void
  handleDrop: (e: React.DragEvent, dropIndex: number) => void
}

export function useTabDragReorder(
  reorderTabs: (fromIndex: number, toIndex: number) => void
): TabDragState {
  const [dragIndex, setDragIndex] = useState<number | null>(null)
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null)

  const handleDragStart = useCallback((e: React.DragEvent, index: number) => {
    setDragIndex(index)
    e.dataTransfer.effectAllowed = 'move'
    if (e.currentTarget instanceof HTMLElement) {
      e.dataTransfer.setDragImage(e.currentTarget, 0, 0)
    }
  }, [])

  const handleDragOver = useCallback((e: React.DragEvent, index: number) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
    setDragOverIndex(index)
  }, [])

  const handleDragEnd = useCallback(() => {
    setDragIndex(null)
    setDragOverIndex(null)
  }, [])

  const handleDrop = useCallback((_e: React.DragEvent, dropIndex: number) => {
    setDragIndex(prev => {
      if (prev !== null && prev !== dropIndex) {
        reorderTabs(prev, dropIndex)
      }
      return null
    })
    setDragOverIndex(null)
  }, [reorderTabs])

  return { dragIndex, dragOverIndex, handleDragStart, handleDragOver, handleDragEnd, handleDrop }
}
