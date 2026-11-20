/**
 * Workspace: the agent's files as a two-pane file manager, the list on the
 * left and a preview (details and text) on the right.
 *
 * Enter or Right opens a folder, Left or Backspace goes up, ~ goes home.
 * v marks files; c copies, x cuts and p pastes the marked files (or the one
 * under the cursor), with the browser's "_copy" names; e renames, d deletes
 * after a confirmation, a and A create a file or folder. u copies a local
 * file in (a path the user types), s saves files to a local path, o opens a
 * file with the system's app and O shows it in its folder (open_file /
 * open_folder). Tab moves to the preview to scroll it.
 *
 * The listing lives in the browser's workspaceSlice; requests go through
 * dataWorkspaceOps with the browser's requestId correlation.
 */
import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Box, Text } from 'ink'
import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'
import { existsSync, statSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { useAppDispatch, useAppSelector, send } from '../state/hooks'
import { store } from '../state/store'
import { selectWorkspace } from '../../../browser/frontend/src/store/selectors/workspace'
import { selectConnected } from '../../../browser/frontend/src/store/selectors/connection'
import {
  FILE_PAGE_SIZE,
  selectFile,
  startLoadMore,
  startNavigate,
  startSearch,
  setError as setWorkspaceError,
} from '../../../browser/frontend/src/store/slices/workspaceSlice'
import { onInboundMessage } from '../../../browser/frontend/src/store/socket/socketMiddleware'
import type {
  FileBatchDeleteResponse,
  FileCopyResponse,
  FileCreateResponse,
  FileDeleteResponse,
  FileItem,
  FileListResponse,
  FileReadResponse,
  FileRenameResponse,
} from '../../../browser/frontend/src/types'
import { Frame, bodyRows } from '../ui/Frame'
import { useScreen, useScreenKeys } from './context'
import { clampList, listKey, LIST_START, type ListState } from '../ui/list'
import { TextField, fieldKey } from '../ui/TextField'
import { ConfirmLine, confirmKey, type PendingConfirm } from '../ui/Confirm'
import * as TB from '../input/TextBuffer'
import { glyphs, ink } from '../theme/theme'
import { padEnd, padStart, truncate, width as cells } from '../text/width'
import { fitRow, seg, type Row } from './dataRows'
import { RowView } from './dataRowView'
import { baseName, formatSize, joinPath, parentPath, previewLines, renameCaret, resolveLocalPath, uniqueName } from './dataFiles'
import { downloadToLocal, request, RequestError, uploadLocalFile } from './dataWorkspaceOps'

type T = TFunction<'screensData'>

const TWO_PANES_AT = 70
const NOTICE_MS = 6000
const REFRESH_MS = 30_000
const READ_DELAY_MS = 120
const SEARCH_DELAY_MS = 300
const MAX_UPLOAD_BYTES = 200 * 1024 * 1024

interface Clipboard {
  action: 'copy' | 'cut'
  paths: string[]
}

type PromptKind = 'rename' | 'newFile' | 'newFolder' | 'upload' | 'download'

interface Prompt {
  kind: PromptKind
  buf: TB.Buffer
  /** rename: the file; download: the files to save. */
  targets: FileItem[]
}

interface Notice {
  text: string
  tone: 'info' | 'error'
}

interface ReadState {
  path: string
  status: 'loading' | 'done' | 'error'
  error?: string
}

// The clipboard outlives the screen, so copy, close, reopen and paste works.
let savedClipboard: Clipboard | null = null

function errorText(t: T, err: unknown): string {
  if (err instanceof RequestError) return err.code === 'notConnected' ? t('common.notConnected') : t('common.timedOut')
  return err instanceof Error ? err.message : String(err)
}

function defaultSaveDir(): string {
  const downloads = join(homedir(), 'Downloads')
  return existsSync(downloads) ? downloads : process.cwd()
}

function isDir(path: string): boolean {
  try {
    return statSync(path).isDirectory()
  } catch {
    return false
  }
}

export function WorkspaceScreen() {
  const { t, i18n } = useTranslation('screensData')
  const dispatch = useAppDispatch()
  const { columns, rows, setTextFocus } = useScreen()
  const ws = useAppSelector(selectWorkspace)
  const connected = useAppSelector(selectConnected)
  const { currentDirectory, files, loading, loadingMore, error, selectedFile, fileContent, fileIsBinary, total, hasMore, offset, search } = ws

  const [list, setList] = useState<ListState>(LIST_START)
  const [marks, setMarks] = useState<Set<string>>(new Set())
  const [clipboard, setClipboardState] = useState<Clipboard | null>(savedClipboard)
  const [prompt, setPrompt] = useState<Prompt | null>(null)
  const [searchBuf, setSearchBuf] = useState<TB.Buffer>(TB.fromText(search))
  const [searching, setSearching] = useState(false)
  const [confirm, setConfirm] = useState<PendingConfirm | null>(null)
  const [notice, setNotice] = useState<Notice | null>(null)
  const [focus, setFocus] = useState<'list' | 'preview'>('list')
  const [previewTop, setPreviewTop] = useState(0)
  const [read, setRead] = useState<ReadState | null>(null)
  const returnTo = useRef<string | null>(null)
  const openRequests = useRef(new Set<string>())

  const say = (text: string, tone: Notice['tone'] = 'info') => setNotice({ text, tone })
  useEffect(() => {
    if (!notice) return
    const timer = setTimeout(() => setNotice(null), NOTICE_MS)
    return () => clearTimeout(timer)
  }, [notice])

  const setClipboard = (next: Clipboard | null) => {
    savedClipboard = next
    setClipboardState(next)
  }

  // ── listing ──
  const listCurrent = useCallback(() => {
    const s = store.getState().workspace
    request<FileListResponse>('file_list', {
      directory: s.currentDirectory,
      offset: 0,
      limit: Math.max(FILE_PAGE_SIZE, s.offset),
      search: s.search,
    }).catch(() => {})
  }, [])

  const navigate = useCallback(
    (directory: string, focusPath: string | null = null) => {
      returnTo.current = focusPath
      dispatch(startNavigate(directory))
      setList(LIST_START)
      setMarks(new Set())
      setSearchBuf(TB.EMPTY)
      setPreviewTop(0)
      request<FileListResponse>('file_list', { directory, offset: 0, limit: FILE_PAGE_SIZE }).catch(err => {
        dispatch(setWorkspaceError(errorText(t, err)))
      })
    },
    [dispatch, t],
  )

  // Open: the first visit loads the root, later ones refresh in place (and
  // after a reconnect); then every 30 s, like the browser page.
  useEffect(() => {
    if (!connected) return
    const s = store.getState().workspace
    if (s.files.length === 0 && !s.loading) navigate(s.currentDirectory)
    else listCurrent()
    const timer = setInterval(listCurrent, REFRESH_MS)
    return () => clearInterval(timer)
  }, [connected, navigate, listCurrent])

  // Files changed on disk (the agent, the browser, anything): reload the
  // folder and re-read the previewed file when they are affected.
  useEffect(
    () =>
      onInboundMessage(msg => {
        if (msg.type === 'open_file' || msg.type === 'open_folder') {
          const d = (msg.data ?? {}) as { path?: string; success?: boolean; error?: string }
          if (!d.path || !openRequests.current.delete(d.path)) return
          if (d.success) setNotice({ text: t('workspace.opened', { name: baseName(d.path) }), tone: 'info' })
          else setNotice({ text: t('workspace.openFailed', { name: baseName(d.path), error: d.error || t('common.unknownError') }), tone: 'error' })
          return
        }
        if (msg.type !== 'resource_changed') return
        const { resource, ids } = (msg.data ?? {}) as { resource?: string; ids?: string[] }
        if (resource !== 'workspace_files') return
        const s = store.getState().workspace
        const touches = (folder: string) => !ids?.length || ids.includes(folder)
        if (s.search || touches(s.currentDirectory)) listCurrent()
        const open = s.selectedFile
        if (open && open.type !== 'directory' && touches(parentPath(open.path))) {
          request<FileReadResponse>('file_read', { path: open.path }).catch(() => {})
        }
      }),
    [listCurrent, t],
  )

  // Put the cursor back on the folder we came up from.
  useEffect(() => {
    if (!returnTo.current || loading) return
    const index = files.findIndex(f => f.path === returnTo.current)
    returnTo.current = null
    if (index >= 0) setList(l => ({ ...l, index }))
  }, [files, loading])

  // Marks only ever cover files that are listed.
  useEffect(() => {
    if (loading || search || marks.size === 0) return
    const listed = new Set(files.map(f => f.path))
    const kept = Array.from(marks).filter(p => listed.has(p))
    if (kept.length !== marks.size) setMarks(new Set(kept))
  }, [files, loading, search, marks])

  // ── layout ──
  const body = bodyRows(rows)
  const listHeight = Math.max(3, body - 3)
  const twoPanes = columns >= TWO_PANES_AT
  const listWidth = twoPanes ? Math.max(36, Math.min(72, Math.floor(columns * 0.55))) : columns - 1
  const previewWidth = twoPanes ? Math.max(16, columns - listWidth - 3) : columns - 1
  const showPreview = twoPanes || focus === 'preview'

  const view = clampList(list, files.length, listHeight)
  const cursor = files[view.index] ?? null

  // Preview the file under the cursor (after a short pause while moving).
  useEffect(() => {
    if (!cursor) return
    if (selectedFile?.path === cursor.path && selectedFile.modified === cursor.modified) return
    const timer = setTimeout(() => {
      dispatch(selectFile(cursor))
      setPreviewTop(0)
      if (cursor.type !== 'file') {
        setRead(null)
        return
      }
      setRead({ path: cursor.path, status: 'loading' })
      request<FileReadResponse>('file_read', { path: cursor.path })
        .then(r => setRead({ path: cursor.path, status: r.success ? 'done' : 'error', error: r.error }))
        .catch(err => setRead({ path: cursor.path, status: 'error', error: errorText(t, err) }))
    }, READ_DELAY_MS)
    return () => clearTimeout(timer)
  }, [cursor, selectedFile, dispatch, t])

  // Load the next page as the cursor nears the end.
  useEffect(() => {
    if (!hasMore || loadingMore || loading || view.index < files.length - 3) return
    dispatch(startLoadMore())
    request<FileListResponse>('file_list', { directory: currentDirectory, offset, limit: FILE_PAGE_SIZE, search }).catch(() =>
      dispatch(setWorkspaceError(null)),
    )
  }, [hasMore, loadingMore, loading, view.index, files.length, currentDirectory, offset, search, dispatch])

  // Typing in the filter lists again after a pause.
  useEffect(() => {
    const query = searchBuf.text.trim()
    if (query === search) return
    const timer = setTimeout(() => {
      dispatch(startSearch(query))
      setList(LIST_START)
      request<FileListResponse>('file_list', { directory: currentDirectory, offset: 0, limit: FILE_PAGE_SIZE, search: query }).catch(() =>
        dispatch(setWorkspaceError(null)),
      )
    }, SEARCH_DELAY_MS)
    return () => clearTimeout(timer)
  }, [searchBuf.text, search, currentDirectory, dispatch])

  const previewText = useMemo(() => {
    if (!selectedFile || selectedFile.type !== 'file' || fileIsBinary || fileContent === null) return [] as string[]
    return previewLines(fileContent, previewWidth)
  }, [selectedFile, fileIsBinary, fileContent, previewWidth])

  // ── operations ──
  const targets = (): FileItem[] => {
    if (marks.size) return files.filter(f => marks.has(f.path))
    return cursor ? [cursor] : []
  }

  const paste = async () => {
    if (!clipboard) return
    const dir = currentDirectory
    say(t('workspace.loading'))
    let existing: Set<string>
    try {
      const listing = await request<FileListResponse>('file_list', { directory: dir, offset: 0, limit: 100_000 }, 'reply-only')
      existing = new Set((listing.success ? listing.files : files).map(f => f.name.toLowerCase()))
    } catch (err) {
      say(t('workspace.pasteFailed', { name: baseName(clipboard.paths[0] ?? ''), error: errorText(t, err) }), 'error')
      return
    }
    let done = 0
    for (const src of clipboard.paths) {
      // Moving into the folder it is already in changes nothing.
      if (clipboard.action === 'cut' && parentPath(src) === dir) continue
      const name = uniqueName(baseName(src), existing)
      existing.add(name.toLowerCase())
      try {
        const reply = await request<FileCopyResponse>(clipboard.action === 'copy' ? 'file_copy' : 'file_move', {
          srcPath: src,
          destPath: joinPath(dir, name),
        })
        if (!reply.success) {
          say(t('workspace.pasteFailed', { name: baseName(src), error: reply.error || t('common.unknownError') }), 'error')
          listCurrent()
          return
        }
        done++
      } catch (err) {
        say(t('workspace.pasteFailed', { name: baseName(src), error: errorText(t, err) }), 'error')
        listCurrent()
        return
      }
    }
    listCurrent()
    if (clipboard.action === 'cut') {
      setClipboard(null)
      say(t('workspace.moved', { count: done }))
    } else {
      say(t('workspace.pasted', { count: done }))
    }
  }

  const remove = (items: FileItem[]) => {
    if (!items.length) return
    setConfirm({
      message: items.length === 1 ? t('workspace.confirmDeleteOne', { name: items[0].name }) : t('workspace.confirmDeleteMany', { count: items.length }),
      onConfirm: () => {
        void (async () => {
          try {
            if (items.length === 1) {
              const r = await request<FileDeleteResponse>('file_delete', { path: items[0].path })
              if (r.success) say(t('workspace.deleted', { count: 1 }))
              else say(t('workspace.deleteFailed', { error: r.error || t('common.unknownError') }), 'error')
            } else {
              const r = await request<FileBatchDeleteResponse>('file_batch_delete', { paths: items.map(i => i.path) })
              const failed = r.results.filter(x => !x.success)
              if (failed.length === 0) say(t('workspace.deleted', { count: r.results.length }))
              else
                say(
                  t('workspace.deletePartial', {
                    succeeded: r.results.length - failed.length,
                    total: r.results.length,
                    failed: failed.length,
                    error: failed[0].error || t('common.unknownError'),
                  }),
                  'error',
                )
            }
          } catch (err) {
            say(t('workspace.deleteFailed', { error: errorText(t, err) }), 'error')
          }
          setMarks(new Set())
        })()
      },
    })
  }

  const doUpload = async (localPath: string, workspacePath: string) => {
    const name = baseName(workspacePath)
    say(t('workspace.loading'))
    try {
      await uploadLocalFile(localPath, workspacePath)
      say(t('workspace.uploaded', { name }))
      returnTo.current = workspacePath
      listCurrent()
    } catch (err) {
      say(t('workspace.uploadFailed', { name, error: errorText(t, err) }), 'error')
    }
  }

  const doDownloads = async (pairs: { item: FileItem; target: string }[]) => {
    for (const { item, target } of pairs) {
      say(t('workspace.loading'))
      try {
        await downloadToLocal(item.path, target)
        say(t('workspace.downloaded', { path: truncate(target, Math.max(20, columns - 12), 'start') }))
      } catch (err) {
        say(t('workspace.downloadFailed', { name: item.name, error: errorText(t, err) }), 'error')
        return
      }
    }
  }

  const submitPrompt = (p: Prompt) => {
    const text = p.buf.text.trim()
    closePrompt()
    if (!text) return
    if (p.kind === 'rename') {
      const target = p.targets[0]
      if (!target || text === target.name) return
      request<FileRenameResponse>('file_rename', { oldPath: target.path, newName: text })
        .then(r => (r.success ? say(t('workspace.renamed', { name: text })) : say(t('workspace.renameFailed', { error: r.error || t('common.unknownError') }), 'error')))
        .catch(err => say(t('workspace.renameFailed', { error: errorText(t, err) }), 'error'))
      return
    }
    if (p.kind === 'newFile' || p.kind === 'newFolder') {
      const path = joinPath(currentDirectory, text)
      request<FileCreateResponse>('file_create', { path, fileType: p.kind === 'newFolder' ? 'directory' : 'file' })
        .then(r => {
          if (!r.success) {
            say(t('workspace.createFailed', { name: text, error: r.error || t('common.unknownError') }), 'error')
            return
          }
          say(t('workspace.created', { name: text }))
          returnTo.current = path
          listCurrent()
        })
        .catch(err => say(t('workspace.createFailed', { name: text, error: errorText(t, err) }), 'error'))
      return
    }
    if (p.kind === 'upload') {
      const local = resolveLocalPath(text, process.cwd(), homedir())
      let size = 0
      try {
        const st = statSync(local)
        if (!st.isFile()) throw new Error('not a file')
        size = st.size
      } catch {
        say(t('workspace.notAFile', { path: local }), 'error')
        return
      }
      const name = baseName(local)
      if (size > MAX_UPLOAD_BYTES) {
        say(t('workspace.tooLarge', { name, size: formatSize(size) }), 'error')
        return
      }
      const destination = joinPath(currentDirectory, name)
      if (files.some(f => f.name.toLowerCase() === name.toLowerCase())) {
        setConfirm({ message: t('workspace.confirmOverwrite', { path: destination }), onConfirm: () => void doUpload(local, destination) })
        return
      }
      void doUpload(local, destination)
      return
    }
    // Download.
    const dest = resolveLocalPath(text, process.cwd(), homedir())
    const items = p.targets
    let pairs: { item: FileItem; target: string }[]
    if (items.length > 1) {
      if (!isDir(dest)) {
        say(t('workspace.downloadNeedsFolder'), 'error')
        return
      }
      pairs = items.map(item => ({ item, target: join(dest, item.name) }))
    } else {
      pairs = [{ item: items[0], target: isDir(dest) ? join(dest, items[0].name) : dest }]
    }
    const clash = pairs.find(pair => existsSync(pair.target))
    if (clash) {
      setConfirm({ message: t('workspace.confirmOverwrite', { path: truncate(clash.target, Math.max(20, columns - 40), 'start') }), onConfirm: () => void doDownloads(pairs) })
      return
    }
    void doDownloads(pairs)
  }

  const openPrompt = (kind: PromptKind, targetsFor: FileItem[] = []) => {
    let buf = TB.EMPTY
    if (kind === 'rename' && targetsFor[0]) buf = { text: targetsFor[0].name, cursor: renameCaret(targetsFor[0].name) }
    if (kind === 'download') {
      const dir = defaultSaveDir()
      buf = TB.fromText(targetsFor.length === 1 ? join(dir, targetsFor[0].name) : dir)
    }
    setPrompt({ kind, buf, targets: targetsFor })
    setTextFocus(true)
  }

  const closePrompt = () => {
    setPrompt(null)
    setTextFocus(false)
  }

  const openWithOs = (type: 'open_file' | 'open_folder', item: FileItem | null) => {
    if (!item) return
    openRequests.current.add(item.path)
    send(type, { path: item.path })
  }

  // ── keys ──
  useScreenKeys((input, key) => {
    if (confirmKey(confirm, input, key, () => setConfirm(null))) return true

    if (prompt) {
      if (key.escape) {
        closePrompt()
        return true
      }
      if (key.return) {
        submitPrompt(prompt)
        return true
      }
      const next = fieldKey(prompt.buf, input, key)
      if (next) setPrompt({ ...prompt, buf: next })
      return true
    }

    if (searching) {
      if (key.escape || key.return) {
        setSearching(false)
        setTextFocus(false)
        if (key.escape) setSearchBuf(TB.EMPTY)
        return true
      }
      if (key.upArrow || key.downArrow) {
        const moved = listKey(view, '', key, files.length, listHeight)
        if (moved) setList(moved)
        return true
      }
      const next = fieldKey(searchBuf, input, key)
      if (next) setSearchBuf(next)
      return true
    }

    if (focus === 'preview') {
      const maxTop = Math.max(0, previewText.length - (listHeight - 5))
      let next: number | null = null
      if (key.downArrow || input === 'j') next = previewTop + 1
      else if (key.upArrow || input === 'k') next = previewTop - 1
      else if (key.pageDown || input === ' ') next = previewTop + listHeight - 5
      else if (key.pageUp) next = previewTop - (listHeight - 5)
      else if (key.home || input === 'g') next = 0
      else if (key.end || input === 'G') next = maxTop
      if (next !== null) {
        setPreviewTop(Math.max(0, Math.min(maxTop, next)))
        return true
      }
      if (key.tab || key.escape || key.leftArrow || input === 'h') {
        setFocus('list')
        return true
      }
      if (input === 'o') {
        openWithOs('open_file', selectedFile)
        return true
      }
      return false
    }

    const moved = listKey(view, input, key, files.length, listHeight)
    if (moved) {
      setList(moved)
      return true
    }
    if (key.return || key.rightArrow || input === 'l') {
      if (cursor?.type === 'directory') navigate(cursor.path)
      else if (cursor) setFocus('preview')
      return true
    }
    if (key.leftArrow || key.backspace || input === 'h') {
      if (currentDirectory) navigate(parentPath(currentDirectory), currentDirectory)
      return true
    }
    if (input === '~') {
      if (currentDirectory) navigate('')
      return true
    }
    if (key.tab) {
      if (cursor) setFocus('preview')
      return true
    }
    if (input === '/') {
      setSearching(true)
      setTextFocus(true)
      return true
    }
    if (input === 'r') {
      listCurrent()
      return true
    }
    if (input === 'v') {
      if (!cursor) return true
      const next = new Set(marks)
      if (next.has(cursor.path)) next.delete(cursor.path)
      else next.add(cursor.path)
      setMarks(next)
      setList(clampList({ ...view, index: view.index + 1 }, files.length, listHeight))
      return true
    }
    if (input === 'V') {
      setMarks(marks.size ? new Set() : new Set(files.map(f => f.path)))
      return true
    }
    if (input === 'c' || input === 'x') {
      const items = targets()
      if (!items.length) return true
      setClipboard({ action: input === 'c' ? 'copy' : 'cut', paths: items.map(i => i.path) })
      setMarks(new Set())
      return true
    }
    if (input === 'p') {
      void paste()
      return true
    }
    if (input === 'e') {
      if (cursor) openPrompt('rename', [cursor])
      return true
    }
    if (input === 'd') {
      remove(targets())
      return true
    }
    if (input === 'a' || input === 'A') {
      openPrompt(input === 'a' ? 'newFile' : 'newFolder')
      return true
    }
    if (input === 'u') {
      openPrompt('upload')
      return true
    }
    if (input === 's') {
      const items = targets()
      const filesOnly = items.filter(i => i.type === 'file')
      if (!filesOnly.length) {
        if (items.length) say(t('workspace.downloadFolder'), 'error')
        return true
      }
      openPrompt('download', filesOnly)
      return true
    }
    if (input === 'o' || input === 'O') {
      openWithOs(input === 'o' ? 'open_file' : 'open_folder', cursor)
      return true
    }
    if (key.escape && (marks.size || search)) {
      setMarks(new Set())
      if (search) setSearchBuf(TB.EMPTY)
      return true
    }
    return false
  })

  // ── render ──
  const g = glyphs()
  const formats = useMemo(() => {
    const make = (opts: Intl.DateTimeFormatOptions) => {
      try {
        return new Intl.DateTimeFormat(i18n.language, opts)
      } catch {
        return new Intl.DateTimeFormat('en', opts)
      }
    }
    return {
      full: make({ year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }),
      // The list column: the time this year, the year otherwise.
      thisYear: make({ month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }),
      otherYear: make({ year: 'numeric', month: 'short', day: 'numeric' }),
    }
  }, [i18n.language])
  const when = (ms?: number) => (ms ? formats.full.format(ms) : '-')
  const shortWhen = (ms?: number) => {
    if (!ms) return '-'
    return new Date(ms).getFullYear() === new Date().getFullYear() ? formats.thisYear.format(ms) : formats.otherYear.format(ms)
  }

  const crumbs = [t('workspace.root'), ...currentDirectory.split('/').filter(Boolean)]
  const status = [
    files.length < total ? t('workspace.shown', { shown: files.length, total }) : t('workspace.count', { count: total }),
    marks.size ? t('workspace.marked', { count: marks.size }) : '',
    clipboard
      ? clipboard.action === 'copy'
        ? t('workspace.clipboardCopy', { count: clipboard.paths.length })
        : t('workspace.clipboardCut', { count: clipboard.paths.length })
      : '',
  ].filter(Boolean)
  const statusText = status.join(` ${g.bullet} `)
  const crumbText = truncate(crumbs.join(' / '), Math.max(10, columns - 2 - cells(statusText) - 2), 'start')

  const showModified = listWidth >= 60
  const sizeWidth = 9
  const modWidth = showModified ? 19 : 0
  const nameWidth = Math.max(8, listWidth - 4 - sizeWidth - modWidth - 1)
  const cutSet = clipboard?.action === 'cut' ? new Set(clipboard.paths) : null

  const hints = prompt
    ? [{ keys: 'Enter', label: t('common.ok') }, { keys: 'Esc', label: t('common.cancel') }]
    : focus === 'preview'
      ? [
          { keys: 'j/k', label: t('common.scroll') },
          { keys: 'o', label: t('workspace.hints.osOpen') },
          { keys: 'Tab', label: t('common.back') },
        ]
      : [
          { keys: 'Enter', label: t('workspace.hints.open') },
          { keys: 'h', label: t('workspace.hints.up') },
          { keys: 'v', label: t('workspace.hints.mark') },
          { keys: 'c', label: t('workspace.hints.copy') },
          { keys: 'x', label: t('workspace.hints.cut') },
          { keys: 'p', label: t('workspace.hints.paste') },
          { keys: 'e', label: t('workspace.hints.rename') },
          { keys: 'd', label: t('common.delete') },
          { keys: 'Tab', label: t('workspace.hints.preview') },
          { keys: 'Esc', label: t('common.back') },
        ]
  // The rest of the keys, on the status line while nothing else is there.
  const moreHints = [
    ['a', t('workspace.hints.newFile')],
    ['A', t('workspace.hints.newFolder')],
    ['u', t('workspace.hints.upload')],
    ['s', t('workspace.hints.download')],
    ['o', t('workspace.hints.osOpen')],
    ['O', t('workspace.hints.reveal')],
    ['/', t('common.search')],
    ['r', t('common.refresh')],
  ]
    .map(([k, label]) => `${k} ${label}`)
    .join('   ')

  const promptLabel = prompt
    ? {
        rename: t('workspace.prompt.rename'),
        newFile: t('workspace.prompt.newFile'),
        newFolder: t('workspace.prompt.newFolder'),
        upload: t('workspace.prompt.upload'),
        download: t('workspace.prompt.download'),
      }[prompt.kind]
    : ''

  const bottom = prompt ? (
    <TextField
      label={`${promptLabel}:`}
      buffer={prompt.buf}
      focused
      width={columns - 1}
      placeholder={prompt.kind === 'upload' ? t('workspace.prompt.uploadPlaceholder') : ''}
    />
  ) : confirm ? (
    <ConfirmLine pending={confirm} columns={columns} hint={t('common.confirm')} />
  ) : notice ? (
    <Text color={notice.tone === 'error' ? ink.error : ink.success}>{truncate(notice.text, columns - 1)}</Text>
  ) : (
    <Text color={ink.muted}>{truncate(focus === 'list' ? moreHints : '', columns - 1)}</Text>
  )

  const listPane = (
    <Box flexDirection="column" width={listWidth}>
      {error ? (
        <Text color={ink.error}>{truncate(error, listWidth)}</Text>
      ) : loading && files.length === 0 ? (
        <Text color={ink.muted}>{t('workspace.loading')}</Text>
      ) : files.length === 0 ? (
        <Text color={ink.muted}>{search ? t('workspace.noMatches') : t('workspace.empty')}</Text>
      ) : (
        files.slice(view.top, view.top + listHeight).map((file, i) => (
          <FileRow
            key={file.path}
            file={file}
            selected={view.top + i === view.index}
            focused={focus === 'list'}
            marked={marks.has(file.path)}
            cut={!!cutSet?.has(file.path)}
            nameWidth={nameWidth}
            sizeWidth={sizeWidth}
            modified={showModified ? shortWhen(file.modified) : ''}
            modWidth={modWidth}
            width={listWidth}
          />
        ))
      )}
      {loadingMore ? <Text color={ink.muted}>{t('workspace.loading')}</Text> : null}
    </Box>
  )

  const previewPane = (
    <Box flexDirection="column" width={previewWidth}>
      <PreviewPane
        t={t}
        item={selectedFile && cursor && selectedFile.path === cursor.path ? selectedFile : cursor}
        selected={selectedFile}
        read={read}
        binary={fileIsBinary}
        lines={previewText}
        top={previewTop}
        width={previewWidth}
        height={listHeight}
        when={when}
        focused={focus === 'preview'}
      />
    </Box>
  )

  return (
    <Frame title={t('workspace.title')} aside={statusText} hints={hints} columns={columns} rows={rows}>
      <Box flexDirection="column" height={body}>
        <RowView row={fitRow([seg(crumbText, undefined, true)], columns - 1)} />
        {searching || search || searchBuf.text ? (
          <TextField label="/" buffer={searchBuf} focused={searching} width={columns - 1} placeholder={t('workspace.searchPlaceholder')} />
        ) : (
          <RowView
            row={fitRow(
              [
                seg('    '),
                seg(padEnd(t('workspace.name'), nameWidth), ink.muted),
                seg(` ${padStart(t('workspace.size'), sizeWidth - 1)}`, ink.muted),
                seg(showModified ? `  ${t('workspace.modified')}` : '', ink.muted),
              ],
              twoPanes ? listWidth : columns - 1,
            )}
          />
        )}
        <Box flexDirection="row" height={listHeight}>
          {!twoPanes && focus === 'preview' ? null : listPane}
          {twoPanes ? (
            <Box flexDirection="column" width={2}>
              {Array.from({ length: listHeight }, (_, i) => (
                <Text key={i} color={ink.muted}>{`${g.vbar} `}</Text>
              ))}
            </Box>
          ) : null}
          {showPreview ? previewPane : null}
        </Box>
        {bottom}
      </Box>
    </Frame>
  )
}

interface FileRowProps {
  file: FileItem
  selected: boolean
  focused: boolean
  marked: boolean
  cut: boolean
  nameWidth: number
  sizeWidth: number
  modified: string
  modWidth: number
  width: number
}

// Memoized: moving the cursor re-renders two rows, not the whole list.
const FileRow = memo(function FileRow({ file, selected, focused, marked, cut, nameWidth, sizeWidth, modified, modWidth, width }: FileRowProps) {
  const g = glyphs()
  const dir = file.type === 'directory'
  const row: Row = [
    seg(selected ? `${g.pointer} ` : '  ', focused ? ink.focus : ink.muted),
    seg(marked ? `${g.checked} ` : '  ', ink.brand),
    seg(padEnd(dir ? `${file.name}/` : file.name, nameWidth), selected && focused ? ink.focus : cut ? ink.muted : dir ? ink.info : undefined, selected || dir),
    seg(` ${padStart(dir ? '' : formatSize(file.size), sizeWidth - 1)}`, ink.muted),
    seg(modified ? `  ${padEnd(modified, modWidth - 2)}` : '', ink.muted),
  ]
  return <RowView row={fitRow(row, width)} />
})

function PreviewPane({
  t,
  item,
  selected,
  read,
  binary,
  lines,
  top,
  width,
  height,
  when,
  focused,
}: {
  t: T
  item: FileItem | null
  selected: FileItem | null
  read: ReadState | null
  binary: boolean
  lines: string[]
  top: number
  width: number
  height: number
  when: (ms?: number) => string
  focused: boolean
}) {
  const g = glyphs()
  if (!item) return <Text color={ink.muted}>{truncate(t('workspace.selectHint'), width)}</Text>
  const dir = item.type === 'directory'
  const meta = (name: string, value: string): Row => [seg(padEnd(name, 10), ink.muted), seg(value)]
  const head: Row[] = [
    [seg(dir ? `${item.name}/` : item.name, focused ? ink.focus : undefined, true)],
    dir ? [seg(t('workspace.folder'), ink.muted)] : meta(t('workspace.size'), formatSize(item.size)),
    meta(t('workspace.modified'), when(item.modified)),
    meta(t('workspace.path'), item.path),
    [seg(g.rule.repeat(Math.max(1, width)), ink.muted)],
  ]
  const room = Math.max(1, height - head.length)
  let bodyRows: Row[] = []
  if (!dir) {
    const current = selected?.path === item.path && read?.path === item.path
    if (!current || read?.status === 'loading') bodyRows = [[seg(t('workspace.previewLoading'), ink.muted)]]
    else if (read?.status === 'error') bodyRows = [[seg(read.error || t('common.unknownError'), ink.error)]]
    else if (binary) bodyRows = [[seg(t('workspace.binary'), ink.muted)]]
    else if (lines.length === 0) bodyRows = [[seg(t('workspace.previewEmpty'), ink.muted)]]
    else bodyRows = lines.slice(top, top + room).map(line => [seg(line)])
  }
  return (
    <>
      {[...head, ...bodyRows].map((row, i) => (
        <RowView key={i} row={fitRow(row, width)} />
      ))}
    </>
  )
}
