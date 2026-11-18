/**
 * Memory: what the agent remembers, without the browser's force graph.
 *
 * Tab "Memories and links": a searchable list of every node (conversation
 * memories newest first, then entities, files and file sections) beside the
 * selected node's detail and its neighbours as a tree (Right expands, Enter
 * goes to a neighbour). 1, 2 and 3 toggle the kinds shown, 4 hides the
 * default files, as the browser's header chips do. a adds, e edits and d
 * deletes conversation memories (memory_item_add / update / remove).
 *
 * Tab "Indexed files": the agent file system as a checkbox tree; Space
 * indexes or stops indexing a file (memory_index_file_add / remove).
 * `[` and `]` switch tabs. Data comes from the browser's memory resources.
 */
import { memo, useEffect, useMemo, useRef, useState } from 'react'
import { Box, Text } from 'ink'
import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'
import { useAppDispatch, useAppSelector, send } from '../state/hooks'
import {
  selectMemoryEnabled,
  selectMemoryGraph,
  selectMemoryHasLoadedFiles,
  selectMemoryIndexCandidates,
  selectMemoryIndexedFiles,
  selectMemoryItems,
} from '../../../browser/frontend/src/store/selectors/memorySettings'
import type { MemoryGraphNode } from '../../../browser/frontend/src/store/slices/memorySettingsSlice'
import { selectUiState } from '../../../browser/frontend/src/store/selectors/ui'
import { setUiState } from '../../../browser/frontend/src/store/slices/uiSlice'
import { UI_STATE } from '../../../browser/frontend/src/store/uiState'
import { RESOURCES, resourceSync, useResource } from '../../../browser/frontend/src/store/resources'
import { onInboundMessage } from '../../../browser/frontend/src/store/socket/socketMiddleware'
import { Frame, bodyRows } from '../ui/Frame'
import { useScreen, useScreenKeys } from './context'
import { clampList, listKey, LIST_START, type ListState } from '../ui/list'
import { TextField, fieldKey } from '../ui/TextField'
import { ConfirmLine, confirmKey, type PendingConfirm } from '../ui/Confirm'
import * as TB from '../input/TextBuffer'
import { glyphs, ink } from '../theme/theme'
import { padEnd, padStart, truncate, width as cells, wrap } from '../text/width'
import { fitRow, seg, type Row } from './dataRows'
import { RowView } from './dataRowView'
import {
  adjacency,
  buildFileTree,
  CATEGORY_OPTIONS,
  countKinds,
  flattenFileTree,
  itemOfNode,
  kindVisible,
  matchesQuery,
  neighbourTree,
  sortNodes,
  withoutCoreFiles,
  type FileTreeRow,
  type TreeRow,
} from './dataMemory'

type T = TFunction<'screensData'>
type Tab = 'nodes' | 'files'
type Pane = 'list' | 'tree'

const TWO_PANES_AT = 72
const NOTICE_MS = 5000
const CONTENT_LINES = 6

interface Notice {
  text: string
  tone: 'info' | 'error'
}

interface ItemForm {
  itemId: string | null
  category: string
  content: TB.Buffer
  superseded: boolean
  field: number
}

function kindGlyph(node: MemoryGraphNode): { mark: string; color?: string } {
  const g = glyphs()
  if (node.kind === 'entity') return { mark: g.idle, color: ink.brand }
  if (node.kind === 'file') return { mark: g.artifact, color: ink.success }
  if (node.source === 'file') return { mark: g.prompt, color: ink.muted }
  return { mark: g.bullet, color: ink.info }
}

function kindLabel(t: T, node: MemoryGraphNode): string {
  if (node.kind === 'entity') return t('memory.kind.entity')
  if (node.kind === 'file') return t('memory.kind.file')
  return node.source === 'file' ? t('memory.kind.fileMemory') : t('memory.kind.memory')
}

function categoryLabel(t: T, category: string | undefined): string {
  const c = category || 'fact'
  return CATEGORY_OPTIONS.includes(c) ? t(`memory.category.${c}`) : c
}

/** The short tag at the right of a list or tree row. */
function nodeMeta(t: T, node: MemoryGraphNode): string {
  if (node.superseded) return t('memory.superseded')
  if (node.kind === 'entity') return t('memory.mentions', { count: node.size ?? 0 })
  if (node.kind === 'file') return t('memory.sections', { count: node.size ?? 0 })
  if (node.source === 'file') return node.file ?? ''
  return categoryLabel(t, node.category)
}

function oneLine(text: string): string {
  return text.replace(/\s+/g, ' ').trim()
}

export function MemoryScreen() {
  const { t, i18n } = useTranslation('screensData')
  const dispatch = useAppDispatch()
  const { columns, rows, setTextFocus } = useScreen()
  useResource(RESOURCES.memoryGraph)
  useResource(RESOURCES.memoryItems)
  useResource(RESOURCES.memoryIndexedFiles)
  useResource(RESOURCES.memoryMode)

  const enabled = useAppSelector(selectMemoryEnabled)
  const graph = useAppSelector(selectMemoryGraph)
  const items = useAppSelector(selectMemoryItems)
  const indexedFiles = useAppSelector(selectMemoryIndexedFiles)
  const candidates = useAppSelector(selectMemoryIndexCandidates)
  const filesLoaded = useAppSelector(selectMemoryHasLoadedFiles)
  const showMemories = useAppSelector(s => selectUiState(s, UI_STATE.memory.showMemories)) as boolean
  const showEntities = useAppSelector(s => selectUiState(s, UI_STATE.memory.showEntities)) as boolean
  const showFiles = useAppSelector(s => selectUiState(s, UI_STATE.memory.showFiles)) as boolean
  const hideCore = useAppSelector(s => selectUiState(s, UI_STATE.memory.hideCoreFiles)) as boolean
  const expandedFolderList = useAppSelector(s => selectUiState(s, UI_STATE.memory.expandedFolders)) as string[]

  const [tab, setTab] = useState<Tab>('nodes')
  const [pane, setPane] = useState<Pane>('list')
  const [detailOpen, setDetailOpen] = useState(false)
  const [search, setSearch] = useState<TB.Buffer>(TB.EMPTY)
  const [searching, setSearching] = useState(false)
  const [list, setList] = useState<ListState>(LIST_START)
  const [focusId, setFocusId] = useState<string | null>(null)
  const [tree, setTree] = useState<{ root: string; open: Set<string>; list: ListState }>({ root: '', open: new Set(), list: LIST_START })
  const [fileList, setFileList] = useState<ListState>(LIST_START)
  const [form, setForm] = useState<ItemForm | null>(null)
  const [confirm, setConfirm] = useState<PendingConfirm | null>(null)
  const [notice, setNotice] = useState<Notice | null>(null)
  const [pendingPaths, setPendingPaths] = useState<Set<string>>(new Set())
  const itemRequests = useRef(0)

  const say = (text: string, tone: Notice['tone'] = 'info') => setNotice({ text, tone })
  useEffect(() => {
    if (!notice) return
    const timer = setTimeout(() => setNotice(null), NOTICE_MS)
    return () => clearTimeout(timer)
  }, [notice])

  // Results of our own requests: item edits and per-file index jobs.
  const tRef = useRef(t)
  tRef.current = t
  useEffect(
    () =>
      onInboundMessage(msg => {
        const tr = tRef.current
        const d = (msg.data ?? {}) as { success?: boolean; error?: string; path?: string; rejected?: { path: string; reason: string }[] }
        if (msg.type === 'memory_item_add' || msg.type === 'memory_item_update' || msg.type === 'memory_item_remove') {
          if (itemRequests.current <= 0) return
          itemRequests.current -= 1
          if (!d.success) setNotice({ text: tr('memory.failed', { error: d.error || tr('common.unknownError') }), tone: 'error' })
          else setNotice({ text: msg.type === 'memory_item_remove' ? tr('memory.deleted') : tr('memory.saved'), tone: 'info' })
          return
        }
        if (msg.type === 'memory_index_file_add' || msg.type === 'memory_index_file_remove') {
          if (d.path) {
            setPendingPaths(prev => {
              if (!prev.has(d.path as string)) return prev
              const next = new Set(prev)
              next.delete(d.path as string)
              return next
            })
          }
          if (!d.success) setNotice({ text: tr('memory.failed', { error: d.error || tr('common.unknownError') }), tone: 'error' })
          else if (d.rejected?.length) setNotice({ text: tr('memory.files.skipped', d.rejected[0]), tone: 'error' })
        }
      }),
    [],
  )

  const toggles = { memories: showMemories, entities: showEntities, files: showFiles }
  const displayGraph = useMemo(() => withoutCoreFiles(graph, indexedFiles, hideCore), [graph, indexedFiles, hideCore])
  const counts = useMemo(() => countKinds(displayGraph), [displayGraph])
  const nodesById = useMemo(() => new Map((displayGraph?.nodes ?? []).map(n => [n.id, n])), [displayGraph])
  const adj = useMemo(() => adjacency(displayGraph), [displayGraph])
  const itemsById = useMemo(() => new Map(items.map(i => [`i:${i.id}`, i])), [items])
  const query = search.text.trim()
  const sorted = useMemo(() => sortNodes(displayGraph?.nodes ?? []), [displayGraph])
  const listNodes = useMemo(
    () => sorted.filter(n => kindVisible(n, toggles) && matchesQuery(n, query, itemsById.get(n.id) ?? null)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [sorted, showMemories, showEntities, showFiles, query, itemsById],
  )

  const twoPanes = columns >= TWO_PANES_AT
  const body = bodyRows(rows)
  const headerRows = 3
  const contentRows = Math.max(3, body - headerRows - 1)
  const listWidth = twoPanes ? Math.max(30, Math.min(56, Math.floor(columns * 0.42))) : columns - 1
  const detailWidth = twoPanes ? Math.max(20, columns - listWidth - 3) : columns - 1

  const view = clampList(list, listNodes.length, contentRows)
  const cursorNode = listNodes[view.index] ?? null
  const detailNode = (focusId ? nodesById.get(focusId) : null) ?? cursorNode
  const detailItem = itemOfNode(detailNode, items)
  const showDetail = twoPanes || detailOpen

  // The neighbour tree of the shown node; its expansion resets per node.
  const treeState = tree.root === detailNode?.id ? tree : { root: detailNode?.id ?? '', open: new Set<string>(), list: LIST_START }
  const g = glyphs()
  const treeRows: TreeRow[] = useMemo(
    () =>
      detailNode
        ? neighbourTree(detailNode.id, adj, nodesById, treeState.open, 40, {
            tee: `${g.tee} `,
            last: `${g.last} `,
            pipe: `${g.vbar} `,
            space: '  ',
          })
        : [],
    [detailNode, adj, nodesById, treeState.open, g.rule, g.vbar],
  )

  const fileRoot = useMemo(() => buildFileTree(indexedFiles, candidates), [indexedFiles, candidates])
  const expandedFolders = useMemo(() => new Set(expandedFolderList), [expandedFolderList])
  const fileRows = useMemo(() => flattenFileTree(fileRoot, expandedFolders), [fileRoot, expandedFolders])
  const fileView = clampList(fileList, fileRows.length, contentRows)

  // ── detail pane rows ──
  const dateFmt = useMemo(() => {
    try {
      return new Intl.DateTimeFormat(i18n.language, { dateStyle: 'medium', timeStyle: 'short' })
    } catch {
      return new Intl.DateTimeFormat('en', { dateStyle: 'medium', timeStyle: 'short' })
    }
  }, [i18n.language])

  const infoRows: Row[] = useMemo(() => {
    if (!detailNode) return [[seg(t('memory.noSelection'), ink.muted)]]
    const out: Row[] = []
    const { mark, color } = kindGlyph(detailNode)
    const head: Row = [seg(`${mark} `, color), seg(kindLabel(t, detailNode), undefined, true)]
    if (detailNode.kind === 'item' && detailNode.source !== 'file') head.push(seg(` ${g.bullet} ${categoryLabel(t, detailNode.category)}`, ink.muted))
    if (detailNode.superseded) head.push(seg(` ${g.bullet} ${t('memory.superseded')}`, ink.warn))
    out.push(head)
    const text = detailNode.kind === 'item' ? detailItem?.displayContent || detailNode.label : detailNode.label
    const lines = wrap(text.replace(/\r/g, ''), Math.max(10, detailWidth)).flatMap(l => l.split('\n'))
    const shown = lines.slice(0, CONTENT_LINES)
    if (lines.length > CONTENT_LINES) shown[CONTENT_LINES - 1] = truncate(`${shown[CONTENT_LINES - 1]} ...`, detailWidth)
    for (const line of shown) out.push([seg(line, detailNode.superseded ? ink.muted : undefined, detailNode.kind !== 'item')])
    const meta = (name: string, value: string): Row => [seg(padEnd(name, 9), ink.muted), seg(value)]
    if (detailNode.kind === 'item' && detailNode.source !== 'file') {
      if (detailNode.timestamp) {
        const when = Date.parse(detailNode.timestamp)
        out.push(meta(t('memory.meta.saved'), Number.isFinite(when) ? dateFmt.format(when) : detailNode.timestamp))
      }
      if (detailItem?.entities?.length) out.push(meta(t('memory.meta.links'), detailItem.entities.join(', ')))
    } else if (detailNode.kind === 'item') {
      out.push(meta(t('memory.meta.file'), detailNode.file ?? ''))
      if (detailNode.section) out.push(meta(t('memory.meta.section'), oneLine(detailNode.section)))
      out.push([seg(t('memory.readOnly'), ink.muted)])
    } else if (detailNode.kind === 'entity') {
      out.push([seg(t('memory.mentions', { count: detailNode.size ?? treeRows.length }), ink.muted)])
    } else {
      out.push([seg(t('memory.sections', { count: detailNode.size ?? treeRows.length }), ink.muted)])
    }
    const neighbours = (adj.get(detailNode.id) ?? []).filter(id => nodesById.has(id)).length
    out.push([seg(neighbours ? t('memory.connected', { count: neighbours }) : t('memory.noNeighbours'), ink.muted, true)])
    return out
  }, [detailNode, detailItem, detailWidth, t, g.bullet, dateFmt, adj, nodesById, treeRows.length])

  const treeHeight = Math.max(1, contentRows - infoRows.length)
  const treeView = clampList(treeState.list, treeRows.length, treeHeight)

  // ── actions ──
  const setToggle = (which: 'showMemories' | 'showEntities' | 'showFiles' | 'hideCoreFiles', value: boolean) => {
    dispatch(setUiState(UI_STATE.memory[which], value))
    setList(LIST_START)
  }

  const goTo = (id: string) => {
    const index = listNodes.findIndex(n => n.id === id)
    if (index >= 0) {
      setList(clampList({ index, top: Math.max(0, index - Math.floor(contentRows / 2)) }, listNodes.length, contentRows))
      setFocusId(null)
    } else {
      setFocusId(id)
    }
    setTree({ root: id, open: new Set(), list: LIST_START })
  }

  const openForm = (itemId: string | null) => {
    const item = itemId ? items.find(i => i.id === itemId) : null
    setForm({
      itemId,
      category: item?.category || 'fact',
      content: item ? TB.fromText(item.content) : TB.EMPTY,
      superseded: item?.superseded ?? false,
      field: 1,
    })
    setTextFocus(true)
  }

  const closeForm = () => {
    setForm(null)
    setTextFocus(false)
  }

  const saveForm = () => {
    if (!form) return
    const content = form.content.text.trim()
    if (!content) {
      say(t('memory.form.empty'), 'error')
      return
    }
    itemRequests.current += 1
    if (form.itemId) {
      send('memory_item_update', { itemId: form.itemId, category: form.category, content, superseded: form.superseded })
    } else {
      send('memory_item_add', { category: form.category, content })
    }
    closeForm()
  }

  const toggleIndex = (row: FileTreeRow) => {
    if (row.type !== 'file' || row.file.core || pendingPaths.has(row.file.path)) return
    setPendingPaths(prev => new Set(prev).add(row.file.path))
    send(row.file.indexed ? 'memory_index_file_remove' : 'memory_index_file_add', { path: row.file.path })
  }

  const setFolder = (path: string, open: boolean) => {
    const next = new Set(expandedFolders)
    if (open) next.add(path)
    else next.delete(path)
    dispatch(setUiState(UI_STATE.memory.expandedFolders, Array.from(next)))
  }

  const refresh = () => resourceSync.handleChanged('memory')

  // ── keys ──
  useScreenKeys((input, key) => {
    if (confirmKey(confirm, input, key, () => setConfirm(null))) return true

    if (form) {
      const fields = form.itemId ? 3 : 2
      if (key.escape) {
        closeForm()
        return true
      }
      if (key.return) {
        saveForm()
        return true
      }
      if (key.tab || key.downArrow || key.upArrow) {
        const step = (key.tab && key.shift) || key.upArrow ? -1 : 1
        setForm({ ...form, field: (form.field + step + fields) % fields })
        return true
      }
      if (form.field === 0) {
        if (key.leftArrow || key.rightArrow || input === ' ') {
          const options = CATEGORY_OPTIONS.includes(form.category) ? CATEGORY_OPTIONS : [...CATEGORY_OPTIONS, form.category]
          const step = key.leftArrow ? -1 : 1
          const index = (options.indexOf(form.category) + step + options.length) % options.length
          setForm({ ...form, category: options[index] })
        }
        return true
      }
      if (form.field === 2) {
        if (input === ' ') setForm({ ...form, superseded: !form.superseded })
        return true
      }
      const next = fieldKey(form.content, input, key)
      if (next) setForm({ ...form, content: next })
      return true
    }

    if (searching) {
      if (key.escape || key.return) {
        setSearching(false)
        setTextFocus(false)
        if (key.escape) setSearch(TB.EMPTY)
        return true
      }
      if (key.upArrow || key.downArrow) {
        const moved = listKey(view, '', key, listNodes.length, contentRows)
        if (moved) setList(moved)
        return true
      }
      const next = fieldKey(search, input, key)
      if (next) {
        setSearch(next)
        setList(LIST_START)
        setFocusId(null)
      }
      return true
    }

    if (input === '[' || input === ']') {
      setTab(tab === 'nodes' ? 'files' : 'nodes')
      return true
    }
    if (input === 'r') {
      refresh()
      return true
    }

    if (tab === 'files') {
      const row = fileRows[fileView.index]
      const moved = listKey(fileView, input, key, fileRows.length, contentRows)
      if (moved) {
        setFileList(moved)
        return true
      }
      if (!row) return false
      if (row.type === 'folder') {
        if (key.return || input === ' ') setFolder(row.path, !row.expanded)
        else if (key.rightArrow || input === 'l') setFolder(row.path, true)
        else if (key.leftArrow || input === 'h') setFolder(row.path, false)
        else return false
        return true
      }
      if (key.return || input === ' ') {
        toggleIndex(row)
        return true
      }
      return false
    }

    // Nodes tab.
    if (input === '1' || input === '2' || input === '3' || input === '4') {
      if (input === '1') setToggle('showMemories', !showMemories)
      if (input === '2') setToggle('showEntities', !showEntities)
      if (input === '3') setToggle('showFiles', !showFiles)
      if (input === '4') setToggle('hideCoreFiles', !hideCore)
      return true
    }
    if (input === '/') {
      setSearching(true)
      setTextFocus(true)
      setPane('list')
      setDetailOpen(false)
      return true
    }
    if (input === 'a') {
      openForm(null)
      return true
    }
    if (input === 'e') {
      if (detailItem) openForm(detailItem.id)
      else if (detailNode) say(t('memory.notEditable'), 'error')
      return true
    }
    if (input === 'd') {
      if (detailItem) {
        const target = detailItem
        setConfirm({
          message: t('memory.confirmDelete'),
          onConfirm: () => {
            itemRequests.current += 1
            send('memory_item_remove', { itemId: target.id })
            setFocusId(null)
          },
        })
      } else if (detailNode) {
        say(t('memory.notEditable'), 'error')
      }
      return true
    }

    const treeFocused = showDetail && pane === 'tree'
    if (treeFocused) {
      const row = treeRows[treeView.index]
      const moved = listKey(treeView, input, key, treeRows.length, treeHeight)
      if (moved) {
        setTree({ ...treeState, list: moved })
        return true
      }
      if (key.tab || key.escape) {
        setPane('list')
        if (!twoPanes && key.escape) setDetailOpen(false)
        return true
      }
      if (!row) {
        if (key.leftArrow || input === 'h') {
          setPane('list')
          if (!twoPanes) setDetailOpen(false)
          return true
        }
        return false
      }
      if ((key.return || input === 'l' || key.rightArrow) && row.id === null) return true
      if (key.rightArrow || input === 'l') {
        if (row.childCount > 0 && !row.expanded) setTree({ ...treeState, open: new Set(treeState.open).add(row.key) })
        return true
      }
      if (key.leftArrow || input === 'h') {
        if (row.expanded) {
          const open = new Set(treeState.open)
          open.delete(row.key)
          setTree({ ...treeState, open })
        } else if (row.depth > 0) {
          const parentKey = row.key.slice(0, row.key.lastIndexOf('>'))
          const parentIndex = treeRows.findIndex(r => r.key === parentKey)
          if (parentIndex >= 0) setTree({ ...treeState, list: clampList({ ...treeView, index: parentIndex }, treeRows.length, treeHeight) })
        } else {
          setPane('list')
          if (!twoPanes) setDetailOpen(false)
        }
        return true
      }
      if (key.return && row.id) {
        goTo(row.id)
        return true
      }
      return false
    }

    const moved = listKey(view, input, key, listNodes.length, contentRows)
    if (moved) {
      setList(moved)
      setFocusId(null)
      return true
    }
    if (key.tab || key.return || key.rightArrow || input === 'l') {
      if (!detailNode) return true
      if (!twoPanes) setDetailOpen(true)
      setPane('tree')
      return true
    }
    if (key.escape && (query || focusId)) {
      setSearch(TB.EMPTY)
      setFocusId(null)
      return true
    }
    return false
  })

  // ── render ──
  const hints = form
    ? [{ keys: 'Enter', label: t('common.save') }, { keys: 'Esc', label: t('common.cancel') }]
    : searching
      ? [{ keys: 'Enter', label: t('common.open') }, { keys: 'Esc', label: t('common.cancel') }]
      : tab === 'files'
        ? [
            { keys: 'Space', label: t('memory.hints.index') },
            { keys: 'Enter', label: t('memory.hints.folder') },
            { keys: '[ ]', label: t('common.tab') },
            { keys: 'r', label: t('common.refresh') },
            { keys: 'Esc', label: t('common.back') },
          ]
        : showDetail && pane === 'tree'
          ? [
              { keys: 'Enter', label: t('memory.hints.goTo') },
              { keys: 'Right', label: t('memory.hints.expand') },
              { keys: 'e', label: t('common.edit') },
              { keys: 'd', label: t('common.delete') },
              { keys: 'Tab', label: t('common.pane') },
              { keys: 'Esc', label: t('common.back') },
            ]
          : [
              { keys: '/', label: t('common.search') },
              { keys: '1-4', label: t('memory.hints.kinds') },
              { keys: 'Tab', label: t('memory.hints.tree') },
              { keys: 'a', label: t('common.add') },
              { keys: 'e', label: t('common.edit') },
              { keys: 'd', label: t('common.delete') },
              { keys: '[ ]', label: t('common.tab') },
              { keys: 'Esc', label: t('common.back') },
            ]


  const tabRow: Row = [
    seg(tab === 'nodes' ? `${g.pointer} ` : '  ', ink.focus),
    seg(t('memory.tabs.nodes'), tab === 'nodes' ? ink.focus : ink.muted, tab === 'nodes'),
    seg(`   ${tab === 'files' ? `${g.pointer} ` : '  '}`, ink.focus),
    seg(t('memory.tabs.files'), tab === 'files' ? ink.focus : ink.muted, tab === 'files'),
  ]

  const toggle = (keyName: string, on: boolean, text: string): Row => [
    seg(`${keyName} `, ink.muted),
    seg(`${on ? g.checked : g.unchecked} `, on ? ink.brand : ink.muted),
    seg(text, on ? undefined : ink.muted),
    seg('   '),
  ]
  const toggleRow: Row = [
    ...toggle('1', showMemories, t('memory.toggle.memories', { count: counts.memories })),
    ...toggle('2', showEntities, t('memory.toggle.entities', { count: counts.entities })),
    ...toggle('3', showFiles, t('memory.toggle.files', { count: counts.files })),
    ...toggle('4', hideCore, t('memory.toggle.hideDefault')),
  ]

  const footerLine = confirm ? (
    <ConfirmLine pending={confirm} columns={columns} hint={t('common.confirm')} />
  ) : notice ? (
    <Text color={notice.tone === 'error' ? ink.error : ink.success}>{truncate(notice.text, columns - 1)}</Text>
  ) : (
    <Text> </Text>
  )

  return (
    <Frame title={t('memory.title')} aside={enabled ? undefined : t('memory.off')} hints={hints} columns={columns} rows={rows}>
      <Box flexDirection="column" height={body}>
        <RowView row={fitRow(tabRow, columns - 1)} />
        {form ? (
          <FormView t={t} form={form} columns={columns} height={body - 2} />
        ) : tab === 'files' ? (
          <>
            <Text color={ink.muted}>{truncate(t('memory.files.hint'), columns - 1)}</Text>
            <Text> </Text>
            <FilesView t={t} rows={fileRows} view={fileView} height={contentRows} width={columns - 1} pending={pendingPaths} loaded={filesLoaded} />
          </>
        ) : (
          <>
            <RowView row={fitRow(toggleRow, columns - 1)} />
            {searching || query ? (
              <TextField label="/" buffer={search} focused={searching} width={columns - 1} placeholder={t('memory.searchPlaceholder')} />
            ) : (
              <Text color={ink.muted}>{truncate(t('memory.searchHint'), columns - 1)}</Text>
            )}
            {!graph ? (
              <Box height={contentRows}>
                <Text color={ink.muted}>{t('memory.loading')}</Text>
              </Box>
            ) : (displayGraph?.nodes.length ?? 0) === 0 ? (
              <Box height={contentRows}>
                <Text color={ink.muted}>{truncate(t('memory.empty'), columns * 2)}</Text>
              </Box>
            ) : (
              <Box flexDirection="row" height={contentRows}>
                {!showDetail || twoPanes ? (
                  <Box flexDirection="column" width={listWidth}>
                    {listNodes.length === 0 ? (
                      <Text color={ink.muted}>{t('memory.noMatches')}</Text>
                    ) : (
                      listNodes.slice(view.top, view.top + contentRows).map((node, i) => {
                        const index = view.top + i
                        const selected = index === view.index
                        return (
                          <NodeRow
                            key={node.id}
                            t={t}
                            node={node}
                            width={twoPanes ? listWidth - 1 : listWidth}
                            selected={selected}
                            focused={selected && pane === 'list' && !focusId}
                          />
                        )
                      })
                    )}
                  </Box>
                ) : null}
                {twoPanes ? (
                  <Box flexDirection="column" width={2}>
                    {Array.from({ length: contentRows }, (_, i) => (
                      <Text key={i} color={ink.muted}>{`${g.vbar} `}</Text>
                    ))}
                  </Box>
                ) : null}
                {showDetail ? (
                  <Box flexDirection="column" width={detailWidth}>
                    {infoRows.map((row, i) => (
                      <RowView key={`i${i}`} row={fitRow(row, detailWidth)} />
                    ))}
                    {treeRows.slice(treeView.top, treeView.top + treeHeight).map((row, i) => {
                      const index = treeView.top + i
                      return (
                        <TreeLine
                          key={row.key}
                          t={t}
                          row={row}
                          node={row.id ? nodesById.get(row.id) ?? null : null}
                          width={detailWidth}
                          selected={pane === 'tree' && index === treeView.index}
                        />
                      )
                    })}
                  </Box>
                ) : null}
              </Box>
            )}
          </>
        )}
        {footerLine}
      </Box>
    </Frame>
  )
}

// Memoized: moving the cursor re-renders two list rows, not all of them.
const NodeRow = memo(function NodeRow({ t, node, width, selected, focused }: { t: T; node: MemoryGraphNode; width: number; selected: boolean; focused: boolean }) {
  const g = glyphs()
  const { mark, color } = kindGlyph(node)
  const meta = truncate(nodeMeta(t, node), Math.min(16, Math.max(6, Math.floor(width / 3))))
  const labelWidth = Math.max(4, width - 4 - cells(meta) - 2)
  const row: Row = [
    seg(selected ? `${g.pointer} ` : '  ', focused ? ink.focus : ink.muted),
    seg(`${mark} `, color),
    seg(padEnd(oneLine(node.label), labelWidth), focused ? ink.focus : node.superseded ? ink.muted : undefined, selected),
    seg(`  ${meta}`, ink.muted),
  ]
  return <RowView row={fitRow(row, width)} />
})

const TreeLine = memo(function TreeLine({ t, row, node, width, selected }: { t: T; row: TreeRow; node: MemoryGraphNode | null; width: number; selected: boolean }) {
  const g = glyphs()
  const pointer = seg(selected ? `${g.pointer} ` : '  ', ink.focus)
  if (!node) {
    return <RowView row={fitRow([pointer, seg(row.prefix, ink.muted), seg(t('memory.moreNeighbours', { count: row.more ?? 0 }), ink.muted)], width)} />
  }
  const { mark, color } = kindGlyph(node)
  const meta = truncate(nodeMeta(t, node), 14)
  // "+" can expand, "-" is expanded.
  const fold = row.childCount > 0 ? (row.expanded ? '-' : '+') : ' '
  const labelWidth = Math.max(4, width - 2 - cells(row.prefix) - 4 - cells(meta) - 2)
  const out: Row = [
    pointer,
    seg(row.prefix, ink.muted),
    seg(`${fold} `, row.childCount > 0 ? ink.brand : ink.muted),
    seg(`${mark} `, color),
    seg(padEnd(oneLine(node.label), labelWidth), selected ? ink.focus : undefined, selected),
    seg(`  ${meta}`, ink.muted),
  ]
  return <RowView row={fitRow(out, width)} />
})

function FilesView({
  t,
  rows,
  view,
  height,
  width,
  pending,
  loaded,
}: {
  t: T
  rows: FileTreeRow[]
  view: ListState
  height: number
  width: number
  pending: Set<string>
  loaded: boolean
}) {
  const g = glyphs()
  if (rows.length === 0) {
    return (
      <Box height={height}>
        <Text color={ink.muted}>{loaded ? t('memory.files.empty') : t('memory.loading')}</Text>
      </Box>
    )
  }
  const open = g.expanded
  return (
    <Box flexDirection="column" height={height}>
      {rows.slice(view.top, view.top + height).map((row, i) => {
        const selected = view.top + i === view.index
        const pointer = seg(selected ? `${g.pointer} ` : '  ', ink.focus)
        const indent = seg('  '.repeat(row.depth))
        if (row.type === 'folder') {
          const out: Row = [
            pointer,
            indent,
            seg(`${row.expanded ? open : g.chunk} `, ink.muted),
            seg(`${row.name}/`, selected ? ink.focus : undefined, selected),
            seg(`  ${row.indexed}/${row.total}`, ink.muted),
          ]
          return <RowView key={`d:${row.path}`} row={fitRow(out, width)} />
        }
        const f = row.file
        const busy = pending.has(f.path)
        const box = busy ? g.running : f.indexed ? g.checked : g.unchecked
        const meta = f.indexed
          ? f.exists
            ? t('memory.files.chunks', { count: f.chunks })
            : t('memory.files.missing')
          : t('memory.files.size', { value: (f.size / 1024).toFixed(1) })
        const state = busy ? t('memory.files.indexing') : f.core ? t('memory.files.always') : ''
        // Fixed columns: name, then sections or size, then always / working.
        const metaWidth = 14
        const stateWidth = 9
        const nameWidth = Math.max(6, width - 4 - row.depth * 2 - metaWidth - stateWidth - 1)
        const out: Row = [
          pointer,
          indent,
          seg(`${box} `, busy ? ink.brand : f.indexed ? ink.success : ink.muted),
          seg(padEnd(f.name, nameWidth), selected ? ink.focus : f.indexed ? undefined : ink.muted, selected),
          seg(` ${padStart(meta, metaWidth - 1)}`, !f.exists ? ink.warn : ink.muted),
          seg(`  ${padEnd(state, stateWidth - 2)}`, busy ? ink.brand : ink.muted),
        ]
        return <RowView key={`f:${f.path}`} row={fitRow(out, width)} />
      })}
    </Box>
  )
}

function FormView({ t, form, columns, height }: { t: T; form: ItemForm; columns: number; height: number }) {
  const g = glyphs()
  const labelWidth = 10
  const fieldWidth = Math.max(10, columns - labelWidth - 3)
  const marker = (field: number) => seg(form.field === field ? `${g.pointer} ` : '  ', ink.focus)
  return (
    <Box flexDirection="column" height={height}>
      <Text> </Text>
      <Text bold>{form.itemId ? t('memory.form.editTitle') : t('memory.form.addTitle')}</Text>
      <Text> </Text>
      <RowView
        row={fitRow(
          [
            marker(0),
            seg(padEnd(t('memory.form.category'), labelWidth), form.field === 0 ? ink.focus : ink.muted),
            seg('< ', ink.muted),
            seg(categoryLabel(t, form.category), undefined, true),
            seg(' >', ink.muted),
          ],
          columns - 1,
        )}
      />
      <Box>
        <RowView row={[marker(1), seg(padEnd(t('memory.form.content'), labelWidth), form.field === 1 ? ink.focus : ink.muted)]} />
        <TextField buffer={form.content} focused={form.field === 1} width={fieldWidth} placeholder={t('memory.form.contentPlaceholder')} />
      </Box>
      {form.itemId ? (
        <RowView
          row={fitRow(
            [
              marker(2),
              seg(padEnd('', labelWidth)),
              seg(`${form.superseded ? g.checked : g.unchecked} `, form.superseded ? ink.warn : ink.muted),
              seg(t('memory.form.superseded'), form.field === 2 ? ink.focus : undefined),
            ],
            columns - 1,
          )}
        />
      ) : null}
      <Text> </Text>
      <Text color={ink.muted}>{truncate(t('memory.form.entitiesHint'), columns - 1)}</Text>
      <Text color={ink.muted}>{truncate(t('memory.form.hint'), columns - 1)}</Text>
    </Box>
  )
}
