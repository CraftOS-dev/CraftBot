import { createSlice, PayloadAction } from '@reduxjs/toolkit'
import { register } from '../socket/messageRegistry'
import type { InboundHandler } from '../socket/messageRegistry'

export interface MemoryItem {
  id: string
  timestamp: string
  category: string
  content: string
  // Content with [[wikilinks]] stripped, for rendering.
  displayContent?: string
  entities?: string[]
  superseded?: boolean
  raw: string
}

// ── Memory graph (the panel's brain view) ──────────────────────────────

export interface MemoryGraphNode {
  id: string
  kind: 'entity' | 'item' | 'file'
  label: string
  size?: number
  community: number
  category?: string
  timestamp?: string
  superseded?: boolean
  // Memory nodes carry their origin: distilled MEMORY.md item ("memory")
  // or a section chunk of an indexed file ("file", read-only).
  source?: 'memory' | 'file'
  file?: string
  section?: string
}

export interface MemoryGraphEdge {
  source: string
  target: string
  // memory→entity links carry a state: "confirmed" (recorded by the
  // entity-indexer) or "pending" (a deterministic provisional guess, shown
  // distinctly until the entity-indexer reviews it). Structural file→chunk
  // edges carry no status.
  status?: 'confirmed' | 'pending'
}

export interface MemoryGraphStats {
  entity_count?: number
  item_count?: number
  file_memory_count?: number
  file_count?: number
  edge_count?: number
  pending_link_count?: number
  community_count?: number
  superseded_count?: number
  unprocessed_events?: number
  memory_item_count?: number
}

export interface MemoryGraph {
  nodes: MemoryGraphNode[]
  edges: MemoryGraphEdge[]
  stats: MemoryGraphStats
}

export interface IndexedFileInfo {
  path: string
  core: boolean
  exists: boolean
  chunk_count: number
  indexed_at: string
}

export interface IndexCandidate {
  path: string
  size: number
}

/** Daily auto-processing schedule as the Settings → Memory form edits it. */
export interface MemorySchedule {
  time: string // "HH:MM"
  threshold: number
}

interface MemorySettingsState {
  enabled: boolean
  items: MemoryItem[]
  hasLoadedMode: boolean
  hasLoadedItems: boolean
  graph: MemoryGraph | null
  graphLoading: boolean
  indexedFiles: IndexedFileInfo[]
  indexCandidates: IndexCandidate[]
  hasLoadedFiles: boolean
  schedule: MemorySchedule | null
  thresholdMax: number
  unprocessedEvents: number
}

const initialState: MemorySettingsState = {
  enabled: true,
  items: [],
  hasLoadedMode: false,
  hasLoadedItems: false,
  graph: null,
  graphLoading: false,
  indexedFiles: [],
  indexCandidates: [],
  hasLoadedFiles: false,
  schedule: null,
  thresholdMax: 100,
  unprocessedEvents: 0,
}

// Backend items arrive snake_cased; normalise the optional graph fields.
interface RawMemoryItem extends MemoryItem {
  display_content?: string
}

function normalizeItem(item: RawMemoryItem): MemoryItem {
  return {
    id: item.id,
    timestamp: item.timestamp,
    category: item.category,
    content: item.content,
    displayContent: item.display_content ?? item.content,
    entities: item.entities ?? [],
    superseded: item.superseded ?? false,
    raw: item.raw,
  }
}

const memorySettingsSlice = createSlice({
  name: 'memorySettings',
  initialState,
  reducers: {
    setEnabled(state, action: PayloadAction<boolean>) {
      state.enabled = action.payload
      state.hasLoadedMode = true
    },
    setItems(state, action: PayloadAction<MemoryItem[]>) {
      state.items = action.payload
      state.hasLoadedItems = true
    },
    setGraph(state, action: PayloadAction<MemoryGraph | null>) {
      state.graph = action.payload
      state.graphLoading = false
    },
    setGraphLoading(state, action: PayloadAction<boolean>) {
      state.graphLoading = action.payload
    },
    setIndexedFiles(state, action: PayloadAction<IndexedFileInfo[]>) {
      state.indexedFiles = action.payload
      state.hasLoadedFiles = true
    },
    setIndexCandidates(state, action: PayloadAction<IndexCandidate[]>) {
      state.indexCandidates = action.payload
    },
    setSchedule(
      state,
      action: PayloadAction<{ schedule: MemorySchedule; thresholdMax?: number; unprocessedEvents?: number }>,
    ) {
      state.schedule = action.payload.schedule
      if (action.payload.thresholdMax !== undefined) state.thresholdMax = action.payload.thresholdMax
      if (action.payload.unprocessedEvents !== undefined) state.unprocessedEvents = action.payload.unprocessedEvents
    },
    // A reset rewrites MEMORY.md and rebuilds the index: the cached items and
    // graph are gone. The views using them refetch via `resource_changed`.
    clearMemoryContent(state) {
      state.items = []
      state.graph = null
    },
  },
})

export const {
  setEnabled,
  setItems,
  setGraph,
  setGraphLoading,
  setIndexedFiles,
  setIndexCandidates,
  setSchedule,
  clearMemoryContent,
} = memorySettingsSlice.actions
export default memorySettingsSlice.reducer

register('memory_mode_get', (data, dispatch) => {
  const d = data as { success: boolean; enabled: boolean }
  if (d.success) dispatch(setEnabled(d.enabled))
})

register('memory_mode_set', (data, dispatch) => {
  const d = data as { success: boolean; enabled: boolean }
  if (d.success) dispatch(setEnabled(d.enabled))
})

register('memory_items_get', (data, dispatch) => {
  const d = data as { success: boolean; items: RawMemoryItem[] }
  if (d.success) dispatch(setItems((d.items || []).map(normalizeItem)))
})

register('memory_graph_get', (data, dispatch) => {
  const d = data as { success: boolean; graph?: MemoryGraph }
  if (d.success && d.graph) {
    dispatch(setGraph(d.graph))
  } else {
    dispatch(setGraphLoading(false))
  }
})

register('memory_indexed_files_get', (data, dispatch) => {
  const d = data as {
    success: boolean
    files?: IndexedFileInfo[]
    candidates?: IndexCandidate[]
  }
  if (d.success) {
    dispatch(setIndexedFiles(d.files || []))
    dispatch(setIndexCandidates(d.candidates || []))
  }
})

register('memory_indexed_files_set', (data, dispatch) => {
  const d = data as { success: boolean; files?: IndexedFileInfo[] }
  if (d.success && d.files) dispatch(setIndexedFiles(d.files))
})

// Per-file add/remove carry the full file list, candidates, AND the fresh
// graph so a single serial round-trip updates everything for THAT file. The
// backend piggy-backs the graph here (rather than the panel sending its own
// memory_graph_get, which would queue behind other still-pending index jobs),
// so each file lands in the graph the moment it finishes indexing.
const applyIndexFileMutation: InboundHandler = (data, dispatch) => {
  const d = data as {
    success: boolean
    files?: IndexedFileInfo[]
    candidates?: IndexCandidate[]
    graph?: MemoryGraph
  }
  if (!d.success) return
  if (d.files) dispatch(setIndexedFiles(d.files))
  if (d.candidates) dispatch(setIndexCandidates(d.candidates))
  if (d.graph) dispatch(setGraph(d.graph))
}

register('memory_index_file_add', applyIndexFileMutation)
register('memory_index_file_remove', applyIndexFileMutation)

register('memory_schedule_get', (data, dispatch) => {
  const d = data as {
    success: boolean
    schedule?: { hour: number; minute: number }
    threshold?: number
    threshold_max?: number
    unprocessed?: number
  }
  if (!d.success || !d.schedule) return
  const pad = (n: number) => String(n).padStart(2, '0')
  dispatch(setSchedule({
    schedule: { time: `${pad(d.schedule.hour)}:${pad(d.schedule.minute)}`, threshold: d.threshold ?? 25 },
    thresholdMax: d.threshold_max,
    unprocessedEvents: d.unprocessed,
  }))
})

register('memory_reset', (data, dispatch) => {
  const d = data as { success: boolean }
  if (d.success) dispatch(clearMemoryContent())
})
