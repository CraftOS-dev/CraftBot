import type { MetricsTimePeriod } from '../../types'
import type { DashboardLayoutsStorage } from '../../pages/Dashboard/layout/types'
import type { SettingsCategory } from '../../pages/Settings/types'
import { defineUiState, defineUiStateFamily, oneOf } from './defineUiState'

/**
 * Every piece of UI state the web interface remembers — the single place to
 * see what is persisted, under which key, and for how long.
 *
 * Pages unmount when the user navigates, so state declared here lives in the
 * Redux `ui` slice instead of component state, and is persisted according to
 * its lifetime ('preference' → survives reloads, 'session' → this browser
 * tab only). Keys are stored as `craftbot.ui.<key>`.
 *
 * To remember something new:
 *   1. Declare it below under its feature, as `<feature>.<name>`.
 *   2. Use it: `const [value, setValue] = usePersistedState(UI_STATE.feature.name)`
 *      (or `usePersistedSet` for id sets, `useScrollRestoration` for scroll).
 *
 * Not everything belongs here: loading flags, open modals, half-typed form
 * input and server data should stay in component state or their data slice.
 */

export type ThemePreference = 'dark' | 'light' | 'system'

export interface ChatReplyTarget {
  displayName: string
  originalContent: string
}

export interface OpenRouterFilters {
  free: boolean
  vision: boolean
  tools: boolean
  cache: boolean
  /** '' = any upstream provider. */
  upstream: string
}

const METRICS_PERIODS: MetricsTimePeriod[] = ['1h', '1d', '1w', '1m', 'total']

export const UI_STATE = {
  theme: defineUiState<ThemePreference>('theme', 'dark', 'preference', {
    isValid: oneOf(['dark', 'light', 'system']),
  }),

  sidebar: {
    collapsed: defineUiState('sidebar.collapsed', false, 'preference'),
  },

  nav: {
    chatsExpanded: defineUiState('nav.chatsExpanded', true, 'preference'),
    agentAppExpanded: defineUiState('nav.agentAppExpanded', true, 'preference'),
  },

  tour: {
    /** By tour id. */
    completed: defineUiStateFamily('tour.completed', false, 'preference'),
  },

  chat: {
    /** Speech-recognition language code; '' follows the browser language. */
    micLanguage: defineUiState('chat.micLanguage', '', 'preference'),
    /** Sent inputs for ↑/↓ recall, oldest first, shared by all sessions. */
    inputHistory: defineUiState<string[]>('chat.inputHistory', [], 'session'),
    /** By session id: ids of the expanded "Action steps" chunks. */
    expandedChunks: defineUiStateFamily<string[]>('chat.expandedChunks', [], 'session'),
    /** By session id: timeline scroll offset; null = following the newest message. */
    scrollOffset: defineUiStateFamily<number | null>('chat.scrollOffset', null, 'session', {
      isValid: value => value === null || typeof value === 'number',
    }),
    /** By session id: the armed "Replying to…" target. */
    replyTarget: defineUiStateFamily<ChatReplyTarget | null>('chat.replyTarget', null, 'session', {
      isValid: value => value === null || typeof value === 'object',
    }),
    /** By message id: "Show message" details disclosure. */
    messageDetailsExpanded: defineUiStateFamily('chat.messageDetailsExpanded', false, 'session'),
    /** By question message id: the typed free-text answer. */
    questionAnswerDraft: defineUiStateFamily('chat.questionAnswerDraft', '', 'session'),
    /** Newest message id seen per session (unread dots); synced across tabs. */
    lastSeenMessageIds: defineUiState<Record<string, string>>('chat.lastSeenMessageIds', {}, 'preference'),
  },

  agentApp: {
    chatPanelOpen: defineUiState('agentApp.chatPanelOpen', true, 'preference'),
    /** Desktop chat panel width in px. */
    chatPanelWidth: defineUiState('agentApp.chatPanelWidth', 350, 'preference'),
    /** Mobile chat panel height as a share of the page. */
    chatPanelMobileRatio: defineUiState('agentApp.chatPanelMobileRatio', 0.4, 'preference'),
  },

  memory: {
    /** Right sidebar width in px. */
    panelWidth: defineUiState('memory.panelWidth', 340, 'preference'),
    hideCoreFiles: defineUiState('memory.hideCoreFiles', false, 'preference'),
    showMemories: defineUiState('memory.showMemories', true, 'preference'),
    showEntities: defineUiState('memory.showEntities', true, 'preference'),
    showFiles: defineUiState('memory.showFiles', true, 'preference'),
    showEntityLinks: defineUiState('memory.showEntityLinks', true, 'preference'),
    showFileLinks: defineUiState('memory.showFileLinks', true, 'preference'),
    /** Folder paths expanded in the file tree. */
    expandedFolders: defineUiState<string[]>('memory.expandedFolders', [], 'preference'),
    selectedNodeId: defineUiState<string | null>('memory.selectedNodeId', null, 'session', {
      isValid: value => value === null || typeof value === 'string',
    }),
    search: defineUiState('memory.search', '', 'session'),
    fileTreeScrollTop: defineUiState('memory.fileTreeScrollTop', 0, 'session'),
  },

  dashboard: {
    /** Named layouts; validated against STORAGE_VERSION by useDashboardLayouts. */
    layouts: defineUiState<DashboardLayoutsStorage | null>('dashboard.layouts', null, 'preference', {
      isValid: value => typeof value === 'object',
    }),
    /** '' = the first layout. */
    activeLayoutId: defineUiState('dashboard.activeLayoutId', '', 'preference'),
    /** By widget id: the selected time range. */
    metricsPeriod: defineUiStateFamily<MetricsTimePeriod>('dashboard.metricsPeriod', 'total', 'preference', {
      isValid: oneOf(METRICS_PERIODS),
    }),
    /** By widget id: "View all" expanded. */
    showAll: defineUiStateFamily('dashboard.showAll', false, 'session'),
    introShowDetails: defineUiState('dashboard.introShowDetails', false, 'session'),
    scrollTop: defineUiState('dashboard.scrollTop', 0, 'session'),
  },

  workspace: {
    /** By directory path. */
    fileListScrollTop: defineUiStateFamily('workspace.fileListScrollTop', 0, 'session'),
    /** Checked file paths. */
    selectedPaths: defineUiState<string[]>('workspace.selectedPaths', [], 'session'),
    mobileShowPreview: defineUiState('workspace.mobileShowPreview', false, 'session'),
  },

  settings: {
    /** Membership is checked by SettingsPage, so a removed tab falls back to General. */
    activeCategory: defineUiState<SettingsCategory>('settings.activeCategory', 'general', 'preference'),
    /** By category: the page scroll offset. */
    scrollTop: defineUiStateFamily('settings.scrollTop', 0, 'session'),
    generalShowAdvanced: defineUiState('settings.general.showAdvanced', false, 'preference'),
    /** By provider: "Use API key instead" expanded. */
    modelApiKeyExpanded: defineUiState<Record<string, boolean>>('settings.model.apiKeyExpanded', {}, 'preference'),
    /** By picker ('llm' | 'vlm'). */
    openRouterSearch: defineUiStateFamily('settings.openRouter.search', '', 'session'),
    /** By picker ('llm' | 'vlm'). */
    openRouterFilters: defineUiStateFamily<OpenRouterFilters>('settings.openRouter.filters', {
      free: false,
      vision: false,
      tools: false,
      cache: false,
      upstream: '',
    }, 'preference'),
    skillsSearch: defineUiState('settings.skills.search', '', 'session'),
    mcpSearch: defineUiState('settings.mcp.search', '', 'session'),
    integrationsSearch: defineUiState('settings.integrations.search', '', 'session'),
    proactiveTaskSearch: defineUiState('settings.proactive.taskSearch', '', 'session'),
    /** Project ids whose cards are expanded. */
    agentAppExpandedProjects: defineUiState<string[]>('settings.agentApp.expandedProjects', [], 'preference'),
    /** By orphaned project id. */
    agentAppOrphanBackupsExpanded: defineUiStateFamily('settings.agentApp.orphanBackupsExpanded', false, 'preference'),
  },

  attachments: {
    /** Markdown attachments: rendered preview or raw source. */
    markdownView: defineUiState<'preview' | 'source'>('attachments.markdownView', 'preview', 'preference', {
      isValid: oneOf(['preview', 'source']),
    }),
  },
} as const
