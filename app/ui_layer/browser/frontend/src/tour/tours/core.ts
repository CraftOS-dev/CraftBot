import type { TourDefinition } from '../types'

// The first-run orientation tour. This is pure data: adding, reordering, or
// rewording a step is a one-line edit here with no engine changes. Keep it
// short (orientation, not documentation) — deeper surfaces are better served
// by their own contextual mini-tours added to the registry later.
export const coreTour: TourDefinition = {
  id: 'core',
  autoStart: true,
  steps: [
    {
      // Opens a fresh New Chat first, so the whole walkthrough runs on a clean
      // draft session rather than the user's persistent Main session.
      id: 'welcome',
      env: ['openNewChat'],
      popover: {
        title: 'Welcome to CraftBot',
        description:
          'One agent for every kind of work. Here is a quick tour of the essentials. It takes about a minute.',
      },
    },
    {
      id: 'chat-composer',
      anchor: 'chat-composer',
      popover: {
        title: 'Talk to your agent',
        description:
          'Type anything here: a question, a task, or a whole project. This is the main way you work with CraftBot.',
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
        title: 'Your Main chat',
        description:
          "Main is the agent's home chat: it can't be deleted or renamed, and anything that happens on its own, like scheduled tasks or updates from connected apps, arrives here. Hover the info icon beside it for the details.",
        side: 'right',
        align: 'start',
      },
    },
    {
      id: 'living-ui',
      anchor: 'nav-living-ui',
      env: ['ensureSidebarVisible', 'closeLivingUIModal'],
      popover: {
        title: 'Living UI apps',
        description:
          'Ask CraftBot to build you a real app (a tracker, a CRM, a dashboard) and it appears here, built and running. There are three ways to add one:',
        side: 'right',
        align: 'start',
      },
    },
    // Open the "Add Living UI" modal and walk its three creation methods, one
    // per tab. The modal is closed again by the Dashboard step below.
    {
      id: 'living-ui-marketplace',
      env: ['openLivingUIModal', { id: 'openLivingUITab', arg: 'marketplace' }],
      anchor: 'livingui-tab-marketplace',
      popover: {
        title: 'Marketplace',
        description:
          'Install a ready-made app from the community marketplace with a single click.',
        side: 'bottom',
        align: 'start',
      },
    },
    {
      id: 'living-ui-custom',
      env: ['openLivingUIModal', { id: 'openLivingUITab', arg: 'custom' }],
      anchor: 'livingui-tab-custom',
      popover: {
        title: 'Create Custom',
        description:
          'Describe what you want and the agent builds it: configure a few basics, answer a short interview, then it writes the spec and builds the app.',
        side: 'bottom',
        align: 'center',
      },
    },
    {
      id: 'living-ui-import',
      env: ['openLivingUIModal', { id: 'openLivingUITab', arg: 'import' }],
      anchor: 'livingui-tab-import',
      popover: {
        title: 'Import',
        description:
          'Bring in an existing Living UI from a ZIP, a folder, or a git URL.',
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
      env: ['closeLivingUIModal', 'ensureSidebarVisible'],
      popover: {
        title: 'Your Dashboard',
        description:
          'A live control room for your agent, tracking usage, activity, and system health.',
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
        title: 'Your workspace',
        description: 'Browse the files your agent reads and writes, and upload your own.',
        side: 'right',
        align: 'start',
      },
    },
    {
      id: 'settings',
      route: '/settings',
      anchor: 'settings-categories',
      popover: {
        title: 'Settings',
        description:
          'Configure everything about your agent here. A few areas worth knowing:',
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
        title: 'Proactive',
        description:
          'Let your agent work on its own: run scheduled tasks and react to events without being asked.',
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
        title: 'Skills',
        description:
          'Add reusable capabilities so your agent knows how to carry out specific tasks.',
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
        title: 'Integrations',
        description:
          'Connect apps like Gmail, Calendar, and Drive so your agent can work across them.',
        side: 'right',
        align: 'center',
      },
    },
    {
      // Return to a fresh New Chat so the user lands ready to start working.
      id: 'done',
      env: ['openNewChat'],
      popover: {
        title: "You're all set",
        description:
          'That is the tour. You can replay it any time from Settings, or the Welcome card on your Dashboard.',
      },
    },
  ],
}
