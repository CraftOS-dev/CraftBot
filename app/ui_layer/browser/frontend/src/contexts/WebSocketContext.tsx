import React, { createContext, useContext, useEffect, useRef, useState, useCallback, ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import type {
  ChatMessage, ActionItem, AgentStatus, InitialState, WSMessage, DashboardMetrics,
  FilteredDashboardMetrics, MetricsTimePeriod, OnboardingStep,
  OnboardingStepResponse, OnboardingSubmitResponse, OnboardingCompleteResponse,
  SkillMeta,
  // Living UI types
  LivingUIProject, LivingUICreateRequest, LivingUIStatusUpdate, LivingUIStateUpdate,
  LivingUITodo, LivingUITodosUpdate,
  LivingUICreateResponse, LivingUIListResponse, LivingUILaunchResponse, LivingUIStopResponse, LivingUIDeleteResponse
} from '../types'
import { scheduleRefreshIframe } from '../pages/LivingUI/iframePool'
import { getSocketClient } from '../store/socket/socketInstance'
import { useAppDispatch, useAppSelector } from '../store/hooks'
import {
  addOptimistic as messagesAddOptimistic,
  setLoadingOlder as messagesSetLoadingOlder,
  markOptionSelected as messagesMarkOptionSelected,
  clear as messagesClear,
} from '../store/slices/messagesSlice'
import {
  selectAllMessages,
  selectHasMoreMessages,
  selectLoadingOlderMessages,
  selectOldestMessageTimestamp,
} from '../store/selectors/messages'
import {
  setLoadingOlder as tasksSetLoadingOlder,
  setCancellingTaskId as tasksSetCancellingTaskId,
} from '../store/slices/tasksSlice'
import {
  selectAllActions,
  selectHasMoreActions,
  selectLoadingOlderActions,
  selectCancellingTaskId,
  selectOldestTaskCreatedAt,
} from '../store/selectors/tasks'
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
  setActiveId as livingUiSetActiveId,
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
  selectCurrentTask,
  selectGuiMode,
  selectFootageUrl,
  selectSkillMeta,
} from '../store/selectors/agent'
import { setStatus } from '../store/slices/agentSlice'

// Module-level reference to the shared SocketClient. The transport (connect,
// reconnect, outbox, message dispatch) lives there; this context now only
// owns the React-side state shape that consumers depend on.
const client = getSocketClient()

// Pending attachment type for upload
interface PendingAttachment {
  name: string
  type: string
  size: number
  content: string  // base64
}

// Reply target for reply-to-chat/task feature
interface ReplyTarget {
  type: 'chat' | 'task'
  sessionId?: string       // May be undefined for old messages without session tracking
  displayName: string      // Truncated preview for UI display
  originalContent: string  // Full content for agent context
}

// Reply context sent with message
interface ReplyContext {
  sessionId?: string
  originalMessage: string
}

// Unique-ish id for client-originating artifacts (optimistic chat messages
// awaiting server echo). Uses crypto.randomUUID when available, falls back
// to a cheap timestamp+random id on older runtimes without the
// secure-context requirement.
const newClientId = (): string =>
  typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `cid-${Date.now()}-${Math.random().toString(36).slice(2)}`

// Local-only React state. Slice-backed fields (messages, actions, pagination,
// cancellingTaskId) live in redux and are injected into the context value by
// the provider via useAppSelector.
interface WebSocketState {
  connected: boolean
  version: string
  // Whether the initial 'init' message has been received from the backend
  initReceived: boolean
  // Unread message tracking
  lastSeenMessageId: string | null
  // Reply state for reply-to-chat/task feature
  replyTarget: ReplyTarget | null
}

interface WebSocketContextType extends WebSocketState {
  // Slice-backed (messagesSlice). Provider injects via useAppSelector.
  messages: ChatMessage[]
  hasMoreMessages: boolean
  loadingOlderMessages: boolean
  // Slice-backed (tasksSlice).
  actions: ActionItem[]
  hasMoreActions: boolean
  loadingOlderActions: boolean
  cancellingTaskId: string | null
  // Slice-backed (dashboardSlice).
  dashboardMetrics: DashboardMetrics | null
  filteredMetricsCache: Record<MetricsTimePeriod, FilteredDashboardMetrics | null>
  // Slice-backed (onboardingSlice).
  onboardingStep: OnboardingStep | null
  onboardingError: string | null
  onboardingLoading: boolean
  needsHardOnboarding: boolean
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
  currentTask: { id: string; name: string } | null
  guiMode: boolean
  footageUrl: string | null
  skillMeta: SkillMeta

  sendMessage: (content: string, attachments?: PendingAttachment[], replyContext?: ReplyContext, livingUIId?: string) => void
  sendCommand: (command: string) => void
  clearMessages: () => void
  cancelTask: (taskId: string) => void
  openFile: (path: string) => void
  openFolder: (path: string) => void
  requestFilteredMetrics: (period: MetricsTimePeriod) => void
  subscribeDashboardMetrics: () => void
  unsubscribeDashboardMetrics: () => void
  // Onboarding methods
  requestOnboardingStep: () => void
  submitOnboardingStep: (value: string | string[]) => void
  skipOnboardingStep: () => void
  goBackOnboardingStep: () => void
  // Unread message tracking
  markMessagesAsSeen: () => void
  // Reply-to-chat/task methods
  setReplyTarget: (target: ReplyTarget) => void
  clearReplyTarget: () => void
  // Chat pagination
  loadOlderMessages: () => void
  // Action pagination
  loadOlderActions: () => void
  // Option click (interactive buttons in chat)
  sendOptionClick: (value: string, sessionId?: string, messageId?: string) => void
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
}

// Initialize lastSeenMessageId from localStorage
const getInitialLastSeenMessageId = (): string | null => {
  try {
    return localStorage.getItem('lastSeenMessageId')
  } catch {
    return null
  }
}

const defaultState: WebSocketState = {
  connected: false,
  version: '',
  initReceived: false,
  // Unread message tracking
  lastSeenMessageId: getInitialLastSeenMessageId(),
  // Reply state
  replyTarget: null,
}

const WebSocketContext = createContext<WebSocketContextType | undefined>(undefined)

export function WebSocketProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<WebSocketState>(defaultState)
  const navigate = useNavigate()
  const navigateRef = useRef(navigate)
  navigateRef.current = navigate

  // Slice-backed fields. Source of truth lives in messagesSlice; the
  // provider re-exposes them on the context so existing consumers keep
  // working without code changes.
  const dispatch = useAppDispatch()
  const messages = useAppSelector(selectAllMessages)
  const hasMoreMessages = useAppSelector(selectHasMoreMessages)
  const loadingOlderMessages = useAppSelector(selectLoadingOlderMessages)
  const oldestMessageTimestamp = useAppSelector(selectOldestMessageTimestamp)
  const actions = useAppSelector(selectAllActions)
  const hasMoreActions = useAppSelector(selectHasMoreActions)
  const loadingOlderActions = useAppSelector(selectLoadingOlderActions)
  const cancellingTaskId = useAppSelector(selectCancellingTaskId)
  const oldestTaskCreatedAt = useAppSelector(selectOldestTaskCreatedAt)
  const dashboardMetrics = useAppSelector(selectDashboardMetrics)
  const filteredMetricsCache = useAppSelector(selectFilteredMetricsCache)
  const onboardingStep = useAppSelector(selectOnboardingStep)
  const onboardingError = useAppSelector(selectOnboardingError)
  const onboardingLoading = useAppSelector(selectOnboardingLoading)
  const needsHardOnboarding = useAppSelector(selectNeedsHardOnboarding)
  const livingUIProjects = useAppSelector(selectLivingUiProjects)
  const livingUICreating = useAppSelector(selectLivingUiCreating)
  const livingUITodos = useAppSelector(selectLivingUiTodos)
  const activeLivingUIId = useAppSelector(selectActiveLivingUiId)
  const livingUIStates = useAppSelector(selectLivingUiStates)
  const agentName = useAppSelector(selectAgentName)
  const agentProfilePictureUrl = useAppSelector(selectAgentProfilePictureUrl)
  const agentProfilePictureHasCustom = useAppSelector(selectAgentProfilePictureHasCustom)
  const status = useAppSelector(selectAgentStatus)
  const currentTask = useAppSelector(selectCurrentTask)
  const guiMode = useAppSelector(selectGuiMode)
  const footageUrl = useAppSelector(selectFootageUrl)
  const skillMeta = useAppSelector(selectSkillMeta)

  // Send-or-queue: delegate to the shared SocketClient which owns the
  // outbox and reconnect lifecycle. Kept as a hook-stable callback so the
  // existing useCallback consumers don't need to be touched.
  const sendOrQueue = useCallback((payloadStr: string) => {
    client.sendString(payloadStr)
  }, [])

  const handleMessage = useCallback((msg: WSMessage) => {
    switch (msg.type) {
      case 'init': {
        // All init payload fields now flow through slice handlers in
        // messageRegistry. The context only needs to flip the "we've seen
        // init" gate that App.tsx uses to unblock rendering.
        setState(prev => ({ ...prev, initReceived: true }))
        break
      }

      // Almost all message handling now lives in slices via the registry.
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
    }
  }, [])

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
    }

    return () => {
      unsubOpen()
      unsubClose()
      unsubMsg()
    }
  }, [handleMessage])

  const loadOlderMessages = useCallback(() => {
    if (!hasMoreMessages || loadingOlderMessages || oldestMessageTimestamp === undefined) return
    if (!client.isConnected) return

    dispatch(messagesSetLoadingOlder(true))
    client.sendString(JSON.stringify({
      type: 'chat_history',
      beforeTimestamp: oldestMessageTimestamp,
      limit: 50,
    }))
  }, [hasMoreMessages, loadingOlderMessages, oldestMessageTimestamp, dispatch])

  const loadOlderActions = useCallback(() => {
    if (!hasMoreActions || loadingOlderActions || oldestTaskCreatedAt === undefined) return
    if (!client.isConnected) return

    dispatch(tasksSetLoadingOlder(true))
    client.sendString(JSON.stringify({
      type: 'action_history',
      beforeTimestamp: oldestTaskCreatedAt,
      limit: 15,
    }))
  }, [hasMoreActions, loadingOlderActions, oldestTaskCreatedAt, dispatch])

  const sendMessage = useCallback((
    content: string,
    attachments?: PendingAttachment[],
    replyContext?: ReplyContext,
    livingUIId?: string,
  ) => {
    const clientId = newClientId()

    // Slash commands are handled by the controller's command executor and
    // never produce a user chat bubble — skip the optimistic insert so a
    // "pending" bubble doesn't linger when the server has nothing to echo.
    const isSlashCommand = content.trimStart().startsWith('/')

    if (!isSlashCommand) {
      // Optimistic insert: show the user's bubble immediately at reduced opacity.
      // The server echo (case 'chat_message') will replace this entry in place by
      // matching on clientId, flipping `pending` -> false.
      const optimistic: ChatMessage = {
        sender: 'You',
        content,
        style: 'user',
        timestamp: Date.now() / 1000,
        messageId: `pending:${clientId}`,
        clientId,
        pending: true,
      }
      dispatch(messagesAddOptimistic(optimistic))
    }

    sendOrQueue(JSON.stringify({
      type: 'message',
      content,
      attachments: attachments || [],
      replyContext: replyContext || null,
      livingUIId: livingUIId || null,
      clientId,
    }))
  }, [sendOrQueue, dispatch])

  const sendCommand = useCallback((command: string) => {
    sendOrQueue(JSON.stringify({ type: 'command', command }))
  }, [sendOrQueue])

  const clearMessages = useCallback(() => {
    dispatch(messagesClear())
  }, [dispatch])

  const cancelTask = useCallback((taskId: string) => {
    if (client.isConnected) {
      dispatch(tasksSetCancellingTaskId(taskId))
      client.sendString(JSON.stringify({ type: 'task_cancel', taskId }))
    }
  }, [dispatch])

  const sendOptionClick = useCallback((value: string, sessionId?: string, messageId?: string) => {
    // Optimistically record the selection in local state so the UI lock
    // survives virtualizer remounts, WS reconnects, and parent re-renders
    // without waiting for a backend round-trip or page refresh.
    if (messageId) {
      dispatch(messagesMarkOptionSelected({ messageId, value }))
    }
    if (client.isConnected) {
      client.sendString(JSON.stringify({ type: 'option_click', value, sessionId, messageId }))
    }
  }, [])

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

  const submitOnboardingStep = useCallback((value: string | string[]) => {
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

  // Mark all current messages as seen
  const markMessagesAsSeen = useCallback(() => {
    if (messages.length === 0) return
    const lastId = messages[messages.length - 1].messageId
    if (!lastId) return
    setState(prev => {
      if (lastId === prev.lastSeenMessageId) return prev
      try {
        localStorage.setItem('lastSeenMessageId', lastId)
      } catch {
        // localStorage may be unavailable
      }
      return { ...prev, lastSeenMessageId: lastId }
    })
  }, [messages])

  // Set reply target for reply-to-chat/task feature
  const setReplyTarget = useCallback((target: ReplyTarget) => {
    setState(prev => ({ ...prev, replyTarget: target }))
  }, [])

  // Clear reply target
  const clearReplyTarget = useCallback(() => {
    setState(prev => ({ ...prev, replyTarget: null }))
  }, [])

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
      // The backend response (living_ui_launch) will flip status to running.
      // No optimistic transition here — the existing 'launching' literal
      // wasn't part of LivingUIStatus and was a no-op for the UI.
      client.sendString(JSON.stringify({
        type: 'living_ui_launch',
        projectId,
      }))
    }
  }, [])

  const stopLivingUI = useCallback((projectId: string) => {
    if (client.isConnected) {
      client.sendString(JSON.stringify({
        type: 'living_ui_stop',
        projectId,
      }))
    }
  }, [])

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

  return (
    <WebSocketContext.Provider
      value={{
        ...state,
        // Slice-backed fields injected here so existing consumers don't need
        // to change their imports yet.
        messages,
        hasMoreMessages,
        loadingOlderMessages,
        actions,
        hasMoreActions,
        loadingOlderActions,
        cancellingTaskId,
        dashboardMetrics,
        filteredMetricsCache,
        onboardingStep,
        onboardingError,
        onboardingLoading,
        needsHardOnboarding,
        livingUIProjects,
        livingUICreating,
        livingUITodos,
        activeLivingUIId,
        livingUIStates,
        agentName,
        agentProfilePictureUrl,
        agentProfilePictureHasCustom,
        status,
        currentTask,
        guiMode,
        footageUrl,
        skillMeta,
        sendMessage,
        sendCommand,
        clearMessages,
        cancelTask,
        openFile,
        openFolder,
        requestFilteredMetrics,
        subscribeDashboardMetrics,
        unsubscribeDashboardMetrics,
        requestOnboardingStep,
        submitOnboardingStep,
        skipOnboardingStep,
        goBackOnboardingStep,
        markMessagesAsSeen,
        setReplyTarget,
        clearReplyTarget,
        loadOlderMessages,
        loadOlderActions,
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
  
