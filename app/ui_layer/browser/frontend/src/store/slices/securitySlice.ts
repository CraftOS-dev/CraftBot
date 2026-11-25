import { createSlice, PayloadAction } from '@reduxjs/toolkit'
import { register } from '../socket/messageRegistry'

/**
 * Settings → Security and the approval card (app/ui_layer/settings/security_settings.py).
 *
 * Shared by the browser and the terminal client: both render from this state
 * and answer approvals with `security_approval_response`.
 */

export type SecurityLevel = 'standard' | 'enhanced' | 'strict'

/** What an action can do, as it declares it (app/security/policy.py Effect). */
export type SecurityEffect =
  | 'execute'
  | 'write_files'
  | 'send_external'
  | 'change_agent'
  | 'use_credentials'

/** The effective settings (SecurityPolicy.to_dict). */
export interface SecurityPolicy {
  level: SecurityLevel
  customized: boolean
  auto_mode: boolean
  approval_effects: SecurityEffect[]
  ask_after_untrusted: boolean
  approval_timeout_s: number
  /** Start MCP servers only as saved through Settings. */
  limit_third_party_runs: boolean
  limit_scheduled_runs: boolean
  check_commands: boolean
  verify_mcp_servers: boolean
  check_mcp_packages: boolean
  scan_skills: boolean
  verify_downloads: boolean
  redact_tool_output: boolean
  strip_chat_tokens: boolean
  protect_secret_files: boolean
  protect_os_credentials: boolean
  guard_memory: boolean
  extra_protected_paths: string[]
  confine_writes: boolean
  workspace_paths: string[]
  network_guard: boolean
  allowed_domains: string[]
  third_party_reader: boolean
  scrub_child_env: boolean
  log_prompts: boolean
  retention_days: number
  /** Only these senders' emails reach the agent; empty: every inbox email. */
  email_allowed_senders: string[]
}

/** Settings the page may change with `security_update` (everything but level/customized). */
export type SecuritySettingKey = Exclude<keyof SecurityPolicy, 'level' | 'customized'>

export interface ApprovalRequest {
  id: string
  session_id: string
  action_name: string
  action_display_name: string
  effects: SecurityEffect[]
  /** 'high_risk': the action's effects need approval. 'untrusted_content': the run read outside content. */
  reason: 'high_risk' | 'untrusted_content' | 'risky_command'
  reason_detail: string
  /** What "allow for this session" covers: the action, or this exact command. */
  grant_scope?: 'action' | 'command'
  /** The action's inputs, long values shortened. */
  inputs: Record<string, unknown>
  /** Unix seconds. */
  created_at: number
  expires_at: number
}

export type ApprovalDecision = 'allow_once' | 'allow_session' | 'deny'

export interface SecurityCheck {
  id: string
  status: 'ok' | 'info' | 'warn' | 'fail'
  title: string
  detail: string
  fix_id: string | null
}

export interface AuditEntry {
  ts: number
  event: string
  prev: string
  [field: string]: unknown
}

export interface AuditView {
  entries: AuditEntry[]
  intact: boolean
  count: number
  brokenAt: number | null
  path: string
}

interface SecurityState {
  policy: SecurityPolicy | null
  /** Each level's preset, for showing what switching level changes. */
  presets: Partial<Record<SecurityLevel, SecurityPolicy>>
  /** Settings changed on top of the level (why it shows as Custom). */
  overrides: string[]
  effects: SecurityEffect[]
  highRiskEffects: SecurityEffect[]
  hasLoaded: boolean
  /** Last refused change, shown on the page until the next success. */
  error: string | null
  approvals: ApprovalRequest[]
  checks: SecurityCheck[]
  hasLoadedChecks: boolean
  audit: AuditView | null
}

const initialState: SecurityState = {
  policy: null,
  presets: {},
  overrides: [],
  effects: [],
  highRiskEffects: [],
  hasLoaded: false,
  error: null,
  approvals: [],
  checks: [],
  hasLoadedChecks: false,
  audit: null,
}

interface StatePayload {
  success: boolean
  error?: string | null
  policy: SecurityPolicy
  presets: Partial<Record<SecurityLevel, SecurityPolicy>>
  overrides: string[]
  effects: SecurityEffect[]
  high_risk_effects: SecurityEffect[]
}

const securitySlice = createSlice({
  name: 'security',
  initialState,
  reducers: {
    setSecurityState(state, action: PayloadAction<StatePayload>) {
      const d = action.payload
      if (d.policy) {
        state.policy = d.policy
        state.presets = d.presets || {}
        state.overrides = d.overrides || []
        state.effects = d.effects || []
        state.highRiskEffects = d.high_risk_effects || []
        state.hasLoaded = true
      }
      state.error = d.success ? null : d.error || 'The change was not saved'
    },
    addApproval(state, action: PayloadAction<ApprovalRequest>) {
      if (!state.approvals.some(a => a.id === action.payload.id)) {
        state.approvals.push(action.payload)
      }
    },
    removeApproval(state, action: PayloadAction<string>) {
      state.approvals = state.approvals.filter(a => a.id !== action.payload)
    },
    setApprovals(state, action: PayloadAction<ApprovalRequest[]>) {
      state.approvals = action.payload
    },
    setChecks(state, action: PayloadAction<SecurityCheck[]>) {
      state.checks = action.payload
      state.hasLoadedChecks = true
    },
    setAudit(state, action: PayloadAction<AuditView>) {
      state.audit = action.payload
    },
    setSecurityError(state, action: PayloadAction<string | null>) {
      state.error = action.payload
    },
  },
})

export const {
  setSecurityState,
  addApproval,
  removeApproval,
  setApprovals,
  setChecks,
  setAudit,
  setSecurityError,
} = securitySlice.actions

export default securitySlice.reducer

register('security_state', (data, dispatch) => {
  dispatch(setSecurityState(data as StatePayload))
})

register('security_approval_request', (data, dispatch) => {
  dispatch(addApproval(data as ApprovalRequest))
})

register('security_approval_resolved', (data, dispatch) => {
  dispatch(removeApproval((data as { id: string }).id))
})

register('security_approvals_pending', (data, dispatch) => {
  const d = data as { success: boolean; requests?: ApprovalRequest[] }
  if (d.success) dispatch(setApprovals(d.requests || []))
})

register('security_approval_answer', (data, dispatch) => {
  const d = data as { success: boolean; error?: string }
  if (!d.success) dispatch(setSecurityError(d.error || 'The answer was not accepted'))
})

register('security_check', (data, dispatch) => {
  const d = data as { success: boolean; checks?: SecurityCheck[]; error?: string }
  if (d.checks) dispatch(setChecks(d.checks))
  if (!d.success) dispatch(setSecurityError(d.error || 'The fix did not apply'))
})

register('security_audit', (data, dispatch) => {
  const d = data as {
    success: boolean
    entries: AuditEntry[]
    intact: boolean
    count: number
    broken_at: number | null
    path: string
  }
  if (d.success) {
    dispatch(
      setAudit({
        entries: d.entries || [],
        intact: d.intact,
        count: d.count,
        brokenAt: d.broken_at,
        path: d.path,
      }),
    )
  }
})
