import React, { useState, useEffect, useRef, useCallback } from 'react'
import {
  FolderOpen,
  File,
  FileText,
  FileCode,
  FileImage,
  ChevronRight,
  ChevronDown,
  Upload,
  Download,
  RefreshCw,
  Home,
  MoreVertical,
  Trash2,
  Edit3,
  Copy,
  Scissors,
  Clipboard,
  FolderPlus,
  FilePlus,
  X,
  Check,
  AlertCircle,
  Loader2,
  ArrowLeft,
  Info,
} from 'lucide-react'
import { IconButton, Button, Badge } from '../../components/ui'
import { useWorkspace } from '../../contexts/WorkspaceContext'
import type { FileItem } from '../../types'
import styles from './WorkspacePage.module.css'

// ─────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────

function formatFileSize(bytes?: number): string {
  if (bytes === undefined || bytes === null) return '-'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`
}

function formatDate(timestamp?: number): string {
  if (!timestamp) return '-'
  return new Date(timestamp).toLocaleString()
}

function getFileExtension(name: string): string {
  const parts = name.split('.')
  return parts.length > 1 ? parts.pop()!.toLowerCase() : ''
}

function getFileIcon(item: FileItem) {
  if (item.type === 'directory') {
    return <FolderOpen size={16} />
  }

  const ext = getFileExtension(item.name)
  const codeExtensions = ['js', 'ts', 'tsx', 'jsx', 'py', 'java', 'cpp', 'c', 'h', 'cs', 'go', 'rs', 'rb', 'php', 'swift', 'kt', 'scala', 'vue', 'svelte']
  const imageExtensions = ['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp', 'ico', 'bmp']
  const textExtensions = ['txt', 'md', 'json', 'xml', 'yaml', 'yml', 'toml', 'ini', 'cfg', 'conf', 'log', 'csv']

  if (codeExtensions.includes(ext)) {
    return <FileCode size={16} />
  }
  if (imageExtensions.includes(ext)) {
    return <FileImage size={16} />
  }
  if (textExtensions.includes(ext)) {
    return <FileText size={16} />
  }
  return <File size={16} />
}

function getFileBadgeVariant(item: FileItem): 'default' | 'primary' | 'success' | 'warning' | 'error' | 'info' {
  if (item.type === 'directory') return 'primary'
  const ext = getFileExtension(item.name)
  const codeExtensions = ['js', 'ts', 'tsx', 'jsx', 'py', 'java', 'cpp', 'c', 'go', 'rs']
  if (codeExtensions.includes(ext)) return 'info'
  return 'default'
}

// ─────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────

export function WorkspacePage() {
  const {
    currentDirectory,
    files,
    loading,
    error,
    selectedFile,
    fileContent,
    fileIsBinary,
    navigateTo,
    refresh,
    selectFile,
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
    listDirectory,
  } = useWorkspace()

  // Selection state
  const [selectedFiles, setSelectedFiles] = useState<Set<string>>(new Set())
  const [lastSelectedIndex, setLastSelectedIndex] = useState<number>(-1)

  // UI state
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; file: FileItem } | null>(null)
  const [emptySpaceMenu, setEmptySpaceMenu] = useState<{ x: number; y: number } | null>(null)
  const [showCreateDialog, setShowCreateDialog] = useState<'file' | 'directory' | null>(null)
  const [createName, setCreateName] = useState('')
  const [editingFile, setEditingFile] = useState<string | null>(null)
  const [editName, setEditName] = useState('')
  const [clipboard, setClipboard] = useState<{ action: 'copy' | 'cut'; paths: string[] } | null>(null)
  const [showPreviewContent, setShowPreviewContent] = useState(false)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [mobileShowPreview, setMobileShowPreview] = useState(false)

  // Refs
  const fileInputRef = useRef<HTMLInputElement>(null)
  const createInputRef = useRef<HTMLInputElement>(null)
  const editInputRef = useRef<HTMLInputElement>(null)

  // ─────────────────────────────────────────────────────────────────────
  // Effects
  // ─────────────────────────────────────────────────────────────────────

  // Close context menus on click outside
  useEffect(() => {
    const handleClick = () => {
      setContextMenu(null)
      setEmptySpaceMenu(null)
    }
    window.addEventListener('click', handleClick)
    return () => window.removeEventListener('click', handleClick)
  }, [])

  // Focus create input when dialog opens
  useEffect(() => {
    if (showCreateDialog && createInputRef.current) {
      createInputRef.current.focus()
    }
  }, [showCreateDialog])

  // Focus edit input when editing
  useEffect(() => {
    if (editingFile && editInputRef.current) {
      editInputRef.current.focus()
      editInputRef.current.select()
    }
  }, [editingFile])

  // Clear selection when directory changes
  useEffect(() => {
    setSelectedFiles(new Set())
    setLastSelectedIndex(-1)
  }, [currentDirectory])

  // Load file content when selected
  useEffect(() => {
    if (selectedFile && selectedFile.type === 'file') {
      setPreviewLoading(true)
      readFile(selectedFile.path).finally(() => {
        setPreviewLoading(false)
        setShowPreviewContent(true)
      })
    } else {
      setShowPreviewContent(false)
    }
  }, [selectedFile, readFile])

  // Keep a ref to the latest refresh function so interval always uses current directory
  const refreshRef = useRef(refresh)
  useEffect(() => {
    refreshRef.current = refresh
  }, [refresh])

  // Auto-refresh: refresh on mount (tab switch) and every 30 seconds
  // This preserves the current directory - only refreshes file list in place
  useEffect(() => {
    // Refresh immediately when user switches to Workspace tab
    refreshRef.current()

    // Set up 30-second auto-refresh interval
    const intervalId = setInterval(() => {
      refreshRef.current()
    }, 30000)

    // Cleanup interval on unmount
    return () => {
      clearInterval(intervalId)
    }
  }, [])

  // ─────────────────────────────────────────────────────────────────────
  // Handlers
  // ─────────────────────────────────────────────────────────────────────

  // Check if we're on mobile (touch device or narrow viewport)
  const isMobile = useCallback(() => {
    return window.innerWidth <= 768 || 'ontouchstart' in window
  }, [])

  const handleFileClick = useCallback((file: FileItem, index: number, e: React.MouseEvent) => {
    // Shift + click for range select (only affects checkboxes)
    if (e.shiftKey && lastSelectedIndex >= 0) {
      const start = Math.min(lastSelectedIndex, index)
      const end = Math.max(lastSelectedIndex, index)
      const paths = files.slice(start, end + 1).map(f => f.path)
      setSelectedFiles(new Set(paths))
    }
    // Normal click
    else {
      setLastSelectedIndex(index)
      selectFile(file)

      // On mobile: directories navigate on single tap, files show preview
      // On desktop: just select (double-click to navigate)
      if (isMobile()) {
        if (file.type === 'directory') {
          navigateTo(file.path)
        } else {
          setMobileShowPreview(true)
        }
      }
    }
  }, [files, lastSelectedIndex, selectFile, isMobile, navigateTo])

  const handleMobilePreviewBack = useCallback(() => {
    setMobileShowPreview(false)
  }, [])

  // Show preview panel for a file (used by mobile preview button)
  const handleShowPreview = useCallback((file: FileItem, e: React.MouseEvent) => {
    e.stopPropagation()
    selectFile(file)
    setMobileShowPreview(true)
  }, [selectFile])

  const handleCheckboxChange = useCallback((file: FileItem, index: number, e: React.MouseEvent) => {
    e.stopPropagation()
    setSelectedFiles(prev => {
      const next = new Set(prev)
      if (next.has(file.path)) {
        next.delete(file.path)
      } else {
        next.add(file.path)
      }
      return next
    })
    setLastSelectedIndex(index)
  }, [])

  const handleFileDoubleClick = useCallback((file: FileItem) => {
    if (file.type === 'directory') {
      navigateTo(file.path)
    }
  }, [navigateTo])

  const handleContextMenu = useCallback((e: React.MouseEvent, file: FileItem) => {
    e.preventDefault()
    e.stopPropagation()
    setContextMenu({ x: e.clientX, y: e.clientY, file })
    setEmptySpaceMenu(null)
  }, [])

  const handleEmptySpaceContextMenu = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    setEmptySpaceMenu({ x: e.clientX, y: e.clientY })
    setContextMenu(null)
  }, [])

  const handleNavigateUp = useCallback(() => {
    if (!currentDirectory) return
    const parts = currentDirectory.split('/')
    parts.pop()
    navigateTo(parts.join('/'))
  }, [currentDirectory, navigateTo])

  const handleCreateSubmit = useCallback(async () => {
    if (!createName.trim() || !showCreateDialog) return

    const path = currentDirectory ? `${currentDirectory}/${createName}` : createName
    const result = await createFile(path, showCreateDialog)

    if (result.success) {
      setShowCreateDialog(null)
      setCreateName('')
    }
  }, [createName, showCreateDialog, currentDirectory, createFile])

  const handleRenameSubmit = useCallback(async () => {
    if (!editingFile || !editName.trim()) return

    const result = await renameFile(editingFile, editName)

    if (result.success) {
      setEditingFile(null)
      setEditName('')
    }
  }, [editingFile, editName, renameFile])

  const handleDelete = useCallback(async (paths: string[]) => {
    if (paths.length === 0) return

    const confirmed = window.confirm(
      paths.length === 1
        ? `Delete "${paths[0].split('/').pop()}"?`
        : `Delete ${paths.length} items?`
    )

    if (!confirmed) return

    if (paths.length === 1) {
      await deleteFile(paths[0])
    } else {
      await batchDelete(paths)
    }

    setSelectedFiles(new Set())
  }, [deleteFile, batchDelete])

  const handleCopy = useCallback((paths: string[]) => {
    setClipboard({ action: 'copy', paths })
  }, [])

  const handleCut = useCallback((paths: string[]) => {
    setClipboard({ action: 'cut', paths })
  }, [])

  const handlePaste = useCallback(async (targetDirectory?: string) => {
    if (!clipboard) return

    const destDir = targetDirectory ?? currentDirectory

    // Get existing files in destination directory
    const existingFiles = await listDirectory(destDir)
    const existingNames = new Set(existingFiles.map(f => f.name.toLowerCase()))

    // Helper to generate unique filename
    const getUniqueFileName = (originalName: string): string => {
      if (!existingNames.has(originalName.toLowerCase())) {
        return originalName
      }

      // Split name and extension
      const lastDot = originalName.lastIndexOf('.')
      const hasExtension = lastDot > 0
      const baseName = hasExtension ? originalName.slice(0, lastDot) : originalName
      const extension = hasExtension ? originalName.slice(lastDot) : ''

      // Try adding _copy suffix
      let newName = `${baseName}_copy${extension}`
      let counter = 2

      while (existingNames.has(newName.toLowerCase())) {
        newName = `${baseName}_copy${counter}${extension}`
        counter++
      }

      return newName
    }

    for (const srcPath of clipboard.paths) {
      // Extract filename from source path
      const originalFileName = srcPath.split(/[/\\]/).pop() || ''
      const fileName = getUniqueFileName(originalFileName)
      const destPath = destDir ? `${destDir}/${fileName}` : fileName

      // Add to existing names to handle multiple files with same name
      existingNames.add(fileName.toLowerCase())

      if (clipboard.action === 'copy') {
        await copyFile(srcPath, destPath)
      } else {
        await moveFile(srcPath, destPath)
      }
    }

    await refresh()

    // Clear clipboard only for cut operations (move)
    if (clipboard.action === 'cut') {
      setClipboard(null)
    }
  }, [clipboard, currentDirectory, copyFile, moveFile, refresh, listDirectory])

  const handleUpload = useCallback(async (uploadFiles: FileList) => {
    for (const file of Array.from(uploadFiles)) {
      const path = currentDirectory ? `${currentDirectory}/${file.name}` : file.name
      await uploadFile(path, file)
    }
    await refresh()
  }, [currentDirectory, uploadFile, refresh])

  const handleDownload = useCallback(async (path: string, fileName: string) => {
    const blob = await downloadFile(path)
    if (blob) {
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = fileName
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    }
  }, [downloadFile])

  const handleBatchDownload = useCallback(async () => {
    for (const path of selectedFiles) {
      const file = files.find(f => f.path === path)
      if (file && file.type === 'file') {
        await handleDownload(file.path, file.name)
      }
    }
  }, [selectedFiles, files, handleDownload])

  // ─────────────────────────────────────────────────────────────────────
  // Render Helpers
  // ─────────────────────────────────────────────────────────────────────

  const pathParts = currentDirectory.split('/').filter(Boolean)

  const renderBreadcrumb = () => (
    <div className={styles.breadcrumb}>
      <button
        className={styles.breadcrumbItem}
        onClick={() => navigateTo('')}
      >
        workspace
      </button>
      {pathParts.map((part, index) => (
        <React.Fragment key={index}>
          <ChevronRight size={14} className={styles.separator} />
          <button
            className={styles.breadcrumbItem}
            onClick={() => {
              const newPath = pathParts.slice(0, index + 1).join('/')
              navigateTo(newPath)
            }}
          >
            {part}
          </button>
        </React.Fragment>
      ))}
    </div>
  )

  const renderFileItem = (file: FileItem, index: number) => {
    const isSelected = selectedFiles.has(file.path)
    const isEditing = editingFile === file.path

    return (
      <div
        key={file.path}
        className={`${styles.fileItem} ${isSelected ? styles.selected : ''} ${
          selectedFile?.path === file.path ? styles.focused : ''
        }`}
        onClick={(e) => handleFileClick(file, index, e)}
        onDoubleClick={() => handleFileDoubleClick(file)}
        onContextMenu={(e) => handleContextMenu(e, file)}
      >
        <div
          className={styles.fileCheckbox}
          onClick={(e) => handleCheckboxChange(file, index, e)}
        >
          <input
            type="checkbox"
            checked={isSelected}
            readOnly
          />
        </div>
        <div className={styles.fileName}>
          <span className={styles.fileIcon}>{getFileIcon(file)}</span>
          {isEditing ? (
            <input
              ref={editInputRef}
              type="text"
              className={styles.editInput}
              value={editName}
              onChange={(e) => setEditName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleRenameSubmit()
                if (e.key === 'Escape') {
                  setEditingFile(null)
                  setEditName('')
                }
              }}
              onBlur={() => {
                setEditingFile(null)
                setEditName('')
              }}
              onClick={(e) => e.stopPropagation()}
            />
          ) : (
            <span className={styles.fileNameText}>
              {file.name}
              {file.type === 'directory' && <span className={styles.dirSlash}>/</span>}
            </span>
          )}
        </div>
        <span className={styles.fileSize}>
          {file.type === 'directory' ? '-' : formatFileSize(file.size)}
        </span>
        <span className={styles.fileModified}>
          {formatDate(file.modified)}
        </span>
        <div className={styles.fileActions}>
          {/* Mobile preview button */}
          <IconButton
            icon={<Info size={14} />}
            size="sm"
            className={styles.mobilePreviewBtn}
            tooltip="View details"
            onClick={(e) => handleShowPreview(file, e)}
          />
          <IconButton
            icon={<MoreVertical size={14} />}
            size="sm"
            onClick={(e) => {
              e.stopPropagation()
              handleContextMenu(e as unknown as React.MouseEvent, file)
            }}
          />
        </div>
      </div>
    )
  }

  const renderContextMenu = () => {
    if (!contextMenu) return null

    const { x, y, file } = contextMenu
    const isDirectory = file.type === 'directory'

    // Calculate position to keep menu within viewport
    const menuWidth = 160
    const menuHeight = isDirectory ? 140 : 180 // Approximate height
    const viewportWidth = window.innerWidth
    const viewportHeight = window.innerHeight

    // Adjust x position if menu would overflow right edge
    let adjustedX = x
    if (x + menuWidth > viewportWidth - 16) {
      adjustedX = viewportWidth - menuWidth - 16
    }
    // Ensure minimum left position
    if (adjustedX < 16) {
      adjustedX = 16
    }

    // Adjust y position if menu would overflow bottom edge
    let adjustedY = y
    if (y + menuHeight > viewportHeight - 16) {
      adjustedY = viewportHeight - menuHeight - 16
    }
    // Ensure minimum top position
    if (adjustedY < 16) {
      adjustedY = 16
    }

    return (
      <div
        className={styles.contextMenu}
        style={{ left: adjustedX, top: adjustedY }}
        onClick={(e) => e.stopPropagation()}
      >
        {!isDirectory && (
          <button
            className={styles.contextMenuItem}
            onClick={() => {
              handleDownload(file.path, file.name)
              setContextMenu(null)
            }}
          >
            <Download size={14} />
            <span>Download</span>
          </button>
        )}
        <button
          className={styles.contextMenuItem}
          onClick={() => {
            setEditingFile(file.path)
            setEditName(file.name)
            setContextMenu(null)
          }}
        >
          <Edit3 size={14} />
          <span>Rename</span>
        </button>
        <button
          className={styles.contextMenuItem}
          onClick={() => {
            handleCopy([file.path])
            setContextMenu(null)
          }}
        >
          <Copy size={14} />
          <span>Copy</span>
        </button>
        <button
          className={styles.contextMenuItem}
          onClick={() => {
            handleCut([file.path])
            setContextMenu(null)
          }}
        >
          <Scissors size={14} />
          <span>Cut</span>
        </button>
        {clipboard && isDirectory && (
          <button
            className={styles.contextMenuItem}
            onClick={() => {
              handlePaste(file.path)
              setContextMenu(null)
            }}
          >
            <Clipboard size={14} />
            <span>Paste here</span>
          </button>
        )}
        <div className={styles.contextMenuDivider} />
        <button
          className={`${styles.contextMenuItem} ${styles.danger}`}
          onClick={() => {
            handleDelete([file.path])
            setContextMenu(null)
          }}
        >
          <Trash2 size={14} />
          <span>Delete</span>
        </button>
      </div>
    )
  }

  const renderEmptySpaceMenu = () => {
    if (!emptySpaceMenu) return null

    // Adjust position to stay within viewport
    const menuWidth = 160
    const menuHeight = clipboard ? 120 : 80
    const viewportWidth = window.innerWidth
    const viewportHeight = window.innerHeight

    const adjustedX = emptySpaceMenu.x + menuWidth > viewportWidth
      ? viewportWidth - menuWidth - 10
      : emptySpaceMenu.x
    const adjustedY = emptySpaceMenu.y + menuHeight > viewportHeight
      ? viewportHeight - menuHeight - 10
      : emptySpaceMenu.y

    return (
      <div
        className={styles.contextMenu}
        style={{ left: adjustedX, top: adjustedY }}
        onClick={(e) => e.stopPropagation()}
      >
        <button
          className={styles.contextMenuItem}
          onClick={() => {
            setShowCreateDialog('file')
            setEmptySpaceMenu(null)
          }}
        >
          <FilePlus size={14} />
          <span>New File</span>
        </button>
        <button
          className={styles.contextMenuItem}
          onClick={() => {
            setShowCreateDialog('directory')
            setEmptySpaceMenu(null)
          }}
        >
          <FolderPlus size={14} />
          <span>New Folder</span>
        </button>
        {clipboard && (
          <>
            <div className={styles.contextMenuDivider} />
            <button
              className={styles.contextMenuItem}
              onClick={() => {
                handlePaste()
                setEmptySpaceMenu(null)
              }}
            >
              <Clipboard size={14} />
              <span>Paste ({clipboard.paths.length})</span>
            </button>
          </>
        )}
      </div>
    )
  }

  const renderCreateDialog = () => {
    if (!showCreateDialog) return null

    return (
      <div className={styles.dialogOverlay} onClick={() => setShowCreateDialog(null)}>
        <div className={styles.dialog} onClick={(e) => e.stopPropagation()}>
          <div className={styles.dialogHeader}>
            <h3>Create {showCreateDialog === 'directory' ? 'Folder' : 'File'}</h3>
            <IconButton
              icon={<X size={16} />}
              size="sm"
              onClick={() => setShowCreateDialog(null)}
            />
          </div>
          <div className={styles.dialogContent}>
            <input
              ref={createInputRef}
              type="text"
              className={styles.dialogInput}
              placeholder={`Enter ${showCreateDialog} name...`}
              value={createName}
              onChange={(e) => setCreateName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleCreateSubmit()
                if (e.key === 'Escape') setShowCreateDialog(null)
              }}
            />
          </div>
          <div className={styles.dialogFooter}>
            <Button variant="secondary" size="sm" onClick={() => setShowCreateDialog(null)}>
              Cancel
            </Button>
            <Button variant="primary" size="sm" onClick={handleCreateSubmit}>
              Create
            </Button>
          </div>
        </div>
      </div>
    )
  }

  const renderPreviewPanel = () => {
    if (!selectedFile) {
      return (
        <div className={styles.emptyPreview}>
          <FolderOpen size={32} />
          <p>Select a file or folder to view details</p>
        </div>
      )
    }

    return (
      <>
        <div className={styles.previewHeader}>
          <div className={styles.previewIcon}>
            {getFileIcon(selectedFile)}
          </div>
          <div className={styles.previewInfo}>
            <h3>{selectedFile.name}</h3>
            <p>{selectedFile.path}</p>
          </div>
        </div>
        <div className={styles.previewContent}>
          <dl className={styles.previewDetails}>
            <dt>Type</dt>
            <dd>
              <Badge variant={getFileBadgeVariant(selectedFile)}>
                {selectedFile.type === 'directory' ? 'Directory' : getFileExtension(selectedFile.name).toUpperCase() || 'File'}
              </Badge>
            </dd>
            <dt>Size</dt>
            <dd>{formatFileSize(selectedFile.size)}</dd>
            <dt>Modified</dt>
            <dd>{formatDate(selectedFile.modified)}</dd>
          </dl>

          {selectedFile.type === 'file' && showPreviewContent && (
            <div className={styles.filePreview}>
              <div className={styles.filePreviewHeader}>
                <span>Preview</span>
              </div>
              {previewLoading ? (
                <div className={styles.previewLoading}>
                  <Loader2 size={20} className={styles.spinner} />
                  <span>Loading...</span>
                </div>
              ) : fileIsBinary ? (
                <div className={styles.previewBinary}>
                  <AlertCircle size={20} />
                  <span>Binary file - cannot preview</span>
                </div>
              ) : fileContent ? (
                <pre className={styles.previewCode}>{fileContent.slice(0, 5000)}</pre>
              ) : (
                <div className={styles.previewEmpty}>Empty file</div>
              )}
            </div>
          )}
        </div>
        <div className={styles.previewActions}>
          {selectedFile.type === 'file' && (
            <Button
              variant="secondary"
              size="sm"
              fullWidth
              icon={<Download size={14} />}
              onClick={() => handleDownload(selectedFile.path, selectedFile.name)}
            >
              Download
            </Button>
          )}
          <Button
            variant="secondary"
            size="sm"
            fullWidth
            icon={<Edit3 size={14} />}
            onClick={() => {
              setEditingFile(selectedFile.path)
              setEditName(selectedFile.name)
            }}
          >
            Rename
          </Button>
          <Button
            variant="danger"
            size="sm"
            fullWidth
            icon={<Trash2 size={14} />}
            onClick={() => handleDelete([selectedFile.path])}
          >
            Delete
          </Button>
        </div>
      </>
    )
  }

  // ─────────────────────────────────────────────────────────────────────
  // Main Render
  // ─────────────────────────────────────────────────────────────────────

  return (
    <div className={styles.workspacePage}>
      {/* Toolbar */}
      <div className={styles.toolbar}>
        <div className={styles.toolbarLeft}>
          <IconButton
            icon={<Home size={16} />}
            tooltip="Home"
            onClick={() => navigateTo('')}
          />
          {currentDirectory && (
            <IconButton
              icon={<ChevronDown size={16} style={{ transform: 'rotate(90deg)' }} />}
              tooltip="Go up"
              onClick={handleNavigateUp}
            />
          )}
          {renderBreadcrumb()}
        </div>
        <div className={styles.toolbarRight}>
          <IconButton
            icon={loading ? <Loader2 size={16} className={styles.spinner} /> : <RefreshCw size={16} />}
            tooltip="Refresh"
            onClick={() => refresh()}
          />
          <IconButton
            icon={<FolderPlus size={16} />}
            tooltip="New Folder"
            onClick={() => setShowCreateDialog('directory')}
            className={styles.mobileOnly}
          />
          <Button
            icon={<FolderPlus size={14} />}
            variant="secondary"
            size="sm"
            onClick={() => setShowCreateDialog('directory')}
            className={styles.desktopOnly}
          >
            New Folder
          </Button>
          <IconButton
            icon={<FilePlus size={16} />}
            tooltip="New File"
            onClick={() => setShowCreateDialog('file')}
            className={styles.mobileOnly}
          />
          <Button
            icon={<FilePlus size={14} />}
            variant="secondary"
            size="sm"
            onClick={() => setShowCreateDialog('file')}
            className={styles.desktopOnly}
          >
            New File
          </Button>
          <IconButton
            icon={<Upload size={16} />}
            tooltip="Upload"
            onClick={() => fileInputRef.current?.click()}
            className={styles.mobileOnly}
          />
          <Button
            icon={<Upload size={14} />}
            variant="secondary"
            size="sm"
            onClick={() => fileInputRef.current?.click()}
            className={styles.desktopOnly}
          >
            Upload
          </Button>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            style={{ display: 'none' }}
            onChange={(e) => {
              if (e.target.files) {
                handleUpload(e.target.files)
                e.target.value = ''
              }
            }}
          />
        </div>
      </div>

      {/* Batch Actions Bar */}
      {selectedFiles.size > 1 && (
        <div className={styles.batchBar}>
          <span className={styles.batchCount}>
            <Check size={14} />
            {selectedFiles.size} selected
          </span>
          <div className={styles.batchActions}>
            <Button
              icon={<Download size={14} />}
              variant="secondary"
              size="sm"
              onClick={handleBatchDownload}
            >
              Download
            </Button>
            <Button
              icon={<Trash2 size={14} />}
              variant="danger"
              size="sm"
              onClick={() => handleDelete(Array.from(selectedFiles))}
            >
              Delete
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setSelectedFiles(new Set())}
            >
              Clear
            </Button>
          </div>
        </div>
      )}

      {/* Main Content */}
      <div className={styles.content}>
        {/* File List */}
        <div className={`${styles.fileList} ${mobileShowPreview ? styles.mobileHidden : ''}`}>
          <div className={styles.fileListHeader}>
            <span className={styles.colCheckbox}>
              <input
                type="checkbox"
                checked={files.length > 0 && selectedFiles.size === files.length}
                onChange={(e) => {
                  if (e.target.checked) {
                    setSelectedFiles(new Set(files.map(f => f.path)))
                  } else {
                    setSelectedFiles(new Set())
                  }
                }}
              />
            </span>
            <span className={styles.colName}>Name</span>
            <span className={styles.colSize}>Size</span>
            <span className={styles.colModified}>Modified</span>
            <span className={styles.colActions}></span>
          </div>
          <div className={styles.fileListBody} onContextMenu={handleEmptySpaceContextMenu}>
            {loading && files.length === 0 ? (
              <div className={styles.loadingState}>
                <Loader2 size={24} className={styles.spinner} />
                <span>Loading files...</span>
              </div>
            ) : error ? (
              <div className={styles.errorState}>
                <AlertCircle size={24} />
                <span>{error}</span>
                <Button variant="secondary" size="sm" onClick={() => refresh()}>
                  Retry
                </Button>
              </div>
            ) : files.length === 0 ? (
              <div className={styles.emptyState}>
                <FolderOpen size={32} />
                <span>This folder is empty</span>
                <div className={styles.emptyActions}>
                  <Button
                    icon={<FolderPlus size={14} />}
                    variant="secondary"
                    size="sm"
                    onClick={() => setShowCreateDialog('directory')}
                  >
                    New Folder
                  </Button>
                  <Button
                    icon={<Upload size={14} />}
                    variant="secondary"
                    size="sm"
                    onClick={() => fileInputRef.current?.click()}
                  >
                    Upload
                  </Button>
                </div>
              </div>
            ) : (
              files.map((file, index) => renderFileItem(file, index))
            )}
          </div>
        </div>

        {/* Preview Panel */}
        <div className={`${styles.previewPanel} ${mobileShowPreview ? styles.mobileVisible : ''}`}>
          {/* Mobile back button */}
          <div className={styles.mobilePreviewHeader}>
            <IconButton
              icon={<ArrowLeft size={18} />}
              variant="ghost"
              onClick={handleMobilePreviewBack}
              tooltip="Back to files"
            />
            <span>File Details</span>
          </div>
          {renderPreviewPanel()}
        </div>
      </div>

      {/* Status Bar */}
      <div className={styles.statusBar}>
        <span>{files.length} item{files.length !== 1 ? 's' : ''}</span>
        {selectedFiles.size > 0 && (
          <span>{selectedFiles.size} selected</span>
        )}
        {clipboard && (
          <span className={styles.clipboardStatus}>
            {clipboard.paths.length} item{clipboard.paths.length !== 1 ? 's' : ''} in clipboard ({clipboard.action})
          </span>
        )}
      </div>

      {/* Context Menu */}
      {renderContextMenu()}
      {renderEmptySpaceMenu()}

      {/* Create Dialog */}
      {renderCreateDialog()}
    </div>
  )
}
