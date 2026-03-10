import React, { createContext, useContext, useState, useCallback, useEffect, useRef, ReactNode } from 'react'
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

// ─────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────

interface WorkspaceState {
  currentDirectory: string
  files: FileItem[]
  loading: boolean
  error: string | null
  selectedFile: FileItem | null
  fileContent: string | null
  fileIsBinary: boolean
  connected: boolean
}

interface PendingOperation<T> {
  resolve: (value: T) => void
  reject: (error: Error) => void
}

interface WorkspaceContextType extends WorkspaceState {
  // Navigation
  navigateTo: (directory: string) => Promise<void>
  refresh: () => Promise<void>
  selectFile: (file: FileItem | null) => void
  listDirectory: (directory: string) => Promise<FileItem[]>

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

const defaultState: WorkspaceState = {
  currentDirectory: '',
  files: [],
  loading: false,
  error: null,
  selectedFile: null,
  fileContent: null,
  fileIsBinary: false,
  connected: false,
}

// ─────────────────────────────────────────────────────────────────────
// Context
// ─────────────────────────────────────────────────────────────────────

const WorkspaceContext = createContext<WorkspaceContextType | undefined>(undefined)

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<WorkspaceState>(defaultState)
  const wsRef = useRef<WebSocket | null>(null)
  const pendingOpsRef = useRef<Map<string, PendingOperation<unknown>>>(new Map())
  const reconnectTimeoutRef = useRef<number | null>(null)
  const isConnectingRef = useRef<boolean>(false)
  const hasInitialLoadRef = useRef<boolean>(false)

  // ─────────────────────────────────────────────────────────────────────
  // Message Handling
  // ─────────────────────────────────────────────────────────────────────

  const handleMessage = useCallback((msg: WSMessage) => {
    const resolvePending = <T,>(key: string, data: T) => {
      const pending = pendingOpsRef.current.get(key)
      if (pending) {
        pending.resolve(data)
        pendingOpsRef.current.delete(key)
      }
    }

    switch (msg.type) {
      case 'file_list': {
        const data = msg.data as unknown as FileListResponse
        setState(prev => ({
          ...prev,
          files: data.files || [],
          loading: false,
          error: data.success ? null : data.error || 'Failed to list files',
        }))
        resolvePending('file_list', data)
        break
      }

      case 'file_read': {
        const data = msg.data as unknown as FileReadResponse
        setState(prev => ({
          ...prev,
          fileContent: data.content,
          fileIsBinary: data.isBinary || false,
        }))
        resolvePending('file_read', data)
        break
      }

      case 'file_write': {
        const data = msg.data as unknown as FileWriteResponse
        resolvePending('file_write', data)
        break
      }

      case 'file_create': {
        const data = msg.data as unknown as FileCreateResponse
        if (data.success && data.fileInfo) {
          setState(prev => ({
            ...prev,
            files: [...prev.files, data.fileInfo!].sort((a, b) => {
              if (a.type !== b.type) return a.type === 'directory' ? -1 : 1
              return a.name.toLowerCase().localeCompare(b.name.toLowerCase())
            }),
          }))
        }
        resolvePending('file_create', data)
        break
      }

      case 'file_delete': {
        const data = msg.data as unknown as FileDeleteResponse
        if (data.success) {
          setState(prev => ({
            ...prev,
            files: prev.files.filter(f => f.path !== data.path),
            selectedFile: prev.selectedFile?.path === data.path ? null : prev.selectedFile,
          }))
        }
        resolvePending('file_delete', data)
        break
      }

      case 'file_rename': {
        const data = msg.data as unknown as FileRenameResponse
        if (data.success && data.fileInfo) {
          setState(prev => ({
            ...prev,
            files: prev.files.map(f =>
              f.path === data.oldPath ? data.fileInfo! : f
            ).sort((a, b) => {
              if (a.type !== b.type) return a.type === 'directory' ? -1 : 1
              return a.name.toLowerCase().localeCompare(b.name.toLowerCase())
            }),
            selectedFile: prev.selectedFile?.path === data.oldPath ? data.fileInfo! : prev.selectedFile,
          }))
        }
        resolvePending('file_rename', data)
        break
      }

      case 'file_batch_delete': {
        const data = msg.data as unknown as FileBatchDeleteResponse
        const deletedPaths = new Set(
          data.results.filter(r => r.success).map(r => r.path)
        )
        setState(prev => ({
          ...prev,
          files: prev.files.filter(f => !deletedPaths.has(f.path)),
          selectedFile: prev.selectedFile && deletedPaths.has(prev.selectedFile.path)
            ? null
            : prev.selectedFile,
        }))
        resolvePending('file_batch_delete', data)
        break
      }

      case 'file_move': {
        const data = msg.data as unknown as FileMoveResponse
        resolvePending('file_move', data)
        break
      }

      case 'file_copy': {
        const data = msg.data as unknown as FileCopyResponse
        resolvePending('file_copy', data)
        break
      }

      case 'file_upload': {
        const data = msg.data as unknown as FileUploadResponse
        if (data.success && data.fileInfo) {
          setState(prev => {
            const exists = prev.files.some(f => f.path === data.fileInfo!.path)
            if (exists) {
              return {
                ...prev,
                files: prev.files.map(f =>
                  f.path === data.fileInfo!.path ? data.fileInfo! : f
                ),
              }
            }
            return {
              ...prev,
              files: [...prev.files, data.fileInfo!].sort((a, b) => {
                if (a.type !== b.type) return a.type === 'directory' ? -1 : 1
                return a.name.toLowerCase().localeCompare(b.name.toLowerCase())
              }),
            }
          })
        }
        resolvePending('file_upload', data)
        break
      }

      case 'file_download': {
        const data = msg.data as unknown as FileDownloadResponse
        resolvePending('file_download', data)
        break
      }
    }
  }, [])

  // ─────────────────────────────────────────────────────────────────────
  // WebSocket Connection (reuse existing or create minimal)
  // ─────────────────────────────────────────────────────────────────────

  const connect = useCallback(() => {
    if (isConnectingRef.current || wsRef.current?.readyState === WebSocket.OPEN) {
      return
    }
    isConnectingRef.current = true

    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${window.location.host}/ws`

    const ws = new WebSocket(wsUrl)
    wsRef.current = ws

    ws.onopen = () => {
      console.log('[Workspace] WebSocket connected')
      isConnectingRef.current = false
      setState(prev => ({ ...prev, connected: true }))
    }

    ws.onmessage = (event) => {
      try {
        const msg: WSMessage = JSON.parse(event.data)
        // Only handle file-related messages
        if (msg.type.startsWith('file_')) {
          handleMessage(msg)
        }
      } catch (err) {
        console.error('[Workspace] Failed to parse message:', err)
      }
    }

    ws.onclose = () => {
      console.log('[Workspace] WebSocket disconnected')
      isConnectingRef.current = false
      setState(prev => ({ ...prev, connected: false }))

      // Reconnect after delay
      reconnectTimeoutRef.current = window.setTimeout(() => {
        connect()
      }, 2000)
    }

    ws.onerror = (err) => {
      console.error('[Workspace] WebSocket error:', err)
      isConnectingRef.current = false
    }
  }, [handleMessage])

  // ─────────────────────────────────────────────────────────────────────
  // Send Operation Helper
  // ─────────────────────────────────────────────────────────────────────

  const sendOperation = useCallback(<T,>(
    type: string,
    data: Record<string, unknown>,
    key: string
  ): Promise<T> => {
    return new Promise((resolve, reject) => {
      if (wsRef.current?.readyState !== WebSocket.OPEN) {
        reject(new Error('WebSocket not connected'))
        return
      }

      pendingOpsRef.current.set(key, {
        resolve: resolve as (value: unknown) => void,
        reject,
      })

      wsRef.current.send(JSON.stringify({ type, ...data }))

      // Timeout after 30 seconds
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
    setState(prev => ({ ...prev, loading: true, error: null, currentDirectory: directory }))
    try {
      await sendOperation<FileListResponse>('file_list', { directory }, 'file_list')
    } catch (error) {
      setState(prev => ({
        ...prev,
        loading: false,
        error: error instanceof Error ? error.message : 'Failed to navigate',
      }))
    }
  }, [sendOperation])

  const refresh = useCallback(async () => {
    await navigateTo(state.currentDirectory)
  }, [navigateTo, state.currentDirectory])

  const selectFile = useCallback((file: FileItem | null) => {
    setState(prev => ({
      ...prev,
      selectedFile: file,
      fileContent: null,
      fileIsBinary: false,
    }))
  }, [])

  const listDirectory = useCallback(async (directory: string): Promise<FileItem[]> => {
    // If requesting current directory, return cached files
    if (directory === state.currentDirectory) {
      return state.files
    }
    // Otherwise fetch from server (using unique key to avoid conflicts)
    const key = `file_list_${Date.now()}`
    const response = await sendOperation<FileListResponse>('file_list', { directory }, key)
    return response.success ? response.files : []
  }, [sendOperation, state.currentDirectory, state.files])

  const readFile = useCallback(async (path: string): Promise<FileReadResponse> => {
    return sendOperation<FileReadResponse>('file_read', { path }, 'file_read')
  }, [sendOperation])

  const writeFile = useCallback(async (path: string, content: string): Promise<FileWriteResponse> => {
    return sendOperation<FileWriteResponse>('file_write', { path, content }, 'file_write')
  }, [sendOperation])

  const createFile = useCallback(async (path: string, fileType: 'file' | 'directory'): Promise<FileCreateResponse> => {
    return sendOperation<FileCreateResponse>('file_create', { path, fileType }, 'file_create')
  }, [sendOperation])

  const deleteFile = useCallback(async (path: string): Promise<FileDeleteResponse> => {
    return sendOperation<FileDeleteResponse>('file_delete', { path }, 'file_delete')
  }, [sendOperation])

  const renameFile = useCallback(async (oldPath: string, newName: string): Promise<FileRenameResponse> => {
    return sendOperation<FileRenameResponse>('file_rename', { oldPath, newName }, 'file_rename')
  }, [sendOperation])

  const batchDelete = useCallback(async (paths: string[]): Promise<FileBatchDeleteResponse> => {
    return sendOperation<FileBatchDeleteResponse>('file_batch_delete', { paths }, 'file_batch_delete')
  }, [sendOperation])

  const moveFile = useCallback(async (srcPath: string, destPath: string): Promise<FileMoveResponse> => {
    return sendOperation<FileMoveResponse>('file_move', { srcPath, destPath }, 'file_move')
  }, [sendOperation])

  const copyFile = useCallback(async (srcPath: string, destPath: string): Promise<FileCopyResponse> => {
    return sendOperation<FileCopyResponse>('file_copy', { srcPath, destPath }, 'file_copy')
  }, [sendOperation])

  const uploadFile = useCallback(async (path: string, file: File): Promise<FileUploadResponse> => {
    return new Promise((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = async () => {
        try {
          const base64 = (reader.result as string).split(',')[1]
          const response = await sendOperation<FileUploadResponse>(
            'file_upload',
            { path, content: base64 },
            'file_upload'
          )
          resolve(response)
        } catch (error) {
          reject(error)
        }
      }
      reader.onerror = () => reject(new Error('Failed to read file'))
      reader.readAsDataURL(file)
    })
  }, [sendOperation])

  const downloadFile = useCallback(async (path: string): Promise<Blob | null> => {
    try {
      const response = await sendOperation<FileDownloadResponse>(
        'file_download',
        { path },
        'file_download'
      )
      if (response.success && response.content) {
        // Decode base64
        const byteString = atob(response.content)
        const bytes = new Uint8Array(byteString.length)
        for (let i = 0; i < byteString.length; i++) {
          bytes[i] = byteString.charCodeAt(i)
        }
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
    connect()

    return () => {
      isConnectingRef.current = false
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current)
      }
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
      }
    }
  }, [connect])

  // Load initial file list when connected
  useEffect(() => {
    if (state.connected && !hasInitialLoadRef.current) {
      hasInitialLoadRef.current = true
      navigateTo('')
    }
  }, [state.connected, navigateTo])

  // ─────────────────────────────────────────────────────────────────────
  // Render
  // ─────────────────────────────────────────────────────────────────────

  return (
    <WorkspaceContext.Provider
      value={{
        ...state,
        navigateTo,
        refresh,
        selectFile,
        listDirectory,
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
