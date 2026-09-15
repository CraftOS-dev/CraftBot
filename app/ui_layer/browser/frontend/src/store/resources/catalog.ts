import type { ResourceDescriptor } from './ResourceSync'

/**
 * Every cached view of server data, keyed by name
 * (docs/plans/ui-data-freshness-plan.md, §A4.3).
 *
 * The pattern: a view calls `useResource(RESOURCES.x)` instead of a
 * fetch-once effect. The reply still lands in its slice as before;
 * ResourceSync only decides when to ask again (first use, a
 * `resource_changed` for `resource` while used, next use after going stale,
 * reconnect). Views keep `onMessage` listeners only for their own results:
 * toasts, spinners, closing modals.
 */
export const RESOURCES = {
  /** Sidebar / Agent App page list. The backend also pushes it on connect. */
  agentAppsList: {
    key: 'agentAppsList',
    resource: 'agent_apps',
    liveness: 'always',
    pushedOnConnect: true,
    request: (send) => send({ type: 'agent_app_list' }),
  },
  /** Sidebar sessions (order follows last activity). Pushed in `init`. */
  sessions: {
    key: 'sessions',
    resource: 'sessions',
    liveness: 'always',
    pushedOnConnect: true,
    request: (send) => send({ type: 'session_list' }),
  },
  /** Settings → Agent App project list with per-project settings. */
  agentAppSettings: {
    key: 'agentAppSettings',
    resource: 'agent_apps',
    request: (send) => send({ type: 'agent_app_settings_get' }),
  },

  // ── Proactive ──
  proactiveMode: {
    key: 'proactiveMode',
    resource: 'proactive',
    request: (send) => send({ type: 'proactive_mode_get' }),
  },
  proactiveTasks: {
    key: 'proactiveTasks',
    resource: 'proactive',
    // Run counts and last/next run change when tasks fire, unannounced.
    pollWhileVisible: 30_000,
    request: (send) => send({ type: 'proactive_tasks_get' }),
  },
  schedulerConfig: {
    key: 'schedulerConfig',
    resource: 'scheduler',
    request: (send) => send({ type: 'scheduler_config_get' }),
  },

  // ── Memory ──
  memoryMode: {
    key: 'memoryMode',
    resource: 'memory',
    request: (send) => send({ type: 'memory_mode_get' }),
  },
  memoryItems: {
    key: 'memoryItems',
    resource: 'memory',
    request: (send) => send({ type: 'memory_items_get' }),
  },
  memoryGraph: {
    key: 'memoryGraph',
    resource: 'memory',
    request: (send) => send({ type: 'memory_graph_get' }),
  },
  memoryIndexedFiles: {
    key: 'memoryIndexedFiles',
    resource: 'memory',
    request: (send) => send({ type: 'memory_indexed_files_get' }),
  },
  /** Daily auto-processing time + threshold (lives in the scheduler). */
  memorySchedule: {
    key: 'memorySchedule',
    resource: 'scheduler',
    request: (send) => send({ type: 'memory_schedule_get' }),
  },

  // ── General ──
  generalSettings: {
    key: 'generalSettings',
    resource: 'general_settings',
    request: (send) => send({ type: 'settings_get' }),
  },
  /** USER.md, AGENT.md and SOUL.md for the General → Advanced editors. */
  agentFiles: {
    key: 'agentFiles',
    resource: 'agent_files',
    request: (send) => {
      for (const filename of ['USER.md', 'AGENT.md', 'SOUL.md']) {
        send({ type: 'agent_file_read', filename })
      }
    },
  },

  // ── Skills, commands, MCP, integrations ──
  skills: {
    key: 'skills',
    resource: 'skills',
    request: (send) => send({ type: 'skill_list' }),
  },
  /** Non-skill slash commands for the chat autocomplete. */
  commands: {
    key: 'commands',
    resource: 'skills',
    request: (send) => send({ type: 'command_list' }),
  },
  /** Internal/reserved skill names (agentSlice). Pushed on every connect. */
  skillMeta: {
    key: 'skillMeta',
    resource: 'skills',
    liveness: 'always',
    pushedOnConnect: true,
    request: (send) => send({ type: 'skill_meta_get' }),
  },
  mcpServers: {
    key: 'mcpServers',
    resource: 'mcp_servers',
    request: (send) => send({ type: 'mcp_list' }),
  },
  integrations: {
    key: 'integrations',
    resource: 'integrations',
    // Listener health and WhatsApp re-link state change without any event.
    pollWhileVisible: 15_000,
    request: (send) => send({ type: 'integration_list' }),
  },

  // ── Model ──
  /** Provider registry; only changes with a backend update. */
  modelProviders: {
    key: 'modelProviders',
    resource: 'static',
    request: (send) => send({ type: 'model_providers_get' }),
  },
  modelSettings: {
    key: 'modelSettings',
    resource: 'model_settings',
    // A subscription can be revoked in the background.
    pollWhileVisible: 30_000,
    request: (send) => send({ type: 'model_settings_get' }),
  },
  slowMode: {
    key: 'slowMode',
    resource: 'model_settings',
    request: (send) => send({ type: 'slow_mode_get' }),
  },

  // ── Static catalogs: refreshed after a reconnect ──
  playbooks: {
    key: 'playbooks',
    resource: 'static',
    request: (send) => send({ type: 'playbook_list' }),
  },
} satisfies Record<string, ResourceDescriptor>
