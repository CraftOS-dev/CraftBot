import { createSlice, PayloadAction } from '@reduxjs/toolkit'
import type {
  FileItem,
  FileListResponse,
  FileReadResponse,
  FileCreateResponse,
  FileDeleteResponse,
  FileRenameResponse,
  FileBatchDeleteResponse,
  FileUploadResponse,
} from '../../types'
import { register } from '../socket/messageRegistry'
import i18n from '../../i18n/config'

export const FILE_PAGE_SIZE = 50

/** A workspace path's folder ("" for the root), with "/" separators. */
export function workspaceParentPath(path: string): string {
  const normalized = normalizePath(path)
  const slash = normalized.lastIndexOf('/')
  return slash === -1 ? '' : normalized.slice(0, slash)
}

function normalizePath(path: string): string {
  return path.replace(/\\/g, '/').replace(/^\/+|\/+$/g, '')
}

// Workspace requests this tab sent, by requestId (the backend echoes it).
// Replies to other tabs' requests are ignored: their changes reach this tab
// through `workspace_files` refreshes instead, so one tab's navigation or
// paste never overwrites another's listing (plan WS-4.6, W3/W4). A
// 'reply-only' request (peeking into another folder) resolves its promise
// without touching the listing.
const ownRequests = new Map<string, 'apply' | 'reply-only'>()

export function trackWorkspaceRequest(requestId: string, mode: 'apply' | 'reply-only'): void {
  ownRequests.set(requestId, mode)
}

export function releaseWorkspaceRequest(requestId: string): void {
  ownRequests.delete(requestId)
}

// Replies without an id (e.g. the HTTP upload broadcast) still apply; the
// appliers check the folder themselves.
function appliesHere(data: unknown): boolean {
  const requestId = (data as { requestId?: unknown } | null)?.requestId
  return typeof requestId !== 'string' || ownRequests.get(requestId) === 'apply'
}

const sortFiles = (a: FileItem, b: FileItem): number => {
  if (a.type !== b.type) return a.type === 'directory' ? -1 : 1
  return a.name.toLowerCase().localeCompare(b.name.toLowerCase())
}

interface WorkspaceSliceState {
  currentDirectory: string
  files: FileItem[]
  loading: boolean
  loadingMore: boolean
  error: string | null
  selectedFile: FileItem | null
  fileContent: string | null
  fileIsBinary: boolean
  total: number
  hasMore: boolean
  offset: number
  search: string
}

const initialState: WorkspaceSliceState = {
  currentDirectory: '',
  files: [],
  loading: false,
  loadingMore: false,
  error: null,
  selectedFile: null,
  fileContent: null,
  fileIsBinary: false,
  total: 0,
  hasMore: false,
  offset: 0,
  search: '',
}

const workspaceSlice = createSlice({
  name: 'workspace',
  initialState,
  reducers: {
    // ── Optimistic / pre-request transitions ──────────────────────────────
    startNavigate(state, action: PayloadAction<string>) {
      state.currentDirectory = action.payload
      state.loading = true
      state.error = null
      state.files = []
      state.offset = 0
      state.hasMore = false
      state.total = 0
      state.search = ''
    },
    startRefresh(state) {
      state.loading = true
      state.error = null
      state.files = []
      state.offset = 0
      state.hasMore = false
      state.total = 0
    },
    startLoadMore(state) {
      state.loadingMore = true
    },
    startSearch(state, action: PayloadAction<string>) {
      state.search = action.payload
      state.loading = true
      state.files = []
      state.offset = 0
      state.hasMore = false
      state.total = 0
    },
    setError(state, action: PayloadAction<string | null>) {
      state.error = action.payload
      state.loading = false
      state.loadingMore = false
    },
    selectFile(state, action: PayloadAction<FileItem | null>) {
      state.selectedFile = action.payload
      state.fileContent = null
      state.fileIsBinary = false
    },
    // ── Inbound-response appliers (called from registry handlers) ─────────
    applyList(state, action: PayloadAction<FileListResponse>) {
      const d = action.payload
      // A late reply for a folder this tab has since left.
      if (typeof d.directory === 'string' && normalizePath(d.directory) !== normalizePath(state.currentDirectory)) return
      const isLoadMore = d.offset > 0
      const incoming = d.files || []
      state.files = isLoadMore ? [...state.files, ...incoming] : incoming
      state.total = d.total ?? 0
      state.hasMore = d.hasMore ?? false
      state.offset = (d.offset ?? 0) + incoming.length
      state.error = d.success ? null : d.error || i18n.t('nav:workspace.failedToListFiles')
      state.loading = false
      state.loadingMore = false
    },
    applyRead(state, action: PayloadAction<FileReadResponse>) {
      const path = action.payload.path
      if (path && normalizePath(path) !== normalizePath(state.selectedFile?.path ?? '')) return
      state.fileContent = action.payload.content ?? null
      state.fileIsBinary = action.payload.isBinary || false
    },
    applyCreate(state, action: PayloadAction<FileCreateResponse>) {
      const r = action.payload
      if (r.success && r.fileInfo && workspaceParentPath(r.fileInfo.path) === normalizePath(state.currentDirectory)) {
        state.files = [...state.files, r.fileInfo].sort(sortFiles)
      }
    },
    applyDelete(state, action: PayloadAction<FileDeleteResponse>) {
      const r = action.payload
      if (r.success) {
        state.files = state.files.filter(f => f.path !== r.path)
        if (state.selectedFile?.path === r.path) state.selectedFile = null
      }
    },
    applyRename(state, action: PayloadAction<FileRenameResponse>) {
      const r = action.payload
      if (r.success && r.fileInfo) {
        state.files = state.files
          .map(f => (f.path === r.oldPath ? r.fileInfo! : f))
          .sort(sortFiles)
        if (state.selectedFile?.path === r.oldPath) state.selectedFile = r.fileInfo
      }
    },
    applyBatchDelete(state, action: PayloadAction<FileBatchDeleteResponse>) {
      const r = action.payload
      const deletedPaths = new Set(r.results.filter(x => x.success).map(x => x.path))
      state.files = state.files.filter(f => !deletedPaths.has(f.path))
      if (state.selectedFile && deletedPaths.has(state.selectedFile.path)) {
        state.selectedFile = null
      }
    },
    applyUpload(state, action: PayloadAction<FileUploadResponse>) {
      const r = action.payload
      if (r.success && r.fileInfo && workspaceParentPath(r.fileInfo.path) === normalizePath(state.currentDirectory)) {
        const exists = state.files.some(f => f.path === r.fileInfo!.path)
        if (exists) {
          state.files = state.files.map(f =>
            f.path === r.fileInfo!.path ? r.fileInfo! : f,
          )
        } else {
          state.files = [...state.files, r.fileInfo].sort(sortFiles)
        }
      }
    },
  },
})

export const {
  startNavigate,
  startRefresh,
  startLoadMore,
  startSearch,
  setError,
  selectFile,
  applyList,
  applyRead,
  applyCreate,
  applyDelete,
  applyRename,
  applyBatchDelete,
  applyUpload,
} = workspaceSlice.actions

export default workspaceSlice.reducer

// --- inbound message handlers --------------------------------------------
// Note: file_write, file_move, file_copy, file_download don't alter slice
// state — they're pure request/response and the context's Promise correlation
// layer resolves them.

register('file_list', (data, dispatch) => {
  if (appliesHere(data)) dispatch(applyList(data as FileListResponse))
})

register('file_read', (data, dispatch) => {
  if (appliesHere(data)) dispatch(applyRead(data as FileReadResponse))
})

register('file_create', (data, dispatch) => {
  if (appliesHere(data)) dispatch(applyCreate(data as FileCreateResponse))
})

register('file_delete', (data, dispatch) => {
  if (appliesHere(data)) dispatch(applyDelete(data as FileDeleteResponse))
})

register('file_rename', (data, dispatch) => {
  if (appliesHere(data)) dispatch(applyRename(data as FileRenameResponse))
})

register('file_batch_delete', (data, dispatch) => {
  if (appliesHere(data)) dispatch(applyBatchDelete(data as FileBatchDeleteResponse))
})

register('file_upload', (data, dispatch) => {
  dispatch(applyUpload(data as FileUploadResponse))
})
