import { createContext, useContext, useEffect, useRef, useState, useCallback, ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import type {
  ChatMessage, ActionItem, AgentStatus, SessionInfo, WSMessage, DashboardMetrics,
  FilteredDashboardMetrics, MetricsTimePeriod, OnboardingStep,
  LocalLLMState,
  SkillMeta,
  // Living UI types
  LivingUIProject, LivingUICreateRequest, LivingUIStatusUpdate, LivingUIStateUpdate,
} from '../types'
import { scheduleRefreshIframe } from '../pages/LivingUI/iframePool'
import { getSocketClient } from '../store/socket/socketInstance'
import { useAppDispatch, useAppSelector } from '../store/hooks'
import {
  addOptimistic as messagesAddOptimistic,
  setLoadingOlder as messagesSetLoadingOlder,
  historyRequested as messagesHistoryRequested,
  markOptionSelected as messagesMarkOptionSelected,
  transferSession as messagesTransferSession,
} from '../store/slices/messagesSlice'
import { transferDraft as chatInputTransferDraft } from '../store/slices/chatInputSlice'
import {
  selectAllMessages,
  selectLastMessageIdBySession,
} from '../store/selectors/messages'
import { selectAllActivity } from '../store/selectors/activity'
import { selectSessions } from '../store/selectors/sessions'
import {
  selectDashboardMetrics,
  selectFilteredMetricsCache,
} from '../store/selectors/dashboard'
import {
  setLoading as onboardingSetLoading,
} from '../store/slices/onboardingSlice'
import {
  selectOnboardingStep,
  selectOnboardingError,
  selectOnboardingLoading,
  selectNeedsHardOnboarding,
} from '../store/selectors/onboarding'
import {
  markChecking as localLlmMarkChecking,
  markInstalling as localLlmMarkInstalling,
  markInstallFailed as localLlmMarkInstallFailed,
  markStarting as localLlmMarkStarting,
  markPullingModel as localLlmMarkPullingModel,
} from '../store/slices/localLlmSlice'
import { selectLocalLlm } from '../store/selectors/localLlm'
import {
  setActiveId as livingUiSetActiveId,
  markLaunching as livingUiMarkLaunching,
  markStopping as livingUiMarkStopping,
  type LivingUITodo,
} from '../store/slices/livingUiSlice'
import {
  selectLivingUiProjects,
  selectLivingUiCreating,
  selectLivingUiTodos,
  selectActiveLivingUiId,
  selectLivingUiStates,
} from '../store/selectors/livingUi'
import {
  selectAgentName,
  selectAgentProfilePictureUrl,
  selectAgentProfilePictureHasCustom,
  selectAgentStatus,
  selectGuiMode,
  selectFootageUrl,
  selectSkillMeta,
} from '../store/selectors/agent'
import { setStatus, setSessionRunState } from '../store/slices/agentSlice'

// Module-level reference to the shared SocketClient. The transport (connect,
// reconnect, outbox, message dispatch) lives there; this context now only
// owns the React-side state shape that consumers depend on.
const client = getSocketClient()

// Pending attachment type for upload
interface PendingAttachment {
  name: string
  type: string
  size: number
  content: string       // base64 for small files; '' when serverPath is set
  serverPath?: string   // pre-uploaded via HTTP (large files)
}

// Unique-ish id for client-originating artifacts (optimistic chat messages
// awaiting server echo). Uses crypto.randomUUID when available, falls back
// to a cheap timestamp+random id on older runtimes without the
// secure-context requirement.
const newClientId = (): string =>
  typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `cid-${Date.now()}-${Math.random().toString(36).slice(2)}`

// Per-session "last seen message" map, persisted so unread dots survive
// reloads. Key: sessionId → messageId of the newest message seen.
const LAST_SEEN_STORAGE_KEY = 'lastSeenMessageIdBySession'

const loadLastSeenBySession = (): Record<string, string> => {
  try {
    const raw = localStorage.getItem(LAST_SEEN_STORAGE_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw)
    if (parsed && typeof parsed === 'object') return parsed as Record<string, string>
  } catch {
    // localStorage may be unavailable or corrupted
  }
  return {}
}

const persistLastSeenBySession = (map: Record<string, string>) => {
  try {
    localStorage.setItem(LAST_SEEN_STORAGE_KEY, JSON.stringify(map))
  } catch {
    // localStorage may be unavailable
  }
}

// Local-only React state. Slice-backed fields (messages, activity, sessions,
// living UI, ...) live in redux and are injected into the context value by
// the provider via useAppSelector.
interface WebSocketState {
  connected: boolean
  version: string
  // Whether the initial 'init' message has been received from the backend
  initReceived: boolean
  // Per-session unread tracking
  lastSeenBySession: Record<string, string>
  // Enhanced prompt result from backend LLM
  enhancedPrompt: string | null
}

interface WebSocketContextType extends WebSocketState {
  // Slice-backed (messagesSlice/activitySlice) aggregates across every
  // session — for global consumers (mascot, dashboard status). Per-session
  // timelines are read via selectors with a sessionId.
  messages: ChatMessage[]
  actions: ActionItem[]
  // Slice-backed (sessionsSlice).
  sessions: SessionInfo[]
  // Slice-backed (dashboardSlice).
  dashboardMetrics: DashboardMetrics | null
  filteredMetricsCache: Record<MetricsTimePeriod, FilteredDashboardMetrics | null>
  // Slice-backed (onboardingSlice).
  onboardingStep: OnboardingStep | null
  onboardingError: string | null
  onboardingLoading: boolean
  needsHardOnboarding: boolean
  // Slice-backed (localLlmSlice).
  localLLM: LocalLLMState
  // Slice-backed (livingUiSlice).
  livingUIProjects: LivingUIProject[]
  livingUICreating: LivingUIStatusUpdate | null
  livingUITodos: Record<string, LivingUITodo[]>
  activeLivingUIId: string | null
  livingUIStates: Record<string, LivingUIStateUpdate['state']>
  // Slice-backed (agentSlice).
  agentName: string
  agentProfilePictureUrl: string
  agentProfilePictureHasCustom: boolean
  status: AgentStatus
  guiMode: boolean
  footageUrl: string | null
  skillMeta: SkillMeta

  sendMessage: (
    content: string,
    attachments: PendingAttachment[] | undefined,
    sessionId: string,
    replyContext?: { originalMessage: string },
  ) => void
  sendCommand: (command: string, sessionId: string) => void
  // Force-stop a session's in-flight run (send button ↔ stop button)
  stopSession: (sessionId: string) => void
  // Session management (sessions are created lazily by the backend on the
  // first message sent with sessionId "new" — there is no create sender)
  deleteSession: (sessionId: string) => void
  renameSession: (sessionId: string, title: string) => void
  clearSession: (sessionId: string) => void
  requestChatHistory: (sessionId: string, beforeTimestamp?: number, limit?: number) => void
  // Per-session unread tracking
  markSessionSeen: (sessionId: string) => void
  openFile: (path: string) => void
  openFolder: (path: string) => void
  requestFilteredMetrics: (period: MetricsTimePeriod) => void
  subscribeDashboardMetrics: () => void
  unsubscribeDashboardMetrics: () => void
  // Onboarding methods
  requestOnboardingStep: () => void
  submitOnboardingStep: (value: string | string[] | Record<string, unknown>) => void
  skipOnboardingStep: () => void
  goBackOnboardingStep: () => void
  // Enhance prompt
  enhancePrompt: (content: string) => void
  clearEnhancedPrompt: () => void
  // Local LLM (Ollama) methods
  checkLocalLLM: () => void
  testLocalLLMConnection: (url: string) => void
  installLocalLLM: () => void
  startLocalLLM: () => void
  requestSuggestedModels: () => void
  pullOllamaModel: (model: string) => void
  // Option click (interactive buttons in chat)
  sendOptionClick: (value: string, messageId: string, sessionId: string) => void
  // Agent profile picture
  uploadAgentProfilePicture: (name: string, mimeType: string, contentBase64: string) => void
  removeAgentProfilePicture: () => void
  // Living UI methods
  createLivingUI: (data: LivingUICreateRequest) => void
  requestLivingUIList: () => void
  launchLivingUI: (projectId: string) => void
  stopLivingUI: (projectId: string) => void
  deleteLivingUI: (projectId: string) => void
  setActiveLivingUI: (projectId: string | null) => void
  updateLivingUITheme: (
    projectId: string,
    theme: {
      themeId: string
      customColors?: { bg: string; surface: string; text: string; accent: string }
    },
  ) => void
}

const defaultState: WebSocketState = {
  connected: false,
  version: '',
  initReceived: false,
  lastSeenBySession: loadLastSeenBySession(),
  enhancedPrompt: null,
}

const WebSocketContext = createContext<WebSocketContextType | undefined>(undefined)

export function WebSocketProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<WebSocketState>(defaultState)
  const navigate = useNavigate()
  const navigateRef = useRef(navigate)
  navigateRef.current = navigate

  // Slice-backed fields. Source of truth lives in redux; the provider
  // re-exposes them on the context so consumers keep a single hook.
  const dispatch = useAppDispatch()
  const messages = useAppSelector(selectAllMessages)
  const actions = useAppSelector(selectAllActivity)
  const sessions = useAppSelector(selectSessions)
  const lastMessageIdBySession = useAppSelector(selectLastMessageIdBySession)
  const dashboardMetrics = useAppSelector(selectDashboardMetrics)
  const filteredMetricsCache = useAppSelector(selectFilteredMetricsCache)
  const onboardingStep = useAppSelector(selectOnboardingStep)
  const onboardingError = useAppSelector(selectOnboardingError)
  const onboardingLoading = useAppSelector(selectOnboardingLoading)
  const needsHardOnboarding = useAppSelector(selectNeedsHardOnboarding)
  const localLLM = useAppSelector(selectLocalLlm)
  const livingUIProjects = useAppSelector(selectLivingUiProjects)
  const livingUICreating = useAppSelector(selectLivingUiCreating)
  const livingUITodos = useAppSelector(selectLivingUiTodos)
  const activeLivingUIId = useAppSelector(selectActiveLivingUiId)
  const livingUIStates = useAppSelector(selectLivingUiStates)
  const agentName = useAppSelector(selectAgentName)
  const agentProfilePictureUrl = useAppSelector(selectAgentProfilePictureUrl)
  const agentProfilePictureHasCustom = useAppSelector(selectAgentProfilePictureHasCustom)
  const status = useAppSelector(selectAgentStatus)
  const guiMode = useAppSelector(selectGuiMode)
  const footageUrl = useAppSelector(selectFootageUrl)
  const skillMeta = useAppSelector(selectSkillMeta)

  // Ref mirror so markSessionSeen doesn't need the map in its dep list.
  const lastMessageIdBySessionRef = useRef(lastMessageIdBySession)
  lastMessageIdBySessionRef.current = lastMessageIdBySession

  // clientIds of messages sent from the draft view (sessionId "new") that
  // are still waiting for the backend to create their session. When a
  // session_created arrives carrying one of these clientIds, this client is
  // the sender and navigates from /session/new to the real session route.
  const pendingDraftClientIdsRef = useRef<Set<string>>(new Set())

  // Send-or-queue: delegate to the shared SocketClient which owns the
  // outbox and reconnect lifecycle.
  const sendOrQueue = useCallback((payloadStr: string) => {
    client.sendString(payloadStr)
  }, [])

  const handleMessage = useCallback((msg: WSMessage) => {
    switch (msg.type) {
      case 'init': {
        // All init payload fields flow through slice handlers in
        // messageRegistry. The context only needs to flip the "we've seen
        // init" gate that App.tsx uses to unblock rendering.
        setState(prev => ({ ...prev, initReceived: true }))
        break
      }

      // Almost all message handling lives in slices via the registry.
      // The two cases below are the residue: one needs the iframe pool
      // (a non-state side effect), the other needs react-router's navigate.
      case 'living_ui_data_changed': {
        const { projectId } = msg.data as { projectId: string }
        if (projectId) scheduleRefreshIframe(projectId)
        break
      }

      case 'navigate': {
        const { path } = (msg.data || {}) as { path?: string }
        if (path) navigateRef.current(path)
        break
      }

      case 'session_created': {
        // sessionsSlice already upserted the session via the registry; here
        // we only handle the draft-view handoff. If this session was created
        // by a message THIS client sent from /session/new, drop the draft
        // bucket (the server echoes the user message into the real session)
        // and replace the route with the real session's.
        const { session, clientId, startsRun } = (msg.data || {}) as {
          session?: SessionInfo
          clientId?: string | null
          startsRun?: boolean
        }
        if (session && clientId && pendingDraftClientIdsRef.current.has(clientId)) {
          pendingDraftClientIdsRef.current.delete(clientId)
          // Move the draft bucket (the optimistic user bubble) into the
          // real session so the message is on screen from the first frame
          // after navigation — the server echo reconciles it by clientId
          // later. Dropping it here instead caused the "Working…" row to
          // appear before/without the user's message.
          dispatch(messagesTransferSession({ from: 'new', to: session.id }))
          // Carry over any composer text typed after the send but before
          // this reply arrived, so it isn't lost when the route switches.
          dispatch(chatInputTransferDraft({ from: 'new', to: session.id }))
          // Transfer the optimistic busy flag from the draft to the real
          // session so the typing indicator survives the handoff. A message
          // or skill send omits/sets startsRun and shows the indicator; a
          // state command like /clear sets startsRun=false and must NOT —
          // it starts no turn, so nothing would ever clear a phantom one.
          dispatch(setSessionRunState({ sessionId: 'new', state: 'idle' }))
          dispatch(setSessionRunState({
            sessionId: session.id,
            state: startsRun === false ? 'idle' : 'running',
          }))
          navigateRef.current(`/session/${session.id}`, { replace: true })
        }
        break
      }

      case 'prompt_enhanced': {
        const { content } = msg as unknown as { type: string; content: string }
        setState(prev => ({ ...prev, enhancedPrompt: content }))
        break
      }
    }
  }, [dispatch])

  useEffect(() => {
    const unsubOpen = client.onOpen(() => {
      setState(prev => ({ ...prev, connected: true }))
      // Backend expects an initial Living UI list request on every connect.
      client.sendString(JSON.stringify({ type: 'living_ui_list' }))
    })
    const unsubClose = client.onClose(() => {
      setState(prev => ({ ...prev, connected: false }))
      // Connection-status surface lives in agentSlice now.
      dispatch(setStatus({ message: 'Disconnected. Reconnecting...', loading: false }))
    })
    const unsubMsg = client.onAnyMessage((msg) => handleMessage(msg as WSMessage))

    // Middleware already called connect() during store bootstrap; this is
    // a no-op when the connection is alive, but covers the edge case where
    // the provider mounts before the middleware has run.
    client.connect()

    // If the singleton already opened before we subscribed (common: middleware
    // boots earlier than React mounting), sync the initial state now.
    if (client.isConnected) {
      setState(prev => ({ ...prev, connected: true }))
      client.sendString(JSON.stringify({ type: 'living_ui_list' }))
    }

    return () => {
      unsubOpen()
      unsubClose()
      unsubMsg()
    }
  }, [handleMessage])

  const sendMessage = useCallback((
    content: string,
    attachments: PendingAttachment[] | undefined,
    sessionId: string,
    replyContext?: { originalMessage: string },
  ) => {
    const clientId = newClientId()

    // Draft view send: remember the clientId so the session_created
    // broadcast (which precedes the chat_message echo) can be recognized as
    // ours and trigger the /session/new -> /session/{id} navigation.
    if (sessionId === 'new') {
      pendingDraftClientIdsRef.current.add(clientId)
    }

    // Slash commands are handled by the controller's command executor and
    // never produce a user chat bubble — skip the optimistic insert so a
    // "pending" bubble doesn't linger when the server has nothing to echo.
    const isSlashCommand = content.trimStart().startsWith('/')

    if (!isSlashCommand) {
      // Optimistic busy: show the typing indicator instantly; the server's
      // session_busy events take over from the run's first trigger.
      dispatch(setSessionRunState({ sessionId, state: 'running' }))

      // Optimistic insert: show the user's bubble immediately at reduced
      // opacity. The server echo (chat_message) replaces this entry in place
      // by matching on clientId, flipping `pending` -> false.
      const optimistic: ChatMessage = {
        sender: 'You',
        content,
        style: 'user',
        timestamp: Date.now() / 1000,
        messageId: `pending:${clientId}`,
        sessionId,
        clientId,
        pending: true,
      }
      dispatch(messagesAddOptimistic(optimistic))
    }

    sendOrQueue(JSON.stringify({
      type: 'message',
      content,
      sessionId,
      attachments: (attachments || []).map(att => att.serverPath
        ? { name: att.name, type: att.type, size: att.size, serverPath: att.serverPath }
        : { name: att.name, type: att.type, size: att.size, content: att.content }
      ),
      replyContext: replyContext || null,
      clientId,
    }))
  }, [sendOrQueue, dispatch])

  const sendCommand = useCallback((command: string, sessionId: string) => {
    const clientId = newClientId()

    // Draft view: a conversation-producing command (skills, /clear) makes the
    // backend create a real session and broadcast session_created carrying
    // this clientId. Register it so the handoff handler recognizes the new
    // session as ours and navigates /session/new -> /session/{id}, exactly
    // like a message send. Global commands produce no session_created and this
    // entry simply never matches — harmless.
    if (sessionId === 'new') {
      pendingDraftClientIdsRef.current.add(clientId)
    }

    sendOrQueue(JSON.stringify({ type: 'command', command, sessionId, clientId }))
  }, [sendOrQueue])

  // Force-stop a session's in-flight run (chat input's stop button).
  // Optimistically enters 'stopping' so the button spins instantly; the
  // server's session_busy broadcasts ('stopping' then terminal 'idle')
  // are authoritative from there.
  const stopSession = useCallback((sessionId: string) => {
    dispatch(setSessionRunState({ sessionId, state: 'stopping' }))
    sendOrQueue(JSON.stringify({ type: 'session_stop', sessionId }))
  }, [sendOrQueue, dispatch])

  // ── Session management ────────────────────────────────────────────

  const deleteSession = useCallback((sessionId: string) => {
    sendOrQueue(JSON.stringify({ type: 'session_delete', sessionId }))
  }, [sendOrQueue])

  const renameSession = useCallback((sessionId: string, title: string) => {
    sendOrQueue(JSON.stringify({ type: 'session_rename', sessionId, title }))
  }, [sendOrQueue])

  const clearSession = useCallback((sessionId: string) => {
    sendOrQueue(JSON.stringify({ type: 'session_clear', sessionId }))
  }, [sendOrQueue])

  const requestChatHistory = useCallback((
    sessionId: string,
    beforeTimestamp?: number,
    limit: number = 50,
  ) => {
    if (!client.isConnected) return
    // Scroll-up pagination shows the "Loading older messages" row; the
    // initial page load (no beforeTimestamp) only tracks its in-flight
    // state so the mount effect doesn't re-request.
    if (beforeTimestamp !== undefined) {
      dispatch(messagesSetLoadingOlder({ sessionId, loading: true }))
    } else {
      dispatch(messagesHistoryRequested({ sessionId }))
    }
    client.sendString(JSON.stringify({
      type: 'chat_history',
      sessionId,
      beforeTimestamp,
      limit,
    }))
  }, [dispatch])

  // Mark a session's newest message as seen (unread-dot bookkeeping).
  const markSessionSeen = useCallback((sessionId: string) => {
    const lastId = lastMessageIdBySessionRef.current[sessionId]
    if (!lastId) return
    setState(prev => {
      if (prev.lastSeenBySession[sessionId] === lastId) return prev
      const next = { ...prev.lastSeenBySession, [sessionId]: lastId }
      persistLastSeenBySession(next)
      return { ...prev, lastSeenBySession: next }
    })
  }, [])

  const enhancePrompt = useCallback((content: string) => {
    sendOrQueue(JSON.stringify({ type: 'enhance_prompt', content }))
  }, [sendOrQueue])

  const clearEnhancedPrompt = useCallback(() => {
    setState(prev => ({ ...prev, enhancedPrompt: null }))
  }, [])

  const sendOptionClick = useCallback((value: string, messageId: string, sessionId: string) => {
    // Optimistically record the selection in local state so the UI lock
    // survives virtualizer remounts, WS reconnects, and parent re-renders
    // without waiting for a backend round-trip or page refresh.
    dispatch(messagesMarkOptionSelected({ sessionId, messageId, value }))
    if (client.isConnected) {
      client.sendString(JSON.stringify({ type: 'option_click', messageId, value, sessionId }))
    }
  }, [dispatch])

  const uploadAgentProfilePicture = useCallback(
    (name: string, mimeType: string, contentBase64: string) => {
      if (client.isConnected) {
        client.sendString(JSON.stringify({
          type: 'agent_profile_picture_upload',
          name,
          mimeType,
          content: contentBase64,
        }))
      }
    },
    []
  )

  const removeAgentProfilePicture = useCallback(() => {
    if (client.isConnected) {
      client.sendString(JSON.stringify({ type: 'agent_profile_picture_remove' }))
    }
  }, [])

  const openFile = useCallback((path: string) => {
    if (client.isConnected) {
      client.sendString(JSON.stringify({ type: 'open_file', path }))
    }
  }, [])

  const openFolder = useCallback((path: string) => {
    if (client.isConnected) {
      client.sendString(JSON.stringify({ type: 'open_folder', path }))
    }
  }, [])

  const requestFilteredMetrics = useCallback((period: MetricsTimePeriod) => {
    if (client.isConnected) {
      client.sendString(JSON.stringify({
        type: 'dashboard_metrics_filter',
        period
      }))
    }
  }, [])

  const subscribeDashboardMetrics = useCallback(() => {
    if (client.isConnected) {
      client.sendString(JSON.stringify({ type: 'subscribe_dashboard_metrics' }))
    }
  }, [])

  const unsubscribeDashboardMetrics = useCallback(() => {
    if (client.isConnected) {
      client.sendString(JSON.stringify({ type: 'unsubscribe_dashboard_metrics' }))
    }
  }, [])

  // Onboarding methods
  const requestOnboardingStep = useCallback(() => {
    if (client.isConnected) {
      dispatch(onboardingSetLoading(true))
      client.sendString(JSON.stringify({ type: 'onboarding_step_get' }))
    }
  }, [dispatch])

  const submitOnboardingStep = useCallback((value: string | string[] | Record<string, unknown>) => {
    if (client.isConnected) {
      dispatch(onboardingSetLoading(true))
      client.sendString(JSON.stringify({ type: 'onboarding_step_submit', value }))
    }
  }, [dispatch])

  const skipOnboardingStep = useCallback(() => {
    if (client.isConnected) {
      dispatch(onboardingSetLoading(true))
      client.sendString(JSON.stringify({ type: 'onboarding_skip' }))
    }
  }, [dispatch])

  const goBackOnboardingStep = useCallback(() => {
    if (client.isConnected) {
      dispatch(onboardingSetLoading(true))
      client.sendString(JSON.stringify({ type: 'onboarding_back' }))
    }
  }, [dispatch])

  // Local LLM (Ollama) methods. All state lives in localLlmSlice; these are
  // just send-helpers that also dispatch the optimistic pre-send transition.
  const checkLocalLLM = useCallback(() => {
    if (!client.isConnected) return
    dispatch(localLlmMarkChecking())
    client.sendString(JSON.stringify({ type: 'local_llm_check' }))
  }, [dispatch])

  const testLocalLLMConnection = useCallback((url: string) => {
    if (client.isConnected) {
      client.sendString(JSON.stringify({ type: 'local_llm_test', url }))
    }
  }, [])

  const installLocalLLM = useCallback(() => {
    if (client.isConnected) {
      dispatch(localLlmMarkInstalling())
      client.sendString(JSON.stringify({ type: 'local_llm_install' }))
    } else {
      dispatch(localLlmMarkInstallFailed('Not connected — please wait a moment and retry.'))
    }
  }, [dispatch])

  const startLocalLLM = useCallback(() => {
    if (client.isConnected) {
      dispatch(localLlmMarkStarting())
      client.sendString(JSON.stringify({ type: 'local_llm_start' }))
    }
  }, [dispatch])

  const requestSuggestedModels = useCallback(() => {
    if (client.isConnected) {
      client.sendString(JSON.stringify({ type: 'local_llm_suggested_models' }))
    }
  }, [])

  const pullOllamaModel = useCallback((model: string) => {
    if (client.isConnected) {
      dispatch(localLlmMarkPullingModel())
      client.sendString(JSON.stringify({ type: 'local_llm_pull_model', model }))
    }
  }, [dispatch])

  // Living UI methods
  const createLivingUI = useCallback((data: LivingUICreateRequest) => {
    if (client.isConnected) {
      client.sendString(JSON.stringify({
        type: 'living_ui_create',
        ...data,
      }))
    }
  }, [])

  const requestLivingUIList = useCallback(() => {
    if (client.isConnected) {
      client.sendString(JSON.stringify({ type: 'living_ui_list' }))
    }
  }, [])

  const launchLivingUI = useCallback((projectId: string) => {
    if (client.isConnected) {
      // Optimistically flip to 'launching' so the button shows a spinner and
      // the content swaps to the launching screen immediately — launch can
      // take many seconds (install/build/start). The backend response
      // (living_ui_launch) resolves it to running or error.
      dispatch(livingUiMarkLaunching({ projectId }))
      client.sendString(JSON.stringify({
        type: 'living_ui_launch',
        projectId,
      }))
    }
  }, [dispatch])

  const stopLivingUI = useCallback((projectId: string) => {
    if (client.isConnected) {
      // Optimistically flip to 'stopping' for immediate feedback; the backend
      // response (living_ui_stop) resolves it to stopped (or reverts on error).
      dispatch(livingUiMarkStopping({ projectId }))
      client.sendString(JSON.stringify({
        type: 'living_ui_stop',
        projectId,
      }))
    }
  }, [dispatch])

  const deleteLivingUI = useCallback((projectId: string) => {
    if (client.isConnected) {
      client.sendString(JSON.stringify({
        type: 'living_ui_delete',
        projectId,
      }))
    }
  }, [])

  const setActiveLivingUI = useCallback((projectId: string | null) => {
    dispatch(livingUiSetActiveId(projectId))
  }, [dispatch])

  const updateLivingUITheme = useCallback((
    projectId: string,
    theme: {
      themeId: string
      customColors?: { bg: string; surface: string; text: string; accent: string }
    },
  ) => {
    if (client.isConnected) {
      client.sendString(JSON.stringify({
        type: 'living_ui_theme_update',
        projectId,
        theme,
      }))
    }
  }, [])

  return (
    <WebSocketContext.Provider
      value={{
        ...state,
        // Slice-backed fields injected here so consumers use a single hook.
        messages,
        actions,
        sessions,
        dashboardMetrics,
        filteredMetricsCache,
        onboardingStep,
        onboardingError,
        onboardingLoading,
        needsHardOnboarding,
        localLLM,
        livingUIProjects,
        livingUICreating,
        livingUITodos,
        activeLivingUIId,
        livingUIStates,
        agentName,
        agentProfilePictureUrl,
        agentProfilePictureHasCustom,
        status,
        guiMode,
        footageUrl,
        skillMeta,
        sendMessage,
        sendCommand,
        stopSession,
        deleteSession,
        renameSession,
        clearSession,
        requestChatHistory,
        markSessionSeen,
        openFile,
        openFolder,
        requestFilteredMetrics,
        subscribeDashboardMetrics,
        unsubscribeDashboardMetrics,
        requestOnboardingStep,
        submitOnboardingStep,
        skipOnboardingStep,
        goBackOnboardingStep,
        checkLocalLLM,
        testLocalLLMConnection,
        installLocalLLM,
        startLocalLLM,
        requestSuggestedModels,
        pullOllamaModel,
        enhancedPrompt: state.enhancedPrompt,
        enhancePrompt,
        clearEnhancedPrompt,
        sendOptionClick,
        uploadAgentProfilePicture,
        removeAgentProfilePicture,
        // Living UI methods
        createLivingUI,
        requestLivingUIList,
        launchLivingUI,
        stopLivingUI,
        deleteLivingUI,
        setActiveLivingUI,
        updateLivingUITheme,
      }}
    >
      {children}
    </WebSocketContext.Provider>
  )
}


export function useWebSocket() {
  const context = useContext(WebSocketContext)
  if (!context) {
    throw new Error('useWebSocket must be used within a WebSocketProvider')
  }
  return context
}
