import { createContext, useContext, useCallback, useEffect, useRef, ReactNode } from 'react'
import type {
  FileItem,
  FileListResponse,
  FileReadResponse,
  FileWriteResponse,
  FileCreateResponse,
  FileDeleteResponse,
  FileRenameResponse,
  FileBatchDeleteResponse,
  FileMoveResponse,
  FileCopyResponse,
  FileUploadResponse,
  FileDownloadResponse,
  WSMessage,
} from '../types'
import { getSocketClient } from '../store/socket/socketInstance'
import { useAppDispatch, useAppSelector } from '../store/hooks'
import {
  startNavigate,
  startRefresh,
  startLoadMore,
  startSearch,
  setError as setWorkspaceError,
  selectFile as selectFileAction,
  FILE_PAGE_SIZE,
} from '../store/slices/workspaceSlice'
import {
  selectWorkspaceCurrentDirectory,
  selectWorkspaceFiles,
  selectWorkspaceLoading,
  selectWorkspaceLoadingMore,
  selectWorkspaceError,
  selectWorkspaceSelectedFile,
  selectWorkspaceFileContent,
  selectWorkspaceFileIsBinary,
  selectWorkspaceTotal,
  selectWorkspaceHasMore,
  selectWorkspaceOffset,
  selectWorkspaceSearch,
} from '../store/selectors/workspace'
import { selectConnected } from '../store/selectors/connection'

const client = getSocketClient()

// ─────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────

interface PendingOperation<T> {
  resolve: (value: T) => void
  reject: (error: Error) => void
}

interface WorkspaceContextType {
  // Slice-backed read state (selectors fed in by the provider):
  currentDirectory: string
  files: FileItem[]
  loading: boolean
  loadingMore: boolean
  error: string | null
  selectedFile: FileItem | null
  fileContent: string | null
  fileIsBinary: boolean
  connected: boolean
  total: number
  hasMore: boolean
  offset: number
  search: string

  // Navigation
  navigateTo: (directory: string) => Promise<void>
  refresh: () => Promise<void>
  selectFile: (file: FileItem | null) => void
  listDirectory: (directory: string) => Promise<FileItem[]>
  loadMore: () => Promise<void>
  setSearch: (query: string) => void

  // File operations
  readFile: (path: string) => Promise<FileReadResponse>
  writeFile: (path: string, content: string) => Promise<FileWriteResponse>
  createFile: (path: string, type: 'file' | 'directory') => Promise<FileCreateResponse>
  deleteFile: (path: string) => Promise<FileDeleteResponse>
  renameFile: (oldPath: string, newName: string) => Promise<FileRenameResponse>
  batchDelete: (paths: string[]) => Promise<FileBatchDeleteResponse>
  moveFile: (srcPath: string, destPath: string) => Promise<FileMoveResponse>
  copyFile: (srcPath: string, destPath: string) => Promise<FileCopyResponse>
  uploadFile: (path: string, file: File) => Promise<FileUploadResponse>
  downloadFile: (path: string) => Promise<Blob | null>
}

const WorkspaceContext = createContext<WorkspaceContextType | undefined>(undefined)

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const dispatch = useAppDispatch()
  const pendingOpsRef = useRef<Map<string, PendingOperation<unknown>>>(new Map())
  const hasInitialLoadRef = useRef<boolean>(false)

  // Slice-backed state. workspaceSlice owns all file/directory state; this
  // provider just routes requests and resolves the Promise side of each
  // request/response operation.
  const currentDirectory = useAppSelector(selectWorkspaceCurrentDirectory)
  const files = useAppSelector(selectWorkspaceFiles)
  const loading = useAppSelector(selectWorkspaceLoading)
  const loadingMore = useAppSelector(selectWorkspaceLoadingMore)
  const error = useAppSelector(selectWorkspaceError)
  const selectedFile = useAppSelector(selectWorkspaceSelectedFile)
  const fileContent = useAppSelector(selectWorkspaceFileContent)
  const fileIsBinary = useAppSelector(selectWorkspaceFileIsBinary)
  const total = useAppSelector(selectWorkspaceTotal)
  const hasMore = useAppSelector(selectWorkspaceHasMore)
  const offset = useAppSelector(selectWorkspaceOffset)
  const search = useAppSelector(selectWorkspaceSearch)
  const connected = useAppSelector(selectConnected)

  // ─────────────────────────────────────────────────────────────────────
  // Promise correlation
  // ─────────────────────────────────────────────────────────────────────
  //
  // The slice handles state updates from inbound messages, but the legacy
  // request/response Promise API still needs response correlation. We keep
  // a per-type pending map here. Responses arrive via onAnyMessage below;
  // the same response also fires the slice handlers via the registry.

  const sendOperation = useCallback(<T,>(
    type: string,
    data: Record<string, unknown>,
    key: string,
  ): Promise<T> => {
    return new Promise((resolve, reject) => {
      if (!client.isConnected) {
        reject(new Error('WebSocket not connected'))
        return
      }
      pendingOpsRef.current.set(key, {
        resolve: resolve as (value: unknown) => void,
        reject,
      })
      client.send(type, data)
      setTimeout(() => {
        const pending = pendingOpsRef.current.get(key)
        if (pending) {
          pending.reject(new Error('Operation timed out'))
          pendingOpsRef.current.delete(key)
        }
      }, 30000)
    })
  }, [])

  // ─────────────────────────────────────────────────────────────────────
  // Public API
  // ─────────────────────────────────────────────────────────────────────

  const navigateTo = useCallback(async (directory: string) => {
    dispatch(startNavigate(directory))
    try {
      await sendOperation<FileListResponse>(
        'file_list', { directory, offset: 0, limit: FILE_PAGE_SIZE }, 'file_list',
      )
    } catch (e) {
      dispatch(setWorkspaceError(e instanceof Error ? e.message : 'Failed to navigate'))
    }
  }, [dispatch, sendOperation])

  const refresh = useCallback(async () => {
    dispatch(startRefresh())
    try {
      await sendOperation<FileListResponse>(
        'file_list',
        { directory: currentDirectory, offset: 0, limit: FILE_PAGE_SIZE, search },
        'file_list',
      )
    } catch (e) {
      dispatch(setWorkspaceError(e instanceof Error ? e.message : 'Failed to refresh'))
    }
  }, [dispatch, sendOperation, currentDirectory, search])

  const loadMore = useCallback(async () => {
    if (!hasMore || loadingMore) return
    dispatch(startLoadMore())
    try {
      await sendOperation<FileListResponse>(
        'file_list',
        { directory: currentDirectory, offset, limit: FILE_PAGE_SIZE, search },
        'file_list',
      )
    } catch {
      dispatch(setWorkspaceError(null))
    }
  }, [dispatch, sendOperation, hasMore, loadingMore, currentDirectory, offset, search])

  const setSearch = useCallback((query: string) => {
    dispatch(startSearch(query))
    sendOperation<FileListResponse>(
      'file_list',
      { directory: currentDirectory, offset: 0, limit: FILE_PAGE_SIZE, search: query },
      'file_list',
    ).catch(() => {
      dispatch(setWorkspaceError(null))
    })
  }, [dispatch, sendOperation, currentDirectory])

  const selectFile = useCallback((file: FileItem | null) => {
    dispatch(selectFileAction(file))
  }, [dispatch])

  const listDirectory = useCallback(async (directory: string): Promise<FileItem[]> => {
    if (directory === currentDirectory) return files
    const key = `file_list_${Date.now()}`
    const response = await sendOperation<FileListResponse>('file_list', { directory }, key)
    return response.success ? response.files : []
  }, [sendOperation, currentDirectory, files])

  const readFile = useCallback((path: string) =>
    sendOperation<FileReadResponse>('file_read', { path }, 'file_read'),
  [sendOperation])

  const writeFile = useCallback((path: string, content: string) =>
    sendOperation<FileWriteResponse>('file_write', { path, content }, 'file_write'),
  [sendOperation])

  const createFile = useCallback((path: string, fileType: 'file' | 'directory') =>
    sendOperation<FileCreateResponse>('file_create', { path, fileType }, 'file_create'),
  [sendOperation])

  const deleteFile = useCallback((path: string) =>
    sendOperation<FileDeleteResponse>('file_delete', { path }, 'file_delete'),
  [sendOperation])

  const renameFile = useCallback((oldPath: string, newName: string) =>
    sendOperation<FileRenameResponse>('file_rename', { oldPath, newName }, 'file_rename'),
  [sendOperation])

  const batchDelete = useCallback((paths: string[]) =>
    sendOperation<FileBatchDeleteResponse>('file_batch_delete', { paths }, 'file_batch_delete'),
  [sendOperation])

  const moveFile = useCallback((srcPath: string, destPath: string) =>
    sendOperation<FileMoveResponse>('file_move', { srcPath, destPath }, 'file_move'),
  [sendOperation])

  const copyFile = useCallback((srcPath: string, destPath: string) =>
    sendOperation<FileCopyResponse>('file_copy', { srcPath, destPath }, 'file_copy'),
  [sendOperation])

  const uploadFile = useCallback(async (path: string, file: File): Promise<FileUploadResponse> => {
    return new Promise((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = async () => {
        try {
          const base64 = (reader.result as string).split(',')[1]
          const response = await sendOperation<FileUploadResponse>(
            'file_upload', { path, content: base64 }, 'file_upload',
          )
          resolve(response)
        } catch (e) {
          reject(e)
        }
      }
      reader.onerror = () => reject(new Error('Failed to read file'))
      reader.readAsDataURL(file)
    })
  }, [sendOperation])

  const downloadFile = useCallback(async (path: string): Promise<Blob | null> => {
    try {
      const response = await sendOperation<FileDownloadResponse>(
        'file_download', { path }, 'file_download',
      )
      if (response.success && response.content) {
        const byteString = atob(response.content)
        const bytes = new Uint8Array(byteString.length)
        for (let i = 0; i < byteString.length; i++) bytes[i] = byteString.charCodeAt(i)
        return new Blob([bytes])
      }
      return null
    } catch {
      return null
    }
  }, [sendOperation])

  // ─────────────────────────────────────────────────────────────────────
  // Effects
  // ─────────────────────────────────────────────────────────────────────

  useEffect(() => {
    // Resolve the Promise side of any pending file_* request when its
    // response arrives. The slice handler (via the registry) updates state
    // in parallel.
    const unsub = client.onAnyMessage((msg) => {
      if (!msg.type.startsWith('file_')) return
      const pending = pendingOpsRef.current.get(msg.type)
      if (pending) {
        pending.resolve((msg as WSMessage).data)
        pendingOpsRef.current.delete(msg.type)
      }
    })
    return unsub
  }, [])

  useEffect(() => {
    if (connected && !hasInitialLoadRef.current) {
      hasInitialLoadRef.current = true
      navigateTo('')
    }
  }, [connected, navigateTo])

  return (
    <WorkspaceContext.Provider
      value={{
        currentDirectory,
        files,
        loading,
        loadingMore,
        error,
        selectedFile,
        fileContent,
        fileIsBinary,
        connected,
        total,
        hasMore,
        offset,
        search,
        navigateTo,
        refresh,
        selectFile,
        listDirectory,
        loadMore,
        setSearch,
        readFile,
        writeFile,
        createFile,
        deleteFile,
        renameFile,
        batchDelete,
        moveFile,
        copyFile,
        uploadFile,
        downloadFile,
      }}
    >
      {children}
    </WorkspaceContext.Provider>
  )
}

export function useWorkspace() {
  const context = useContext(WorkspaceContext)
  if (!context) {
    throw new Error('useWorkspace must be used within a WorkspaceProvider')
  }
  return context
}
