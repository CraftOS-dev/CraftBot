import { useEffect, useState, type KeyboardEvent, type ReactNode } from 'react'
import {
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  Info,
  Loader2,
  Plus,
  RefreshCw,
  RotateCcw,
  Shield,
  ShieldCheck,
  ShieldPlus,
  SlidersHorizontal,
  Wrench,
  X,
  XCircle,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Badge, Button, ConfirmModal } from '../../components/ui'
import { useConfirmModal, usePersistedState } from '../../hooks'
import i18n from '../../i18n/config'
import { formatDateTime, formatNumber } from '../../i18n/format'
import { RESOURCES, useResource } from '../../store/resources'
import { useAppSelector } from '../../store/hooks'
import { UI_STATE } from '../../store/uiState'
import type {
  AuditEntry,
  SecurityCheck,
  SecurityEffect,
  SecurityLevel,
  SecurityPolicy,
  SecuritySettingKey,
} from '../../store/slices/securitySlice'
import styles from './SettingsPage.module.css'
import sec from './SecuritySettings.module.css'
import { useSettingsWebSocket } from './useSettingsWebSocket'

const LEVELS: SecurityLevel[] = ['standard', 'enhanced', 'strict']
const LEVEL_RANK: Record<SecurityLevel, number> = { standard: 0, enhanced: 1, strict: 2 }
const LEVEL_ICONS = { standard: Shield, enhanced: ShieldCheck, strict: ShieldPlus } as const

/** "Ask before" options, in the order the page lists them. */
const EFFECTS: SecurityEffect[] = ['execute', 'write_files', 'send_external', 'change_agent', 'use_credentials']

/** Approval timeout choices in seconds (the backend accepts 10–3600). */
const TIMEOUT_OPTIONS = [30, 60, 120, 300, 600, 900, 1800, 3600]

/** Retention choices in days; 0 keeps everything. */
const RETENTION_OPTIONS = [0, 7, 14, 30, 90, 180, 365]

type ToggleKey =
  | 'limit_third_party_runs'
  | 'limit_scheduled_runs'
  | 'check_commands'
  | 'verify_mcp_servers'
  | 'check_mcp_packages'
  | 'scan_skills'
  | 'verify_downloads'
  | 'redact_tool_output'
  | 'strip_chat_tokens'
  | 'protect_secret_files'
  | 'protect_os_credentials'
  | 'guard_memory'
  | 'confine_writes'
  | 'network_guard'
  | 'third_party_reader'
  | 'scrub_child_env'
  | 'log_prompts'

type ListKey = 'extra_protected_paths' | 'workspace_paths' | 'allowed_domains' | 'email_allowed_senders'

/** Allow-lists: empty means everything is allowed, so the page says so. */
type AllowListKey = 'allowed_domains' | 'email_allowed_senders'
const isAllowList = (key: ListKey): key is AllowListKey =>
  key === 'allowed_domains' || key === 'email_allowed_senders'

const AUDIT_EVENTS = ['action_approval', 'security_settings_changed', 'security_check_fixed'] as const
type KnownAuditEvent = (typeof AUDIT_EVENTS)[number]
const AUDIT_SHOWN = 50
const AUDIT_HIDDEN_FIELDS = new Set(['ts', 'event', 'prev'])

const isKnownAuditEvent = (event: string): event is KnownAuditEvent =>
  (AUDIT_EVENTS as readonly string[]).includes(event)

// "30 seconds", "5 minutes", "1 hour".
function formatTimeout(seconds: number): string {
  if (seconds >= 3600 && seconds % 3600 === 0) {
    return i18n.t('settings:security.autoMode.hours', { count: seconds / 3600 })
  }
  if (seconds >= 60 && seconds % 60 === 0) {
    return i18n.t('settings:security.autoMode.minutes', { count: seconds / 60 })
  }
  return i18n.t('settings:security.autoMode.seconds', { count: seconds })
}

function formatRetention(days: number): string {
  return days === 0
    ? i18n.t('settings:security.fields.retention_days.forever')
    : i18n.t('settings:security.fields.retention_days.days', { count: days })
}

function withCurrent(options: number[], current: number): number[] {
  return options.includes(current) ? options : [...options, current].sort((a, b) => a - b)
}

function auditEventLabel(event: string): string {
  if (isKnownAuditEvent(event)) return i18n.t(`settings:security.audit.events.${event}`)
  const text = event.replace(/_/g, ' ')
  return text.charAt(0).toUpperCase() + text.slice(1)
}

/** Setting names as the page shows them, for "changed" in the audit log. */
const SETTING_LABELS: Record<string, string> = {
  level: 'settings:security.level.title',
  auto_mode: 'settings:security.autoMode.label',
  approval_effects: 'settings:security.autoMode.askTitle',
  ask_after_untrusted: 'settings:security.autoMode.askAfterUntrusted',
  approval_timeout_s: 'settings:security.autoMode.timeout',
}

function settingLabel(key: string): string {
  const id = SETTING_LABELS[key] ?? `settings:security.fields.${key}.label`
  if (i18n.exists(id)) return String(i18n.t(id as never))
  // A setting older records name that is no longer on the page.
  const text = key.replace(/_/g, ' ')
  return text.charAt(0).toUpperCase() + text.slice(1)
}

function auditValue(value: unknown): string {
  if (Array.isArray(value)) return value.map(v => (typeof v === 'string' ? v : JSON.stringify(v))).join(', ')
  if (value !== null && typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

type Send = (type: string, data?: Record<string, unknown>) => void
type OnMessage = (type: string, handler: (data: unknown) => void) => () => void

export function SecuritySettings() {
  const { t } = useTranslation(['settings', 'common'])
  const { send, onMessage } = useSettingsWebSocket()
  const { modalProps: confirmModalProps, confirm } = useConfirmModal()
  const [showAdvanced, setShowAdvanced] = usePersistedState(UI_STATE.settings.securityShowAdvanced)

  // Cached in securitySlice; ResourceSync refetches it whenever the settings
  // change (this tab, another window or the terminal).
  useResource(RESOURCES.securityState)
  const policy = useAppSelector(state => state.security.policy)
  const hasLoaded = useAppSelector(state => state.security.hasLoaded)
  const error = useAppSelector(state => state.security.error)

  // Each change sends just that setting; the reply updates every window.
  const update = <K extends SecuritySettingKey>(key: K, value: SecurityPolicy[K]) => {
    send('security_update', { changes: { [key]: value } })
  }

  const levelName = (level: SecurityLevel) => t(`settings:security.level.${level}.name`)

  // Raising security applies at once; lowering it asks first.
  const chooseLevel = (level: SecurityLevel) => {
    if (!policy || level === policy.level) return
    const apply = () => send('security_set_level', { level })
    if (LEVEL_RANK[level] >= LEVEL_RANK[policy.level]) {
      apply()
      return
    }
    confirm({
      title: t('settings:security.level.lowerTitle', { level: levelName(level) }),
      message: t('settings:security.level.lowerMessage', { from: levelName(policy.level) }),
      confirmText: t('settings:security.level.lowerConfirm', { level: levelName(level) }),
      variant: 'danger',
    }, apply)
  }

  const header = (
    <div className={styles.sectionHeader}>
      <h3>{t('settings:security.title')}</h3>
      <p>{t('settings:security.subtitle')}</p>
    </div>
  )

  if (!hasLoaded || !policy) {
    return (
      <div className={styles.settingsSection}>
        {header}
        <div className={styles.loadingState}>
          <Loader2 size={20} className={styles.spinning} />
          <span>{t('settings:security.loading')}</span>
        </div>
      </div>
    )
  }

  const toggleEffect = (effect: SecurityEffect, on: boolean) => {
    const current = policy.approval_effects.filter(e => e !== effect)
    update('approval_effects', (on ? [...current, effect] : current).sort())
  }

  const label = (key: ToggleKey | ListKey | 'retention_days') => t(`settings:security.fields.${key}.label`)

  // A protection; a list that only applies while it is on shows under it.
  const toggleRow = (key: ToggleKey, list?: ListKey) => (
    <div className={sec.item} key={key}>
      <div className={sec.row}>
        <span className={sec.rowLabel}>{label(key)}</span>
        <input
          type="checkbox"
          className={styles.toggle}
          aria-label={label(key)}
          checked={policy[key]}
          onChange={e => update(key, e.target.checked)}
        />
      </div>
      {list && policy[key] && listField(list, true)}
    </div>
  )

  const listField = (key: ListKey, nested = false) => (
    <ListField
      key={key}
      label={label(key)}
      nested={nested}
      placeholder={t(`settings:security.fields.${key}.placeholder`)}
      emptyText={isAllowList(key) ? t(`settings:security.fields.${key}.empty`) : undefined}
      items={policy[key]}
      onChange={items => update(key, items)}
    />
  )

  const group = (id: 'files' | 'content' | 'network' | 'messages' | 'tools' | 'logs', rows: ReactNode) => (
    <div className={sec.group}>
      <div className={sec.groupTitle}>{t(`settings:security.advanced.groups.${id}`)}</div>
      <div className={sec.panel}>{rows}</div>
    </div>
  )

  return (
    <div className={styles.settingsSection}>
      {header}

      {error && (
        <div className={`${styles.errorText} ${sec.error}`} role="alert">
          {error}
        </div>
      )}

      {/* Auto mode; off, chosen actions wait for an approval card */}
      <div className={sec.panel}>
        <div className={sec.item}>
          <div className={sec.row}>
            <span className={sec.rowText}>
              <span className={sec.rowLabel}>{t('settings:security.autoMode.label')}</span>
              <span className={sec.rowDesc}>{t('settings:security.autoMode.desc')}</span>
            </span>
            <input
              type="checkbox"
              className={styles.toggle}
              aria-label={t('settings:security.autoMode.label')}
              checked={policy.auto_mode}
              onChange={e => update('auto_mode', e.target.checked)}
            />
          </div>
        </div>
        {!policy.auto_mode && (
          <>
            <div className={sec.item}>
              <div className={sec.askTitle}>{t('settings:security.autoMode.askTitle')}</div>
              <div className={sec.askGrid}>
                {EFFECTS.map(effect => (
                  <label key={effect} className={sec.check}>
                    <input
                      type="checkbox"
                      checked={policy.approval_effects.includes(effect)}
                      onChange={e => toggleEffect(effect, e.target.checked)}
                    />
                    <span>{t(`settings:security.effects.${effect}`)}</span>
                  </label>
                ))}
                <label className={sec.check}>
                  <input
                    type="checkbox"
                    checked={policy.ask_after_untrusted}
                    onChange={e => update('ask_after_untrusted', e.target.checked)}
                  />
                  <span>{t('settings:security.autoMode.askAfterUntrusted')}</span>
                </label>
              </div>
            </div>
            <div className={sec.item}>
              <div className={sec.row}>
                <label htmlFor="security-approval-timeout" className={sec.rowLabel}>
                  {t('settings:security.autoMode.timeout')}
                </label>
                <select
                  id="security-approval-timeout"
                  className={sec.select}
                  value={policy.approval_timeout_s}
                  onChange={e => update('approval_timeout_s', Number(e.target.value))}
                >
                  {withCurrent(TIMEOUT_OPTIONS, policy.approval_timeout_s).map(seconds => (
                    <option key={seconds} value={seconds}>{formatTimeout(seconds)}</option>
                  ))}
                </select>
              </div>
            </div>
          </>
        )}
      </div>

      {/* Level: presets over the protections under Advanced */}
      <div className={styles.subsection}>
        <div className={sec.titleRow}>
          <h4 className={styles.subsectionTitle}>{t('settings:security.level.title')}</h4>
          {policy.customized && (
            <Button
              variant="ghost"
              size="sm"
              icon={<RotateCcw size={14} />}
              onClick={() => send('security_set_level', { level: policy.level })}
            >
              {t('settings:security.level.reset')}
            </Button>
          )}
        </div>
        <div className={sec.levelGrid} role="radiogroup" aria-label={t('settings:security.level.title')}>
          {LEVELS.map(level => {
            const active = policy.level === level
            const Icon = LEVEL_ICONS[level]
            return (
              <button
                key={level}
                type="button"
                role="radio"
                aria-checked={active}
                className={`${sec.levelCard} ${active ? sec.levelCardActive : ''}`}
                onClick={() => chooseLevel(level)}
              >
                <span className={sec.levelHead}>
                  <Icon size={16} className={sec.levelIcon} />
                  <span className={sec.levelName}>{levelName(level)}</span>
                  {active && policy.customized && (
                    <Badge variant="warning">{t('settings:security.level.custom')}</Badge>
                  )}
                </span>
                <span className={sec.levelDesc}>{t(`settings:security.level.${level}.desc`)}</span>
              </button>
            )
          })}
        </div>
      </div>

      {/* Advanced: each protection on its own */}
      <div className={styles.advancedSection}>
        <button
          type="button"
          className={styles.advancedToggle}
          aria-expanded={showAdvanced}
          onClick={() => setShowAdvanced(!showAdvanced)}
        >
          <SlidersHorizontal size={18} />
          <span>{t('settings:security.advanced.toggle')}</span>
          <ChevronRight size={14} className={`${styles.advancedChevron} ${showAdvanced ? styles.open : ''}`} />
        </button>
        {showAdvanced && (
          <div className={styles.advancedContent}>
            {group('files', <>
              {toggleRow('protect_secret_files', 'extra_protected_paths')}
              {toggleRow('protect_os_credentials')}
              {toggleRow('confine_writes', 'workspace_paths')}
            </>)}
            {group('content', <>
              {toggleRow('redact_tool_output')}
              {toggleRow('strip_chat_tokens')}
              {toggleRow('guard_memory')}
            </>)}
            {group('network', <>
              {toggleRow('network_guard', 'allowed_domains')}
              {toggleRow('third_party_reader')}
            </>)}
            {group('messages', <>
              {toggleRow('limit_third_party_runs')}
              {toggleRow('limit_scheduled_runs')}
              <div className={sec.item}>{listField('email_allowed_senders')}</div>
            </>)}
            {group('tools', <>
              {toggleRow('check_commands')}
              {toggleRow('scrub_child_env')}
              {toggleRow('verify_mcp_servers')}
              {toggleRow('check_mcp_packages')}
              {toggleRow('scan_skills')}
              {toggleRow('verify_downloads')}
            </>)}
            {group('logs', <>
              {toggleRow('log_prompts')}
              <div className={sec.item}>
                <div className={sec.row}>
                  <label htmlFor="security-retention" className={sec.rowLabel}>{label('retention_days')}</label>
                  <select
                    id="security-retention"
                    className={sec.select}
                    value={policy.retention_days}
                    onChange={e => update('retention_days', Number(e.target.value))}
                  >
                    {withCurrent(RETENTION_OPTIONS, policy.retention_days).map(days => (
                      <option key={days} value={days}>{formatRetention(days)}</option>
                    ))}
                  </select>
                </div>
              </div>
            </>)}
          </div>
        )}
      </div>

      <SecurityCheckSection send={send} onMessage={onMessage} />
      <AuditLogSection send={send} onMessage={onMessage} />

      <ConfirmModal {...confirmModalProps} />
    </div>
  )
}

// ── List setting ───────────────────────────────────────────────────

interface ListFieldProps {
  label: string
  nested: boolean
  placeholder: string
  emptyText?: string
  items: string[]
  onChange: (items: string[]) => void
}

/** Paths, domains or addresses: entries as chips, then an add box. */
function ListField({ label, nested, placeholder, emptyText, items, onChange }: ListFieldProps) {
  const { t } = useTranslation(['settings'])
  const [draft, setDraft] = useState('')
  const [duplicate, setDuplicate] = useState(false)

  const add = () => {
    const value = draft.trim()
    if (!value) return
    if (items.includes(value)) {
      setDuplicate(true)
      return
    }
    onChange([...items, value])
    setDraft('')
  }

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.nativeEvent.isComposing) {
      e.preventDefault()
      add()
    }
  }

  return (
    <div className={`${sec.list} ${nested ? sec.listNested : ''}`}>
      <div className={sec.row}>
        <span className={nested ? sec.listLabel : sec.rowLabel}>{label}</span>
        {items.length === 0 && emptyText && <span className={sec.chipEmpty}>{emptyText}</span>}
      </div>
      <div className={sec.chips}>
        {items.map(item => (
          <span key={item} className={sec.chip} title={item}>
            <span className={sec.chipValue}>{item}</span>
            <button
              type="button"
              className={sec.chipRemove}
              aria-label={t('settings:security.list.remove', { item })}
              onClick={() => onChange(items.filter(i => i !== item))}
            >
              <X size={12} />
            </button>
          </span>
        ))}
      </div>
      <div className={sec.addRow}>
        <input
          type="text"
          value={draft}
          placeholder={placeholder}
          aria-label={label}
          onChange={e => {
            setDraft(e.target.value)
            setDuplicate(false)
          }}
          onKeyDown={onKeyDown}
        />
        <Button
          variant="secondary"
          size="sm"
          icon={<Plus size={14} />}
          onClick={add}
          disabled={!draft.trim()}
          aria-label={t('settings:security.list.add')}
        />
      </div>
      {duplicate && <span className={styles.formError}>{t('settings:security.list.duplicate')}</span>}
    </div>
  )
}

// ── Security check ─────────────────────────────────────────────────

const CHECK_ICONS = {
  ok: CheckCircle2,
  info: Info,
  warn: AlertTriangle,
  fail: XCircle,
} as const

function SecurityCheckSection({ send, onMessage }: { send: Send; onMessage: OnMessage }) {
  const { t } = useTranslation(['settings'])
  // Runs the check when the tab opens and again after any security change.
  useResource(RESOURCES.securityChecks)
  const checks = useAppSelector(state => state.security.checks)
  const hasLoaded = useAppSelector(state => state.security.hasLoadedChecks)
  // 'run' while "Run again" is in flight, else the fix being applied.
  const [busy, setBusy] = useState<string | null>(null)

  useEffect(() => onMessage('security_check', () => setBusy(null)), [onMessage])

  const runAgain = () => {
    setBusy('run')
    send('security_check_run')
  }

  const fix = (check: SecurityCheck) => {
    if (!check.fix_id) return
    setBusy(check.fix_id)
    send('security_check_fix', { id: check.fix_id })
  }

  return (
    <div className={styles.subsection}>
      <div className={sec.titleRow}>
        <h4 className={styles.subsectionTitle}>{t('settings:security.check.title')}</h4>
        <Button
          variant="ghost"
          size="sm"
          onClick={runAgain}
          disabled={busy !== null}
          icon={<RefreshCw size={14} className={busy === 'run' ? styles.spinning : undefined} />}
        >
          {busy === 'run' ? t('settings:security.check.running') : t('settings:security.check.runAgain')}
        </Button>
      </div>

      {!hasLoaded ? (
        <div className={styles.loadingState}>
          <Loader2 size={20} className={styles.spinning} />
          <span>{t('settings:security.check.running')}</span>
        </div>
      ) : checks.length === 0 ? (
        <div className={styles.emptyState}>
          <p>{t('settings:security.check.empty')}</p>
        </div>
      ) : (
        <div className={sec.panel}>
          {checks.map(check => {
            const status = check.status in CHECK_ICONS ? check.status : 'info'
            const Icon = CHECK_ICONS[status]
            // Passing checks speak for themselves; only problems say more.
            const showDetail = (status === 'warn' || status === 'fail') && check.detail
            return (
              <div key={check.id} className={`${sec.item} ${sec.checkItem}`}>
                <Icon
                  size={16}
                  className={`${sec.checkIcon} ${sec[`status_${status}`]}`}
                  aria-label={t(`settings:security.check.status.${status}`)}
                />
                <div className={sec.checkText}>
                  <span className={sec.rowLabel}>{check.title}</span>
                  {showDetail && <span className={sec.rowDesc}>{check.detail}</span>}
                </div>
                {check.fix_id && (
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={() => fix(check)}
                    disabled={busy !== null}
                    icon={busy === check.fix_id
                      ? <Loader2 size={14} className={styles.spinning} />
                      : <Wrench size={14} />}
                  >
                    {t('settings:security.check.fix')}
                  </Button>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ── Audit log ──────────────────────────────────────────────────────

function AuditLogSection({ send, onMessage }: { send: Send; onMessage: OnMessage }) {
  const { t } = useTranslation(['settings'])
  useResource(RESOURCES.securityAudit)
  const audit = useAppSelector(state => state.security.audit)
  const [refreshing, setRefreshing] = useState(false)

  useEffect(() => onMessage('security_audit', () => setRefreshing(false)), [onMessage])

  const refresh = () => {
    setRefreshing(true)
    send('security_audit_list')
  }

  const entries: AuditEntry[] = audit ? audit.entries.slice(0, AUDIT_SHOWN) : []

  return (
    <div className={styles.subsection}>
      <div className={sec.titleRow}>
        <h4 className={styles.subsectionTitle}>{t('settings:security.audit.title')}</h4>
        {audit && audit.count > 0 && (
          audit.intact ? (
            <Badge variant="success">{t('settings:security.audit.intact', { count: audit.count })}</Badge>
          ) : (
            <Badge variant="error">
              {t('settings:security.audit.broken', { line: formatNumber(audit.brokenAt ?? 0) })}
            </Badge>
          )
        )}
        <span className={sec.titleSpacer} />
        <Button
          variant="ghost"
          size="sm"
          onClick={refresh}
          disabled={refreshing}
          aria-label={t('settings:security.audit.refresh')}
          icon={<RefreshCw size={14} className={refreshing ? styles.spinning : undefined} />}
        />
      </div>

      {!audit ? (
        <div className={styles.loadingState}>
          <Loader2 size={20} className={styles.spinning} />
          <span>{t('settings:security.audit.loading')}</span>
        </div>
      ) : entries.length === 0 ? (
        <div className={styles.emptyState}>
          <p>{t('settings:security.audit.empty')}</p>
        </div>
      ) : (
        <>
          <div className={sec.auditList}>
            {entries.map((entry, index) => {
              const fields = Object.entries(entry).filter(([key]) => !AUDIT_HIDDEN_FIELDS.has(key))
              return (
                <div key={`${entry.ts}-${index}`} className={sec.auditEntry}>
                  <span className={sec.auditTime}>
                    {formatDateTime(new Date(entry.ts * 1000), {
                      month: 'short',
                      day: 'numeric',
                      hour: '2-digit',
                      minute: '2-digit',
                      second: '2-digit',
                      hourCycle: 'h23',
                    })}
                  </span>
                  <span className={sec.auditEvent}>{auditEventLabel(entry.event)}</span>
                  {fields.length > 0 && (
                    <span className={sec.auditFields}>
                      {fields.map(([key, value]) =>
                        key === 'changed' && Array.isArray(value) ? (
                          <span key={key} className={sec.auditChanged}>{value.map(v => settingLabel(String(v))).join(', ')}</span>
                        ) : (
                          <span key={key}>
                            <span className={sec.auditFieldKey}>{key}:</span> {auditValue(value)}
                          </span>
                        ),
                      )}
                    </span>
                  )}
                </div>
              )
            })}
          </div>
          {audit.entries.length > entries.length && (
            <span className={sec.auditCount}>
              {t('settings:security.audit.showing', {
                shown: formatNumber(entries.length),
                total: formatNumber(audit.count),
              })}
            </span>
          )}
        </>
      )}
    </div>
  )
}
