// CraftBot Frontend Types

// ─────────────────────────────────────────────────────────────────────
// Chat Types
// ─────────────────────────────────────────────────────────────────────

export interface Attachment {
  name: string
  path: string
  type: string
  size: number
  url: string
}

export interface ChatMessageOption {
  label: string
  value: string
  style?: 'primary' | 'danger' | 'default'
  url?: string  // If set, clicking also opens this URL in a new tab (e.g. a billing link)
}

export interface ChatMessage {
  sender: string
  content: string
  style: 'user' | 'agent' | 'system' | 'error' | 'info'
  timestamp: number
  messageId: string
  sessionId: string
  attachments?: Attachment[]
  options?: ChatMessageOption[]
  requiresChoice?: boolean  // True when options is a blocking choice (e.g. Continue/Stop) vs. convenience action links; absent/true means show "Please select a response to continue"
  optionSelected?: string  // Value of the option that was selected
  clientId?: string  // Client-generated UUID for reconciling optimistic pending messages with server echo
  pending?: boolean  // True while an optimistic message is awaiting server acknowledgment
  errorCategory?: string  // ErrorCategory value (e.g. "auth", "rate_limit") when style === 'error'
  errorCode?: string  // Stable error code (e.g. "LLM_AUTH", "CONFIG_NO_API_KEY")
  errorSeverity?: 'info' | 'warning' | 'error' | 'critical'
  continueWork?: boolean  // True for a mid-run agent progress update (send_message continue_work=true): the run keeps going after this bubble, so it must NOT hide the "Working…" live row
  isQuestion?: boolean  // True for an agent question with suggested responses: pinned above the composer until optionSelected is set (answer or dismissal)
  allowFreeText?: boolean  // Question only: whether the pinned box also offers a free-text answer field
}

// Recorded as optionSelected when the user dismisses a pinned question
// instead of answering. Mirrors QUESTION_DISMISSED_VALUE on the backend.
export const QUESTION_DISMISSED = '__dismissed__'

// ─────────────────────────────────────────────────────────────────────
// Session Types
// ─────────────────────────────────────────────────────────────────────

export type SessionType = 'main' | 'chat' | 'living_ui'

export interface SessionInfo {
  id: string
  type: SessionType
  title: string
  createdAt: string
  lastActiveAt: string
  livingUiProjectId?: string | null
}

// ─────────────────────────────────────────────────────────────────────
// Activity Types (inline actions + reasoning in the session timeline)
// ─────────────────────────────────────────────────────────────────────

export type ActionStatus = 'running' | 'completed' | 'error' | 'pending' | 'cancelled' | 'waiting' | 'paused'
export type ItemType = 'action' | 'reasoning'

export interface ActionItem {
  id: string
  name: string
  status: ActionStatus
  itemType: ItemType
  sessionId: string
  parentId?: string
  createdAt?: number
  completedAt?: number
  input?: string
  output?: string
  error?: string
  duration?: number
  selectedSkills?: string[]
  workflowId?: string
  inputTokens?: number
  outputTokens?: number
  cacheTokens?: number
}

// ─────────────────────────────────────────────────────────────────────
// Agent State
// ─────────────────────────────────────────────────────────────────────

export type AgentState = 'idle' | 'thinking' | 'working' | 'waiting' | 'error'

export interface AgentStatus {
  state: AgentState
  message: string
  loading: boolean
}

// ─────────────────────────────────────────────────────────────────────
// WebSocket Message Types
// ─────────────────────────────────────────────────────────────────────

export type WSMessageType =
  | 'init'
  | 'message'
  | 'chat_message'
  | 'chat_history'
  | 'chat_clear'
  | 'action_add'
  | 'action_update'
  | 'action_remove'
  // Sessions (creation is lazy: a "message" with sessionId "new" makes the
  // backend create the session and broadcast session_created)
  | 'session_delete'
  | 'session_rename'
  | 'session_clear'
  | 'session_list'
  | 'session_created'
  | 'session_updated'
  | 'session_deleted'
  | 'session_cleared'
  | 'session_busy'
  | 'session_stop'
  | 'agent_state'
  | 'status_update'
  | 'navigate'
  | 'footage_update'
  | 'footage_clear'
  | 'footage_visibility'
  | 'state_update'
  | 'dashboard_metrics'
  | 'dashboard_metrics_filter'
  | 'dashboard_filtered_metrics'
  | 'subscribe_dashboard_metrics'
  | 'unsubscribe_dashboard_metrics'
  // File operations
  | 'file_list'
  | 'file_read'
  | 'file_write'
  | 'file_create'
  | 'file_delete'
  | 'file_rename'
  | 'file_batch_delete'
  | 'file_move'
  | 'file_copy'
  | 'file_upload'
  | 'file_download'
  // Chat attachment operations
  | 'chat_attachment_upload'
  | 'open_file'
  | 'open_folder'
  // Skill creation from a session transcript
  | 'create_skill_from_session'
  | 'skill_meta'
  // Option click (interactive buttons in chat)
  | 'option_click'
  // Pinned agent question (suggested responses): answer/dismiss + broadcast
  | 'question_response'
  | 'question_answered'
  // Onboarding
  | 'onboarding_step'
  | 'onboarding_step_get'
  | 'onboarding_step_submit'
  | 'onboarding_submit'
  | 'onboarding_skip'
  | 'onboarding_back'
  | 'onboarding_complete'
  // Local LLM (Ollama)
  | 'local_llm_check'
  | 'local_llm_test'
  | 'local_llm_install'
  | 'local_llm_install_progress'
  | 'local_llm_start'
  | 'local_llm_suggested_models'
  | 'local_llm_pull_model'
  | 'local_llm_pull_progress'
  // Update
  | 'check_update'
  | 'update_check_result'
  | 'do_update'
  | 'update_progress'
  // Agent profile picture
  | 'agent_profile_picture_upload'
  | 'agent_profile_picture_remove'
  // Living UI operations
  | 'living_ui_create'
  | 'living_ui_status'
  | 'living_ui_ready'
  | 'living_ui_list'
  | 'living_ui_launch'
  | 'living_ui_stop'
  | 'living_ui_delete'
  | 'living_ui_state_update'
  | 'living_ui_data_changed'
  | 'living_ui_build_event'
  | 'living_ui_build_events_replay'
  | 'living_ui_error'
  | 'prompt_enhanced'

export interface WSMessage {
  type: WSMessageType
  data: Record<string, unknown>
}

export interface InitialState {
  version?: string
  agentState: AgentState
  guiMode: boolean
  messages: ChatMessage[]
  actions: ActionItem[]
  sessions: SessionInfo[]
  /** Sessions with a run in flight — seeds the typing indicator on connect. */
  busySessions?: string[]
  status: string
  dashboardMetrics?: DashboardMetrics
  needsHardOnboarding?: boolean
  agentName?: string
}

export interface SkillMeta {
  internalWorkflowIds: string[]
  internalSkillNames: string[]
  reservedSkillNames: string[]
}

// ─────────────────────────────────────────────────────────────────────
// Dashboard Types
// ─────────────────────────────────────────────────────────────────────

export interface TokenUsage {
  inputTokens: number
  outputTokens: number
  totalTokens: number
  cost?: number
}

export interface MCPServer {
  name: string
  status: 'connected' | 'disconnected' | 'error'
  tools: string[]
}

export interface Skill {
  name: string
  description: string
  enabled: boolean
}

export interface DashboardStats {
  tasksCompleted: number
  tasksFailed: number
  actionsTotal: number
  uptime: number
  tokenUsage: TokenUsage
  mcpServers: MCPServer[]
  skills: Skill[]
}

// New Dashboard Metrics Types
export interface CostMetrics {
  perRequestAvg: number
  perTaskAvg: number
  today: number
  thisWeek: number
  thisMonth: number
  total: number
}

export interface TaskMetrics {
  total: number
  completed: number
  failed: number
  running: number
  successRate: number
}

export interface TokenMetrics {
  input: number
  output: number
  cached: number
  total: number
}

export interface SystemMetrics {
  cpuPercent: number
  memoryPercent: number
  memoryUsedMb: number
  memoryTotalMb: number
  diskPercent: number
  diskUsedGb: number
  diskTotalGb: number
  networkSentMb: number
  networkRecvMb: number
  networkSentRateKbps: number
  networkRecvRateKbps: number
}

export interface ThreadPoolMetrics {
  activeThreads: number
  maxWorkers: number
  pendingTasks: number
  utilizationPercent: number
}

export interface UsageMetrics {
  requestsLastHour: number
  requestsToday: number
  peakHour: number
  peakHourRequests: number
  hourlyDistribution: number[]
}

export interface UsageCount {
  name: string
  count: number
}

export interface MCPServerInfo {
  name: string
  status: 'connected' | 'disconnected' | 'error'
  toolCount: number
  transport: 'stdio' | 'sse' | 'websocket'
  actionSet: string
  tools: string[]
}

export interface MCPMetrics {
  totalServers: number
  connectedServers: number
  totalTools: number
  totalCalls: number
  servers: MCPServerInfo[]
  topTools: UsageCount[]
}

export interface SkillInfo {
  name: string
  enabled: boolean
  description: string
  userInvocable: boolean
  actionSets: string[]
}

export interface SkillMetrics {
  totalSkills: number
  enabledSkills: number
  totalInvocations: number
  skills: SkillInfo[]
  topSkills: UsageCount[]
}

export interface ModelMetrics {
  provider: string
  modelId: string
  modelName: string
}

export interface IntegrationMetrics {
  totalIntegrations: number
  connectedIntegrations: number
  totalCalls: number
  topIntegrations: UsageCount[]
}

export interface DashboardMetrics {
  uptimeSeconds: number
  timestamp: number
  cost: CostMetrics
  task: TaskMetrics
  token: TokenMetrics
  system: SystemMetrics
  threadPool: ThreadPoolMetrics
  usage: UsageMetrics
  mcp: MCPMetrics
  skill: SkillMetrics
  integration: IntegrationMetrics
  model: ModelMetrics
}

// Time period for filtered metrics
export type MetricsTimePeriod = '1h' | '1d' | '1w' | '1m' | 'total'

// Filtered metrics response for a specific time period
export interface FilteredDashboardMetrics {
  period: MetricsTimePeriod
  token: TokenMetrics
  task: TaskMetrics
  usage: UsageMetrics
}

// ─────────────────────────────────────────────────────────────────────
// Settings Types
// ─────────────────────────────────────────────────────────────────────

export interface GeneralSettings {
  language: string
  agentName: string
}

export interface ModelSettings {
  provider: string
  model: string
  apiKey?: string
}

// Model Configuration Types
export interface ProviderInfo {
  id: string
  name: string
  requires_api_key: boolean
  api_key_env?: string
  base_url_env?: string
  llm_model: string | null
  vlm_model: string | null
  has_vlm: boolean
}

export interface ApiKeyStatus {
  has_key: boolean
  masked_key: string
}

export interface ModelSettingsData {
  success: boolean
  llm_provider: string
  vlm_provider: string
  llm_model: string | null
  vlm_model: string | null
  api_keys: Record<string, ApiKeyStatus>
  base_urls: Record<string, string>
  error?: string
}

export interface ConnectionTestResult {
  success: boolean
  message: string
  provider: string
  error?: string
}

export interface ValidationResult {
  success: boolean
  can_save: boolean
  warnings: string[]
  errors: string[]
}

export interface Settings {
  general: GeneralSettings
  model: ModelSettings
}

// ─────────────────────────────────────────────────────────────────────
// MCP Settings Types
// ─────────────────────────────────────────────────────────────────────

export interface MCPServerConfig {
  name: string
  description: string
  enabled: boolean
  transport: 'stdio' | 'sse' | 'websocket'
  command?: string
  action_set: string
  env: Record<string, string>
}

export interface MCPListResponse {
  success: boolean
  servers?: MCPServerConfig[]
  error?: string
}

export interface MCPActionResponse {
  success: boolean
  message?: string
  name?: string
  error?: string
}

export interface MCPEnvResponse {
  success: boolean
  name: string
  env?: Record<string, string>
  error?: string
}

// ─────────────────────────────────────────────────────────────────────
// Workspace/File Types
// ─────────────────────────────────────────────────────────────────────

export interface FileItem {
  name: string
  path: string
  type: 'file' | 'directory'
  size?: number
  modified?: number
}

export interface FileListResponse {
  directory: string
  files: FileItem[]
  total: number
  hasMore: boolean
  offset: number
  success: boolean
  error?: string
}

export interface FileReadResponse {
  path: string
  content: string | null
  isBinary: boolean
  fileInfo: FileItem
  success: boolean
  error?: string
}

export interface FileWriteResponse {
  path: string
  fileInfo?: FileItem
  success: boolean
  error?: string
}

export interface FileCreateResponse {
  path: string
  fileType: 'file' | 'directory'
  fileInfo?: FileItem
  success: boolean
  error?: string
}

export interface FileDeleteResponse {
  path: string
  success: boolean
  error?: string
}

export interface FileRenameResponse {
  oldPath: string
  newPath?: string
  fileInfo?: FileItem
  success: boolean
  error?: string
}

export interface FileBatchDeleteResponse {
  results: Array<{ path: string; success: boolean; error?: string }>
  success: boolean
}

export interface FileMoveResponse {
  srcPath: string
  destPath: string
  fileInfo?: FileItem
  success: boolean
  error?: string
}

export interface FileCopyResponse {
  srcPath: string
  destPath: string
  fileInfo?: FileItem
  success: boolean
  error?: string
}

export interface FileUploadResponse {
  path: string
  fileInfo?: FileItem
  success: boolean
  error?: string
}

export interface FileDownloadResponse {
  path: string
  content?: string  // base64 encoded
  fileInfo?: FileItem
  success: boolean
  error?: string
}

export interface ChatAttachmentUploadResponse {
  success: boolean
  attachment?: Attachment
  error?: string
}

export interface OpenFileResponse {
  path: string
  success: boolean
  error?: string
}

export interface OpenFolderResponse {
  path: string
  success: boolean
  error?: string
}

// ─────────────────────────────────────────────────────────────────────
// Navigation
// ─────────────────────────────────────────────────────────────────────

export type NavTab = 'chat' | 'dashboard' | 'screen' | 'workspace' | 'settings' | 'living-ui'

// ─────────────────────────────────────────────────────────────────────
// Onboarding Types
// ─────────────────────────────────────────────────────────────────────

export interface OnboardingStepOption {
  value: string
  label: string
  description: string
  default: boolean
  icon?: string  // Lucide icon name
  requires_setup?: boolean  // Whether this option needs API key or additional setup
}

export interface OnboardingFormField {
  name: string
  label: string
  field_type: 'text' | 'select' | 'multi_checkbox' | 'image_upload'
  options: OnboardingStepOption[]
  default: string | string[]
  placeholder: string
}

export interface OnboardingStep {
  name: string
  title: string
  description: string
  required: boolean
  index: number
  total: number
  options: OnboardingStepOption[]
  default: string | string[] | null
  provider?: string | null   // only present on the api_key step
  // Subscription OAuth (ChatGPT Plus/Pro, SuperGrok) hints — only meaningful on
  // the api_key step. When true the step shows a "Sign in with <provider>"
  // button as an alternative to pasting an API key.
  supports_subscription_oauth?: boolean
  subscription_label?: string | null
  form_fields?: OnboardingFormField[] | null  // present on form steps (e.g., user_profile)
}

// ─────────────────────────────────────────────────────────────────────
// Local LLM (Ollama) Types
// ─────────────────────────────────────────────────────────────────────

export type LocalLLMPhase =
  | 'idle'
  | 'checking'
  | 'not_installed'
  | 'not_running'
  | 'running'
  | 'installing'
  | 'starting'
  | 'connected'
  | 'error'
  | 'selecting_model'
  | 'pulling_model'

export interface SuggestedModel {
  name: string
  label: string
  size: string
  recommended: boolean
}

export interface LocalLLMState {
  phase: LocalLLMPhase
  version?: string
  defaultUrl: string
  installProgress: string[]
  pullProgress: string[]
  pullBytes: { completed: number; total: number; percent: number } | null
  suggestedModels: SuggestedModel[]
  testResult?: { success: boolean; message?: string; error?: string; models?: string[] }
  error?: string
}

export interface LocalLLMCheckResponse {
  success: boolean
  installed: boolean
  running: boolean
  version?: string
  default_url: string
  error?: string
}

export interface LocalLLMTestResponse {
  success: boolean
  message?: string
  models?: string[]
  error?: string
}

export interface LocalLLMInstallResponse {
  success: boolean
  message?: string
  error?: string
}

export interface LocalLLMProgressResponse {
  message: string
}

export interface LocalLLMPullProgressResponse {
  message: string
  total: number
  completed: number
  percent: number
}

export interface OnboardingStepResponse {
  success: boolean
  completed?: boolean
  step?: OnboardingStep
  error?: string
}

export interface OnboardingSubmitResponse {
  success: boolean
  nextStep?: OnboardingStep
  error?: string
  index?: number
}

export interface OnboardingCompleteResponse {
  success: boolean
  agentName?: string
  error?: string
}

// ─────────────────────────────────────────────────────────────────────
// Living UI Types
// ─────────────────────────────────────────────────────────────────────

// 'launching'/'stopping' are optimistic transient states set on the client the
// moment the user clicks launch/stop, so the UI reacts immediately (the backend
// only reports the terminal 'running'/'stopped'/'error').
export type LivingUIStatus = 'creating' | 'launching' | 'ready' | 'running' | 'stopping' | 'stopped' | 'error'
export type LivingUICreationPhase = 'initializing' | 'scaffolding' | 'coding' | 'testing' | 'building' | 'launching'

export interface LivingUIProject {
  id: string
  name: string
  description: string
  status: LivingUIStatus
  path: string
  /** Chat session backing this project's chat panel. */
  sessionId?: string
  port?: number
  url?: string
  createdAt: number
  /** "lucide:<Name>" or "file:<relpath>" (uploaded favicon). */
  icon?: string | null
  features?: string[]
  error?: string
  stylePack?: string
  /** Server-persisted display theme; adopted when no local override exists. */
  uiTheme?: { themeId?: string; customColors?: Record<string, string> } | null
  /** 'native' (a Living UI) | 'external' (foreign app running as-is). */
  projectType?: 'native' | 'external'
  /** External apps only: detected runtime (node/python/static/go/rust). */
  appRuntime?: string | null
  /** CraftBot version that acquired this project (provenance). */
  craftbotVersion?: string | null
}

export interface LivingUICreateRequest {
  name: string
  description: string
  features?: string[]  // Optional, defaults to empty array
  dataSource?: string
  theme?: 'light' | 'dark' | 'system'
  authMode?: 'none' | 'multi-user'
  layout?: string
  stylePack?: string
  referenceFiles?: string[]
}

// One derived "the app is being built" event, produced read-only by the
// backend construction observer (app/living_ui/construction_events.py) and
// rendered in the construction dock's feed + CodePeek.
export interface LivingUIBuildEvent {
  id: string
  ts: number
  kind: 'file_write' | 'file_edit' | 'test_run' | 'scaffold' | 'read' | 'search' | 'run' | 'verify' | 'todo'
  area: 'backend' | 'frontend' | 'tests' | 'docs' | 'config' | 'other'
  label: string
  file?: string
  entities?: {
    models?: string[]
    routes?: string[]
    components?: string[]
    tests?: string[]
  }
  snippet?: string
  tests?: { passed: number; failed: number }
  /** Authoritative counts scanned from the project on disk at event time —
   * the source of truth for the dock's summary chips (not the per-write
   * entities above, which only describe what that one write touched). */
  snapshot?: { collections: number; components: number; routes: number }
}

export interface LivingUIStatusUpdate {
  projectId: string
  phase: LivingUICreationPhase
  progress: number  // 0-100
  message: string
  logs?: string[]
}

export interface LivingUIStateUpdate {
  projectId: string
  state: {
    componentTree: LivingUIComponentState[]
    visibleText: string[]
    inputValues: Record<string, string>
    currentView: string
    scrollPosition: { x: number; y: number }
    timestamp: number
  }
}

export interface LivingUIComponentState {
  name: string
  props: Record<string, unknown>
  children?: LivingUIComponentState[]
}

// Response types for Living UI operations
export interface LivingUICreateResponse {
  success: boolean
  projectId?: string
  project?: LivingUIProject
  error?: string
}

export interface LivingUIListResponse {
  success: boolean
  projects?: LivingUIProject[]
  error?: string
}

export interface LivingUILaunchResponse {
  success: boolean
  projectId?: string
  url?: string
  port?: number
  error?: string
}

export interface LivingUIStopResponse {
  success: boolean
  projectId?: string
  error?: string
}

export interface LivingUIDeleteResponse {
  success: boolean
  projectId?: string
  error?: string
}
