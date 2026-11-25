/**
 * Pure helpers of Settings > Security: the levels in order, which effects
 * ask first, the Advanced settings' order and parsing the retention input.
 */
import type {
  SecurityEffect,
  SecurityLevel,
  SecurityPolicy,
} from '../../../../browser/frontend/src/store/slices/securitySlice'

export const SECURITY_LEVELS: readonly SecurityLevel[] = ['standard', 'enhanced', 'strict']

/** Effects that can ask first, in the page's order (app/security/policy.py Effect). */
export const APPROVAL_EFFECTS: readonly SecurityEffect[] = ['execute', 'write_files', 'send_external', 'change_agent', 'use_credentials']

/** The Advanced on/off settings, in the page's order. */
export const ADVANCED_TOGGLES = [
  'protect_secret_files',
  'protect_os_credentials',
  'confine_writes',
  'redact_tool_output',
  'strip_chat_tokens',
  'guard_memory',
  'network_guard',
  'third_party_reader',
  'limit_third_party_runs',
  'limit_scheduled_runs',
  'check_commands',
  'scrub_child_env',
  'verify_mcp_servers',
  'check_mcp_packages',
  'scan_skills',
  'verify_downloads',
  'log_prompts',
] as const satisfies readonly (keyof SecurityPolicy)[]

export type AdvancedToggle = (typeof ADVANCED_TOGGLES)[number]

/** The path and domain lists (shown read-only here). */
export const SECURITY_LISTS = ['extra_protected_paths', 'workspace_paths', 'allowed_domains', 'email_allowed_senders'] as const satisfies readonly (keyof SecurityPolicy)[]

export function levelRank(level: SecurityLevel): number {
  return Math.max(0, SECURITY_LEVELS.indexOf(level))
}

/** Switching `from` to `to` turns protections off. */
export function isLowering(from: SecurityLevel, to: SecurityLevel): boolean {
  return levelRank(to) < levelRank(from)
}

/** `effects` with `effect` asked (on) or not (off), in the page's order. */
export function withEffect(effects: readonly SecurityEffect[], effect: SecurityEffect, on: boolean): SecurityEffect[] {
  const next = new Set(effects)
  if (on) next.add(effect)
  else next.delete(effect)
  return APPROVAL_EFFECTS.filter(e => next.has(e))
}

/** A retention input as whole days (0 keeps everything), or null when it is not one. */
export function parseRetentionDays(input: string): number | null {
  const text = input.trim()
  if (!/^\d+$/.test(text)) return null
  const days = Number(text)
  return Number.isSafeInteger(days) ? days : null
}
