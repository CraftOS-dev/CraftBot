import React, { useState, useEffect } from 'react'
import {
  Brain,
  Database,
  AlertTriangle,
  Loader2,
  Plus,
  Edit2,
  Trash2,
  RotateCcw,
  X,
} from 'lucide-react'
import { Button, Badge, ConfirmModal } from '../../components/ui'
import { useToast } from '../../contexts/ToastContext'
import { useConfirmModal } from '../../hooks'
import styles from './SettingsPage.module.css'
import { useSettingsWebSocket } from './useSettingsWebSocket'
import { useAppSelector } from '../../store/hooks'
import {
  selectMemoryEnabled,
  selectMemoryItems,
  selectMemoryHasLoadedMode,
  selectMemoryHasLoadedItems,
} from '../../store/selectors/memorySettings'
import type { MemoryItem } from '../../store/slices/memorySettingsSlice'

// Memory Item Form Modal Component
interface MemoryItemFormModalProps {
  item: MemoryItem | null
  onClose: () => void
  onSave: (itemData: { category: string; content: string }) => void
}

function MemoryItemFormModal({ item, onClose, onSave }: MemoryItemFormModalProps) {
  const [category, setCategory] = useState(item?.category || 'preference')
  const [content, setContent] = useState(item?.content || '')

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    onSave({ category: category.toLowerCase().trim(), content })
  }

  return (
    <div className={styles.modalOverlay} onClick={onClose}>
      <div className={styles.modalContent} onClick={e => e.stopPropagation()}>
        <div className={styles.modalHeader}>
          <h3>{item ? 'Edit Memory' : 'Add Memory Item'}</h3>
          <button className={styles.modalClose} onClick={onClose}>
            <X size={18} />
          </button>
        </div>
        <form onSubmit={handleSubmit}>
          <div className={styles.modalBody}>
            <div className={styles.formGroup}>
              <label>Category</label>
              <input
                type="text"
                value={category}
                onChange={e => setCategory(e.target.value)}
                placeholder="e.g., preference, fact, work, reminder"
                required
              />
              <span className={styles.hint}>
                Use categories like preference, fact, work, event, or reminder
              </span>
            </div>

            <div className={styles.formGroup}>
              <label>Content</label>
              <textarea
                value={content}
                onChange={e => setContent(e.target.value)}
                placeholder="Enter the memory content. Use clear, factual statements like 'User prefers dark mode' or 'John's birthday is March 15th'"
                rows={4}
                required
              />
              <span className={styles.hint}>
                Write in third person. The agent will reference this information in future conversations.
              </span>
            </div>
          </div>

          <div className={styles.modalFooter}>
            <Button variant="secondary" type="button" onClick={onClose}>
              Cancel
            </Button>
            <Button variant="primary" type="submit">
              {item ? 'Save Changes' : 'Add Memory'}
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}

export function MemorySettings() {
  const { send, onMessage, isConnected } = useSettingsWebSocket()
  const { showToast } = useToast()

  // Slice-backed: cached across remounts.
  const memoryEnabled = useAppSelector(selectMemoryEnabled)
  const items = useAppSelector(selectMemoryItems)
  const hasLoadedMode = useAppSelector(selectMemoryHasLoadedMode)
  const hasLoadedItems = useAppSelector(selectMemoryHasLoadedItems)
  const isLoadingMode = !hasLoadedMode
  const isLoadingItems = !hasLoadedItems

  // UI state (transient)
  const [showItemForm, setShowItemForm] = useState(false)
  const [editingItem, setEditingItem] = useState<MemoryItem | null>(null)
  const [isResetting, setIsResetting] = useState(false)
  const [isProcessing, setIsProcessing] = useState(false)
  const [sortOrder, setSortOrder] = useState<'latest' | 'oldest'>('latest')

  // Confirm modal
  const { modalProps: confirmModalProps, confirm } = useConfirmModal()

  // Side-effect handlers (toasts, modal close). List/enabled state itself
  // is owned by memorySettingsSlice via the registry.
  useEffect(() => {
    if (!isConnected) return

    const cleanups = [
      onMessage('memory_mode_set', (data: unknown) => {
        const d = data as { success: boolean; enabled: boolean; error?: string }
        if (d.success) showToast('success', `Memory ${d.enabled ? 'enabled' : 'disabled'}`)
        else showToast('error', d.error || 'Failed to update memory mode')
      }),
      onMessage('memory_item_add', (data: unknown) => {
        const d = data as { success: boolean; error?: string }
        if (d.success) {
          send('memory_items_get')
          setShowItemForm(false)
          setEditingItem(null)
          showToast('success', 'Memory item added')
        } else {
          showToast('error', d.error || 'Failed to add memory item')
        }
      }),
      onMessage('memory_item_update', (data: unknown) => {
        const d = data as { success: boolean; error?: string }
        if (d.success) {
          send('memory_items_get')
          setShowItemForm(false)
          setEditingItem(null)
          showToast('success', 'Memory item updated')
        } else {
          showToast('error', d.error || 'Failed to update memory item')
        }
      }),
      onMessage('memory_item_remove', (data: unknown) => {
        const d = data as { success: boolean; error?: string }
        if (d.success) {
          send('memory_items_get')
          showToast('success', 'Memory item deleted')
        } else {
          showToast('error', d.error || 'Failed to delete memory item')
        }
      }),
      onMessage('memory_reset', (data: unknown) => {
        const d = data as { success: boolean; error?: string }
        setIsResetting(false)
        if (d.success) {
          send('memory_items_get')
          showToast('success', 'Memory reset to default')
        } else {
          showToast('error', d.error || 'Failed to reset memory')
        }
      }),
      onMessage('memory_process_trigger', (data: unknown) => {
        const d = data as { success: boolean; message?: string; error?: string }
        setIsProcessing(false)
        if (d.success) showToast('success', d.message || 'Memory processing started')
        else showToast('error', d.error || 'Failed to start memory processing')
      }),
    ]

    if (!hasLoadedMode) send('memory_mode_get')
    if (!hasLoadedItems) send('memory_items_get')

    return () => cleanups.forEach(c => c())
  }, [isConnected, send, onMessage, hasLoadedMode, hasLoadedItems, showToast])

  const handleToggleMemory = (enabled: boolean) => {
    send('memory_mode_set', { enabled })
  }

  const handleAddItem = () => {
    setEditingItem(null)
    setShowItemForm(true)
  }

  const handleEditItem = (item: MemoryItem) => {
    setEditingItem(item)
    setShowItemForm(true)
  }

  const handleDeleteItem = (itemId: string) => {
    confirm({
      title: 'Delete Memory Item',
      message: 'Are you sure you want to delete this memory item?',
      confirmText: 'Delete',
      variant: 'danger',
    }, () => {
      send('memory_item_remove', { itemId })
    })
  }

  const handleProcessMemory = () => {
    confirm({
      title: 'Process Memory',
      message: 'This will process all unprocessed events into long-term memory. Continue?',
      confirmText: 'Process',
      variant: 'default',
    }, () => {
      setIsProcessing(true)
      send('memory_process_trigger')
    })
  }

  const handleResetMemory = () => {
    confirm({
      title: 'Reset Memory',
      message: 'Are you sure you want to reset all memory? This will clear all memory items and unprocessed events. This action cannot be undone.',
      confirmText: 'Reset',
      variant: 'danger',
    }, () => {
      setIsResetting(true)
      send('memory_reset')
    })
  }

  const sortedItems = [...items].sort((a, b) => {
    const dateA = new Date(a.timestamp).getTime()
    const dateB = new Date(b.timestamp).getTime()
    return sortOrder === 'latest' ? dateB - dateA : dateA - dateB
  })

  return (
    <div className={styles.settingsSection}>
      <div className={styles.sectionHeader}>
        <h3>Memory Settings</h3>
        <p>Manage agent memory, stored facts, and event processing</p>
      </div>

      {/* Master Toggle */}
      <div className={styles.settingsForm}>
        <div className={styles.toggleGroup}>
          <div className={styles.toggleInfo}>
            <span className={styles.toggleLabel}>Enable Memory</span>
            <span className={styles.toggleDesc}>
              When enabled, the agent remembers facts from conversations and uses them in context.
              When disabled, memory search is skipped and new events are not logged.
            </span>
          </div>
          <input
            type="checkbox"
            className={styles.toggle}
            checked={memoryEnabled}
            onChange={(e) => handleToggleMemory(e.target.checked)}
            disabled={isLoadingMode}
          />
        </div>
      </div>

      {/* Toggleable Content */}
      <div className={`${styles.toggleableContent} ${!memoryEnabled ? styles.disabledContent : ''}`}>
        {/* Memory Items */}
        <div className={styles.subsection}>
          <div className={styles.subsectionHeader}>
            <h4 className={styles.subsectionTitle}>Memory Items</h4>
            <div className={styles.headerActions}>
              <select
                className={styles.filterSelect}
                value={sortOrder}
                onChange={(e) => setSortOrder(e.target.value as 'latest' | 'oldest')}
              >
                <option value="latest">Newest first</option>
                <option value="oldest">Oldest first</option>
              </select>
              <Button variant="primary" size="sm" onClick={handleAddItem} icon={<Plus size={14} />} disabled={!memoryEnabled}>
                Add Memory
              </Button>
            </div>
          </div>
          <p className={styles.subsectionDesc}>
            Long-term memories stored in MEMORY.md. These are facts the agent has learned from interactions.
          </p>

          {isLoadingItems ? (
            <div className={styles.loadingState}>
              <Loader2 size={20} className={styles.spinning} />
              <span>Loading memory items...</span>
            </div>
          ) : items.length === 0 ? (
            <div className={styles.emptyState}>
              <Database size={32} className={styles.emptyIcon} />
              <p>No memory items yet.</p>
              <p className={styles.emptyHint}>
                Memory items are created when the agent processes events or when you add them manually.
              </p>
              <Button variant="secondary" size="sm" onClick={handleAddItem} disabled={!memoryEnabled}>
                Add your first memory
              </Button>
            </div>
          ) : (
            <div className={styles.memoryList}>
              {sortedItems.map(item => (
                <div key={item.id} className={styles.memoryCard}>
                  <div className={styles.memoryMain}>
                    <div className={styles.memoryHeader}>
                      <Badge variant="info">{item.category}</Badge>
                      <span className={styles.memoryTimestamp}>{item.timestamp}</span>
                    </div>
                    <p className={styles.memoryContent}>{item.content}</p>
                  </div>
                  <div className={styles.memoryActions}>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleEditItem(item)}
                      icon={<Edit2 size={14} />}
                    />
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleDeleteItem(item.id)}
                      icon={<Trash2 size={14} />}
                    />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Memory Processing */}
        <div className={styles.subsection}>
          <h4 className={styles.subsectionTitle}>Memory Processing</h4>
          <p className={styles.subsectionDesc}>
            Memory processing analyzes unprocessed events and extracts important facts into long-term memory.
            This normally runs automatically at 3 AM daily.
          </p>
          <Button
            variant="secondary"
            onClick={handleProcessMemory}
            disabled={isProcessing || !memoryEnabled}
            icon={isProcessing ? <Loader2 size={14} className={styles.spinning} /> : <Brain size={14} />}
          >
            {isProcessing ? 'Processing...' : 'Process Memory Now'}
          </Button>
          {!memoryEnabled && (
            <span className={styles.hint}>Enable memory to use this feature</span>
          )}
        </div>
      </div>

      {/* Reset Memory */}
      <div className={styles.dangerZone}>
        <div className={styles.dangerHeader}>
          <AlertTriangle size={18} className={styles.dangerIcon} />
          <h4>Reset Memory</h4>
        </div>
        <p className={styles.dangerDescription}>
          This will clear all memory items in MEMORY.md and restore it from the default template.
          All unprocessed events will also be cleared. This action cannot be undone.
        </p>
        <Button
          variant="danger"
          onClick={handleResetMemory}
          disabled={isResetting}
          icon={isResetting ? <Loader2 size={14} className={styles.spinning} /> : <RotateCcw size={14} />}
        >
          {isResetting ? 'Resetting...' : 'Reset All Memory'}
        </Button>
      </div>

      {/* Memory Item Form Modal */}
      {showItemForm && (
        <MemoryItemFormModal
          item={editingItem}
          onClose={() => {
            setShowItemForm(false)
            setEditingItem(null)
          }}
          onSave={(itemData) => {
            if (editingItem) {
              send('memory_item_update', { itemId: editingItem.id, ...itemData })
            } else {
              send('memory_item_add', itemData)
            }
          }}
        />
      )}

      {/* Confirm Modal */}
      <ConfirmModal {...confirmModalProps} />
    </div>
  )
}
