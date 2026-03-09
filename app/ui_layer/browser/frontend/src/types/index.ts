// CraftBot Frontend Types

// ─────────────────────────────────────────────────────────────────────
// Chat Types
// ─────────────────────────────────────────────────────────────────────

export interface ChatMessage {
  sender: string
  content: string
  style: 'user' | 'agent' | 'system' | 'error' | 'info'
  timestamp: number
  messageId: string
}

// ─────────────────────────────────────────────────────────────────────
// Action/Task Types
// ─────────────────────────────────────────────────────────────────────

export type ActionStatus = 'running' | 'completed' | 'error' | 'pending' | 'cancelled'
export type ItemType = 'task' | 'action' | 'reasoning'

export interface ActionItem {
  id: string
  name: string
  status: ActionStatus
  itemType: ItemType
  parentId?: string
  createdAt?: number
  input?: string
  output?: string
  error?: string
  duration?: number
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
  | 'chat_message'
  | 'chat_clear'
  | 'action_add'
  | 'action_update'
  | 'action_remove'
  | 'action_clear'
  | 'status_update'
  | 'footage_update'
  | 'footage_clear'
  | 'footage_visibility'
  | 'state_update'
  | 'dashboard_metrics'
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
  // Task control
  | 'task_cancel'
  | 'task_cancel_response'

export interface WSMessage {
  type: WSMessageType
  data: Record<string, unknown>
}

export interface InitialState {
  agentState: AgentState
  guiMode: boolean
  currentTask: { id: string; name: string } | null
  messages: ChatMessage[]
  actions: ActionItem[]
  status: string
  dashboardMetrics?: DashboardMetrics
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
  model: ModelMetrics
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

export interface Settings {
  general: GeneralSettings
  model: ModelSettings
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

// ─────────────────────────────────────────────────────────────────────
// Task Control
// ─────────────────────────────────────────────────────────────────────

export interface TaskCancelResponse {
  taskId: string
  success: boolean
  status?: 'cancelled' | 'error'
  error?: string
}

// ─────────────────────────────────────────────────────────────────────
// Navigation
// ─────────────────────────────────────────────────────────────────────

export type NavTab = 'chat' | 'tasks' | 'dashboard' | 'screen' | 'workspace' | 'settings'
