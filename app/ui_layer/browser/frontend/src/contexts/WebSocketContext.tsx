import { createContext, useContext, useEffect, useMemo, useRef, useState, useCallback, ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { useStore } from 'react-redux'
import type {
  ChatMessage, SessionInfo, WSMessage, MetricsTimePeriod,
  AgentAppCreateRequest,
} from '../types'
import { QUESTION_DISMISSED } from '../types'
import i18n from '../i18n/config'
import { useToast } from './ToastContext'
import type { AppDispatch, RootState } from '../store'
import { getSocketClient } from '../store/socket/socketInstance'
import { onInboundMessage } from '../store/socket/socketMiddleware'
import type { OutboundEnvelope } from '../store/socket/types'
import { useAppDispatch } from '../store/hooks'
import {
  addOptimistic as messagesAddOptimistic,
  setLoadingOlder as messagesSetLoadingOlder,
  historyRequested as messagesHistoryRequested,
  markOptionSelected as messagesMarkOptionSelected,
  transferSession as messagesTransferSession,
} from '../store/slices/messagesSlice'
import { transferDraft as chatInputTransferDraft } from '../store/slices/chatInputSlice'
import { selectLastMessageIdBySession } from '../store/selectors/messages'
import { setLoading as onboardingSetLoading } from '../store/slices/onboardingSlice'
import {
  markChecking as localLlmMarkChecking,
  markInstalling as localLlmMarkInstalling,
  markInstallFailed as localLlmMarkInstallFailed,
  markStarting as localLlmMarkStarting,
  markPullingModel as localLlmMarkPullingModel,
} from '../store/slices/localLlmSlice'
import {
  setActiveId as agentAppSetActiveId,
  markLaunching as agentAppMarkLaunching,
  markStopping as agentAppMarkStopping,
} from '../store/slices/agentAppSlice'
import { setStatus, setSessionRunState } from '../store/slices/agentSlice'
import { setUiState } from '../store/slices/uiSlice'
import { selectUiState } from '../store/selectors/ui'
import { UI_STATE } from '../store/uiState'

// This context exposes the app's *actions* that talk to the backend, plus two
// rarely-changing local values. Server data (messages, sessions, metrics, …)
// lives in Redux and components read it with selectors: when the provider
// re-exposed every slice, each socket message re-rendered the whole app
// (docs/plans/ui-data-freshness-plan.md, RS-2.1). The context value is
// memoized and changes only when `initReceived` or `enhancedPrompt` does.

// Module-level reference to the shared SocketClient (transport, reconnect,
// outbox and dispatch live there).
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

// Undo optimistic UI for queued actions that expired before the connection
// came back (see SocketClient outbox TTL). Everything else is repaired by the
// reconnect resync (`init`, `agent_app_list`).
const rollbackExpiredSend = (envelope: OutboundEnvelope, dispatch: AppDispatch) => {
  switch (envelope.type) {
    case 'message':
    case 'question_response':
    case 'session_stop':
      if (typeof envelope.sessionId === 'string') {
        dispatch(setSessionRunState({ sessionId: envelope.sessionId, state: 'idle' }))
      }
      break
    case 'onboarding_step_submit':
    case 'onboarding_skip':
    case 'onboarding_back':
      dispatch(onboardingSetLoading(false))
      break
    case 'local_llm_install':
      dispatch(localLlmMarkInstallFailed(i18n.t('nav:connection.notConnectedRetry')))
      break
  }
}

interface WebSocketState {
  // Whether the initial 'init' message has been received from the backend
  initReceived: boolean
  // Enhanced prompt result from backend LLM
  enhancedPrompt: string | null
}

interface WebSocketContextType extends WebSocketState {
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
  // Per-session unread tracking (read with UI_STATE.chat.lastSeenMessageIds)
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
  // Pinned agent question: answer with a suggestion/free text, or dismiss
  sendQuestionAnswer: (messageId: string, value: string, sessionId: string, dismissed?: boolean) => void
  // Agent profile picture
  uploadAgentProfilePicture: (name: string, mimeType: string, contentBase64: string) => void
  removeAgentProfilePicture: () => void
  // Agent App methods
  createAgentApp: (data: AgentAppCreateRequest) => void
  requestAgentAppList: () => void
  launchAgentApp: (projectId: string) => void
  stopAgentApp: (projectId: string) => void
  deleteAgentApp: (projectId: string) => void
  setActiveAgentApp: (projectId: string | null) => void
  updateAgentAppTheme: (
    projectId: string,
    theme: {
      themeId: string
      customColors?: { bg: string; surface: string; text: string; accent: string }
    },
  ) => void
}

const WebSocketContext = createContext<WebSocketContextType | undefined>(undefined)

export function WebSocketProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<WebSocketState>({ initReceived: false, enhancedPrompt: null })
  const navigate = useNavigate()
  const navigateRef = useRef(navigate)
  navigateRef.current = navigate

  const dispatch = useAppDispatch()
  const store = useStore<RootState>()
  const { showToast } = useToast()

  // clientIds of messages sent from the draft view (sessionId "new") that
  // are still waiting for the backend to create their session. When a
  // session_created arrives carrying one of these clientIds, this client is
  // the sender and navigates from /session/new to the real session route.
  const pendingDraftClientIdsRef = useRef<Set<string>>(new Set())

  // Send-or-queue: delegate to the shared SocketClient which owns the
  // outbox and reconnect lifecycle. User actions (send, delete, launch,
  // onboarding steps, …) go through here so a click during a reconnect runs
  // once the connection is back (or expires with a toast, see below).
  // Sync requests (history pages, metric filters, subscriptions, lists,
  // status checks) stay connected-only: the views re-issue them on
  // reconnect, so queueing them would only duplicate work.
  const sendOrQueue = useCallback((payloadStr: string) => {
    client.sendString(payloadStr)
  }, [])

  const handleMessage = useCallback((msg: WSMessage) => {
    switch (msg.type) {
      case 'init': {
        // All init payload fields flow through slice handlers in
        // messageRegistry. The context only needs to flip the "we've seen
        // init" gate that App.tsx uses to unblock rendering.
        setState(prev => (prev.initReceived ? prev : { ...prev, initReceived: true }))
        break
      }

      // Almost all message handling lives in slices via the registry.
      // The case below is the residue: it needs react-router's navigate.

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
    // The backend pushes the Agent App list on every connect, and
    // ResourceSync refetches it on changes (store/resources).
    const unsubClose = client.onClose(() => {
      // Connection-status surface lives in agentSlice.
      dispatch(setStatus({ message: i18n.t('nav:connection.disconnectedReconnecting'), loading: false }))
    })
    // Delivered after the store has applied each message.
    const unsubMsg = onInboundMessage((msg) => handleMessage(msg as WSMessage))

    // Middleware already called connect() during store bootstrap; this is
    // a no-op when the connection is alive, but covers the edge case where
    // the provider mounts before the middleware has run.
    client.connect()

    return () => {
      unsubClose()
      unsubMsg()
    }
  }, [handleMessage, dispatch])

  // Queued actions that waited too long for the connection were dropped:
  // tell the user once per batch and undo their optimistic UI.
  useEffect(() => client.onOutboxExpired((expired) => {
    showToast('error', i18n.t('nav:connection.actionsNotSent', { count: expired.length }))
    for (const envelope of expired) rollbackExpiredSend(envelope, dispatch)
  }), [dispatch, showToast])

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

  // Mark a session's newest message as seen (unread-dot bookkeeping). Stored
  // as persisted UI state, so it survives reloads and syncs across tabs.
  const markSessionSeen = useCallback((sessionId: string) => {
    const current = store.getState()
    const lastId = selectLastMessageIdBySession(current)[sessionId]
    if (!lastId) return
    const seen = selectUiState(current, UI_STATE.chat.lastSeenMessageIds)
    if (seen[sessionId] === lastId) return
    dispatch(setUiState(UI_STATE.chat.lastSeenMessageIds, { ...seen, [sessionId]: lastId }))
  }, [dispatch, store])

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
    sendOrQueue(JSON.stringify({ type: 'option_click', messageId, value, sessionId }))
  }, [sendOrQueue, dispatch])

  // Answer (or dismiss) a pinned agent question. Optimistically records the
  // selection — which un-pins the box instantly — then round-trips through
  // the backend, which paints the answer as a user bubble and hands it to
  // the agent as a regular user-message trigger.
  const sendQuestionAnswer = useCallback((
    messageId: string,
    value: string,
    sessionId: string,
    dismissed = false,
  ) => {
    dispatch(messagesMarkOptionSelected({
      sessionId,
      messageId,
      value: dismissed ? QUESTION_DISMISSED : value,
    }))
    if (!dismissed) {
      // The answer wakes/feeds the agent — show the typing indicator now,
      // exactly like a normal send. The server's session_busy takes over.
      dispatch(setSessionRunState({ sessionId, state: 'running' }))
    }
    sendOrQueue(JSON.stringify({ type: 'question_response', messageId, value, sessionId, dismissed }))
  }, [sendOrQueue, dispatch])

  const uploadAgentProfilePicture = useCallback(
    (name: string, mimeType: string, contentBase64: string) => {
      sendOrQueue(JSON.stringify({
        type: 'agent_profile_picture_upload',
        name,
        mimeType,
        content: contentBase64,
      }))
    },
    [sendOrQueue]
  )

  const removeAgentProfilePicture = useCallback(() => {
    sendOrQueue(JSON.stringify({ type: 'agent_profile_picture_remove' }))
  }, [sendOrQueue])

  const openFile = useCallback((path: string) => {
    sendOrQueue(JSON.stringify({ type: 'open_file', path }))
  }, [sendOrQueue])

  const openFolder = useCallback((path: string) => {
    sendOrQueue(JSON.stringify({ type: 'open_folder', path }))
  }, [sendOrQueue])

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
    dispatch(onboardingSetLoading(true))
    sendOrQueue(JSON.stringify({ type: 'onboarding_step_submit', value }))
  }, [sendOrQueue, dispatch])

  const skipOnboardingStep = useCallback(() => {
    dispatch(onboardingSetLoading(true))
    sendOrQueue(JSON.stringify({ type: 'onboarding_skip' }))
  }, [sendOrQueue, dispatch])

  const goBackOnboardingStep = useCallback(() => {
    dispatch(onboardingSetLoading(true))
    sendOrQueue(JSON.stringify({ type: 'onboarding_back' }))
  }, [sendOrQueue, dispatch])

  // Local LLM (Ollama) methods. All state lives in localLlmSlice; these are
  // just send-helpers that also dispatch the optimistic pre-send transition.
  const checkLocalLLM = useCallback(() => {
    if (!client.isConnected) return
    dispatch(localLlmMarkChecking())
    client.sendString(JSON.stringify({ type: 'local_llm_check' }))
  }, [dispatch])

  const testLocalLLMConnection = useCallback((url: string) => {
    sendOrQueue(JSON.stringify({ type: 'local_llm_test', url }))
  }, [sendOrQueue])

  const installLocalLLM = useCallback(() => {
    dispatch(localLlmMarkInstalling())
    sendOrQueue(JSON.stringify({ type: 'local_llm_install' }))
  }, [sendOrQueue, dispatch])

  const startLocalLLM = useCallback(() => {
    dispatch(localLlmMarkStarting())
    sendOrQueue(JSON.stringify({ type: 'local_llm_start' }))
  }, [sendOrQueue, dispatch])

  const requestSuggestedModels = useCallback(() => {
    if (client.isConnected) {
      client.sendString(JSON.stringify({ type: 'local_llm_suggested_models' }))
    }
  }, [])

  const pullOllamaModel = useCallback((model: string) => {
    dispatch(localLlmMarkPullingModel())
    sendOrQueue(JSON.stringify({ type: 'local_llm_pull_model', model }))
  }, [sendOrQueue, dispatch])

  // Agent App methods
  const createAgentApp = useCallback((data: AgentAppCreateRequest) => {
    sendOrQueue(JSON.stringify({
      type: 'agent_app_create',
      ...data,
    }))
  }, [sendOrQueue])

  const requestAgentAppList = useCallback(() => {
    if (client.isConnected) {
      client.sendString(JSON.stringify({ type: 'agent_app_list' }))
    }
  }, [])

  const launchAgentApp = useCallback((projectId: string) => {
    // Optimistically flip to 'launching' so the button shows a spinner and
    // the content swaps to the launching screen immediately — launch can
    // take many seconds (install/build/start). The backend response
    // (agent_app_launch) resolves it to running or error.
    dispatch(agentAppMarkLaunching({ projectId }))
    sendOrQueue(JSON.stringify({
      type: 'agent_app_launch',
      projectId,
    }))
  }, [sendOrQueue, dispatch])

  const stopAgentApp = useCallback((projectId: string) => {
    // Optimistically flip to 'stopping' for immediate feedback; the backend
    // response (agent_app_stop) resolves it to stopped (or reverts on error).
    dispatch(agentAppMarkStopping({ projectId }))
    sendOrQueue(JSON.stringify({
      type: 'agent_app_stop',
      projectId,
    }))
  }, [sendOrQueue, dispatch])

  const deleteAgentApp = useCallback((projectId: string) => {
    sendOrQueue(JSON.stringify({
      type: 'agent_app_delete',
      projectId,
    }))
  }, [sendOrQueue])

  const setActiveAgentApp = useCallback((projectId: string | null) => {
    dispatch(agentAppSetActiveId(projectId))
  }, [dispatch])

  const updateAgentAppTheme = useCallback((
    projectId: string,
    theme: {
      themeId: string
      customColors?: { bg: string; surface: string; text: string; accent: string }
    },
  ) => {
    sendOrQueue(JSON.stringify({
      type: 'agent_app_theme_update',
      projectId,
      theme,
    }))
  }, [sendOrQueue])

  const value = useMemo<WebSocketContextType>(() => ({
    ...state,
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
    enhancePrompt,
    clearEnhancedPrompt,
    sendOptionClick,
    sendQuestionAnswer,
    uploadAgentProfilePicture,
    removeAgentProfilePicture,
    createAgentApp,
    requestAgentAppList,
    launchAgentApp,
    stopAgentApp,
    deleteAgentApp,
    setActiveAgentApp,
    updateAgentAppTheme,
  }), [
    state, sendMessage, sendCommand, stopSession, deleteSession, renameSession, clearSession,
    requestChatHistory, markSessionSeen, openFile, openFolder, requestFilteredMetrics,
    subscribeDashboardMetrics, unsubscribeDashboardMetrics, requestOnboardingStep,
    submitOnboardingStep, skipOnboardingStep, goBackOnboardingStep, checkLocalLLM,
    testLocalLLMConnection, installLocalLLM, startLocalLLM, requestSuggestedModels, pullOllamaModel,
    enhancePrompt, clearEnhancedPrompt, sendOptionClick, sendQuestionAnswer,
    uploadAgentProfilePicture, removeAgentProfilePicture, createAgentApp, requestAgentAppList,
    launchAgentApp, stopAgentApp, deleteAgentApp, setActiveAgentApp, updateAgentAppTheme,
  ])

  return (
    <WebSocketContext.Provider value={value}>
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
