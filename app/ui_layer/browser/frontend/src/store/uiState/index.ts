// Persisted UI state: descriptors, the catalog of everything remembered, and
// the storage/persistence plumbing wired into the store. Components use it
// through the hooks in src/hooks (usePersistedState & co.).
export { UI_STATE } from './catalog'
export type { ChatReplyTarget, OpenRouterFilters, ThemePreference } from './catalog'
export type { UiStateDescriptor, UiStateLifetime } from './defineUiState'
export { createUiPersistenceMiddleware, loadPersistedUiState } from './persistence'
