import { describe, expect, it } from 'vitest'
import { parseConfig } from '../../src/config'
import { startupMessageReady } from '../../src/runtime/startupMessage'
import type { RootState } from '../../src/state/store'

function state(over: { connected?: boolean; hello?: boolean; needsHardOnboarding?: boolean; screens?: string[] } = {}): RootState {
  return {
    connection: { connected: over.connected ?? true },
    tui: {
      hello: over.hello === false ? null : { protocol: 1, edition: 'terminal', version: '1.4.6' },
      screens: (over.screens ?? []).map(id => ({ id })),
    },
    onboarding: { needsHardOnboarding: over.needsHardOnboarding ?? false },
  } as unknown as RootState
}

describe('--message', () => {
  it('is read in both spellings, trimmed, and empty means none', () => {
    expect(parseConfig(['--message', '  make a theme  '], {}).message).toBe('make a theme')
    expect(parseConfig(['--message=--starts with a dash'], {}).message).toBe('--starts with a dash')
    expect(parseConfig(['--message', '   '], {}).message).toBeNull()
    expect(parseConfig([], {}).message).toBeNull()
  })

  it('waits for the backend to greet the client and send its init', () => {
    expect(startupMessageReady(state(), false)).toBe(false)
    expect(startupMessageReady(state({ hello: false }), true)).toBe(false)
    expect(startupMessageReady(state({ connected: false }), true)).toBe(false)
    expect(startupMessageReady(state(), true)).toBe(true)
  })

  it('never reaches an agent that still needs onboarding', () => {
    expect(startupMessageReady(state({ needsHardOnboarding: true }), true)).toBe(false)
    expect(startupMessageReady(state({ screens: ['onboarding'] }), true)).toBe(false)
    expect(startupMessageReady(state({ screens: ['settings'] }), true)).toBe(true)
  })
})
