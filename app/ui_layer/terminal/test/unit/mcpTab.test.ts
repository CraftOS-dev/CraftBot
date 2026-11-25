/**
 * Settings > MCP: env editing is write-only (#185). The backend sends only
 * which env keys are set, never their values, so the form starts empty and
 * an empty field must mean "keep the stored value", never "set it to ''".
 */
import { describe, expect, it } from 'vitest'
import { envKeysToSave, needsConfig } from '../../src/screens/settings/mcpEnv'
import type { MCPServerConfig } from '../../../browser/frontend/src/store/slices/mcpSettingsSlice'

const server = (overrides: Partial<MCPServerConfig> = {}): MCPServerConfig => ({
  name: 'remote',
  description: '',
  enabled: true,
  transport: 'http',
  action_set: 'mcp_remote',
  env: {},
  ...overrides,
})

describe('envKeysToSave', () => {
  it('saves only keys the user typed a value for', () => {
    expect(envKeysToSave(['A', 'B', 'C'], { A: 'new', B: '', C: undefined })).toEqual(['A'])
  })

  it('never turns an untouched field into an empty value', () => {
    // The old editor compared against stored values; with write-only
    // values every untouched field is '' and must be left alone.
    expect(envKeysToSave(['TOKEN'], { TOKEN: '' })).toEqual([])
  })

  it('ignores non-text form values', () => {
    expect(envKeysToSave(['A'], { A: true })).toEqual([])
  })
})

describe('needsConfig', () => {
  it('uses the backend flag when present', () => {
    expect(needsConfig(server({ needs_config: true, env: { A: true } }))).toBe(true)
    expect(needsConfig(server({ needs_config: false, env: { A: false } }))).toBe(false)
  })

  it('falls back to which env keys are set', () => {
    expect(needsConfig(server({ env: { A: true, B: false } }))).toBe(true)
    expect(needsConfig(server({ env: { A: true } }))).toBe(false)
    expect(needsConfig(server({ env: {} }))).toBe(false)
  })
})
