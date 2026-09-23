import type { TourDefinition } from '../types'

// The first-run orientation tour. This is pure structure: adding, reordering,
// or repositioning a step is a one-line edit here with no engine changes. The
// step copy (title + description) is NOT stored here — it lives in the `tour`
// i18n catalog keyed by step id (`tour:steps.<id>.title` / `.description`), so
// it stays translatable. Keep the tour short (orientation, not documentation).
export const coreTour: TourDefinition = {
  id: 'core',
  autoStart: true,
  steps: [
    {
      // Opens a fresh New Chat first, so the whole walkthrough runs on a clean
      // draft session rather than the user's persistent Main session.
      id: 'welcome',
      env: ['openNewChat'],
    },
    {
      id: 'chat-composer',
      anchor: 'chat-composer',
      popover: {
        side: 'top',
        align: 'center',
      },
    },
    {
      // Opens the Main chat view, then highlights its pinned sidebar row (which
      // carries the "Why is Main different?" info tooltip) to explain it.
      id: 'main-session',
      route: '/',
      anchor: 'nav-main-session',
      env: ['ensureSidebarVisible', 'ensureChatsExpanded'],
      popover: {
        side: 'right',
        align: 'start',
      },
    },
    {
      id: 'agent-app',
      anchor: 'nav-agent-app',
      env: ['ensureSidebarVisible', 'closeAgentAppModal'],
      popover: {
        side: 'right',
        align: 'start',
      },
    },
    // Open the "Add Agent App" modal and walk its three creation methods, one
    // per tab. The modal is closed again by the Dashboard step below.
    {
      id: 'living-ui-marketplace',
      env: ['openAgentAppModal', { id: 'openAgentAppTab', arg: 'marketplace' }],
      anchor: 'agentapp-tab-marketplace',
      popover: {
        side: 'bottom',
        align: 'start',
      },
    },
    {
      id: 'agent-app-custom',
      env: ['openAgentAppModal', { id: 'openAgentAppTab', arg: 'custom' }],
      anchor: 'agentapp-tab-custom',
      popover: {
        side: 'bottom',
        align: 'center',
      },
    },
    {
      id: 'agent-app-import',
      env: ['openAgentAppModal', { id: 'openAgentAppTab', arg: 'import' }],
      anchor: 'agentapp-tab-import',
      popover: {
        side: 'bottom',
        align: 'end',
      },
    },
    // These steps open a destination and show the real page. Dashboard and
    // Workspace also highlight their sidebar button; Settings highlights an
    // element on the page itself.
    {
      id: 'dashboard',
      route: '/dashboard',
      anchor: 'nav-dashboard',
      env: ['closeAgentAppModal', 'ensureSidebarVisible'],
      popover: {
        side: 'right',
        align: 'start',
      },
    },
    {
      id: 'memory',
      route: '/memory',
      anchor: 'nav-memory',
      env: ['ensureSidebarVisible'],
      popover: {
        side: 'right',
        align: 'start',
      },
    },
    {
      id: 'workspace',
      route: '/workspace',
      anchor: 'nav-workspace',
      env: ['ensureSidebarVisible'],
      popover: {
        side: 'right',
        align: 'start',
      },
    },
    {
      id: 'settings',
      route: '/settings',
      anchor: 'settings-categories',
      popover: {
        side: 'right',
        align: 'start',
      },
    },
    {
      id: 'settings-proactive',
      route: '/settings',
      anchor: 'settings-proactive',
      env: [{ id: 'openSettingsTab', arg: 'proactive' }],
      popover: {
        side: 'right',
        align: 'center',
      },
    },
    {
      id: 'settings-skills',
      route: '/settings',
      anchor: 'settings-skills',
      env: [{ id: 'openSettingsTab', arg: 'skills' }],
      popover: {
        side: 'right',
        align: 'center',
      },
    },
    {
      id: 'settings-integrations',
      route: '/settings',
      anchor: 'settings-integrations',
      env: [{ id: 'openSettingsTab', arg: 'integrations' }],
      popover: {
        side: 'right',
        align: 'center',
      },
    },
    {
      // Return to a fresh New Chat so the user lands ready to start working.
      id: 'done',
      env: ['openNewChat'],
    },
  ],
}
