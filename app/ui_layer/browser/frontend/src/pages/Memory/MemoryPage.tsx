import React, { useEffect, useMemo, useRef, useState } from 'react'
import {
  Waypoints,
  RefreshCw,
  Maximize2,
  Search,
  Plus,
  Pencil,
  Trash2,
  Lock,
  FileText,
  X,
  Archive,
  Tag,
  Clock,
  Link2,
  Hash,
  Layers,
  ChevronRight,
  Folder,
  Check,
  Loader2,
  Info,
  EyeOff,
} from 'lucide-react'
import { Button, ConfirmModal } from '../../components/ui'
import { useToast } from '../../contexts/ToastContext'
import { useConfirmModal } from '../../hooks'
import { useSettingsWebSocket } from '../Settings/useSettingsWebSocket'
import { useAppSelector } from '../../store/hooks'
import {
  selectMemoryEnabled,
  selectMemoryItems,
  selectMemoryGraph,
  selectMemoryIndexedFiles,
  selectMemoryIndexCandidates,
} from '../../store/selectors/memorySettings'
import type {
  MemoryItem,
  MemoryGraphNode,
} from '../../store/slices/memorySettingsSlice'
import { MemoryGraphCanvas } from './MemoryGraphCanvas'
import styles from './MemoryPage.module.css'

const CATEGORY_OPTIONS = [
  'fact', 'preference', 'event', 'decision', 'learning', 'project', 'contact',
]

// Sidebar width bounds (resizable like the Living UI chat panel).
const PANEL_MIN_WIDTH = 280
const PANEL_MAX_WIDTH = 600

// ── Item add/edit modal ──────────────────────────────────────────────────

interface ItemFormModalProps {
  item: MemoryItem | null
  onClose: () => void
  onSave: (data: { category: string; content: string; superseded: boolean }) => void
}

function ItemFormModal({ item, onClose, onSave }: ItemFormModalProps) {
  const [category, setCategory] = useState(item?.category || 'fact')
  const [content, setContent] = useState(item?.content || '')
  const [superseded, setSuperseded] = useState(item?.superseded || false)

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!content.trim()) return
    onSave({ category, content: content.trim(), superseded })
  }

  return (
    <div className={styles.modalOverlay} onClick={onClose}>
      <div className={styles.modal} onClick={e => e.stopPropagation()}>
        <div className={styles.modalHeader}>
          <h3>{item ? 'Edit memory' : 'Add memory'}</h3>
          <button className={styles.iconButton} onClick={onClose} aria-label="Close">
            <X size={16} />
          </button>
        </div>
        <form onSubmit={submit}>
          <div className={styles.modalBody}>
            <label className={styles.fieldLabel}>Category</label>
            <select
              className={styles.select}
              value={category}
              onChange={e => setCategory(e.target.value)}
            >
              {CATEGORY_OPTIONS.map(c => (
                <option key={c} value={c}>{c}</option>
              ))}
              {!CATEGORY_OPTIONS.includes(category) && (
                <option value={category}>{category}</option>
              )}
            </select>

            <label className={styles.fieldLabel}>Content</label>
            <textarea
              className={styles.textarea}
              value={content}
              onChange={e => setContent(e.target.value)}
              rows={4}
              placeholder="e.g. John prefers concise replies"
              autoFocus
            />
            <span className={styles.hint}>
              Entities are identified and linked automatically the next time
              memory processing runs.
            </span>

            {item && (
              <label className={styles.checkboxRow}>
                <input
                  type="checkbox"
                  checked={superseded}
                  onChange={e => setSuperseded(e.target.checked)}
                />
                Superseded (kept as history, excluded from recall)
              </label>
            )}
          </div>
          <div className={styles.modalFooter}>
            <Button variant="secondary" type="button" size="sm" onClick={onClose}>
              Cancel
            </Button>
            <Button variant="primary" type="submit" size="sm">
              {item ? 'Save' : 'Add'}
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Page ─────────────────────────────────────────────────────────────────

export function MemoryPage() {
  const { send, onMessage } = useSettingsWebSocket()
  const { showToast } = useToast()
  const { modalProps: confirmModalProps, confirm } = useConfirmModal()

  const enabled = useAppSelector(selectMemoryEnabled)
  const items = useAppSelector(selectMemoryItems)
  const graph = useAppSelector(selectMemoryGraph)
  const indexedFiles = useAppSelector(selectMemoryIndexedFiles)
  const candidates = useAppSelector(selectMemoryIndexCandidates)

  const [selected, setSelected] = useState<MemoryGraphNode | null>(null)
  const [search, setSearch] = useState('')
  const [showItemForm, setShowItemForm] = useState(false)
  const [editingItem, setEditingItem] = useState<MemoryItem | null>(null)
  const [fitNonce, setFitNonce] = useState(0)
  const [refreshNonce, setRefreshNonce] = useState(0)
  // Hide the default (core) indexed files and their chunk memories from
  // the graph — MEMORY.md's items and ENTITIES.md stay visible.
  const [hideCoreFiles, setHideCoreFiles] = useState(false)
  // Header stat chips double as visibility toggles for the graph.
  const [showMemories, setShowMemories] = useState(true)
  const [showEntities, setShowEntities] = useState(true)
  const [showFiles, setShowFiles] = useState(true)
  // Two link kinds toggle independently: memory→entity ("entity links") and
  // memory→file ("file links", the radial branch lines). Render-only.
  const [showEntityLinks, setShowEntityLinks] = useState(true)
  const [showFileLinks, setShowFileLinks] = useState(true)

  // Sidebar resize (same pointer-drag pattern as the Living UI chat panel).
  const pageRef = useRef<HTMLDivElement>(null)
  const [panelWidth, setPanelWidth] = useState(340)
  const [isResizing, setIsResizing] = useState(false)

  const handleResizeStart = (e: React.PointerEvent) => {
    e.preventDefault()
    setIsResizing(true)
  }

  useEffect(() => {
    if (!isResizing) return
    const handlePointerMove = (e: PointerEvent) => {
      const rect = pageRef.current?.getBoundingClientRect()
      if (!rect) return
      const newWidth = rect.right - e.clientX
      setPanelWidth(Math.max(PANEL_MIN_WIDTH, Math.min(PANEL_MAX_WIDTH, newWidth)))
    }
    const handlePointerUp = () => setIsResizing(false)
    document.addEventListener('pointermove', handlePointerMove)
    document.addEventListener('pointerup', handlePointerUp)
    document.addEventListener('pointercancel', handlePointerUp)
    return () => {
      document.removeEventListener('pointermove', handlePointerMove)
      document.removeEventListener('pointerup', handlePointerUp)
      document.removeEventListener('pointercancel', handlePointerUp)
    }
  }, [isResizing])

  const refreshAll = () => {
    send('memory_graph_get')
    send('memory_items_get')
    send('memory_indexed_files_get')
    send('memory_mode_get')
  }

  useEffect(() => {
    refreshAll()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Any mutation re-syncs the graph and item list (the backend re-indexes
  // synchronously before broadcasting, so an immediate refetch is fresh).
  useEffect(() => {
    const unsubs = [
      onMessage('memory_item_add', () => { send('memory_items_get'); send('memory_graph_get') }),
      onMessage('memory_item_update', () => { send('memory_items_get'); send('memory_graph_get') }),
      onMessage('memory_item_remove', () => { send('memory_items_get'); send('memory_graph_get') }),
      onMessage('memory_reset', () => refreshAll()),
      onMessage('memory_indexed_files_set', (data) => {
        const d = data as { success: boolean; error?: string; rejected?: { path: string; reason: string }[] }
        setPendingPaths(new Set())
        if (!d.success) {
          showToast('error', d.error || 'Failed to update indexed files')
        } else if (d.rejected && d.rejected.length > 0) {
          showToast('error', `Skipped ${d.rejected[0].path}: ${d.rejected[0].reason}`)
        }
        send('memory_indexed_files_get')
        send('memory_graph_get')
      }),
    ]
    return () => unsubs.forEach(u => u())
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Graph shown on the canvas: optionally without the default indexed
  // files and their chunk memories. MEMORY.md, USER.md, and ENTITIES.md
  // are exempt — user knowledge stays visible; it's the bulky
  // documentation files (AGENT.md, PROACTIVE.md) that get hidden.
  const displayGraph = useMemo(() => {
    if (!graph || !hideCoreFiles) return graph
    const exempt = new Set(['MEMORY.md', 'USER.md', 'ENTITIES.md'])
    const hiddenFiles = new Set(
      indexedFiles.filter(f => f.core && !exempt.has(f.path)).map(f => f.path),
    )
    if (hiddenFiles.size === 0) return graph
    const nodes = graph.nodes.filter(n => {
      if (n.kind === 'file' && hiddenFiles.has(n.label)) return false
      if (n.kind === 'item' && n.source === 'file' && hiddenFiles.has(n.file || '')) return false
      return true
    })
    const kept = new Set(nodes.map(n => n.id))
    const edges = graph.edges.filter(e => kept.has(e.source) && kept.has(e.target))
    return { ...graph, nodes, edges }
  }, [graph, hideCoreFiles, indexedFiles])

  // A node hidden by the filter cannot stay selected.
  useEffect(() => {
    if (!selected || !displayGraph) return
    if (!displayGraph.nodes.some(n => n.id === selected.id)) setSelected(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [displayGraph])

  // Header counts describe what is actually ON SCREEN, so they follow the
  // hide-default-files toggle instead of the backend's full-graph stats.
  const displayCounts = useMemo(() => {
    const nodes = displayGraph?.nodes || []
    const edges = displayGraph?.edges || []
    return {
      memories: nodes.filter(n => n.kind === 'item').length,
      entities: nodes.filter(n => n.kind === 'entity').length,
      files: nodes.filter(n => n.kind === 'file').length,
      // Edges with a status are memory→entity; the rest are file→chunk.
      entityLinks: edges.filter(e => e.status).length,
      fileLinks: edges.filter(e => !e.status).length,
    }
  }, [displayGraph])

  // Node visibility toggles (the header chips) applied on top of the
  // core-file filter. Nodes of a hidden kind and any edge that loses an
  // endpoint drop out. Link visibility is handled render-side by the canvas
  // (so hiding lines never disturbs the layout), not here. The chips keep
  // showing the full counts — they are the toggles, not the result.
  const visibleGraph = useMemo(() => {
    if (!displayGraph) return displayGraph
    if (showMemories && showEntities && showFiles) return displayGraph
    const nodes = displayGraph.nodes.filter(n => {
      if (n.kind === 'item' && !showMemories) return false
      if (n.kind === 'entity' && !showEntities) return false
      if (n.kind === 'file' && !showFiles) return false
      return true
    })
    const kept = new Set(nodes.map(n => n.id))
    const edges = displayGraph.edges.filter(e => kept.has(e.source) && kept.has(e.target))
    return { ...displayGraph, nodes, edges }
  }, [displayGraph, showMemories, showEntities, showFiles])

  // Neighbour lookup for the selection detail.
  const neighboursOfSelected = useMemo(() => {
    if (!selected || !displayGraph) return []
    const ids = new Set<string>()
    for (const e of displayGraph.edges) {
      if (e.source === selected.id) ids.add(e.target)
      if (e.target === selected.id) ids.add(e.source)
    }
    return displayGraph.nodes.filter(n => ids.has(n.id))
  }, [selected, displayGraph])

  const filteredItems = useMemo(() => {
    const q = search.trim().toLowerCase()
    const sorted = [...items].sort((a, b) => b.timestamp.localeCompare(a.timestamp))
    if (!q) return sorted
    return sorted.filter(i =>
      (i.displayContent || i.content).toLowerCase().includes(q) ||
      i.category.toLowerCase().includes(q) ||
      (i.entities || []).some(e => e.toLowerCase().includes(q)),
    )
  }, [items, search])

  // Memories sourced from indexed files (read-only), grouped per file.
  const fileMemoryGroups = useMemo(() => {
    const q = search.trim().toLowerCase()
    const groups = new Map<string, MemoryGraphNode[]>()
    for (const node of displayGraph?.nodes || []) {
      if (node.kind !== 'item' || node.source !== 'file') continue
      if (q && !node.label.toLowerCase().includes(q) &&
          !(node.section || '').toLowerCase().includes(q) &&
          !(node.file || '').toLowerCase().includes(q)) continue
      const key = node.file || 'unknown'
      let list = groups.get(key)
      if (!list) groups.set(key, list = [])
      list.push(node)
    }
    return Array.from(groups.entries()).sort((a, b) => a[0].localeCompare(b[0]))
  }, [displayGraph, search])

  const extraFiles = useMemo(
    () => indexedFiles.filter(f => !f.core).map(f => f.path),
    [indexedFiles],
  )

  // ── File tree: indexed files + candidates merged into folders ──
  interface TreeFile {
    path: string
    name: string
    core: boolean
    indexed: boolean
    meta: string
  }
  interface TreeFolder {
    path: string
    name: string
    folders: TreeFolder[]
    files: TreeFile[]
  }

  const fileTree = useMemo<TreeFolder>(() => {
    const root: TreeFolder = { path: '', name: '', folders: [], files: [] }
    const folderMap = new Map<string, TreeFolder>([['', root]])

    const ensureFolder = (path: string): TreeFolder => {
      const existing = folderMap.get(path)
      if (existing) return existing
      const idx = path.lastIndexOf('/')
      const parent = ensureFolder(idx === -1 ? '' : path.slice(0, idx))
      const node: TreeFolder = {
        path,
        name: idx === -1 ? path : path.slice(idx + 1),
        folders: [],
        files: [],
      }
      parent.folders.push(node)
      folderMap.set(path, node)
      return node
    }

    const addFile = (file: TreeFile) => {
      const idx = file.path.lastIndexOf('/')
      ensureFolder(idx === -1 ? '' : file.path.slice(0, idx)).files.push(file)
    }

    for (const f of indexedFiles) {
      addFile({
        path: f.path,
        name: f.path.slice(f.path.lastIndexOf('/') + 1),
        core: f.core,
        indexed: true,
        meta: f.exists ? `${f.chunk_count} chunks` : 'missing',
      })
    }
    for (const c of candidates) {
      addFile({
        path: c.path,
        name: c.path.slice(c.path.lastIndexOf('/') + 1),
        core: false,
        indexed: false,
        meta: `${(c.size / 1024).toFixed(1)} KB`,
      })
    }

    const sortTree = (node: TreeFolder) => {
      node.folders.sort((a, b) => a.name.localeCompare(b.name))
      node.files.sort((a, b) => a.name.localeCompare(b.name))
      node.folders.forEach(sortTree)
    }
    sortTree(root)
    return root
  }, [indexedFiles, candidates])

  // Folders are collapsed by default; only paths in this set render expanded.
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(new Set())
  // Files whose index/unindex request is in flight — their tree rows show
  // a spinner until the backend confirms (memory_indexed_files_set).
  const [pendingPaths, setPendingPaths] = useState<Set<string>>(new Set())
  const toggleFolder = (path: string) => {
    setExpandedFolders(prev => {
      const next = new Set(prev)
      if (next.has(path)) next.delete(path)
      else next.add(path)
      return next
    })
  }

  const renderFolder = (folder: TreeFolder, depth: number): React.ReactNode => {
    const isRoot = folder.path === ''
    const isCollapsed = !expandedFolders.has(folder.path)
    return (
      <React.Fragment key={folder.path || '__root__'}>
        {!isRoot && (
          <button
            className={styles.treeRow}
            style={{ paddingLeft: 6 + depth * 14 }}
            onClick={() => toggleFolder(folder.path)}
            aria-expanded={!isCollapsed}
          >
            <ChevronRight
              size={12}
              className={`${styles.treeChevron} ${isCollapsed ? '' : styles.treeChevronOpen}`}
            />
            <Folder size={12} className={styles.treeIcon} />
            <span className={styles.treeName}>{folder.name}</span>
          </button>
        )}
        {(isRoot || !isCollapsed) && (
          <>
            {folder.folders.map(f => renderFolder(f, isRoot ? depth : depth + 1))}
            {folder.files.map(file => (
              <div
                key={file.path}
                className={styles.treeRow}
                style={{ paddingLeft: 6 + (isRoot ? depth : depth + 1) * 14 + 16 }}
              >
                <FileText size={12} className={styles.treeIcon} />
                <span className={styles.treeName} title={file.path}>{file.name}</span>
                <span className={styles.treeMeta}>{file.meta}</span>
                {file.core ? (
                  <span title="Always indexed"><Lock size={11} className={styles.treeIcon} /></span>
                ) : pendingPaths.has(file.path) ? (
                  <span title="Indexing…" aria-label="Indexing">
                    <Loader2 size={13} className={styles.treeSpinner} />
                  </span>
                ) : (
                  <button
                    className={styles.iconButton}
                    onClick={() =>
                      file.indexed ? handleRemoveFile(file.path) : handleAddFile(file.path)}
                    aria-label={file.indexed ? `Stop indexing ${file.path}` : `Index ${file.path}`}
                    title={file.indexed ? 'Indexed — click to remove' : 'Index this file'}
                  >
                    {file.indexed
                      ? <Check size={13} className={styles.treeIndexed} />
                      : <Plus size={13} />}
                  </button>
                )}
              </div>
            ))}
          </>
        )}
      </React.Fragment>
    )
  }

  // The editable MemoryItem behind a selected conversation-memory node.
  const selectedItem = useMemo(() => {
    if (!selected || selected.kind !== 'item' || selected.source === 'file') return null
    return items.find(i => `i:${i.id}` === selected.id) ?? null
  }, [selected, items])

  const handleSaveItem = (data: { category: string; content: string; superseded: boolean }) => {
    if (editingItem) {
      send('memory_item_update', {
        itemId: editingItem.id,
        category: data.category,
        content: data.content,
        superseded: data.superseded,
      })
    } else {
      send('memory_item_add', { category: data.category, content: data.content })
    }
    setShowItemForm(false)
    setEditingItem(null)
  }

  const handleDeleteItem = (item: MemoryItem) => {
    confirm(
      {
        title: 'Delete memory',
        message: 'This permanently removes the memory item. Consider marking it superseded instead to keep history.',
        confirmText: 'Delete',
        variant: 'danger',
      },
      () => {
        send('memory_item_remove', { itemId: item.id })
        setSelected(null)
      },
    )
  }

  const handleAddFile = (path: string) => {
    setPendingPaths(prev => new Set(prev).add(path))
    send('memory_indexed_files_set', { paths: [...extraFiles, path] })
  }

  const handleRemoveFile = (path: string) => {
    setPendingPaths(prev => new Set(prev).add(path))
    send('memory_indexed_files_set', { paths: extraFiles.filter(p => p !== path) })
  }

  // Selecting an item row focuses its node in the graph (when present).
  const selectItemInGraph = (item: MemoryItem) => {
    const node = graph?.nodes.find(n => n.id === `i:${item.id}`)
    setSelected(node || null)
  }

  return (
    <div
      ref={pageRef}
      className={`${styles.page} ${isResizing ? styles.resizing : ''}`}
    >
      {/* ── Graph area ── */}
      <div className={styles.graphArea}>
        <div className={styles.graphHeader}>
          <div className={styles.titleGroup}>
            <Waypoints size={18} />
            <h2>Memory</h2>
            {!enabled && <span className={`${styles.tag} ${styles.tagWarning}`}>Memory disabled</span>}
          </div>
          <div className={styles.statChips}>
            <button
              type="button"
              className={`${styles.statChip} ${styles.statChipToggle} ${showMemories ? '' : styles.statChipOff}`}
              onClick={() => setShowMemories(v => !v)}
              title={showMemories ? 'Hide memories' : 'Show memories'}
              aria-pressed={showMemories}
            >
              {displayCounts.memories} memories
            </button>
            <button
              type="button"
              className={`${styles.statChip} ${styles.statChipToggle} ${showEntities ? '' : styles.statChipOff}`}
              onClick={() => setShowEntities(v => !v)}
              title={showEntities ? 'Hide entities' : 'Show entities'}
              aria-pressed={showEntities}
            >
              {displayCounts.entities} entities
            </button>
            <button
              type="button"
              className={`${styles.statChip} ${styles.statChipToggle} ${showFiles ? '' : styles.statChipOff}`}
              onClick={() => setShowFiles(v => !v)}
              title={showFiles ? 'Hide files' : 'Show files'}
              aria-pressed={showFiles}
            >
              {displayCounts.files} {displayCounts.files === 1 ? 'file' : 'files'}
            </button>
            <button
              type="button"
              className={`${styles.statChip} ${styles.statChipToggle} ${showEntityLinks ? '' : styles.statChipOff}`}
              onClick={() => setShowEntityLinks(v => !v)}
              title={showEntityLinks ? 'Hide memory→entity links' : 'Show memory→entity links'}
              aria-pressed={showEntityLinks}
            >
              {displayCounts.entityLinks} entity links
            </button>
            <button
              type="button"
              className={`${styles.statChip} ${styles.statChipToggle} ${showFileLinks ? '' : styles.statChipOff}`}
              onClick={() => setShowFileLinks(v => !v)}
              title={showFileLinks ? 'Hide memory→file links' : 'Show memory→file links'}
              aria-pressed={showFileLinks}
            >
              {displayCounts.fileLinks} file links
            </button>
            <button
              className={`${styles.iconButton} ${hideCoreFiles ? styles.iconButtonActive : ''}`}
              onClick={() => setHideCoreFiles(v => !v)}
              title={hideCoreFiles ? 'Show default files' : 'Hide default files (AGENT.md, PROACTIVE.md)'}
              aria-label="Toggle default files"
              aria-pressed={hideCoreFiles}
            >
              <EyeOff size={14} />
            </button>
            <button
              className={styles.iconButton}
              onClick={() => setFitNonce(n => n + 1)}
              title="Fit view"
              aria-label="Fit view"
            >
              <Maximize2 size={14} />
            </button>
            <button
              className={styles.iconButton}
              onClick={() => {
                send('memory_graph_get')
                setRefreshNonce(n => n + 1)
              }}
              title="Refresh graph"
              aria-label="Refresh graph"
            >
              <RefreshCw size={14} />
            </button>
          </div>
        </div>

        <MemoryGraphCanvas
          graph={visibleGraph}
          selectedId={selected?.id ?? null}
          onSelect={setSelected}
          fitNonce={fitNonce}
          refreshNonce={refreshNonce}
          showEntityLinks={showEntityLinks}
          showFileLinks={showFileLinks}
        />

        {graph && graph.nodes.length === 0 && (
          <div className={styles.emptyOverlay}>
            <Waypoints size={32} />
            <p>No memories yet</p>
            <span>
              As you chat, CraftBot distills what matters into memory and it
              appears here as a living graph.
            </span>
          </div>
        )}
      </div>

      {/* ── Resize handle ── */}
      <div
        className={`${styles.resizeHandle} ${isResizing ? styles.resizing : ''}`}
        onPointerDown={handleResizeStart}
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize panel"
      />

      {/* ── Right panel: selection/memories on top, files below ── */}
      <aside
        className={styles.panel}
        style={{ ['--panel-w' as string]: `${panelWidth}px` }}
      >
        <div className={styles.topPane}>
          {selected ? (
            <div className={styles.detail}>
              {/* Header: what am I looking at + dismiss */}
              <div className={styles.detailTop}>
                <span className={`${styles.kindDot} ${styles[`kind_${selected.kind}`]}`} />
                <span className={styles.kindLabel}>
                  {selected.kind === 'item'
                    ? (selected.source === 'file' ? 'File memory' : 'Memory')
                    : selected.kind === 'entity' ? 'Entity' : 'File'}
                </span>
                {selected.superseded && <span className={`${styles.tag} ${styles.tagWarning}`}>superseded</span>}
                <button
                  className={`${styles.iconButton} ${styles.detailClose}`}
                  onClick={() => setSelected(null)}
                  aria-label="Close details"
                  title="Close"
                >
                  <X size={14} />
                </button>
              </div>

              {/* Content: names read as titles, memories read as prose */}
              <div className={selected.kind === 'item' ? styles.detailBody : styles.detailName}>
                {selected.label}
              </div>

              {/* Metadata: one aligned row per fact about this node */}
              <div className={styles.metaList}>
                {selected.kind === 'item' && selected.source !== 'file' && (
                  <>
                    <div className={styles.metaRow}>
                      <Tag size={12} />
                      <span>{selected.category || 'fact'}</span>
                    </div>
                    {selected.timestamp && (
                      <div className={styles.metaRow}>
                        <Clock size={12} />
                        <span>{selected.timestamp}</span>
                      </div>
                    )}
                    {(selectedItem?.entities?.length ?? 0) > 0 && (
                      <div className={styles.metaRow}>
                        <Link2 size={12} />
                        <span>{(selectedItem?.entities ?? []).join(', ')}</span>
                      </div>
                    )}
                  </>
                )}
                {selected.kind === 'item' && selected.source === 'file' && (
                  <>
                    <div className={styles.metaRow}>
                      <FileText size={12} />
                      <span>{selected.file}</span>
                    </div>
                    {selected.section && (
                      <div className={styles.metaRow}>
                        <Hash size={12} />
                        <span title={selected.section}>{selected.section}</span>
                      </div>
                    )}
                  </>
                )}
                {selected.kind === 'entity' && (
                  <div className={styles.metaRow}>
                    <Link2 size={12} />
                    <span>{selected.size ?? neighboursOfSelected.length} mention{(selected.size ?? 0) === 1 ? '' : 's'}</span>
                  </div>
                )}
                {selected.kind === 'file' && (
                  <div className={styles.metaRow}>
                    <Layers size={12} />
                    <span>{selected.size ?? neighboursOfSelected.length} section{(selected.size ?? 0) === 1 ? '' : 's'}</span>
                  </div>
                )}
              </div>

              {/* Related nodes */}
              {neighboursOfSelected.length > 0 && (
                <div className={styles.detailSection}>
                  <div className={styles.sectionLabel}>
                    Connected · {neighboursOfSelected.length}
                  </div>
                  <div className={styles.chipsScroll}>
                    {neighboursOfSelected.map(n => (
                      <button
                        key={n.id}
                        className={styles.neighbourChip}
                        onClick={() => setSelected(n)}
                        title={n.label}
                      >
                        <span className={`${styles.chipDot} ${styles[`kind_${n.kind}`]}`} />
                        {n.label.length > 34 ? `${n.label.slice(0, 34)}…` : n.label}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Actions: explicit, labelled, always at the pane's foot */}
              {selectedItem && (
                <div className={styles.detailFooter}>
                  <Button
                    variant="secondary"
                    size="sm"
                    icon={<Pencil size={13} />}
                    onClick={() => { setEditingItem(selectedItem); setShowItemForm(true) }}
                  >
                    Edit
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    icon={<Trash2 size={13} />}
                    onClick={() => handleDeleteItem(selectedItem)}
                  >
                    Delete
                  </Button>
                </div>
              )}
            </div>
          ) : (
            <>
              {/* No selection: search / add memories */}
              <div className={styles.toolbar}>
                <div className={styles.searchBox}>
                  <Search size={13} />
                  <input
                    value={search}
                    onChange={e => setSearch(e.target.value)}
                    placeholder="Search memories…"
                  />
                </div>
                <Button
                  variant="secondary"
                  size="sm"
                  icon={<Plus size={13} />}
                  onClick={() => { setEditingItem(null); setShowItemForm(true) }}
                >
                  Add
                </Button>
              </div>

              {search.trim() ? (
                // Results appear only while searching — the pane is not an
                // inventory list.
                <div className={styles.itemList}>
                  {filteredItems.length === 0 && fileMemoryGroups.length === 0 && (
                    <div className={styles.emptyList}>No matches.</div>
                  )}
                  {filteredItems.map(item => (
                    <div
                      key={item.id}
                      className={`${styles.itemRow} ${item.superseded ? styles.itemSuperseded : ''}`}
                      onClick={() => selectItemInGraph(item)}
                    >
                      <div className={styles.itemTop}>
                        <span className={`${styles.chipDot} ${styles.kind_item}`} />
                        <span className={styles.itemKind}>{item.category}</span>
                        {item.superseded && (
                          <span className={styles.supersededTag}>
                            <Archive size={11} /> superseded
                          </span>
                        )}
                        <span className={styles.itemTime}>{item.timestamp.slice(0, 10)}</span>
                      </div>
                      <div className={styles.itemContent}>
                        {item.displayContent || item.content}
                      </div>
                    </div>
                  ))}
                  {fileMemoryGroups.map(([filePath, nodes]) => (
                    <React.Fragment key={filePath}>
                      <div className={`${styles.sectionLabel} ${styles.sectionLabelClip}`}>
                        <FileText size={11} /> {filePath} · {nodes.length}
                      </div>
                      {nodes.map(node => (
                        <div
                          key={node.id}
                          className={styles.itemRow}
                          onClick={() => setSelected(node)}
                        >
                          <div className={styles.itemTop}>
                            <span className={`${styles.chipDot} ${styles.kind_file}`} />
                            <span className={styles.itemKind} title={node.section}>
                              {node.section
                                ? (node.section.length > 40 ? `${node.section.slice(0, 40)}…` : node.section)
                                : 'section'}
                            </span>
                          </div>
                          <div className={styles.itemContent}>{node.label}</div>
                        </div>
                      ))}
                    </React.Fragment>
                  ))}
                </div>
              ) : (
                <div className={styles.paneEmpty}>
                  <Waypoints size={22} />
                  <span>
                    Select a node in the graph to see its details, or search
                    your memories above.
                  </span>
                </div>
              )}
            </>
          )}
        </div>

        {/* ── Bottom: agent file system tree ── */}
        <div className={styles.bottomPane}>
          <div className={styles.sectionLabel}>
            Agent files
            <span className={styles.infoTip} aria-label="About file indexing">
              <Info size={11} />
              <span className={styles.infoTooltip} role="tooltip">
                <strong>What is indexing?</strong>
                Indexed files become part of CraftBot's memory: their
                content is split into sections, made searchable, and shown
                in the graph as file memories.
                <br /><br />
                After indexing, a background task reads each file and
                identifies the people, projects, and tools it mentions —
                linking it into the same knowledge graph as conversation
                memories, so recall draws on both.
              </span>
            </span>
          </div>
          <div className={styles.tree}>
            {renderFolder(fileTree, 0)}
          </div>
          <span className={styles.hint}>
            Check a file to index it into memory. Locked files are always
            indexed.
          </span>
        </div>
      </aside>

      {isResizing && <div className={styles.resizeOverlay} aria-hidden="true" />}

      {showItemForm && (
        <ItemFormModal
          item={editingItem}
          onClose={() => { setShowItemForm(false); setEditingItem(null) }}
          onSave={handleSaveItem}
        />
      )}
      <ConfirmModal {...confirmModalProps} />
    </div>
  )
}
