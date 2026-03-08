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

export type ActionStatus = 'running' | 'completed' | 'error' | 'pending'
export type ItemType = 'task' | 'action'

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
// Navigation
// ─────────────────────────────────────────────────────────────────────

export type NavTab = 'chat' | 'tasks' | 'dashboard' | 'screen' | 'workspace' | 'settings'
