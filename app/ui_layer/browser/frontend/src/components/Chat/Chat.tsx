import React, { useState, useRef, useEffect, useLayoutEffect, KeyboardEvent, useCallback, ChangeEvent, useMemo } from 'react'
import { Send, Paperclip, Plus, X, Loader2, File, AlertCircle, Mic, MicOff, ChevronDown, Sparkles, BookOpen, Reply } from 'lucide-react'
import { useVirtualizer } from '@tanstack/react-virtual'
import { useWebSocket } from '../../contexts/WebSocketContext'
import { useToast } from '../../contexts/ToastContext'
import { SlashCommandAutocomplete, AttachmentPreviewModal, PlaybookModal } from '../ui'
import type { SlashCommandAutocompleteHandle } from '../ui'
import { ChatMessageItem } from '../../pages/Chat/ChatMessage'
import { TypingIndicatorRow } from '../../pages/Chat/TypingIndicator'
import { ReasoningBlock, ActionBlock, ChunkHeaderRow } from '../activity/ActivityBlocks'
import { normalizeActionName } from '../activity/actionNames'
import { useAppDispatch, useAppSelector } from '../../store/hooks'
import { selectPendingPrefill } from '../../store/selectors/chatInput'
import { clearPendingPrefill, setPendingPrefill } from '../../store/slices/chatInputSlice'
import { useSettingsWebSocket } from '../../pages/Settings/useSettingsWebSocket'
import { DraftMascot, DRAFT_MASCOT_EXIT_MS } from '@mascot'
import {
  selectSessionMessages,
  selectSessionHasMoreMessages,
  selectSessionLoadingOlderMessages,
  selectSessionOldestMessageTimestamp,
} from '../../store/selectors/messages'
import { selectSessionActivity } from '../../store/selectors/activity'
import { selectSessionBusy } from '../../store/selectors/agent'
import type { ActionItem, ChatMessage } from '../../types'
import styles from './Chat.module.css'

// Pending attachment type
interface PendingAttachment {
  name: string
  type: string
  size: number
  content: string           // base64 for small files; '' when serverPath is set
  serverPath?: string       // set after HTTP pre-upload for large files
  url?: string              // server URL returned with serverPath (for preview)
  uploadStatus?: 'uploading' | 'ready' | 'error'
}

interface ChatProps {
  /** Session whose timeline this chat renders and whose id outgoing messages carry. */
  sessionId: string
  /** Optional placeholder text for the input */
  placeholder?: string
}

// One row of the linear session timeline: a chat message or an inline
// activity item (action / reasoning block), merged by timestamp.
type TimelineEntry =
  | { kind: 'message'; ts: number; message: ChatMessage }
  | { kind: 'activity'; ts: number; item: ActionItem }

// One RENDERED row. Activity entries are grouped into chunks (consecutive
// items between chat bubbles); each chunk renders a clickable header row
// and, only when expanded, its item rows.
type DisplayRow =
  | { kind: 'message'; ts: number; message: ChatMessage }
  | {
      kind: 'chunkHeader'
      ts: number
      chunkId: string
      count: number
      expanded: boolean
      /** Chunk sits at the very end of the timeline (no bubble after it) —
       *  the one a busy run is currently appending to. */
      tail: boolean
      startTs: number
    }
  | { kind: 'activity'; ts: number; item: ActionItem }

// Slim view of a playbook for the suggestion chips under the input.
interface SuggestedPlaybook {
  id: string
  name: string
  emoji?: string
  description?: string
  prompt: string
}

const SUGGESTED_PLAYBOOK_COUNT = 3

// Chat-delivery actions — the ones whose visible form IS a chat bubble in
// this interface. A chunk whose only actions are these renders nothing at
// all (no header, no reasoning): the bubble speaks for itself. Platform
// sends (whatsapp/gmail/discord/... actions) are different action names
// and keep their chunk. Closed set of controlled action names.
const CHAT_SEND_ACTIONS = new Set(['send_message', 'send_message_with_attachment'])
const isChatSend = (item: ActionItem): boolean =>
  item.itemType === 'action' && CHAT_SEND_ACTIONS.has(normalizeActionName(item.name))

const MIC_LANGUAGES = [
  { code: 'en-US', label: 'EN', full: 'English' },
  { code: 'ja-JP', label: 'JA', full: '日本語' },
  { code: 'zh-CN', label: 'ZH', full: '中文 (简体)' },
  { code: 'zh-TW', label: 'ZH-TW', full: '中文 (繁體)' },
  { code: 'ko-KR', label: 'KO', full: '한국어' },
  { code: 'ar-SA', label: 'AR', full: 'العربية' },
  { code: 'es-ES', label: 'ES', full: 'Español' },
  { code: 'fr-FR', label: 'FR', full: 'Français' },
  { code: 'de-DE', label: 'DE', full: 'Deutsch' },
  { code: 'pt-BR', label: 'PT', full: 'Português' },
  { code: 'hi-IN', label: 'HI', full: 'हिन्दी' },
  { code: 'ru-RU', label: 'RU', full: 'Русский' },
  { code: 'it-IT', label: 'IT', full: 'Italiano' },
]

// Attachment limits
const MAX_ATTACHMENT_COUNT = 10
const MAX_TOTAL_SIZE_BYTES = 200 * 1024 * 1024   // 200MB hard cap
const HTTP_UPLOAD_THRESHOLD = 50 * 1024 * 1024   // >50MB → HTTP pre-upload

const formatFileSize = (bytes: number): string => {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
}

// Stable per-day key (local time) for grouping consecutive rows by date.
const getDateKey = (tsMs: number): string => {
  const d = new Date(tsMs)
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`
}

// Slack-style date divider label: "Today", "Yesterday", weekday for the
// last week, otherwise a full localized date.
const formatDateDivider = (tsMs: number): string => {
  const date = new Date(tsMs)
  const now = new Date()
  const sameDay = (a: Date, b: Date) =>
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()

  if (sameDay(date, now)) return 'Today'
  const yesterday = new Date(now)
  yesterday.setDate(yesterday.getDate() - 1)
  if (sameDay(date, yesterday)) return 'Yesterday'

  if (date.getFullYear() === now.getFullYear()) {
    return date.toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })
  }
  return date.toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' })
}

export function Chat({ sessionId, placeholder }: ChatProps) {
  const {
    connected,
    sendMessage,
    sendCommand,
    sendOptionClick,
    openFile,
    openFolder,
    lastSeenBySession,
    markSessionSeen,
    requestChatHistory,
    enhancedPrompt,
    enhancePrompt,
    clearEnhancedPrompt,
  } = useWebSocket()

  // Draft view (/session/new): renders an empty timeline with the normal
  // input. No history requests and no seen/unread bookkeeping — the real
  // session only exists after the backend answers the first send with
  // session_created (the context then navigates to /session/{id}).
  const isDraft = sessionId === 'new'

  const messages = useAppSelector(state => selectSessionMessages(state, sessionId))
  const activity = useAppSelector(state => selectSessionActivity(state, sessionId))
  const hasMoreMessages = useAppSelector(state => selectSessionHasMoreMessages(state, sessionId))
  const loadingOlderMessages = useAppSelector(state => selectSessionLoadingOlderMessages(state, sessionId))
  const oldestMessageTimestamp = useAppSelector(state => selectSessionOldestMessageTimestamp(state, sessionId))

  // Live status row: while a run is in flight, the timeline ends with ONE
  // persistent row that is EITHER the currently-running action OR the
  // "Working…" indicator — never both, never neither. The row itself never
  // unmounts between actions (only its content swaps), so the chat never
  // jumps up and down in the split moment between an action finishing and
  // the next one starting.
  //
  // busy is run-scoped and server-driven (session_busy events, optimistic
  // on send). The running action is taken from the newest activity item so
  // a stale 'running' item stuck mid-history can't hijack the row.
  // send_message is excluded: it isn't rendered as an action row (the chat
  // bubble is its visible form), so "Working…" stays up while it runs.
  const busy = useAppSelector(state => selectSessionBusy(state, sessionId))
  // The bubble itself retires the "Working…" row: once the newest thing
  // in the whole timeline is an agent reply bubble, the row is suppressed
  // in the SAME render that inserts the bubble — one layout change
  // instead of two (bubble-in, then busy=false unmounting the row a few
  // frames later), which was the run-end flicker. The later busy=false is
  // then a visual no-op. Mid-run progress bubbles don't stick: any newer
  // activity item brings the row back.
  const lastMsg = messages.length > 0 ? messages[messages.length - 1] : null
  const lastActivityTs =
    activity.length > 0 ? (activity[activity.length - 1].createdAt ?? 0) : 0
  const agentBubbleIsNewest =
    !!lastMsg && lastMsg.style === 'agent' && lastMsg.timestamp * 1000 >= lastActivityTs
  const showLiveRow =
    busy && connected && !agentBubbleIsNewest && (!isDraft || messages.length > 0)
  const { showToast } = useToast()

  // ONE linear timeline: chat messages + inline activity (reasoning blocks,
  // action blocks) merged by timestamp. Message timestamps are epoch
  // seconds; activity createdAt is epoch ms — normalize to ms.
  // Chat-send items stay in the timeline HERE so chunking can tell a
  // "reply-only" chunk apart from real work — they are dropped from the
  // rendered rows in the chunking pass below.
  const timeline = useMemo<TimelineEntry[]>(() => {
    const entries: TimelineEntry[] = []
    for (const message of messages) {
      entries.push({ kind: 'message', ts: message.timestamp * 1000, message })
    }
    for (const item of activity) {
      entries.push({ kind: 'activity', ts: item.createdAt ?? 0, item })
    }
    entries.sort((a, b) => a.ts - b.ts)
    return entries
  }, [messages, activity])

  // Chunk collapse state, keyed by the chunk's first item id. Chunks are
  // COLLAPSED by default: a slim header row stands in for the whole
  // reasoning+actions block. While the run is appending to the tail chunk
  // the collapsed header shows the working animation + elapsed time; once
  // settled it reads "Action steps · N" with no time. Clicking toggles.
  const [expandedChunks, setExpandedChunks] = useState<Record<string, boolean>>({})
  const toggleChunk = useCallback((chunkId: string) => {
    setExpandedChunks(prev => {
      const opening = !prev[chunkId]
      if (opening) {
        // Expanding inserts rows below the header. Release the bottom pin
        // so BOTH auto-scroll paths (new-row and content-growth) stay
        // quiet and the view remains anchored where the user clicked —
        // no jump to the bottom. Collapsing keeps the pin (content only
        // shrinks; the scroll position clamps naturally).
        stickToBottomRef.current = false
      }
      return { ...prev, [chunkId]: opening }
    })
  }, [])

  const { displayRows, tailChunk } = useMemo(() => {
    type TailChunkInfo = { chunkId: string; expanded: boolean; startTs: number }
    const rows: DisplayRow[] = []
    let chunk: ActionItem[] = []
    // Assigned inside flush(); the cast at the return defeats TS's bogus
    // "still null" narrowing (closure writes aren't flow-tracked).
    let tail: TailChunkInfo | null = null
    const flush = (isTail: boolean) => {
      if (chunk.length === 0) return
      const items = chunk
      chunk = []

      // Chat-send rows never render (the bubble is their visible form).
      const visible = items.filter(i => !isChatSend(i))
      const actionCount = visible.filter(i => i.itemType === 'action').length

      // A chunk renders ONLY when it contains at least one real action.
      // Action-less chunks (quick replies where the bubble speaks for
      // itself, or silent runs) render NOTHING — ever. This also keeps
      // quick-reply runs on ONE continuous "Working…" live row from start
      // to bubble: no header appears mid-run just to vanish at the end.
      if (actionCount === 0) return

      const chunkId = visible[0].id
      const expanded = !!expandedChunks[chunkId]
      const startTs = visible[0].createdAt ?? 0
      rows.push({
        kind: 'chunkHeader',
        ts: startTs,
        chunkId,
        // Header counts ACTIONS only — reasoning rows are commentary, not
        // executed work.
        count: actionCount,
        expanded,
        tail: isTail,
        startTs,
      })
      if (expanded) {
        for (const item of visible) {
          rows.push({ kind: 'activity', ts: item.createdAt ?? 0, item })
        }
      }
      if (isTail) tail = { chunkId, expanded, startTs }
    }
    for (const entry of timeline) {
      if (entry.kind === 'message') {
        flush(false)
        rows.push(entry)
      } else {
        chunk.push(entry.item)
      }
    }
    flush(true)
    return { displayRows: rows, tailChunk: tail as TailChunkInfo | null }
  }, [timeline, expandedChunks])

  const [input, setInput] = useState('')
  const [enhancing, setEnhancing] = useState(false)
  // Reply-to-bubble: set from an agent bubble's hover Reply action. The
  // next send carries the quoted original so the event stream records
  // which message the user replied to. No routing — session is explicit.
  const [replyTarget, setReplyTarget] = useState<{
    displayName: string
    originalContent: string
  } | null>(null)
  const dispatch = useAppDispatch()
  const pendingPrefill = useAppSelector(selectPendingPrefill)
  const [pendingAttachments, setPendingAttachments] = useState<PendingAttachment[]>([])
  const [attachmentError, setAttachmentError] = useState<string | null>(null)
  const [isDragOver, setIsDragOver] = useState(false)
  const [previewAttachment, setPreviewAttachment] = useState<PendingAttachment | null>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const autocompleteRef = useRef<SlashCommandAutocompleteHandle>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Voice input state
  const [isListening, setIsListening] = useState(false)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const recognitionRef = useRef<any>(null)
  const [micLang, setMicLang] = useState(() => {
    const browserLang = navigator.language || 'en-US'
    return MIC_LANGUAGES.some(l => l.code === browserLang) ? browserLang : 'en-US'
  })
  const [langOpen, setLangOpen] = useState(false)
  const langDropdownRef = useRef<HTMLDivElement>(null)

  // "+" menu inside the input shell (attach file / AI enhance)
  const [plusOpen, setPlusOpen] = useState(false)
  const plusMenuRef = useRef<HTMLDivElement>(null)

  // Playbook suggestion chips under the input + the full playbook browser.
  // The full list is cached; the displayed chips are a RANDOM sample,
  // re-rolled every time the draft hero is entered.
  const { send: sendSettings, onMessage: onSettingsMessage, isConnected: settingsConnected } = useSettingsWebSocket()
  const [allPlaybooks, setAllPlaybooks] = useState<SuggestedPlaybook[]>([])
  const [suggestedPlaybooks, setSuggestedPlaybooks] = useState<SuggestedPlaybook[]>([])
  const [playbookOpen, setPlaybookOpen] = useState(false)

  // Input history (terminal-style up/down arrow navigation)
  const inputHistoryRef = useRef<string[]>([])
  const historyIndexRef = useRef(-1)
  const parentRef = useRef<HTMLDivElement>(null)
  // Stick-to-bottom INTENT: true means "keep me pinned to the newest
  // content". Released ONLY by real user input (wheel up, touch drag,
  // scrollbar drag) — never by scroll events themselves. scrollTop moves
  // for non-user reasons all the time (the virtualizer shifts it when a
  // row above the offset is re-measured, the browser clamps it when the
  // canvas shrinks), so any heuristic that reads scroll position/direction
  // to infer intent misfires and silently kills auto-follow mid-run.
  // Re-engaged when the user returns to the bottom, clicks the jump
  // button, or sends a message.
  const stickToBottomRef = useRef(true)
  const prevRowCountRef = useRef(0)
  const hasInitialScrolled = useRef(false)
  const [showScrollToBottom, setShowScrollToBottom] = useState(false)

  // Ticker so live durations keep updating — running action rows AND the
  // collapsed tail chunk's "Working… <elapsed>" header (which ticks for
  // the whole run, even while only reasoning is streaming).
  const [, forceTick] = useState(0)
  useEffect(() => {
    const hasRunning = activity.some(a => a.status === 'running' || a.status === 'waiting')
    if (!hasRunning && !busy) return
    const interval = setInterval(() => forceTick(t => t + 1), 100)
    return () => clearInterval(interval)
  }, [activity, busy])

  const attachmentValidation = useMemo(() => {
    const totalSize = pendingAttachments.reduce((sum, att) => sum + att.size, 0)
    const count = pendingAttachments.length
    if (count > MAX_ATTACHMENT_COUNT) {
      return { valid: false, error: `Maximum ${MAX_ATTACHMENT_COUNT} files allowed. You have ${count} files.` }
    }
    if (totalSize > MAX_TOTAL_SIZE_BYTES) {
      return { valid: false, error: `Total size (${formatFileSize(totalSize)}) exceeds 200 MB limit.` }
    }
    return { valid: true, error: null }
  }, [pendingAttachments])

  // The live status row renders as one extra virtual row appended after
  // the timeline — but ONLY while the tail chunk is expanded (or no tail
  // chunk exists yet this run). A collapsed tail chunk's header already
  // carries the working state, so the live row would be redundant.
  const showLiveRowEffective = showLiveRow && (!tailChunk || tailChunk.expanded)
  const rowCount = displayRows.length + (showLiveRowEffective ? 1 : 0)

  // Fresh draft: the input floats at the vertical center of the panel
  // (hero layout). The first send adds the optimistic message row, which
  // flips this off and the animated bottom spacer eases the input down to
  // its docked position.
  const centered = isDraft && rowCount === 0

  // Draft mascot lifecycle: shown while centered; on the first send it
  // plays its exit dive (into the input box) and unmounts after the
  // animation instead of popping out of existence.
  const [mascotPhase, setMascotPhase] = useState<'shown' | 'leaving' | 'hidden'>(
    () => (centered ? 'shown' : 'hidden'),
  )
  useEffect(() => {
    if (centered) {
      setMascotPhase('shown')
      return
    }
    setMascotPhase(prev => (prev === 'shown' ? 'leaving' : prev))
  }, [centered])
  useEffect(() => {
    if (mascotPhase !== 'leaving') return
    const t = window.setTimeout(() => setMascotPhase('hidden'), DRAFT_MASCOT_EXIT_MS)
    return () => window.clearTimeout(t)
  }, [mascotPhase])

  const virtualizer = useVirtualizer({
    count: rowCount,
    getScrollElement: () => parentRef.current,
    // Honest per-kind estimates. When an estimate is far off (the old flat
    // 100 vs ~32px real activity rows), every measurement makes the
    // virtualizer shift scrollTop by the difference to keep content
    // stable — constant multi-pixel corrections that fought stick-to-
    // bottom and left phantom gaps. Close estimates make those
    // corrections negligible.
    estimateSize: (index) => {
      if (index >= displayRows.length) return 54 // live status row + bottom padding
      return displayRows[index].kind === 'message' ? 96 : 36
    },
    overscan: 5,
  })

  // "First unread" divider: frozen on mount so it doesn't chase the user
  // down the timeline as new messages arrive while they read.
  const lastSeenMessageId = lastSeenBySession[sessionId] ?? null
  const firstUnreadMessageIdRef = useRef<string | null | undefined>(undefined)

  // The component persists across /session/* routes (no key-remount — a
  // remount recreated the draft spacer in its final state and killed the
  // dock animation). So per-session UI state resets IN PLACE on a session
  // switch — except the draft→real handoff, which is the same conversation
  // continuing and must keep scroll/animation continuity.
  const prevSessionIdRef = useRef(sessionId)
  const sessionResetPendingRef = useRef(false)
  if (prevSessionIdRef.current !== sessionId) {
    const isDraftHandoff = prevSessionIdRef.current === 'new' && sessionId !== 'new'
    prevSessionIdRef.current = sessionId
    if (!isDraftHandoff) {
      firstUnreadMessageIdRef.current = undefined
      hasInitialScrolled.current = false
      prevRowCountRef.current = 0
      stickToBottomRef.current = true
      sessionResetPendingRef.current = true
    }
  }

  useEffect(() => {
    if (!sessionResetPendingRef.current) return
    sessionResetPendingRef.current = false
    setInput('')
    setReplyTarget(null)
    setExpandedChunks({})
    setPendingAttachments([])
    setAttachmentError(null)
    setIsDragOver(false)
    setPreviewAttachment(null)
    setPlusOpen(false)
    setLangOpen(false)
    setShowScrollToBottom(false)
    if (isListening) {
      try { recognitionRef.current?.stop() } catch { /* already stopped */ }
      setIsListening(false)
    }
  })

  if (firstUnreadMessageIdRef.current === undefined && messages.length > 0) {
    if (!lastSeenMessageId) {
      firstUnreadMessageIdRef.current = null
    } else {
      const lastSeenIdx = messages.findIndex(m => m.messageId === lastSeenMessageId)
      firstUnreadMessageIdRef.current =
        lastSeenIdx === -1 || lastSeenIdx === messages.length - 1
          ? null
          : messages[lastSeenIdx + 1].messageId
    }
  }
  const firstUnreadMessageId = firstUnreadMessageIdRef.current ?? null

  const getFirstUnreadIndex = useCallback(() => {
    if (!firstUnreadMessageId) return -1
    return displayRows.findIndex(
      e => e.kind === 'message' && e.message.messageId === firstUnreadMessageId,
    )
  }, [displayRows, firstUnreadMessageId])

  // Close language dropdown when clicking outside
  useEffect(() => {
    if (!langOpen) return
    const handler = (e: MouseEvent) => {
      if (langDropdownRef.current && !langDropdownRef.current.contains(e.target as Node)) {
        setLangOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [langOpen])

  // Close the "+" menu when clicking outside
  useEffect(() => {
    if (!plusOpen) return
    const handler = (e: MouseEvent) => {
      if (plusMenuRef.current && !plusMenuRef.current.contains(e.target as Node)) {
        setPlusOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [plusOpen])

  // Load the playbook catalog for the suggestion chips (same playbook_list
  // channel the modal uses; extra broadcasts are harmless).
  useEffect(() => {
    return onSettingsMessage('playbook_list', (data: unknown) => {
      const d = data as { success?: boolean; playbooks?: SuggestedPlaybook[] }
      if (d?.success && Array.isArray(d.playbooks)) {
        setAllPlaybooks(d.playbooks)
      }
    })
  }, [onSettingsMessage])

  useEffect(() => {
    if (!settingsConnected || allPlaybooks.length > 0) return
    sendSettings('playbook_list')
  }, [settingsConnected, allPlaybooks.length, sendSettings])

  // Re-roll the displayed chips (Fisher–Yates sample) each time the user
  // lands on the draft hero, so New Chat surfaces different playbooks
  // every visit instead of always the first N of the catalog.
  useEffect(() => {
    if (!isDraft || allPlaybooks.length === 0) return
    const pool = [...allPlaybooks]
    for (let i = pool.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1))
      ;[pool[i], pool[j]] = [pool[j], pool[i]]
    }
    setSuggestedPlaybooks(pool.slice(0, SUGGESTED_PLAYBOOK_COUNT))
  }, [isDraft, allPlaybooks])

  // Scroll bookkeeping. Scroll events only RE-ENGAGE the pin (reaching the
  // bottom) and drive the jump button + history loading — they never
  // release the pin, because scrollTop also moves programmatically (see
  // stickToBottomRef above). Releasing is handled by the input listeners
  // below, which fire only on real user gestures:
  //  - wheel up
  //  - touch drag downward (finger pulls content down = scrolling up)
  //  - scrollbar drag (pointer held down while the view leaves the bottom)
  useEffect(() => {
    const container = parentRef.current
    if (!container) return

    let pointerHeld = false

    const handleScroll = () => {
      const scrollTop = container.scrollTop
      const distFromBottom = container.scrollHeight - scrollTop - container.clientHeight
      const nearBottom = distFromBottom < 100

      if (nearBottom) {
        stickToBottomRef.current = true
      } else if (pointerHeld) {
        // The only scroll-driven release: the user is actively dragging
        // the scrollbar away from the bottom.
        stickToBottomRef.current = false
      }
      setShowScrollToBottom(!nearBottom && !stickToBottomRef.current)

      if (!isDraft && scrollTop < 100 && hasMoreMessages && !loadingOlderMessages && oldestMessageTimestamp !== undefined) {
        requestChatHistory(sessionId, oldestMessageTimestamp, 50)
      }
    }

    const handleWheel = (e: WheelEvent) => {
      // Guard on scrollTop > 0 so a wheel-up with nowhere to go doesn't
      // strand the pin released while everything still fits on screen.
      if (e.deltaY < 0 && container.scrollTop > 0) {
        stickToBottomRef.current = false
      }
    }

    let lastTouchY: number | null = null
    const handleTouchStart = (e: TouchEvent) => {
      lastTouchY = e.touches[0]?.clientY ?? null
    }
    const handleTouchMove = (e: TouchEvent) => {
      const y = e.touches[0]?.clientY
      if (y == null || lastTouchY == null) return
      if (y > lastTouchY && container.scrollTop > 0) {
        stickToBottomRef.current = false
      }
      lastTouchY = y
    }

    const handlePointerDown = () => { pointerHeld = true }
    const handlePointerUp = () => { pointerHeld = false }

    container.addEventListener('scroll', handleScroll)
    container.addEventListener('wheel', handleWheel, { passive: true })
    container.addEventListener('touchstart', handleTouchStart, { passive: true })
    container.addEventListener('touchmove', handleTouchMove, { passive: true })
    container.addEventListener('pointerdown', handlePointerDown)
    window.addEventListener('pointerup', handlePointerUp)
    return () => {
      container.removeEventListener('scroll', handleScroll)
      container.removeEventListener('wheel', handleWheel)
      container.removeEventListener('touchstart', handleTouchStart)
      container.removeEventListener('touchmove', handleTouchMove)
      container.removeEventListener('pointerdown', handlePointerDown)
      window.removeEventListener('pointerup', handlePointerUp)
    }
  }, [hasMoreMessages, loadingOlderMessages, oldestMessageTimestamp, requestChatHistory, sessionId, isDraft])

  // Instant jump to the true bottom (now + next frame, so post-commit
  // re-measures by the virtualizer are covered too). No smooth animation:
  // an animated scroll chasing a moving bottom lands short, which is what
  // caused the pin to give up mid-run.
  const pinToBottom = useCallback(() => {
    const container = parentRef.current
    if (!container) return
    container.scrollTop = container.scrollHeight
    requestAnimationFrame(() => {
      const c = parentRef.current
      if (c && stickToBottomRef.current) c.scrollTop = c.scrollHeight
    })
  }, [])

  const scrollToBottom = useCallback(() => {
    if (rowCount === 0) return
    stickToBottomRef.current = true
    pinToBottom()
    setShowScrollToBottom(false)
  }, [rowCount, pinToBottom])

  // Scroll to unread on mount; while stick-to-bottom is engaged, follow
  // new rows. rowCount includes the live status row.
  useEffect(() => {
    if (rowCount === 0) return

    const isNewRow = rowCount > prevRowCountRef.current
    prevRowCountRef.current = rowCount

    if (!hasInitialScrolled.current) {
      hasInitialScrolled.current = true
      const firstUnreadIdx = getFirstUnreadIndex()
      setTimeout(() => {
        if (firstUnreadIdx !== -1) {
          stickToBottomRef.current = false
          virtualizer.scrollToIndex(firstUnreadIdx, { align: 'start', behavior: 'auto' })
        } else {
          stickToBottomRef.current = true
          pinToBottom()
        }
        if (!isDraft) markSessionSeen(sessionId)
      }, 50)
    } else if (isNewRow && stickToBottomRef.current) {
      pinToBottom()
      if (!isDraft) markSessionSeen(sessionId)
    }
  }, [rowCount, virtualizer, getFirstUnreadIndex, markSessionSeen, sessionId, isDraft, pinToBottom])

  // Follow content that grows IN PLACE — streaming reasoning text makes an
  // existing row taller and pushes the live status row below the fold
  // without changing rowCount, so the effect above never fires. Every
  // re-measure changes getTotalSize(); while the pin is engaged, follow it.
  const totalContentSize = virtualizer.getTotalSize()
  useEffect(() => {
    if (!hasInitialScrolled.current || !stickToBottomRef.current) return
    pinToBottom()
  }, [totalContentSize, pinToBottom])

  const adjustTextareaHeight = useCallback(() => {
    const textarea = inputRef.current
    if (!textarea) return
    // When the textarea is empty, let CSS min-height control the height.
    // Reading scrollHeight on an empty textarea in a narrow container can
    // include wrapped placeholder text, which would balloon the input to
    // multiple visual rows.
    if (!textarea.value) {
      textarea.style.height = ''
      return
    }
    textarea.style.height = 'auto'
    textarea.style.height = `${textarea.scrollHeight}px`
  }, [])

  useLayoutEffect(() => {
    adjustTextareaHeight()
  }, [input, adjustTextareaHeight])

  // Consume a one-shot prefill payload from the chatInput slice (e.g. when the
  // user picks a playbook). Replaces the current input so the prompt is ready
  // to send or edit, then clears the payload so it doesn't re-apply.
  useEffect(() => {
    if (pendingPrefill === null) return
    setInput(pendingPrefill)
    dispatch(clearPendingPrefill())
    // Focus + move caret to the end after the textarea has updated.
    setTimeout(() => {
      const ta = inputRef.current
      if (ta) {
        ta.focus()
        const end = ta.value.length
        ta.setSelectionRange(end, end)
      }
    }, 0)
  }, [pendingPrefill, dispatch])

  // Consume enhanced prompt from context when WS response arrives
  useEffect(() => {
    if (enhancedPrompt === null) return
    setInput(enhancedPrompt)
    setEnhancing(false)
    clearEnhancedPrompt()
    inputRef.current?.focus()
  }, [enhancedPrompt, clearEnhancedPrompt])

  // Reset enhancing spinner if the WebSocket disconnects mid-request
  useEffect(() => {
    if (!connected) setEnhancing(false)
  }, [connected])

  const handleEnhancePrompt = useCallback(() => {
    if (!input.trim() || enhancing) return
    setEnhancing(true)
    enhancePrompt(input.trim())
  }, [input, enhancing, enhancePrompt])

  const handleOptionClick = useCallback((value: string, messageId: string) => {
    sendOptionClick(value, messageId, sessionId)
  }, [sendOptionClick, sessionId])

  // Reply action from an agent bubble — arm the reply bar and focus the
  // input so the user can type straight away.
  const handleChatReply = useCallback((displayName: string, originalContent: string) => {
    setReplyTarget({ displayName, originalContent })
  }, [])

  useEffect(() => {
    if (replyTarget) inputRef.current?.focus()
  }, [replyTarget])

  const toggleListening = useCallback(() => {
    if (isListening) {
      recognitionRef.current?.stop()
      setIsListening(false)
      return
    }

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const w = window as any
    const SpeechRecognitionAPI = w.SpeechRecognition || w.webkitSpeechRecognition

    if (!SpeechRecognitionAPI) {
      alert('Speech recognition is not supported in this browser.')
      return
    }

    const recognition = new SpeechRecognitionAPI()
    recognition.continuous = true
    recognition.interimResults = true
    recognition.lang = micLang

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    recognition.onresult = (event: any) => {
      let finalTranscript = ''
      for (let i = event.resultIndex; i < event.results.length; i++) {
        if (event.results[i].isFinal) {
          finalTranscript += event.results[i][0].transcript
        }
      }
      if (finalTranscript) {
        setInput(prev => prev + (prev.endsWith(' ') || prev === '' ? '' : ' ') + finalTranscript)
        if (inputRef.current) {
          inputRef.current.style.height = 'auto'
          inputRef.current.style.height = inputRef.current.scrollHeight + 'px'
        }
      }
    }

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    recognition.onerror = (event: any) => {
      setIsListening(false)
      if (event.error === 'not-allowed' || event.error === 'service-not-allowed') {
        alert('Microphone access denied. Please allow microphone permission in your browser settings.')
      }
    }
    recognition.onend = () => setIsListening(false)

    recognitionRef.current = recognition
    recognition.start()
    setIsListening(true)
    inputRef.current?.focus()
  }, [isListening, micLang])

  // Stop mic if component unmounts while listening
  useEffect(() => {
    return () => { recognitionRef.current?.abort() }
  }, [])

  const handleSend = () => {
    if (!attachmentValidation.valid) return
    if (input.trim() || pendingAttachments.length > 0) {
      // Save to input history
      if (input.trim()) {
        inputHistoryRef.current.push(input.trim())
      }
      historyIndexRef.current = -1

      // Stop mic if still listening when message is sent
      if (isListening) {
        recognitionRef.current?.stop()
        setIsListening(false)
      }

      const trimmed = input.trim()
      // Slash commands route through the dedicated command channel so no
      // optimistic user bubble is inserted — the backend's CommandExecutor
      // responds with system/error messages rather than echoing user input.
      // Attachments + slash command falls through to chat (commands don't
      // accept attachments), which preserves the existing behavior for that
      // edge case.
      const isSlashCommand = trimmed.startsWith('/') && pendingAttachments.length === 0
      if (isSlashCommand) {
        sendCommand(trimmed, sessionId)
      } else {
        sendMessage(
          trimmed,
          pendingAttachments.length > 0 ? pendingAttachments : undefined,
          sessionId,
          replyTarget ? { originalMessage: replyTarget.originalContent } : undefined,
        )
      }
      if (!connected) {
        showToast('info', 'Reconnecting — your message will send when the connection is restored.')
      }
      // Sending always snaps the view back to the newest content.
      stickToBottomRef.current = true
      setInput('')
      setReplyTarget(null)
      setPendingAttachments([])
      setAttachmentError(null)
      if (inputRef.current) {
        inputRef.current.style.height = 'auto'
      }
      inputRef.current?.focus()
    }
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Tab' && !e.shiftKey) {
      if (autocompleteRef.current?.handleTab()) {
        e.preventDefault()
        return
      }
    }
    if (e.key === 'ArrowUp') {
      if (autocompleteRef.current?.handleUpArrow()) {
        e.preventDefault()
        return
      }
    }
    if (e.key === 'ArrowDown') {
      if (autocompleteRef.current?.handleDownArrow()) {
        e.preventDefault()
        return
      }
    }
    if (e.nativeEvent.isComposing) {
      e.preventDefault()
      return
    }
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      if (autocompleteRef.current?.handleEnter()) {
        return
      }
      handleSend()
    } else if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
      const history = inputHistoryRef.current
      if (history.length === 0) return
      if (historyIndexRef.current === -1 && input.trim() !== '') return

      if (e.key === 'ArrowUp') {
        e.preventDefault()
        if (historyIndexRef.current === -1) {
          historyIndexRef.current = history.length - 1
        } else if (historyIndexRef.current > 0) {
          historyIndexRef.current--
        }
        setInput(history[historyIndexRef.current])
      } else if (e.key === 'ArrowDown') {
        e.preventDefault()
        if (autocompleteRef.current?.handleDownArrow()) {
          e.preventDefault()
          return
        }
        if (historyIndexRef.current === -1) return
        if (historyIndexRef.current < history.length - 1) {
          historyIndexRef.current++
          setInput(history[historyIndexRef.current])
        } else {
          historyIndexRef.current = -1
          setInput('')
        }
      }
    }
  }

  const handleAttachClick = () => {
    fileInputRef.current?.click()
  }

  const uploadChatAttachment = (file: globalThis.File, placeholder: PendingAttachment) => {
    const formData = new FormData()
    formData.append('file', file)

    const xhr = new XMLHttpRequest()

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          const data = JSON.parse(xhr.responseText)
          if (data.success) {
            setPendingAttachments(prev => prev.map(a =>
              a === placeholder
                ? { ...a, serverPath: data.serverPath, url: data.url, uploadStatus: 'ready' as const }
                : a
            ))
            return
          }
        } catch {}
      }
      setPendingAttachments(prev => prev.map(a =>
        a === placeholder ? { ...a, uploadStatus: 'error' as const } : a
      ))
      setAttachmentError(`Failed to upload "${file.name}".`)
    }

    xhr.onerror = () => {
      setPendingAttachments(prev => prev.map(a =>
        a === placeholder ? { ...a, uploadStatus: 'error' as const } : a
      ))
      setAttachmentError(`Failed to upload "${file.name}": network error.`)
    }

    const name = encodeURIComponent(file.name)
    const type = encodeURIComponent(file.type || 'application/octet-stream')
    xhr.open('POST', `/api/chat-attachments/upload?name=${name}&type=${type}`)
    xhr.send(formData)
  }

  const processFiles = async (files: globalThis.File[]) => {
    if (files.length === 0) return

    const totalFileCount = pendingAttachments.length + files.length
    if (totalFileCount > MAX_ATTACHMENT_COUNT) {
      setAttachmentError(`Maximum ${MAX_ATTACHMENT_COUNT} files allowed.`)
      return
    }

    let newTotalSize = pendingAttachments.reduce((sum, att) => sum + att.size, 0)

    // Validate sizes first before doing any I/O
    for (const file of files) {
      if (file.size > MAX_TOTAL_SIZE_BYTES) {
        setAttachmentError(`File "${file.name}" (${formatFileSize(file.size)}) exceeds the 200 MB limit.`)
        return
      }
      if (newTotalSize + file.size > MAX_TOTAL_SIZE_BYTES) {
        setAttachmentError(`Adding "${file.name}" would exceed the 200 MB total size limit.`)
        return
      }
      newTotalSize += file.size
    }

    setAttachmentError(null)

    for (const file of files) {
      if (file.size <= HTTP_UPLOAD_THRESHOLD) {
        // Small file: read to base64 inline
        try {
          const content = await readFileAsBase64(file)
          setPendingAttachments(prev => [...prev, {
            name: file.name,
            type: file.type || 'application/octet-stream',
            size: file.size,
            content,
          }])
        } catch {
          setAttachmentError(`Failed to read file "${file.name}".`)
          return
        }
      } else {
        // Large file: HTTP pre-upload so it never gets base64-encoded in memory
        const placeholder: PendingAttachment = {
          name: file.name,
          type: file.type || 'application/octet-stream',
          size: file.size,
          content: '',
          uploadStatus: 'uploading',
        }
        setPendingAttachments(prev => [...prev, placeholder])
        uploadChatAttachment(file, placeholder)
      }
    }
  }

  const handleFileSelect = async (e: ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files || files.length === 0) return
    await processFiles(Array.from(files))
    e.target.value = ''
  }

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragOver(true)
  }

  const handleDragLeave = (e: React.DragEvent) => {
    if (!e.currentTarget.contains(e.relatedTarget as Node)) {
      setIsDragOver(false)
    }
  }

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragOver(false)
    const files = Array.from(e.dataTransfer.files)
    await processFiles(files)
  }

  const handlePaste = async (e: React.ClipboardEvent) => {
    const files = Array.from(e.clipboardData.files)
    if (files.length === 0) return
    e.preventDefault()
    await processFiles(files)
  }

  const removeAttachment = (index: number) => {
    setPendingAttachments(prev => prev.filter((_, i) => i !== index))
    setAttachmentError(null)
  }

  const openPreview = (att: PendingAttachment) => {
    setPreviewAttachment(att)
  }

  const readFileAsBase64 = (file: globalThis.File): Promise<string> => {
    return new Promise((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = () => {
        const result = reader.result as string
        resolve(result.split(',')[1])
      }
      reader.onerror = reject
      reader.readAsDataURL(file)
    })
  }

  return (
    <div className={styles.chat}>
      <div className={styles.messagesArea}>
        <div className={styles.messagesContainer} ref={parentRef}>
          {rowCount === 0 ? null : (
            <div
              className={styles.timelineColumn}
              style={{ height: `${virtualizer.getTotalSize()}px` }}
            >
              {loadingOlderMessages && (
                <div style={{ textAlign: 'center', padding: '8px 0', color: 'var(--text-tertiary)', fontSize: 'var(--text-xs)' }}>
                  <Loader2 size={14} style={{ display: 'inline', animation: 'spin 1s linear infinite' }} /> Loading older messages...
                </div>
              )}
              {virtualizer.getVirtualItems().map((virtualItem) => {
                // The row after the last timeline entry is the live status
                // row (only present while a run is in flight). Its key is
                // constant so React keeps the same DOM node when the content
                // swaps between "Working…" and a running action — no
                // unmount/remount, no height bounce. Bottom padding keeps it
                // clear of the input bar.
                if (virtualItem.index >= displayRows.length) {
                  return (
                    <div
                      key="live-status-row"
                      data-index={virtualItem.index}
                      ref={virtualizer.measureElement}
                      style={{
                        position: 'absolute',
                        top: 0,
                        left: 0,
                        width: '100%',
                        transform: `translateY(${virtualItem.start}px)`,
                        paddingBottom: 24,
                      }}
                    >
                      {/* ALWAYS "Working…" — never the action name. */}
                      <TypingIndicatorRow />
                    </div>
                  )
                }
                const entry = displayRows[virtualItem.index]
                const prev = virtualItem.index > 0 ? displayRows[virtualItem.index - 1] : null
                const showDateDivider = !prev || getDateKey(prev.ts) !== getDateKey(entry.ts)
                const showUnreadDivider =
                  entry.kind === 'message' &&
                  firstUnreadMessageId !== null &&
                  entry.message.messageId === firstUnreadMessageId
                // Prefer clientId as the React key so that when a pending optimistic
                // message is reconciled with the server echo (messageId changes from
                // `pending:<cid>` to the real id), React reuses the same DOM node
                // instead of remounting the bubble.
                //
                // NOTE: rows must NOT get a CSS transition on transform. Rows
                // slide to new offsets whenever one above is re-measured, and
                // an animated translateY keeps expanding the container's
                // scrollHeight for 250ms AFTER React finished rendering — the
                // true bottom drifts away from any scroll position set at
                // render time, which broke stick-to-bottom (verified with a
                // live scroll trace: every pin landed at dist=0, then the
                // animation grew the page ~35px with no further events).
                const rowKey = entry.kind === 'message'
                  ? (entry.message.clientId || entry.message.messageId || virtualItem.index)
                  : entry.kind === 'chunkHeader'
                    ? `chunk:${entry.chunkId}`
                    : entry.item.id
                // Vertical rhythm (as bottom padding so the virtualizer
                // measures it): consecutive activity rows sit 10px apart so
                // a chunk reads as one work block; the block's last row
                // (before a bubble or the timeline end) gets an 18px break.
                // A collapsed chunk header IS the whole block, so it takes
                // the 18px break itself. Message rows own their spacing via
                // .messageWrapper's padding.
                const next = virtualItem.index < displayRows.length - 1
                  ? displayRows[virtualItem.index + 1]
                  : null
                const rowGap = entry.kind === 'activity'
                  ? (next?.kind === 'activity' ? 10 : 18)
                  : entry.kind === 'chunkHeader'
                    ? (entry.expanded ? 10 : 18)
                    : 0
                return (
                  <div
                    key={rowKey}
                    data-index={virtualItem.index}
                    ref={virtualizer.measureElement}
                    style={{
                      position: 'absolute',
                      top: 0,
                      left: 0,
                      width: '100%',
                      transform: `translateY(${virtualItem.start}px)`,
                      paddingBottom: rowGap,
                    }}
                  >
                    {showDateDivider && (
                      <div className={styles.dateDivider} role="separator" aria-label={formatDateDivider(entry.ts)}>
                        <span className={styles.dateDividerLine} />
                        <span className={styles.dateDividerLabel}>{formatDateDivider(entry.ts)}</span>
                        <span className={styles.dateDividerLine} />
                      </div>
                    )}
                    {showUnreadDivider && (
                      <div className={styles.unreadDivider} role="separator" aria-label="New messages">
                        <span className={styles.unreadDividerLine} />
                        <span className={styles.unreadDividerLabel}>New</span>
                        <span className={styles.unreadDividerLine} />
                      </div>
                    )}
                    {entry.kind === 'message' ? (
                      <ChatMessageItem
                        message={entry.message}
                        onOpenFile={openFile}
                        onOpenFolder={openFolder}
                        onOptionClick={handleOptionClick}
                        onReply={handleChatReply}
                      />
                    ) : entry.kind === 'chunkHeader' ? (
                      <ChunkHeaderRow
                        count={entry.count}
                        expanded={entry.expanded}
                        working={entry.tail && showLiveRow}
                        elapsedMs={
                          entry.tail && showLiveRow
                            ? Math.max(0, Date.now() - entry.startTs)
                            : undefined
                        }
                        onToggle={() => toggleChunk(entry.chunkId)}
                      />
                    ) : entry.item.itemType === 'reasoning' ? (
                      <ReasoningBlock item={entry.item} />
                    ) : (
                      <ActionBlock item={entry.item} />
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </div>
        {/* Draft hero: the lightweight mascot wanders just above the
            centered input. On the first send it dives into the input box
            (exit animation) and then unmounts. */}
        {mascotPhase !== 'hidden' && (
          <div className={styles.draftMascotDock}>
            <DraftMascot size={60} leaving={mascotPhase === 'leaving'} />
          </div>
        )}
        {showScrollToBottom && rowCount > 0 && (
          <button
            type="button"
            className={styles.scrollToBottomBtn}
            onClick={scrollToBottom}
            aria-label="Scroll to latest message"
            title="Scroll to latest message"
          >
            <ChevronDown size={18} />
          </button>
        )}
      </div>

      {/* Input area: one self-contained shell — textarea on top, controls
          row inside it ("+" menu on the left, mic/lang + send on the
          right). The area is width-capped and centered like the timeline. */}
      <div className={styles.inputArea}>
        <input ref={fileInputRef} type="file" multiple className={styles.hiddenFileInput} onChange={handleFileSelect} />
        <div
          className={`${styles.inputShell}${isDragOver ? ` ${styles.inputShellDragOver}` : ''}`}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
        >
          {replyTarget && (
            <div className={styles.replyBar}>
              <Reply size={14} />
              <span className={styles.replyText}>Replying to: <em>{replyTarget.displayName}</em></span>
              <button className={styles.replyCancel} onClick={() => setReplyTarget(null)} title="Cancel reply">
                <X size={14} />
              </button>
            </div>
          )}

          {(attachmentError || !attachmentValidation.valid) && (
            <div className={styles.attachmentError}>
              <AlertCircle size={14} />
              <span>{attachmentError || attachmentValidation.error}</span>
              <button className={styles.dismissError} onClick={() => setAttachmentError(null)} title="Dismiss">
                <X size={12} />
              </button>
            </div>
          )}

          {pendingAttachments.length > 0 && (
            <div className={styles.pendingAttachments}>
              {pendingAttachments.map((att, idx) => (
                <div key={idx} className={styles.pendingAttachment}>
                  <button
                    className={styles.pendingAttachmentBody}
                    onClick={() => openPreview(att)}
                    title="Click to preview"
                  >
                    {att.uploadStatus === 'uploading' ? (
                      <Loader2 size={12} className={styles.uploadingSpinner} />
                    ) : att.type.startsWith('image/') ? (
                      <img
                        src={att.content ? `data:${att.type};base64,${att.content}` : (att.url ?? '')}
                        alt={att.name}
                        className={styles.pendingImageThumb}
                      />
                    ) : (
                      <File size={12} />
                    )}
                    <span className={styles.pendingFileName} title={att.name}>{att.name}</span>
                    <span className={styles.pendingFileSize}>({formatFileSize(att.size)})</span>
                  </button>
                  <button className={styles.removeAttachment} onClick={() => removeAttachment(idx)} title="Remove">
                    <X size={12} />
                  </button>
                </div>
              ))}
            </div>
          )}

          <SlashCommandAutocomplete
            ref={autocompleteRef}
            input={input}
            onSelectItem={(name) => {
              setInput(`/${name}`)
              inputRef.current?.focus()
            }}
          />
          <textarea
            ref={inputRef}
            className={styles.input}
            placeholder={isListening ? 'Listening... speak now' : (placeholder || 'What can I do for you?')}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            onPaste={handlePaste}
            rows={1}
            lang={micLang}
            inputMode="text"
          />

          <div className={styles.inputControls}>
            <div className={styles.plusWrap} ref={plusMenuRef}>
              <button
                type="button"
                className={styles.plusBtn}
                onClick={() => setPlusOpen(o => !o)}
                title="Attach and tools"
                aria-label="Attach and tools"
                aria-expanded={plusOpen}
              >
                <Plus size={18} />
              </button>
              {plusOpen && (
                <div className={styles.plusMenu}>
                  <button
                    className={styles.plusMenuItem}
                    onClick={() => { setPlusOpen(false); handleAttachClick() }}
                  >
                    <Paperclip size={15} />
                    <span>Attach files</span>
                  </button>
                  <button
                    className={styles.plusMenuItem}
                    onClick={() => { setPlusOpen(false); handleEnhancePrompt() }}
                    disabled={!input.trim() || enhancing}
                  >
                    {enhancing
                      ? <Loader2 size={15} className={styles.uploadingSpinner} />
                      : <Sparkles size={15} />}
                    <span>{enhancing ? 'Enhancing…' : 'AI Enhance'}</span>
                  </button>
                </div>
              )}
            </div>

            <div className={styles.controlsRight}>
              <div className={styles.micGroup} ref={langDropdownRef}>
                <button
                  type="button"
                  className={`${styles.micCombo}${isListening ? ` ${styles.micComboActive}` : ''}`}
                  title={isListening ? 'Stop listening' : 'Voice input'}
                  onClick={toggleListening}
                >
                  <span className={styles.micIconWrap}>
                    {isListening ? <MicOff size={18} /> : <Mic size={18} />}
                    {isListening && <span className={styles.micPulseRing} />}
                  </span>
                </button>
                <button
                  className={`${styles.langBtn}${isListening ? ` ${styles.langBtnActive}` : ''}`}
                  onClick={() => !isListening && setLangOpen(o => !o)}
                  title="Speech language"
                  disabled={isListening}
                >
                  {MIC_LANGUAGES.find(l => l.code === micLang)?.label ?? 'EN'}
                </button>
                {langOpen && (
                  <div className={styles.langDropdown}>
                    {MIC_LANGUAGES.map(lang => (
                      <button
                        key={lang.code}
                        className={`${styles.langOption}${micLang === lang.code ? ` ${styles.langOptionActive}` : ''}`}
                        onClick={() => { setMicLang(lang.code); setLangOpen(false) }}
                      >
                        <span className={styles.langCode}>{lang.label}</span>
                        <span className={styles.langFull}>{lang.full}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <button
                type="button"
                className={styles.sendBtn}
                onClick={handleSend}
                disabled={(!input.trim() && pendingAttachments.length === 0) || !attachmentValidation.valid}
                title="Send"
                aria-label="Send message"
              >
                <Send size={16} />
              </button>
            </div>
          </div>
        </div>

        {/* Playbook suggestions: a few quick-start chips, ending with the
            entry point into the full playbook browser. Draft-only — they
            disappear once the first request is sent. */}
        {centered && (
        <div className={styles.suggestionsRow}>
          {suggestedPlaybooks.map(p => (
            <button
              key={p.id}
              type="button"
              className={styles.suggestionChip}
              title={p.description || p.name}
              onClick={() => dispatch(setPendingPrefill(p.prompt))}
            >
              <span aria-hidden="true">{p.emoji || '📖'}</span>
              <span className={styles.suggestionChipName}>{p.name}</span>
            </button>
          ))}
          <button
            type="button"
            className={`${styles.suggestionChip} ${styles.suggestionMore}`}
            onClick={() => setPlaybookOpen(true)}
          >
            <BookOpen size={13} />
            <span>All playbooks</span>
          </button>
        </div>
        )}
      </div>

      {/* Animated spacer: flex-grows below the input in a fresh draft so
          the input sits at the vertical center; collapses (with a
          transition) on the first send, easing the input down to the
          bottom where it stays docked. */}
      <div className={`${styles.bottomSpacer}${centered ? ` ${styles.bottomSpacerOpen}` : ''}`} aria-hidden="true" />

      <AttachmentPreviewModal
        isOpen={previewAttachment !== null}
        attachment={previewAttachment}
        onClose={() => setPreviewAttachment(null)}
      />
      <PlaybookModal isOpen={playbookOpen} onClose={() => setPlaybookOpen(false)} />
    </div>
  )
}
