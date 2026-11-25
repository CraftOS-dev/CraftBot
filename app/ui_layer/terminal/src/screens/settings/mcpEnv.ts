/**
 * Settings > MCP env editing, without the UI (#185).
 *
 * Env editing is write-only: the backend sends only which env keys are set,
 * never their values, so the form starts empty and an empty field means
 * "keep the stored value", never "set it to ''".
 */
import type { MCPServerConfig } from '../../../../browser/frontend/src/store/slices/mcpSettingsSlice'

/** The backend says whether a server still needs values (env says only
 * which keys are set: values are never sent to a client). */
export function needsConfig(server: MCPServerConfig): boolean {
  if (typeof server.needs_config === 'boolean') return server.needs_config
  return Object.values(server.env ?? {}).some(isSet => !isSet)
}

/** Env keys to save: those the user typed a value for. Stored values never
 * reach this client, so an empty field means "keep what is stored". */
export function envKeysToSave(keys: string[], values: Record<string, unknown>): string[] {
  return keys.filter(key => typeof values[key] === 'string' && values[key] !== '')
}
