import { createSlice, PayloadAction } from '@reduxjs/toolkit'
import { register } from '../socket/messageRegistry'

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
  // Palette group for node colour — driven by the entity a node is about,
  // so a map with several entities shows several colours (community would
  // collapse to one). Falls back to community if absent.
  colorGroup?: number
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
  },
})

export const {
  setEnabled,
  setItems,
  setGraph,
  setGraphLoading,
  setIndexedFiles,
  setIndexCandidates,
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
