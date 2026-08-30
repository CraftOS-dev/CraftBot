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
import { useTranslation, Trans } from 'react-i18next'
import { formatNumber, formatDate, formatDateTime, formatList } from '../../i18n/format'
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


// Sidebar width bounds (resizable like the Agent App chat panel).
const PANEL_MIN_WIDTH = 280
const PANEL_MAX_WIDTH = 600

// ── Item add/edit modal ──────────────────────────────────────────────────

interface ItemFormModalProps {
  item: MemoryItem | null
  onClose: () => void
  onSave: (data: { category: string; content: string; superseded: boolean }) => void
}

function ItemFormModal({ item, onClose, onSave }: ItemFormModalProps) {
  const { t } = useTranslation(['memory', 'common'])
  // Translated label for a known category; custom values pass through verbatim.
  const categoryLabel = (c: string): string => ({
    fact: t('memory:category.fact'),
    preference: t('memory:category.preference'),
    event: t('memory:category.event'),
    decision: t('memory:category.decision'),
    learning: t('memory:category.learning'),
    project: t('memory:category.project'),
    contact: t('memory:category.contact'),
  } as Record<string, string>)[c] ?? c
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
          <h3>{item ? t('memory:item.editTitle') : t('memory:item.addTitle')}</h3>
          <button className={styles.iconButton} onClick={onClose} aria-label={t('common:actions.close')}>
            <X size={16} />
          </button>
        </div>
        <form onSubmit={submit}>
          <div className={styles.modalBody}>
            <label className={styles.fieldLabel}>{t('memory:field.category')}</label>
            <select
              className={styles.select}
              value={category}
              onChange={e => setCategory(e.target.value)}
            >
              {CATEGORY_OPTIONS.map(c => (
                <option key={c} value={c}>{categoryLabel(c)}</option>
              ))}
              {!CATEGORY_OPTIONS.includes(category) && (
                <option value={category}>{categoryLabel(category)}</option>
              )}
            </select>

            <label className={styles.fieldLabel}>{t('memory:field.content')}</label>
            <textarea
              className={styles.textarea}
              value={content}
              onChange={e => setContent(e.target.value)}
              rows={4}
              placeholder={t('memory:item.contentPlaceholder')}
              autoFocus
            />
            <span className={styles.hint}>
              {t('memory:item.entitiesHint')}
            </span>

            {item && (
              <label className={styles.checkboxRow}>
                <input
                  type="checkbox"
                  checked={superseded}
                  onChange={e => setSuperseded(e.target.checked)}
                />
                {t('memory:item.supersededLabel')}
              </label>
            )}
          </div>
          <div className={styles.modalFooter}>
            <Button variant="secondary" type="button" size="sm" onClick={onClose}>
              {t('common:actions.cancel')}
            </Button>
            <Button variant="primary" type="submit" size="sm">
              {item ? t('common:actions.save') : t('common:actions.add')}
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Page ─────────────────────────────────────────────────────────────────

export function MemoryPage() {
  const { t } = useTranslation(['memory', 'common'])
  // Translated label for a known category; custom values pass through verbatim.
  const categoryLabel = (c: string): string => ({
    fact: t('memory:category.fact'),
    preference: t('memory:category.preference'),
    event: t('memory:category.event'),
    decision: t('memory:category.decision'),
    learning: t('memory:category.learning'),
    project: t('memory:category.project'),
    contact: t('memory:category.contact'),
  } as Record<string, string>)[c] ?? c
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

  // Sidebar resize (same pointer-drag pattern as the Agent App chat panel).
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
      // Per-file add/remove completion: clear ONLY the finished file's
      // spinner so other still-pending files keep spinning. (The old full
      // replace cleared every spinner on the first response, masking the
      // clobbered files as if they had indexed.)
      ...(['memory_index_file_add', 'memory_index_file_remove'] as const).map(msg =>
        onMessage(msg, (data) => {
          const d = data as {
            success: boolean; path?: string; error?: string
            rejected?: { path: string; reason: string }[]
          }
          if (d.path) {
            setPendingPaths(prev => {
              const next = new Set(prev)
              next.delete(d.path as string)
              return next
            })
          }
          if (!d.success) {
            showToast('error', d.error || t('memory:toast.updateFailed'))
          } else if (d.rejected && d.rejected.length > 0) {
            showToast('error', t('memory:toast.skipped', { path: d.rejected[0].path, reason: d.rejected[0].reason }))
          }
          // No memory_graph_get / memory_indexed_files_get round-trip here:
          // the response already carries the fresh graph, files, and
          // candidates (applied by the slice). Sending them would queue
          // behind other still-pending index jobs and defer the refresh.
        }),
      ),
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
        meta: f.exists
          ? t('memory:tree.chunks', { count: f.chunk_count, formatted: formatNumber(f.chunk_count) })
          : t('memory:tree.missing'),
      })
    }
    for (const c of candidates) {
      addFile({
        path: c.path,
        name: c.path.slice(c.path.lastIndexOf('/') + 1),
        core: false,
        indexed: false,
        meta: t('memory:tree.sizeKb', {
          size: formatNumber(c.size / 1024, { minimumFractionDigits: 1, maximumFractionDigits: 1 }),
        }),
      })
    }

    const sortTree = (node: TreeFolder) => {
      node.folders.sort((a, b) => a.name.localeCompare(b.name))
      node.files.sort((a, b) => a.name.localeCompare(b.name))
      node.folders.forEach(sortTree)
    }
    sortTree(root)
    return root
  }, [indexedFiles, candidates, t])

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
                  <span title={t('memory:tree.alwaysIndexed')}><Lock size={11} className={styles.treeIcon} /></span>
                ) : pendingPaths.has(file.path) ? (
                  <span title={t('memory:tree.indexing')} aria-label={t('memory:tree.indexing')}>
                    <Loader2 size={13} className={styles.treeSpinner} />
                  </span>
                ) : (
                  <button
                    className={styles.iconButton}
                    onClick={() =>
                      file.indexed ? handleRemoveFile(file.path) : handleAddFile(file.path)}
                    aria-label={file.indexed ? t('memory:tree.stopIndexing', { path: file.path }) : t('memory:tree.indexFile', { path: file.path })}
                    title={file.indexed ? t('memory:tree.indexedRemove') : t('memory:tree.indexThis')}
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
        title: t('memory:item.deleteTitle'),
        message: t('memory:item.deleteMessage'),
        confirmText: t('common:actions.delete'),
        variant: 'danger',
      },
      () => {
        send('memory_item_remove', { itemId: item.id })
        setSelected(null)
      },
    )
  }

  // Additive per-file mutations: the backend reads the persisted list fresh
  // and adds/removes just this path. Sending the whole list (derived from the
  // stale `extraFiles` memo) meant rapid clicks each rebuilt their payload
  // from the same pre-update base, so the last write clobbered the rest and
  // only one file ended up indexed.
  const handleAddFile = (path: string) => {
    setPendingPaths(prev => new Set(prev).add(path))
    send('memory_index_file_add', { path })
  }

  const handleRemoveFile = (path: string) => {
    setPendingPaths(prev => new Set(prev).add(path))
    send('memory_index_file_remove', { path })
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
            <h2>{t('memory:page.title')}</h2>
            {!enabled && <span className={`${styles.tag} ${styles.tagWarning}`}>{t('memory:page.disabled')}</span>}
          </div>
          <div className={styles.statChips}>
            <button
              type="button"
              className={`${styles.statChip} ${styles.statChipToggle} ${showMemories ? '' : styles.statChipOff}`}
              onClick={() => setShowMemories(v => !v)}
              title={showMemories ? t('memory:toggle.hideMemories') : t('memory:toggle.showMemories')}
              aria-pressed={showMemories}
            >
              {t('memory:stats.memories', { count: displayCounts.memories, formatted: formatNumber(displayCounts.memories) })}
            </button>
            <button
              type="button"
              className={`${styles.statChip} ${styles.statChipToggle} ${showEntities ? '' : styles.statChipOff}`}
              onClick={() => setShowEntities(v => !v)}
              title={showEntities ? t('memory:toggle.hideEntities') : t('memory:toggle.showEntities')}
              aria-pressed={showEntities}
            >
              {t('memory:stats.entities', { count: displayCounts.entities, formatted: formatNumber(displayCounts.entities) })}
            </button>
            <button
              type="button"
              className={`${styles.statChip} ${styles.statChipToggle} ${showFiles ? '' : styles.statChipOff}`}
              onClick={() => setShowFiles(v => !v)}
              title={showFiles ? t('memory:toggle.hideFiles') : t('memory:toggle.showFiles')}
              aria-pressed={showFiles}
            >
              {t('memory:stats.files', { count: displayCounts.files, formatted: formatNumber(displayCounts.files) })}
            </button>
            <button
              type="button"
              className={`${styles.statChip} ${styles.statChipToggle} ${showEntityLinks ? '' : styles.statChipOff}`}
              onClick={() => setShowEntityLinks(v => !v)}
              title={showEntityLinks ? t('memory:toggle.hideEntityLinks') : t('memory:toggle.showEntityLinks')}
              aria-pressed={showEntityLinks}
            >
              {t('memory:stats.entityLinks', { count: displayCounts.entityLinks, formatted: formatNumber(displayCounts.entityLinks) })}
            </button>
            <button
              type="button"
              className={`${styles.statChip} ${styles.statChipToggle} ${showFileLinks ? '' : styles.statChipOff}`}
              onClick={() => setShowFileLinks(v => !v)}
              title={showFileLinks ? t('memory:toggle.hideFileLinks') : t('memory:toggle.showFileLinks')}
              aria-pressed={showFileLinks}
            >
              {t('memory:stats.fileLinks', { count: displayCounts.fileLinks, formatted: formatNumber(displayCounts.fileLinks) })}
            </button>
            <button
              className={`${styles.iconButton} ${hideCoreFiles ? styles.iconButtonActive : ''}`}
              onClick={() => setHideCoreFiles(v => !v)}
              title={hideCoreFiles ? t('memory:toggle.showDefaultFiles') : t('memory:toggle.hideDefaultFiles')}
              aria-label={t('memory:toggle.toggleDefaultFiles')}
              aria-pressed={hideCoreFiles}
            >
              <EyeOff size={14} />
            </button>
            <button
              className={styles.iconButton}
              onClick={() => setFitNonce(n => n + 1)}
              title={t('memory:toggle.fitView')}
              aria-label={t('memory:toggle.fitView')}
            >
              <Maximize2 size={14} />
            </button>
            <button
              className={styles.iconButton}
              onClick={() => {
                send('memory_graph_get')
                setRefreshNonce(n => n + 1)
              }}
              title={t('memory:toggle.refreshGraph')}
              aria-label={t('memory:toggle.refreshGraph')}
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
            <p>{t('memory:empty.title')}</p>
            <span>
              {t('memory:empty.body')}
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
        aria-label={t('memory:a11y.resizePanel')}
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
                    ? (selected.source === 'file' ? t('memory:kind.fileMemory') : t('memory:kind.memory'))
                    : selected.kind === 'entity' ? t('memory:kind.entity') : t('memory:kind.file')}
                </span>
                {selected.superseded && <span className={`${styles.tag} ${styles.tagWarning}`}>{t('memory:tag.superseded')}</span>}
                <button
                  className={`${styles.iconButton} ${styles.detailClose}`}
                  onClick={() => setSelected(null)}
                  aria-label={t('memory:detail.closeAria')}
                  title={t('common:actions.close')}
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
                      <span>{categoryLabel(selected.category || 'fact')}</span>
                    </div>
                    {selected.timestamp && (
                      <div className={styles.metaRow}>
                        <Clock size={12} />
                        <span>{formatDateTime(new Date(selected.timestamp))}</span>
                      </div>
                    )}
                    {(selectedItem?.entities?.length ?? 0) > 0 && (
                      <div className={styles.metaRow}>
                        <Link2 size={12} />
                        <span>{formatList(selectedItem?.entities ?? [])}</span>
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
                    <span>{t('memory:meta.mentions', { count: selected.size ?? neighboursOfSelected.length, formatted: formatNumber(selected.size ?? neighboursOfSelected.length) })}</span>
                  </div>
                )}
                {selected.kind === 'file' && (
                  <div className={styles.metaRow}>
                    <Layers size={12} />
                    <span>{t('memory:meta.sections', { count: selected.size ?? neighboursOfSelected.length, formatted: formatNumber(selected.size ?? neighboursOfSelected.length) })}</span>
                  </div>
                )}
              </div>

              {/* Related nodes */}
              {neighboursOfSelected.length > 0 && (
                <div className={styles.detailSection}>
                  <div className={styles.sectionLabel}>
                    {t('memory:detail.connected', { value: formatNumber(neighboursOfSelected.length) })}
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
                    {t('common:actions.edit')}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    icon={<Trash2 size={13} />}
                    onClick={() => handleDeleteItem(selectedItem)}
                  >
                    {t('common:actions.delete')}
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
                    placeholder={t('memory:toolbar.searchPlaceholder')}
                  />
                </div>
                <Button
                  variant="secondary"
                  size="sm"
                  icon={<Plus size={13} />}
                  onClick={() => { setEditingItem(null); setShowItemForm(true) }}
                >
                  {t('common:actions.add')}
                </Button>
              </div>

              {search.trim() ? (
                // Results appear only while searching — the pane is not an
                // inventory list.
                <div className={styles.itemList}>
                  {filteredItems.length === 0 && fileMemoryGroups.length === 0 && (
                    <div className={styles.emptyList}>{t('memory:list.noMatches')}</div>
                  )}
                  {filteredItems.map(item => (
                    <div
                      key={item.id}
                      className={`${styles.itemRow} ${item.superseded ? styles.itemSuperseded : ''}`}
                      onClick={() => selectItemInGraph(item)}
                    >
                      <div className={styles.itemTop}>
                        <span className={`${styles.chipDot} ${styles.kind_item}`} />
                        <span className={styles.itemKind}>{categoryLabel(item.category)}</span>
                        {item.superseded && (
                          <span className={styles.supersededTag}>
                            <Archive size={11} /> {t('memory:tag.superseded')}
                          </span>
                        )}
                        <span className={styles.itemTime}>{formatDate(new Date(item.timestamp))}</span>
                      </div>
                      <div className={styles.itemContent}>
                        {item.displayContent || item.content}
                      </div>
                    </div>
                  ))}
                  {fileMemoryGroups.map(([filePath, nodes]) => (
                    <React.Fragment key={filePath}>
                      <div className={`${styles.sectionLabel} ${styles.sectionLabelClip}`}>
                        <FileText size={11} /> {filePath} · {formatNumber(nodes.length)}
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
                                : t('memory:list.sectionFallback')}
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
                    {t('memory:paneEmpty')}
                  </span>
                </div>
              )}
            </>
          )}
        </div>

        {/* ── Bottom: agent file system tree ── */}
        <div className={styles.bottomPane}>
          <div className={styles.sectionLabel}>
            {t('memory:files.title')}
            <span className={styles.infoTip} aria-label={t('memory:files.aboutAria')}>
              <Info size={11} />
              <span className={styles.infoTooltip} role="tooltip">
                <Trans
                  ns="memory"
                  i18nKey="files.indexingTooltip"
                  components={{ 1: <strong />, 2: <br />, 3: <br /> }}
                />
              </span>
            </span>
          </div>
          <div className={styles.tree}>
            {renderFolder(fileTree, 0)}
          </div>
          <span className={styles.hint}>
            {t('memory:files.hint')}
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
