import React, { createContext, useContext, useEffect, useRef, useState, useCallback, ReactNode } from 'react'
import type {
  ChatMessage, ActionItem, AgentStatus, InitialState, WSMessage, DashboardMetrics,
  TaskCancelResponse, FilteredDashboardMetrics, MetricsTimePeriod, OnboardingStep,
  OnboardingStepResponse, OnboardingSubmitResponse, OnboardingCompleteResponse,
  LocalLLMState, LocalLLMCheckResponse, LocalLLMTestResponse, LocalLLMInstallResponse,
  LocalLLMProgressResponse, LocalLLMPullProgressResponse, SuggestedModel,
  SkillMeta,
  // Living UI types
  LivingUIProject, LivingUICreateRequest, LivingUIStatusUpdate, LivingUIStateUpdate,
  LivingUITodo, LivingUITodosUpdate,
  LivingUICreateResponse, LivingUIListResponse, LivingUILaunchResponse, LivingUIStopResponse, LivingUIDeleteResponse
} from '../types'
import { getWsUrl } from '../utils/connection'

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

// Unique-ish id for client-originating artifacts (WS connection attempts,
// optimistic chat messages awaiting server echo). Uses crypto.randomUUID
// when available, falls back to a cheap timestamp+random id on older
// runtimes without the secure-context requirement.
const newClientId = (): string =>
  typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `cid-${Date.now()}-${Math.random().toString(36).slice(2)}`

interface WebSocketState {
  connected: boolean
  version: string
  messages: ChatMessage[]
  actions: ActionItem[]
  status: AgentStatus
  guiMode: boolean
  currentTask: { id: string; name: string } | null
  footageUrl: string | null
  dashboardMetrics: DashboardMetrics | null
  filteredMetricsCache: Record<MetricsTimePeriod, FilteredDashboardMetrics | null>
  cancellingTaskId: string | null
  // Whether the initial 'init' message has been received from the backend
  initReceived: boolean
  // Onboarding state
  needsHardOnboarding: boolean
  agentName: string
  agentProfilePictureUrl: string
  agentProfilePictureHasCustom: boolean
  onboardingStep: OnboardingStep | null
  onboardingError: string | null
  onboardingLoading: boolean
  // Unread message tracking
  lastSeenMessageId: string | null
  // Reply state for reply-to-chat/task feature
  replyTarget: ReplyTarget | null
  // Chat pagination
  hasMoreMessages: boolean
  loadingOlderMessages: boolean
  // Action pagination
  hasMoreActions: boolean
  loadingOlderActions: boolean
  // Local LLM (Ollama) state
  localLLM: LocalLLMState
  // Living UI state
  livingUIProjects: LivingUIProject[]
  livingUICreating: LivingUIStatusUpdate | null
  livingUITodos: Record<string, LivingUITodo[]>
  activeLivingUIId: string | null
  livingUIStates: Record<string, LivingUIStateUpdate['state']>
  skillMeta: SkillMeta
}

interface WebSocketContextType extends WebSocketState {
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
  // Local LLM (Ollama) methods
  checkLocalLLM: () => void
  testLocalLLMConnection: (url: string) => void
  installLocalLLM: () => void
  startLocalLLM: () => void
  requestSuggestedModels: () => void
  pullOllamaModel: (model: string) => void
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
  messages: [],
  actions: [],
  status: {
    state: 'idle',
    message: 'Connecting...',
    loading: false,
  },
  guiMode: false,
  currentTask: null,
  footageUrl: null,
  dashboardMetrics: null,
  filteredMetricsCache: {
    '1h': null,
    '1d': null,
    '1w': null,
    '1m': null,
    'total': null,
  },
  cancellingTaskId: null,
  // Onboarding state
  initReceived: false,
  needsHardOnboarding: false,
  agentName: 'Agent',
  agentProfilePictureUrl: '/api/agent-profile-picture',
  agentProfilePictureHasCustom: false,
  onboardingStep: null,
  onboardingError: null,
  onboardingLoading: false,
  // Unread message tracking
  lastSeenMessageId: getInitialLastSeenMessageId(),
  // Reply state
  replyTarget: null,
  // Chat pagination
  hasMoreMessages: true,
  loadingOlderMessages: false,
  // Action pagination
  hasMoreActions: true,
  loadingOlderActions: false,
  // Local LLM (Ollama) state
  localLLM: {
    phase: 'idle',
    defaultUrl: 'http://localhost:11434',
    installProgress: [],
    pullProgress: [],
    pullBytes: null,
    suggestedModels: [],
  },
  // Living UI state
  livingUIProjects: [],
  livingUICreating: null,
  livingUITodos: {},
  activeLivingUIId: null,
  livingUIStates: {},
  skillMeta: {
    internalWorkflowIds: [],
    internalSkillNames: [],
    reservedSkillNames: [],
  },
}

const WebSocketContext = createContext<WebSocketContextType | undefined>(undefined)

export function WebSocketProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<WebSocketState>(defaultState)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<number | null>(null)
  const isConnectingRef = useRef<boolean>(false)
  const reconnectCountRef = useRef<number>(0)
  const maxReconnectAttemptsRef = useRef<number>(10)
  // Outbox: payloads queued while the socket is not OPEN. Flushed on reconnect.
  const outboxRef = useRef<string[]>([])

  // Small helper so `sendMessage` and the on-open flush share one policy:
  // try to send via the current socket; on failure or non-OPEN, queue for
  // the next successful `onopen`. Keeping this as a closure over the refs
  // (not a class) is enough — there's no state beyond the outbox itself.
  const sendOrQueue = useCallback((payloadStr: string) => {
    const ws = wsRef.current
    if (ws?.readyState === WebSocket.OPEN) {
      try {
        ws.send(payloadStr)
        return
      } catch (err) {
        console.warn('[WS] send threw, queuing payload:', err)
      }
    }
    outboxRef.current.push(payloadStr)
  }, [])

  const connect = useCallback(() => {
    // Prevent duplicate connections (React StrictMode calls useEffect twice)
    if (isConnectingRef.current || wsRef.current?.readyState === WebSocket.OPEN) {
      return
    }
    isConnectingRef.current = true

    // Close any existing connection before creating new one
    if (wsRef.current) {
      try {
        wsRef.current.close()
      } catch {
        // Already closed — ignore.
      }
      wsRef.current = null
    }

    // attemptId is sent as a URL query param so the server can correlate a
    // failed `ws.prepare()` attempt with a specific client-side attempt. The
    // UUID itself is not logged here — the server logs it on failure.
    const attemptId = newClientId()
    const baseUrl = getWsUrl()
    const wsUrl = `${baseUrl}${baseUrl.includes('?') ? '&' : '?'}attempt=${attemptId}`

    try {
      const ws = new WebSocket(wsUrl)
      wsRef.current = ws

      ws.onopen = () => {
        console.log('[WS] connected')
        isConnectingRef.current = false
        reconnectCountRef.current = 0
        setState(prev => ({ ...prev, connected: true }))

        ws.send(JSON.stringify({ type: 'living_ui_list' }))

        // Drain the outbox (messages sent while the socket was down).
        // Any send that fails re-enqueues via sendOrQueue for the next open.
        if (outboxRef.current.length > 0) {
          const pending = outboxRef.current
          outboxRef.current = []
          for (const payloadStr of pending) sendOrQueue(payloadStr)
        }
      }

      ws.onmessage = (event) => {
        try {
          const msg: WSMessage = JSON.parse(event.data)
          handleMessage(msg)
        } catch (err) {
          console.error('[WS] parse failed:', err, 'raw:', event.data)
        }
      }

      ws.onclose = (event) => {
        console.log('[WS] disconnected code=' + event.code, 'clean=' + event.wasClean)
        isConnectingRef.current = false
        setState(prev => ({
          ...prev,
          connected: false,
          status: { ...prev.status, message: 'Disconnected. Reconnecting...' },
        }))

        // Immediate first retry, then exponential backoff.
        const attempt = reconnectCountRef.current
        const reconnectDelay = attempt === 0
          ? 500
          : Math.min(1000 * Math.pow(1.5, attempt - 1), 30000)
        reconnectCountRef.current = attempt + 1

        if (reconnectCountRef.current <= maxReconnectAttemptsRef.current) {
          reconnectTimeoutRef.current = window.setTimeout(connect, reconnectDelay)
        } else {
          console.error(`[WS] giving up after ${maxReconnectAttemptsRef.current} reconnect attempts`)
          setState(prev => ({
            ...prev,
            status: { ...prev.status, message: 'Connection failed - please refresh the page' },
          }))
        }
      }

      ws.onerror = (err) => {
        // Browser error events are opaque; onclose fires after this with
        // the real code/reason, so we just log and let onclose handle retry.
        console.error('[WS] error:', err)
      }
    } catch (err) {
      console.error('[WS] failed to construct WebSocket:', err)
      isConnectingRef.current = false
      reconnectCountRef.current += 1
      const reconnectDelay = Math.min(1000 * Math.pow(1.5, reconnectCountRef.current), 30000)
      reconnectTimeoutRef.current = window.setTimeout(connect, reconnectDelay)
    }
  }, [sendOrQueue])

  const handleMessage = useCallback((msg: WSMessage) => {
    switch (msg.type) {
      case 'init': {
        const data = msg.data as unknown as InitialState
        const initMessages = data.messages || []
        const initActions = data.actions || []
        setState(prev => ({
          ...prev,
          version: data.version || '',
          messages: initMessages,
          actions: initActions,
          status: {
            state: data.agentState || 'idle',
            message: data.status || 'Ready',
            loading: false,
          },
          guiMode: data.guiMode || false,
          currentTask: data.currentTask || null,
          dashboardMetrics: data.dashboardMetrics || null,
          initReceived: true,
          needsHardOnboarding: data.needsHardOnboarding || false,
          agentName: data.agentName || 'Agent',
          agentProfilePictureUrl:
            (data as InitialState & { agentProfilePictureUrl?: string }).agentProfilePictureUrl
            || '/api/agent-profile-picture',
          agentProfilePictureHasCustom:
            (data as InitialState & { agentProfilePictureHasCustom?: boolean }).agentProfilePictureHasCustom
            || false,
          hasMoreMessages: initMessages.length >= 50,
          hasMoreActions: initActions.filter((a: ActionItem) => a.itemType === 'task').length >= 15,
        }))
        break
      }

      case 'skill_meta': {
        const data = msg.data as unknown as SkillMeta
        setState(prev => ({
          ...prev,
          skillMeta: {
            internalWorkflowIds: data.internalWorkflowIds || [],
            internalSkillNames: data.internalSkillNames || [],
            reservedSkillNames: data.reservedSkillNames || [],
          },
        }))
        break
      }

      case 'chat_message': {
        const message = msg.data as unknown as ChatMessage
        setState(prev => {
          // If this echo has a clientId that matches a pending optimistic message,
          // replace it in place (preserving position, flipping pending -> false)
          // so the bubble appears confirmed rather than duplicated.
          if (message.clientId) {
            const idx = prev.messages.findIndex(
              m => m.pending && m.clientId === message.clientId,
            )
            if (idx !== -1) {
              const next = prev.messages.slice()
              next[idx] = { ...message, pending: false }
              return { ...prev, messages: next }
            }
          }
          return { ...prev, messages: [...prev.messages, message] }
        })
        break
      }

      case 'chat_history': {
        const data = msg.data as unknown as { messages: ChatMessage[]; hasMore: boolean }
        setState(prev => ({
          ...prev,
          messages: [...(data.messages || []), ...prev.messages],
          hasMoreMessages: data.hasMore,
          loadingOlderMessages: false,
        }))
        break
      }

      case 'chat_clear':
        setState(prev => ({ ...prev, messages: [], hasMoreMessages: false }))
        break

      case 'action_history': {
        const data = msg.data as unknown as { actions: ActionItem[]; hasMore: boolean }
        setState(prev => ({
          ...prev,
          actions: [...(data.actions || []), ...prev.actions],
          hasMoreActions: data.hasMore,
          loadingOlderActions: false,
        }))
        break
      }

      case 'action_add': {
        const action = msg.data as unknown as ActionItem
        setState(prev => {
          // Prevent duplicate items by ID only
          const existingItem = prev.actions.find(a => a.id === action.id)
          if (existingItem) {
            // Update existing item's status if different
            if (existingItem.status !== action.status) {
              return {
                ...prev,
                actions: prev.actions.map(a =>
                  a.id === action.id ? { ...a, status: action.status } : a
                ),
              }
            }
            return prev // No change needed
          }
          return {
            ...prev,
            actions: [...prev.actions, action],
          }
        })
        break
      }

      case 'action_update': {
        const { id, status, duration, output, error } = msg.data as {
          id: string
          status: string
          duration?: number
          output?: string
          error?: string
        }
        setState(prev => ({
          ...prev,
          actions: prev.actions.map(a =>
            a.id === id
              ? { ...a, status: status as ActionItem['status'], duration, output, error }
              : a
          ),
        }))
        break
      }

      case 'action_remove': {
        const { id } = msg.data as { id: string }
        setState(prev => ({
          ...prev,
          actions: prev.actions.filter(a => a.id !== id),
        }))
        break
      }

      case 'action_clear':
        setState(prev => ({ ...prev, actions: [] }))
        break

      case 'status_update': {
        const { message, loading } = msg.data as { message: string; loading: boolean }
        setState(prev => ({
          ...prev,
          status: { ...prev.status, message, loading },
        }))
        break
      }

      case 'footage_update': {
        const { image } = msg.data as { image: string }
        setState(prev => ({ ...prev, footageUrl: image }))
        break
      }

      case 'footage_clear':
        setState(prev => ({ ...prev, footageUrl: null }))
        break

      case 'footage_visibility': {
        const { visible } = msg.data as { visible: boolean }
        setState(prev => ({ ...prev, guiMode: visible }))
        break
      }

      case 'dashboard_metrics': {
        const metrics = msg.data as unknown as DashboardMetrics
        setState(prev => ({ ...prev, dashboardMetrics: metrics }))
        break
      }

      case 'dashboard_filtered_metrics': {
        const metrics = msg.data as unknown as FilteredDashboardMetrics
        // Cache by period so each card can have independent data
        setState(prev => ({
          ...prev,
          filteredMetricsCache: {
            ...prev.filteredMetricsCache,
            [metrics.period]: metrics,
          },
        }))
        break
      }

      case 'task_cancel_response': {
        const response = msg.data as unknown as TaskCancelResponse
        if (response.success) {
          // Update the task status to cancelled
          setState(prev => ({
            ...prev,
            cancellingTaskId: null,
            actions: prev.actions.map(a =>
              a.id === response.taskId
                ? { ...a, status: 'cancelled' as const }
                : a
            ),
          }))
        } else {
          // Cancel failed, reset cancelling state
          setState(prev => ({ ...prev, cancellingTaskId: null }))
        }
        break
      }

      // Onboarding message handlers
      case 'onboarding_step': {
        const response = msg.data as unknown as OnboardingStepResponse
        if (response.success) {
          if (response.completed) {
            // Onboarding already complete
            setState(prev => ({
              ...prev,
              needsHardOnboarding: false,
              onboardingStep: null,
              onboardingLoading: false,
              onboardingError: null,
            }))
          } else if (response.step) {
            setState(prev => ({
              ...prev,
              onboardingStep: response.step!,
              onboardingLoading: false,
              onboardingError: null,
            }))
          }
        } else {
          setState(prev => ({
            ...prev,
            onboardingError: response.error || 'Failed to get step',
            onboardingLoading: false,
          }))
        }
        break
      }

      case 'onboarding_submit': {
        const response = msg.data as unknown as OnboardingSubmitResponse
        if (response.success && response.nextStep) {
          setState(prev => ({
            ...prev,
            onboardingStep: response.nextStep!,
            onboardingLoading: false,
            onboardingError: null,
          }))
        } else if (!response.success) {
          setState(prev => ({
            ...prev,
            onboardingError: response.error || 'Failed to submit',
            onboardingLoading: false,
          }))
        }
        break
      }

      case 'onboarding_skip': {
        const response = msg.data as unknown as OnboardingSubmitResponse
        if (response.success && response.nextStep) {
          setState(prev => ({
            ...prev,
            onboardingStep: response.nextStep!,
            onboardingLoading: false,
            onboardingError: null,
          }))
        } else if (!response.success) {
          setState(prev => ({
            ...prev,
            onboardingError: response.error || 'Cannot skip this step',
            onboardingLoading: false,
          }))
        }
        break
      }

      case 'onboarding_back': {
        const response = msg.data as unknown as { success: boolean; step?: OnboardingStep; error?: string }
        if (response.success && response.step) {
          setState(prev => ({
            ...prev,
            onboardingStep: response.step!,
            onboardingLoading: false,
            onboardingError: null,
          }))
        } else if (!response.success) {
          setState(prev => ({
            ...prev,
            onboardingError: response.error || 'Cannot go back',
            onboardingLoading: false,
          }))
        }
        break
      }

      case 'onboarding_complete': {
        const response = msg.data as unknown as OnboardingCompleteResponse & {
          agentProfilePictureUrl?: string
          agentProfilePictureHasCustom?: boolean
        }
        if (response.success) {
          setState(prev => ({
            ...prev,
            needsHardOnboarding: false,
            onboardingStep: null,
            onboardingLoading: false,
            onboardingError: null,
            agentName: response.agentName || 'Agent',
            agentProfilePictureUrl:
              response.agentProfilePictureUrl || prev.agentProfilePictureUrl,
            agentProfilePictureHasCustom:
              response.agentProfilePictureHasCustom ?? prev.agentProfilePictureHasCustom,
          }))
        }
        break
      }

      case 'agent_profile_picture_upload': {
        const r = msg.data as unknown as {
          success: boolean
          url?: string
          has_custom?: boolean
          error?: string
        }
        if (r.success && r.url) {
          setState(prev => ({
            ...prev,
            agentProfilePictureUrl: r.url!,
            agentProfilePictureHasCustom: r.has_custom ?? true,
          }))
        }
        break
      }

      case 'agent_profile_picture_remove': {
        const r = msg.data as unknown as {
          success: boolean
          url?: string
          has_custom?: boolean
        }
        if (r.success) {
          setState(prev => ({
            ...prev,
            agentProfilePictureUrl: r.url || '/api/agent-profile-picture',
            agentProfilePictureHasCustom: r.has_custom ?? false,
          }))
        }
        break
      }

      // ── Local LLM (Ollama) ───────────────────────────────────────────────
      case 'local_llm_check': {
        const r = msg.data as unknown as LocalLLMCheckResponse
        // Phases that must not be overridden by a background check result
        const BUSY_PHASES: LocalLLMState['phase'][] = ['installing', 'starting', 'pulling_model']
        if (!r.success) {
          setState(prev => {
            if (BUSY_PHASES.includes(prev.localLLM.phase)) return prev
            return { ...prev, localLLM: { ...prev.localLLM, phase: 'error', error: r.error } }
          })
          break
        }
        let phase: LocalLLMState['phase']
        if (r.running) {
          phase = 'running'
        } else if (r.installed) {
          phase = 'not_running'
        } else {
          phase = 'not_installed'
        }
        setState(prev => {
          if (BUSY_PHASES.includes(prev.localLLM.phase)) return prev
          return {
            ...prev,
            localLLM: {
              ...prev.localLLM,
              phase,
              version: r.version,
              defaultUrl: r.default_url || 'http://localhost:11434',
              error: undefined,
              testResult: undefined,
            },
          }
        })
        break
      }

      case 'local_llm_test': {
        const r = msg.data as unknown as LocalLLMTestResponse
        if (r.success && (!r.models || r.models.length === 0)) {
          // Connected but no models — ask user to pick one
          setState(prev => ({
            ...prev,
            localLLM: {
              ...prev.localLLM,
              phase: 'selecting_model',
              testResult: { success: r.success, message: r.message, error: r.error, models: r.models },
            },
          }))
          wsRef.current?.send(JSON.stringify({ type: 'local_llm_suggested_models' }))
        } else {
          setState(prev => ({
            ...prev,
            localLLM: {
              ...prev.localLLM,
              phase: r.success ? 'connected' : prev.localLLM.phase,
              testResult: { success: r.success, message: r.message, error: r.error, models: r.models },
            },
          }))
        }
        break
      }

      // Living UI message handlers
      case 'living_ui_list': {
        const response = msg.data as unknown as LivingUIListResponse
        if (response.success && response.projects) {
          setState(prev => ({
            ...prev,
            livingUIProjects: response.projects!,
          }))
        }
        break
      }

      case 'living_ui_create': {
        const response = msg.data as unknown as LivingUICreateResponse
        if (response.success && response.project) {
          setState(prev => ({
            ...prev,
            livingUIProjects: [...prev.livingUIProjects, response.project!],
          }))
        }
        break
      }

      case 'local_llm_install_progress': {
        const r = msg.data as unknown as LocalLLMProgressResponse
        setState(prev => ({
          ...prev,
          localLLM: {
            ...prev.localLLM,
            installProgress: [...prev.localLLM.installProgress, r.message],
          },
        }))
        break
      }

      case 'living_ui_status': {
        const status = msg.data as unknown as LivingUIStatusUpdate
        setState(prev => ({
          ...prev,
          livingUICreating: status,
          // Only update project status during creation; never downgrade a running project
          // back to 'creating'/'ready' just because the agent emitted a progress event.
          livingUIProjects: prev.livingUIProjects.map(p => {
            if (p.id !== status.projectId) return p
            if (p.status === 'running') return p
            return { ...p, status: status.phase === 'launching' ? 'ready' : 'creating' }
          }),
        }))
        break
      }

      case 'living_ui_todos': {
        const update = msg.data as unknown as LivingUITodosUpdate
        setState(prev => ({
          ...prev,
          livingUITodos: { ...prev.livingUITodos, [update.projectId]: update.todos },
        }))
        break
      }

      case 'local_llm_install': {
        const r = msg.data as unknown as LocalLLMInstallResponse
        if (r.success) {
          // Trigger a status check instead of assuming 'not_running' —
          // the installer may have auto-launched Ollama already
          setState(prev => ({ ...prev, localLLM: { ...prev.localLLM, phase: 'checking', installProgress: [] } }))
          wsRef.current?.send(JSON.stringify({ type: 'local_llm_check' }))
        } else {
          setState(prev => ({
            ...prev,
            localLLM: { ...prev.localLLM, phase: 'error', error: r.error ?? 'Installation failed' },
          }))
        }
        break
      }

      case 'local_llm_start': {
        const r = msg.data as unknown as LocalLLMInstallResponse
        setState(prev => ({
          ...prev,
          localLLM: {
            ...prev.localLLM,
            phase: r.success ? 'running' : 'error',
            error: r.success ? undefined : (r.error ?? 'Failed to start Ollama'),
            testResult: undefined,
          },
        }))
        break
      }

      case 'living_ui_ready': {
        const readyData = msg.data as { projectId: string; url: string; port: number }
        setState(prev => {
          const exists = prev.livingUIProjects.some(p => p.id === readyData.projectId)
          if (exists) {
            return {
              ...prev,
              livingUICreating: null,
              livingUIProjects: prev.livingUIProjects.map(p =>
                p.id === readyData.projectId
                  ? { ...p, status: 'running' as const, url: readyData.url, port: readyData.port }
                  : p
              ),
            }
          }
          // Project not in list yet — refresh the full list from server
          wsRef.current?.send(JSON.stringify({ type: 'living_ui_list' }))
          return { ...prev, livingUICreating: null }
        })
        break
      }

      case 'local_llm_suggested_models': {
        const r = msg.data as unknown as { models: SuggestedModel[] }
        setState(prev => ({ ...prev, localLLM: { ...prev.localLLM, suggestedModels: r.models } }))
        break
      }

      case 'local_llm_pull_progress': {
        const r = msg.data as unknown as LocalLLMPullProgressResponse
        setState(prev => {
          // Only append to the log for non-byte-progress status lines
          const isDownloading = r.total > 0
          const newLog = isDownloading
            ? prev.localLLM.pullProgress  // don't spam log with repeated byte updates
            : r.message && !prev.localLLM.pullProgress.includes(r.message)
              ? [...prev.localLLM.pullProgress, r.message]
              : prev.localLLM.pullProgress
          return {
            ...prev,
            localLLM: {
              ...prev.localLLM,
              pullProgress: newLog,
              pullBytes: isDownloading
                ? { completed: r.completed, total: r.total, percent: r.percent }
                : prev.localLLM.pullBytes,
            },
          }
        })
        break
      }

      case 'local_llm_pull_model': {
        const r = msg.data as unknown as LocalLLMInstallResponse & { model?: string }
        if (r.success) {
          // Re-test to refresh model count and advance to 'connected'
          setState(prev => {
            wsRef.current?.send(JSON.stringify({ type: 'local_llm_test', url: prev.localLLM.defaultUrl }))
            return { ...prev, localLLM: { ...prev.localLLM, pullProgress: [], error: undefined } }
          })
        } else {
          setState(prev => ({
            ...prev,
            localLLM: { ...prev.localLLM, phase: 'error', error: r.error ?? 'Model download failed' },
          }))
        }
        break
      }

      case 'living_ui_launch': {
        const response = msg.data as unknown as LivingUILaunchResponse
        if (response.success) {
          setState(prev => ({
            ...prev,
            livingUIProjects: prev.livingUIProjects.map(p =>
              p.id === response.projectId
                ? { ...p, status: 'running', url: response.url, port: response.port }
                : p
            ),
          }))
        }
        break
      }

      case 'living_ui_stop': {
        const response = msg.data as unknown as LivingUIStopResponse
        if (response.success) {
          setState(prev => ({
            ...prev,
            livingUIProjects: prev.livingUIProjects.map(p =>
              p.id === response.projectId
                ? { ...p, status: 'stopped', url: undefined, port: undefined }
                : p
            ),
          }))
        }
        break
      }

      case 'living_ui_delete': {
        const response = msg.data as unknown as LivingUIDeleteResponse
        if (response.success) {
          setState(prev => {
            const { [response.projectId]: _removed, ...remainingTodos } = prev.livingUITodos
            return {
              ...prev,
              livingUIProjects: prev.livingUIProjects.filter(p => p.id !== response.projectId),
              livingUITodos: remainingTodos,
              // Clear active if it was the deleted one
              activeLivingUIId: prev.activeLivingUIId === response.projectId ? null : prev.activeLivingUIId,
            }
          })
        }
        break
      }

      case 'living_ui_state_update': {
        const update = msg.data as unknown as LivingUIStateUpdate
        setState(prev => ({
          ...prev,
          livingUIStates: {
            ...prev.livingUIStates,
            [update.projectId]: update.state,
          },
        }))
        break
      }

      case 'living_ui_error': {
        const { projectId, error } = msg.data as { projectId: string; error: string }
        setState(prev => ({
          ...prev,
          livingUICreating: null,
          livingUIProjects: prev.livingUIProjects.map(p =>
            p.id === projectId
              ? { ...p, status: 'error', error }
              : p
          ),
        }))
        break
      }
    }
  }, [])

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

  const loadOlderMessages = useCallback(() => {
    if (!state.hasMoreMessages || state.loadingOlderMessages || state.messages.length === 0) return
    if (wsRef.current?.readyState !== WebSocket.OPEN) return

    const oldestTimestamp = state.messages[0]?.timestamp
    if (!oldestTimestamp) return

    setState(prev => ({ ...prev, loadingOlderMessages: true }))
    wsRef.current.send(JSON.stringify({
      type: 'chat_history',
      beforeTimestamp: oldestTimestamp,
      limit: 50,
    }))
  }, [state.hasMoreMessages, state.loadingOlderMessages, state.messages])

  const loadOlderActions = useCallback(() => {
    if (!state.hasMoreActions || state.loadingOlderActions || state.actions.length === 0) return
    if (wsRef.current?.readyState !== WebSocket.OPEN) return

    // Find the oldest task's createdAt (not action) for the before_timestamp
    const oldestTask = state.actions.find(a => a.itemType === 'task')
    const oldestCreatedAt = oldestTask?.createdAt || state.actions[0]?.createdAt
    if (!oldestCreatedAt) return

    setState(prev => ({ ...prev, loadingOlderActions: true }))
    wsRef.current.send(JSON.stringify({
      type: 'action_history',
      beforeTimestamp: oldestCreatedAt,
      limit: 15,
    }))
  }, [state.hasMoreActions, state.loadingOlderActions, state.actions])

  const sendMessage = useCallback((
    content: string,
    attachments?: PendingAttachment[],
    replyContext?: ReplyContext,
    livingUIId?: string,
  ) => {
    const clientId = newClientId()

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
    setState(prev => ({ ...prev, messages: [...prev.messages, optimistic] }))

    sendOrQueue(JSON.stringify({
      type: 'message',
      content,
      attachments: attachments || [],
      replyContext: replyContext || null,
      livingUIId: livingUIId || null,
      clientId,
    }))
  }, [sendOrQueue])

  const sendCommand = useCallback((command: string) => {
    sendOrQueue(JSON.stringify({ type: 'command', command }))
  }, [sendOrQueue])

  const clearMessages = useCallback(() => {
    setState(prev => ({ ...prev, messages: [] }))
  }, [])

  const cancelTask = useCallback((taskId: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      setState(prev => ({ ...prev, cancellingTaskId: taskId }))
      wsRef.current.send(JSON.stringify({ type: 'task_cancel', taskId }))
    }
  }, [])

  const sendOptionClick = useCallback((value: string, sessionId?: string, messageId?: string) => {
    // Optimistically record the selection in local state so the UI lock
    // survives virtualizer remounts, WS reconnects, and parent re-renders
    // without waiting for a backend round-trip or page refresh.
    if (messageId) {
      setState(prev => {
        let changed = false
        const nextMessages = prev.messages.map(m => {
          if (m.messageId === messageId && !m.optionSelected) {
            changed = true
            return { ...m, optionSelected: value }
          }
          return m
        })
        return changed ? { ...prev, messages: nextMessages } : prev
      })
    }
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'option_click', value, sessionId, messageId }))
    }
  }, [])

  const uploadAgentProfilePicture = useCallback(
    (name: string, mimeType: string, contentBase64: string) => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({
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
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'agent_profile_picture_remove' }))
    }
  }, [])

  const openFile = useCallback((path: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'open_file', path }))
    }
  }, [])

  const openFolder = useCallback((path: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'open_folder', path }))
    }
  }, [])

  const requestFilteredMetrics = useCallback((period: MetricsTimePeriod) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        type: 'dashboard_metrics_filter',
        period
      }))
    }
  }, [])

  const subscribeDashboardMetrics = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'subscribe_dashboard_metrics' }))
    }
  }, [])

  const unsubscribeDashboardMetrics = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'unsubscribe_dashboard_metrics' }))
    }
  }, [])

  // Onboarding methods
  const requestOnboardingStep = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      setState(prev => ({ ...prev, onboardingLoading: true, onboardingError: null }))
      wsRef.current.send(JSON.stringify({ type: 'onboarding_step_get' }))
    }
  }, [])

  const submitOnboardingStep = useCallback((value: string | string[]) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      setState(prev => ({ ...prev, onboardingLoading: true, onboardingError: null }))
      wsRef.current.send(JSON.stringify({ type: 'onboarding_step_submit', value }))
    }
  }, [])

  const skipOnboardingStep = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      setState(prev => ({ ...prev, onboardingLoading: true, onboardingError: null }))
      wsRef.current.send(JSON.stringify({ type: 'onboarding_skip' }))
    }
  }, [])

  const goBackOnboardingStep = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      setState(prev => ({ ...prev, onboardingLoading: true, onboardingError: null }))
      wsRef.current.send(JSON.stringify({ type: 'onboarding_back' }))
    }
  }, [])

  // Mark all current messages as seen
  const markMessagesAsSeen = useCallback(() => {
    setState(prev => {
      if (prev.messages.length > 0) {
        const lastId = prev.messages[prev.messages.length - 1].messageId
        if (lastId && lastId !== prev.lastSeenMessageId) {
          try {
            localStorage.setItem('lastSeenMessageId', lastId)
          } catch {
            // localStorage may be unavailable
          }
          return { ...prev, lastSeenMessageId: lastId }
        }
      }
      return prev
    })
  }, [])

  // Set reply target for reply-to-chat/task feature
  const setReplyTarget = useCallback((target: ReplyTarget) => {
    setState(prev => ({ ...prev, replyTarget: target }))
  }, [])

  // Clear reply target
  const clearReplyTarget = useCallback(() => {
    setState(prev => ({ ...prev, replyTarget: null }))
  }, [])

  // Local LLM (Ollama) methods
  const checkLocalLLM = useCallback(() => {
    if (wsRef.current?.readyState !== WebSocket.OPEN) return
    const BUSY_PHASES: LocalLLMState['phase'][] = ['installing', 'starting', 'pulling_model']
    setState(prev => {
      if (BUSY_PHASES.includes(prev.localLLM.phase)) return prev  // Don't interrupt active ops
      return { ...prev, localLLM: { ...prev.localLLM, phase: 'checking', error: undefined } }
    })
    wsRef.current.send(JSON.stringify({ type: 'local_llm_check' }))
  }, [])

  const testLocalLLMConnection = useCallback((url: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'local_llm_test', url }))
    }
  }, [])

  const installLocalLLM = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      setState(prev => ({
        ...prev,
        localLLM: { ...prev.localLLM, phase: 'installing', installProgress: [], error: undefined },
      }))
      wsRef.current.send(JSON.stringify({ type: 'local_llm_install' }))
    } else {
      setState(prev => ({
        ...prev,
        localLLM: { ...prev.localLLM, phase: 'error', error: 'Not connected — please wait a moment and retry.' },
      }))
    }
  }, [])

  const startLocalLLM = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      setState(prev => ({ ...prev, localLLM: { ...prev.localLLM, phase: 'starting', error: undefined } }))
      wsRef.current.send(JSON.stringify({ type: 'local_llm_start' }))
    }
  }, [])

  const requestSuggestedModels = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'local_llm_suggested_models' }))
    }
  }, [])

  const pullOllamaModel = useCallback((model: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      setState(prev => ({
        ...prev,
        localLLM: { ...prev.localLLM, phase: 'pulling_model', pullProgress: [], pullBytes: null, error: undefined },
      }))
      wsRef.current.send(JSON.stringify({ type: 'local_llm_pull_model', model }))
    }
  }, [])

  // Living UI methods
  const createLivingUI = useCallback((data: LivingUICreateRequest) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        type: 'living_ui_create',
        ...data,
      }))
    }
  }, [])

  const requestLivingUIList = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'living_ui_list' }))
    }
  }, [])

  const launchLivingUI = useCallback((projectId: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      // Immediately show loading state
      setState(prev => ({
        ...prev,
        livingUIProjects: prev.livingUIProjects.map(p =>
          p.id === projectId ? { ...p, status: 'launching' as const } : p
        ),
      }))
      wsRef.current.send(JSON.stringify({
        type: 'living_ui_launch',
        projectId,
      }))
    }
  }, [])

  const stopLivingUI = useCallback((projectId: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        type: 'living_ui_stop',
        projectId,
      }))
    }
  }, [])

  const deleteLivingUI = useCallback((projectId: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        type: 'living_ui_delete',
        projectId,
      }))
    }
  }, [])

  const setActiveLivingUI = useCallback((projectId: string | null) => {
    setState(prev => ({ ...prev, activeLivingUIId: projectId }))
  }, [])

  return (
    <WebSocketContext.Provider
      value={{
        ...state,
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
        checkLocalLLM,
        testLocalLLMConnection,
        installLocalLLM,
        startLocalLLM,
        requestSuggestedModels,
        pullOllamaModel,
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
  
