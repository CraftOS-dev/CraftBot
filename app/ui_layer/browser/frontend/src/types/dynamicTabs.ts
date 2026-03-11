// Dynamic Tab Types

export type DynamicTabType = 'code' | 'stock' | 'planner' | 'custom'

export interface DynamicTab {
  id: string
  type: DynamicTabType
  label: string
  iconName: string // lucide icon name
  path: string
  taskId: string | null // linked task ID
  createdAt: number
  lastAccessed: number
}

// ─── Tab Data Types ───────────────────────────────────────────────────
// Structured data pushed by the agent for each tab type

export interface CodeTabData {
  rawDiff?: string       // Raw unified diff output (e.g. from `git diff`)
  commits?: CommitEntry[]
  summary?: string
}

export interface CommitEntry {
  hash: string
  message: string
  author: string
  timestamp: number
}

export interface StockTabData {
  ticker?: string
  name?: string
  price?: number
  change?: number
  changePercent?: number
  chartData?: StockDataPoint[]
  summary?: string
}

export interface StockDataPoint {
  timestamp: number
  open: number
  high: number
  low: number
  close: number
  volume: number
}

export interface PlannerTabData {
  title?: string
  milestones?: PlannerMilestone[]
  tasks?: PlannerTask[]
  summary?: string
}

export interface PlannerMilestone {
  id: string
  name: string
  date: string
  status: 'pending' | 'in-progress' | 'completed'
}

export interface PlannerTask {
  id: string
  name: string
  status: 'todo' | 'in-progress' | 'done'
  priority: 'low' | 'medium' | 'high'
  assignee?: string
  dueDate?: string
  milestoneId?: string
}

export interface CustomTabData {
  title?: string
  content?: string // markdown content
  data?: Record<string, unknown> // arbitrary JSON
}

export type TabData = CodeTabData | StockTabData | PlannerTabData | CustomTabData

// ─── Persistence & Preferences ────────────────────────────────────────

export interface PersistedTabState {
  tabs: DynamicTab[]
  activeTabId: string | null
  userPreferences: DynamicTabPreferences
}

export interface DynamicTabPreferences {
  autoCreateTabs: boolean
  maxTabs: number
}

export const DEFAULT_TAB_PREFERENCES: DynamicTabPreferences = {
  autoCreateTabs: true,
  maxTabs: 10,
}

export const TAB_TYPE_CONFIG: Record<DynamicTabType, { defaultIcon: string; defaultLabel: string }> = {
  code: { defaultIcon: 'Code2', defaultLabel: 'Code' },
  stock: { defaultIcon: 'TrendingUp', defaultLabel: 'Stocks' },
  planner: { defaultIcon: 'CalendarRange', defaultLabel: 'Planner' },
  custom: { defaultIcon: 'LayoutPanelLeft', defaultLabel: 'Custom' },
}
