import React, { useState, useEffect, useCallback } from 'react'
import * as LucideIcons from 'lucide-react'
import {
  Globe,
  Package,
  AlertTriangle,
  Loader2,
  Plus,
  RotateCcw,
  X,
  Power,
  Wrench,
  HelpCircle,
  ChevronRight,
  ChevronLeft,
} from 'lucide-react'
import {
  Gmail,
  Slack,
  Notion,
  GitHubDark,
  GitHubLight,
  Discord,
  LinkedIn,
  Stripe,
  Twitter,
  Telegram,
  WhatsApp,
  GoogleCalendar,
  GoogleDrive,
  YouTube,
  MicrosoftOutlook,
} from '@ridemountainpig/svgl-react'
import { Button, Badge, ConfirmModal } from '../../components/ui'
import { useToast } from '../../contexts/ToastContext'
import { useConfirmModal } from '../../hooks'
import { useTheme } from '../../contexts/ThemeContext'
import styles from './SettingsPage.module.css'
import { useSettingsWebSocket } from './useSettingsWebSocket'
import { useAppDispatch, useAppSelector } from '../../store/hooks'
import {
  setDisconnected,
  type Integration,
  type ConfigField,
} from '../../store/slices/integrationsSettingsSlice'
import type {
  ManagedAccount,
  StagedAccountEdits,
  AccountChanges,
  IntegrationAccountsAddResult,
  IntegrationApplyAccountChangesResult,
} from './types'

// --- Multi-account staged-edit helpers -------------------

const emptyStaged = (): StagedAccountEdits => ({
  disconnect: [],
  primary: null,
  aliases: {},
  listen: {},
})

const stagedIsEmpty = (s: StagedAccountEdits): boolean =>
  s.disconnect.length === 0 &&
  s.primary === null &&
  Object.keys(s.aliases).length === 0 &&
  Object.keys(s.listen).length === 0
import {
  selectIntegrations,
  selectIntegrationsTotal,
  selectIntegrationsConnected,
  selectIntegrationsHasLoaded,
} from '../../store/selectors/integrationsSettings'

// Full-color SVGL brand components (@ridemountainpig/svgl-react) keyed by
// integration id. GitHub is monochrome and handled separately (theme-matched
// light/dark variant), so it is not in this map.
type SvglIcon = (props: React.SVGProps<SVGSVGElement>) => React.JSX.Element
const SVGL_BY_ID: Record<string, SvglIcon> = {
  gmail: Gmail,
  slack: Slack,
  notion: Notion,
  discord: Discord,
  linkedin: LinkedIn,
  stripe: Stripe,
  twitter: Twitter,
  telegram_bot: Telegram,
  telegram_user: Telegram,
  whatsapp_web: WhatsApp,
  whatsapp_business: WhatsApp,
  google_calendar: GoogleCalendar,
  google_drive: GoogleDrive,
  google_youtube: YouTube,
  outlook: MicrosoftOutlook,
}

// Integration icon component. Lookup order:
//   1. SVGL brand component keyed by integration id (the standard for every
//      brand SVGL ships; GitHub resolves to a theme-matched variant).
//   2. Hand-crafted brand SVG for the brands SVGL doesn't carry
//      (jira, hubspot, line, lark, google_docs), keyed by the backend ``icon``.
//   3. Lucide icon by the backend ``icon`` name (e.g. Outlook's "Inbox").
//   4. Generic globe fallback.
const IntegrationIcon = ({ id, icon, size = 20 }: { id: string; icon?: string; size?: number }) => {
  const { theme } = useTheme()

  // 1. SVGL. GitHub's mark is monochrome: pick the variant that shows against
  //    the active theme (GitHubDark = white mark for dark UI, GitHubLight = dark
  //    mark for light UI).
  const svgl: SvglIcon | undefined =
    id === 'github'
      ? (theme === 'dark' ? GitHubDark : GitHubLight)
      : SVGL_BY_ID[id]
  if (svgl) {
    const Logo = svgl
    return (
      <span className={styles.integrationIconSvg}>
        <Logo width={size} height={size} />
      </span>
    )
  }

  // 2. Hand-crafted brand SVGs — only for brands SVGL doesn't have.
  const icons: Record<string, React.ReactNode> = {
    google_docs: (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <path d="M5 2h9l5 5v13a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z" fill="#4285F4"/>
        <path d="M14 2v5h5l-5-5z" fill="#A1C2FA"/>
        <rect x="6" y="11" width="12" height="1.2" rx="0.6" fill="#fff"/>
        <rect x="6" y="14" width="12" height="1.2" rx="0.6" fill="#fff"/>
        <rect x="6" y="17" width="9" height="1.2" rx="0.6" fill="#fff"/>
      </svg>
    ),
    line: (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="#06C755">
        <path d="M19.365 9.863c.349 0 .63.285.63.631 0 .345-.281.63-.63.63H17.61v1.125h1.755c.349 0 .63.283.63.63 0 .344-.281.629-.63.629h-2.386c-.345 0-.627-.285-.627-.629V8.108c0-.345.282-.63.63-.63h2.386c.346 0 .627.285.627.63 0 .349-.281.63-.63.63H17.61v1.125h1.755zm-3.855 3.016c0 .27-.174.51-.432.596-.064.021-.133.031-.199.031-.211 0-.391-.09-.51-.25l-2.443-3.317v2.94c0 .344-.279.629-.631.629-.346 0-.626-.285-.626-.629V8.108c0-.27.173-.51.43-.595.06-.023.136-.033.194-.033.195 0 .375.104.495.254l2.462 3.33V8.108c0-.345.282-.63.63-.63.345 0 .63.285.63.63v4.771zm-5.741 0c0 .344-.282.629-.631.629-.345 0-.627-.285-.627-.629V8.108c0-.345.282-.63.63-.63.346 0 .628.285.628.63v4.771zm-2.466.629H4.917c-.345 0-.63-.285-.63-.629V8.108c0-.345.285-.63.63-.63.348 0 .63.285.63.63v4.141h1.756c.348 0 .629.283.629.63 0 .344-.282.629-.629.629M24 10.314C24 4.943 18.615.572 12 .572S0 4.943 0 10.314c0 4.811 4.27 8.842 10.035 9.608.391.082.923.258 1.058.59.12.301.079.766.038 1.08l-.164 1.02c-.045.301-.24 1.186 1.049.645 1.291-.539 6.916-4.078 9.436-6.975C23.176 14.393 24 12.458 24 10.314"/>
      </svg>
    ),
    lark: (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <defs>
          <linearGradient id="larkGrad" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#00D6B9"/>
            <stop offset="50%" stopColor="#00B8E0"/>
            <stop offset="100%" stopColor="#3370FF"/>
          </linearGradient>
        </defs>
        <rect x="2" y="2" width="20" height="20" rx="4.5" fill="url(#larkGrad)"/>
        <path d="M7.5 9.2c0-.66.54-1.2 1.2-1.2h6.4c.66 0 1.2.54 1.2 1.2v2.4c0 1.66-1.34 3-3 3H10.6l-2.6 2.2c-.3.25-.5.05-.5-.3v-7.3z" fill="#fff"/>
      </svg>
    ),
    jira: (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="#0052CC">
        <path d="M11.571 11.513H0a5.218 5.218 0 0 0 5.232 5.215h2.13v2.057A5.215 5.215 0 0 0 12.575 24V12.518a1.005 1.005 0 0 0-1.005-1.005z"/>
        <path d="M6.348 6.349H-5.224a5.218 5.218 0 0 0 5.232 5.215h2.13v2.057a5.215 5.215 0 0 0 5.215 5.215V7.354a1.005 1.005 0 0 0-1.005-1.005z" transform="translate(5.224)"/>
        <path d="M11.571 0H0a5.218 5.218 0 0 0 5.232 5.215h2.13v2.057A5.215 5.215 0 0 0 12.575 12.487V1.005A1.005 1.005 0 0 0 11.571 0z" transform="translate(.348 1.164)"/>
      </svg>
    ),
    hubspot: (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        {/* Connector lines end on the ring stroke centerline (r=5.5 from ring center),
            so the ring draws OVER the line end and the hole stays clean. */}
        <line x1="4" y1="4" x2="11.1" y2="11.1" stroke="#FF7A59" strokeWidth="2.5" strokeLinecap="round"/>
        <line x1="17.5" y1="3" x2="17.5" y2="10.1" stroke="#FF7A59" strokeWidth="2.5" strokeLinecap="round"/>
        <line x1="8" y1="21.5" x2="11" y2="18.7" stroke="#FF7A59" strokeWidth="2.5" strokeLinecap="round"/>
        {/* Main ring (donut) — fill="none" + stroke creates the visible hole */}
        <circle cx="15" cy="15" r="5.5" stroke="#FF7A59" strokeWidth="2.5" fill="none"/>
        {/* Satellite dots */}
        <circle cx="4" cy="4" r="2.5" fill="#FF7A59"/>
        <circle cx="17.5" cy="3" r="2.2" fill="#FF7A59"/>
        <circle cx="8" cy="21.5" r="2.2" fill="#FF7A59"/>
      </svg>
    ),
  }
  if (icon && icons[icon]) {
    return <span className={styles.integrationIconSvg}>{icons[icon]}</span>
  }
  if (icons[id]) {
    return <span className={styles.integrationIconSvg}>{icons[id]}</span>
  }

  // 3. Lucide fallback for non-brand icons (e.g. Outlook's "Inbox").
  if (icon) {
    const lucideMap = LucideIcons as unknown as Record<string, React.ComponentType<{ size?: number }>>
    const LucideIcon = lucideMap[icon]
    if (LucideIcon) {
      return <span className={styles.integrationIconSvg}><LucideIcon size={size} /></span>
    }
  }

  // 4. Generic fallback.
  return <span className={styles.integrationIconSvg}><Globe size={size} /></span>
}

// Schema-driven settings fields for the integration-settings page of the
// Manage modal. Renders one control per ``ConfigField`` and flushes values
// back to the parent via ``onChange``; the single Save lives in the modal
// footer, so this component has no save button of its own. Checkboxes render
// as the same label+description toggle row used across the Settings tabs;
// every other type is a labeled input.
const ConfigFields = ({
  integrationId,
  schema,
  values,
  onChange,
}: {
  integrationId: string
  schema: ConfigField[]
  values: Record<string, any>
  onChange: (values: Record<string, any>) => void
}) => {
  const setField = (key: string, value: any) => {
    onChange({ ...values, [key]: value })
  }

  const renderInput = (field: ConfigField, id: string) => {
    const cur = values[field.key]
    switch (field.type) {
      case 'textarea':
        return (
          <textarea
            id={id}
            className={styles.input}
            placeholder={field.placeholder}
            value={cur ?? ''}
            onChange={e => setField(field.key, e.target.value)}
            rows={4}
          />
        )

      case 'list': {
        // Comma-separated <input>. The backend coerces "a, b, c" → ["a","b","c"]
        // on save (see service.py:_coerce). Keep the raw string in state while
        // the user types — converting to an array on every keystroke would
        // strip trailing commas and stop the user typing a second item.
        const display = Array.isArray(cur) ? cur.join(', ') : (cur ?? '')
        return (
          <input
            id={id}
            type="text"
            className={styles.input}
            placeholder={field.placeholder}
            value={display}
            onChange={e => setField(field.key, e.target.value)}
          />
        )
      }

      case 'select':
        return (
          <select
            id={id}
            className={styles.input}
            value={cur ?? ''}
            onChange={e => setField(field.key, e.target.value)}
          >
            {(field.options ?? []).map(opt => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        )

      case 'number':
        return (
          <input
            id={id}
            type="number"
            className={styles.input}
            placeholder={field.placeholder}
            value={cur ?? ''}
            onChange={e => setField(field.key, e.target.value)}
          />
        )

      case 'text':
      default:
        return (
          <input
            id={id}
            type="text"
            className={styles.input}
            placeholder={field.placeholder}
            value={cur ?? ''}
            onChange={e => setField(field.key, e.target.value)}
          />
        )
    }
  }

  return (
    <div className={styles.mSettingsList}>
      {schema.map(field => {
        const id = `cfg-${integrationId}-${field.key}`
        if (field.type === 'checkbox') {
          return (
            <label key={field.key} htmlFor={id} className={styles.toggleGroup}>
              <div className={styles.toggleInfo}>
                <span className={styles.toggleLabel}>{field.label}</span>
                {field.help && <span className={styles.toggleDesc}>{field.help}</span>}
              </div>
              <input
                id={id}
                type="checkbox"
                className={styles.toggle}
                checked={Boolean(values[field.key])}
                onChange={e => setField(field.key, e.target.checked)}
              />
            </label>
          )
        }
        return (
          <div key={field.key} className={styles.formGroup}>
            <label htmlFor={id}>{field.label}</label>
            {renderInput(field, id)}
            {field.help && <p className={styles.hint}>{field.help}</p>}
          </div>
        )
      })}
    </div>
  )
}

// Account list + per-account detail are rendered inline in the Manage modal
// (see the drill-down pages in IntegrationsSettings' render). Staging helpers
// (stageAlias / stagePrimary / stageListen / stageDisconnect) live on the
// parent and are committed as one ``integration_apply_account_changes``.

export function IntegrationsSettings({ hideHeader = false }: { hideHeader?: boolean } = {}) {
  const { send, onMessage, isConnected } = useSettingsWebSocket()
  const { showToast } = useToast()
  const dispatch = useAppDispatch()

  // Slice-backed: list state cached across remounts.
  const integrations = useAppSelector(selectIntegrations)
  const totalIntegrations = useAppSelector(selectIntegrationsTotal)
  const connectedCount = useAppSelector(selectIntegrationsConnected)
  const hasLoaded = useAppSelector(selectIntegrationsHasLoaded)
  const isLoading = !hasLoaded

  // Search
  const [searchQuery, setSearchQuery] = useState('')

  // Reload state
  const [isReloading, setIsReloading] = useState(false)
  const isReloadingRef = React.useRef(false)

  // Connect modal state
  const [showConnectModal, setShowConnectModal] = useState(false)
  const [selectedIntegration, setSelectedIntegration] = useState<Integration | null>(null)
  const [credentials, setCredentials] = useState<Record<string, string>>({})
  const [connectError, setConnectError] = useState('')
  const [isConnecting, setIsConnecting] = useState(false)
  const [showConnectHelp, setShowConnectHelp] = useState(false)
  // Mirrors ``selectedIntegration`` for the WebSocket handlers below, whose
  // useEffect doesn't re-subscribe when state changes (so a direct read would
  // be stale). Used to auto-open Manage after a successful connect.
  const selectedIntegrationRef = React.useRef<Integration | null>(null)
  useEffect(() => {
    selectedIntegrationRef.current = selectedIntegration
  }, [selectedIntegration])

  // Manage modal state
  const [showManageModal, setShowManageModal] = useState(false)
  const [managingIntegration, setManagingIntegration] = useState<Integration | null>(null)
  // Mirrors ``managingIntegration`` for the WebSocket handlers (same reason
  // as ``selectedIntegrationRef`` above — the subscription effect doesn't
  // re-run on state changes, so direct reads would be stale).
  const managingIntegrationRef = React.useRef<Integration | null>(null)
  useEffect(() => {
    managingIntegrationRef.current = managingIntegration
  }, [managingIntegration])
  // True only between an explicit user-triggered ``integration_info`` request
  // and its response. ``integration_info`` results NEVER open the Manage
  // modal unless this flag is set — broadcasts must not open modals.
  const manageRequestedRef = React.useRef(false)

  // --- Multi-account state -------------------------------
  // Real account list for the currently-managed integration, from the
  // ``accounts`` field of the ``integration_info`` payload (and refreshed by
  // accounts-mutation result broadcasts). null = integration without
  // multi-account support → legacy accounts UI.
  const [managedAccounts, setManagedAccounts] = useState<ManagedAccount[] | null>(null)
  // Staged (uncommitted) edits, keyed by integration id. Discarded on every
  // modal close path; pruned when identities vanish from refreshed lists.
  const [stagedEdits, setStagedEdits] = useState<Record<string, StagedAccountEdits>>({})
  const [accountsSaving, setAccountsSaving] = useState(false)
  const [accountsError, setAccountsError] = useState('')
  // Integration id with an "Add account" OAuth flow in flight. Deliberately
  // NOT cleared on modal close (the OAuth flow keeps running server-side and
  // can take minutes); cleared only by the matching result broadcast.
  const [addingAccountFor, setAddingAccountFor] = useState<string | null>(null)
  // Outstanding request ids WE sent (requestId → integration id). Results are
  // broadcast to every client; only ids in these maps may trigger UI
  // reactions (toast / spinner clear / staged clear). Foreign results update
  // data silently. No wall-clock timers anywhere: entries live until their
  // result arrives.
  const pendingAddRef = React.useRef<Map<string, string>>(new Map())
  const pendingApplyRef = React.useRef<Map<string, string>>(new Map())

  // Prune staged entries whose identities no longer exist in a refreshed
  // account list. A staged primary whose account vanished resets to null,
  // i.e. falls back to the real primary.
  const pruneStagedFor = useCallback((integrationId: string, accounts: ManagedAccount[]) => {
    setStagedEdits(prev => {
      const cur = prev[integrationId]
      if (!cur) return prev
      const ids = new Set(accounts.map(a => a.identity))
      const next: StagedAccountEdits = {
        disconnect: cur.disconnect.filter(identity => ids.has(identity)),
        primary: cur.primary !== null && ids.has(cur.primary) ? cur.primary : null,
        aliases: Object.fromEntries(
          Object.entries(cur.aliases).filter(([identity]) => ids.has(identity)),
        ),
        listen: Object.fromEntries(
          Object.entries(cur.listen).filter(([identity]) => ids.has(identity)),
        ),
      }
      if (stagedIsEmpty(next)) {
        const { [integrationId]: _gone, ...rest } = prev
        return rest
      }
      return { ...prev, [integrationId]: next }
    })
  }, [])

  // Apply a fresh account list from any source (our result, foreign
  // broadcast). Updates the open modal's data if it shows this integration;
  // never opens anything.
  const refreshManagedAccounts = useCallback((integrationId: string, accounts: ManagedAccount[]) => {
    const current = managingIntegrationRef.current
    if (current && current.id === integrationId) {
      setManagedAccounts(accounts)
    }
    pruneStagedFor(integrationId, accounts)
  }, [pruneStagedFor])

  // Single close path for the Manage modal — every way of closing it (X,
  // overlay click, disconnect flows) goes through here so staged edits are
  // always discarded.
  const closeManageModal = useCallback(() => {
    setShowManageModal(false)
    setManagingIntegration(null)
    setManagedAccounts(null)
    setAccountsSaving(false)
    setAccountsError('')
    setStagedEdits({})
    setManagePage('list')
    setSelectedAccountIdentity(null)
    setConfigValues({})
    setConfigBaseline({})
  }, [])

  // Slow operation overlay — shown during long disconnects (WhatsApp Web's
  // bridge teardown can take 20–30 seconds; without this the user has no
  // feedback until the backend confirms). Cleared by integration_disconnect_result.
  const [pendingOp, setPendingOp] = useState<{
    kind: 'disconnect'
    id: string
    label: string
  } | null>(null)

  // Per-integration runtime config — populated from integration_get_config
  // when the Manage modal opens for an integration with has_config === true.
  // ``configValues`` is keyed by config_field.key. The form is fully driven
  // by ``managingIntegration.config_fields`` (the schema from the backend).
  const [configValues, setConfigValues] = useState<Record<string, any>>({})
  // Last saved/loaded config values — the baseline the current form is diffed
  // against to decide whether the footer shows "unsaved changes".
  const [configBaseline, setConfigBaseline] = useState<Record<string, any>>({})
  const [configLoading, setConfigLoading] = useState(false)
  const [configSaving, setConfigSaving] = useState(false)

  // Manage modal has two pages: the main page (accounts LIST + integration
  // settings) and one account's DETAIL. Reset to 'list' on every open/close.
  const [managePage, setManagePage] = useState<'list' | 'account'>('list')
  const [selectedAccountIdentity, setSelectedAccountIdentity] = useState<string | null>(null)

  // WhatsApp QR code state — states mirror the backend LinkFlow verbatim:
  // qr_ready → scanned → promoting → connected, plus timeout/error.
  const [whatsappQrCode, setWhatsappQrCode] = useState<string | null>(null)
  const [whatsappSessionId, setWhatsappSessionId] = useState<string | null>(null)
  const [whatsappStatus, setWhatsappStatus] = useState<'idle' | 'loading' | 'qr_ready' | 'scanned' | 'promoting' | 'connected' | 'timeout' | 'error'>('idle')
  const [whatsappError, setWhatsappError] = useState<string | null>(null)
  // Seconds left in the current QR window (the backend refreshes the code
  // in cycles); updated on every poll result.
  const [whatsappExpiresIn, setWhatsappExpiresIn] = useState<number | null>(null)
  const whatsappPollRef = React.useRef<ReturnType<typeof setInterval> | null>(null)

  // Confirm modal
  const { modalProps: confirmModalProps, confirm } = useConfirmModal()

  // User-gesture close path (X button, overlay click): staged edits are
  // real unsent work — closing silently threw them away in the live bug
  // (typed alias lost with no warning). Ask first when dirty. Programmatic
  // closes (disconnect flows, disconnect_result) still use closeManageModal
  // directly: their outcome supersedes any staged edits.
  const requestCloseManage = () => {
    const staged = managingIntegration
      ? stagedEdits[managingIntegration.id]
      : undefined
    const accountsDirty = staged !== undefined && !stagedIsEmpty(staged)
    const settingsDirty =
      JSON.stringify(configValues) !== JSON.stringify(configBaseline)
    if (managingIntegration && (accountsDirty || settingsDirty)) {
      confirm({
        title: 'Discard unsaved changes?',
        message: `Your changes to ${managingIntegration.name} haven't been saved yet.`,
        confirmText: 'Discard',
        cancelText: 'Keep editing',
        variant: 'danger',
      }, closeManageModal)
      return
    }
    closeManageModal()
  }

  // Subscribe to side-effect messages (toasts, modal close). The integrations
  // list itself is updated by the slice via the registry.
  useEffect(() => {
    if (!isConnected) return

    const cleanups = [
      // The slice handles populating the list. Here we only handle the
      // reload-success toast and error reporting.
      onMessage('integration_list', (data: unknown) => {
        const d = data as { success: boolean; error?: string }
        const wasReloading = isReloadingRef.current
        setIsReloading(false)
        isReloadingRef.current = false
        if (d.success) {
          if (wasReloading) {
            showToast('success', 'Integrations reloaded')
          }
        } else if (d.error) {
          showToast('error', d.error)
        }
      }),
      onMessage('integration_connect_result', (data: unknown) => {
        const d = data as { success: boolean; message?: string; error?: string; id?: string }
        setIsConnecting(false)
        if (d.success) {
          showToast('success', d.message || 'Connected successfully')
          setShowConnectModal(false)
          setCredentials({})
          setConnectError('')
          const just = selectedIntegrationRef.current
          if (just && just.has_config && (just.config_fields?.length ?? 0) > 0) {
            // Deliberate modal open: follow-up to the user's own connect.
            manageRequestedRef.current = true
            send('integration_info', { id: just.id })
          }
        } else {
          setConnectError(d.error || d.message || 'Connection failed')
        }
      }),
      onMessage('integration_disconnect_result', (data: unknown) => {
        const d = data as { success: boolean; message?: string; error?: string; id?: string }
        // Clear the slow-disconnect overlay if this result is for the
        // operation it was tracking.
        setPendingOp(prev => (prev && d.id && prev.id === d.id) ? null : prev)
        if (d.success) {
          showToast('success', d.message || 'Disconnected successfully')
          closeManageModal()
        } else {
          showToast('error', d.error || 'Failed to disconnect')
        }
      }),
      onMessage('integration_info', (data: unknown) => {
        const d = data as {
          success: boolean
          integration?: Integration
          // multi-account integrations: real account list (identity,
          // alias, isPrimary, listen). Absent for legacy integrations.
          accounts?: ManagedAccount[]
          error?: string
        }
        if (d.success && d.integration) {
          if (manageRequestedRef.current) {
            // Response to OUR explicit request (Manage click / post-connect
            // follow-up) — the only path that may OPEN the modal.
            manageRequestedRef.current = false
            setManagingIntegration(d.integration)
            setShowManageModal(true)
            // Always open on the accounts list (never a stale detail page).
            setManagePage('list')
            setSelectedAccountIdentity(null)
            setManagedAccounts(d.accounts ?? null)
            if (d.accounts) pruneStagedFor(d.integration.id, d.accounts)
            // If this integration has runtime config, kick off a fetch so the
            // Settings page is populated by the time the user opens it.
            if (d.integration.has_config) {
              setConfigLoading(true)
              setConfigValues({})
              setConfigBaseline({})
              send('integration_get_config', { id: d.integration.id })
            }
          } else if (managingIntegrationRef.current?.id === d.integration.id) {
            // Unsolicited info for the integration already on screen —
            // refresh the data silently. Never opens the modal. A payload
            // WITHOUT ``accounts`` (transient v2 lookup failure server-side)
            // must not null out the live account list: that would blank the
            // Manage modal mid-edit and hide the user's staged changes.
            // Keep the last good list instead.
            setManagingIntegration(d.integration)
            if (d.accounts) {
              setManagedAccounts(d.accounts)
              pruneStagedFor(d.integration.id, d.accounts)
            }
          }
        } else if (manageRequestedRef.current) {
          manageRequestedRef.current = false
          showToast('error', d.error || 'Failed to get integration info')
        }
      }),
      // Result broadcast for "Add account" (real OAuth; can take minutes).
      // Broadcast to EVERY client — only requestIds we sent may drive UI
      // reactions; foreign results refresh data silently.
      onMessage('integration_accounts_add_result', (data: unknown) => {
        const d = data as IntegrationAccountsAddResult
        const mine = Boolean(d.requestId) && pendingAddRef.current.has(d.requestId)
        // Fresh account list benefits everyone, ours or not — but ONLY from
        // success payloads. Failure payloads carry a best-effort list that
        // may be a fabricated empty array; treating it as authoritative
        // would blank the modal and prune (= silently discard) every staged
        // edit, including an alias mid-typing.
        if (d.ok && d.accounts) refreshManagedAccounts(d.id, d.accounts)
        if (!mine) return
        pendingAddRef.current.delete(d.requestId)
        setAddingAccountFor(prev => (prev === d.id ? null : prev))
        if (d.ok) {
          showToast('success', d.message || 'Account added')
        } else {
          showToast('error', d.message || 'Failed to add account')
        }
      }),
      // Result broadcast for the batched "Save changes" request.
      onMessage('integration_apply_account_changes_result', (data: unknown) => {
        const d = data as IntegrationApplyAccountChangesResult
        const mine = Boolean(d.requestId) && pendingApplyRef.current.has(d.requestId)
        if (d.ok && d.accounts) {
          if (mine) {
            // OUR save succeeded — clear this integration's staged edits
            // BEFORE rendering the returned list, so no stale overrides
            // shadow the authoritative state.
            setStagedEdits(prev => {
              const { [d.id]: _gone, ...rest } = prev
              return rest
            })
          }
          refreshManagedAccounts(d.id, d.accounts)
        }
        if (!mine) return
        pendingApplyRef.current.delete(d.requestId)
        setAccountsSaving(false)
        if (d.ok) {
          setAccountsError('')
          showToast('success', 'Account changes saved')
        } else {
          // Failure keeps the staged edits (nothing cleared above) so the
          // user can retry; surface the error inline and as a toast.
          const msg = d.error || 'Failed to apply account changes'
          setAccountsError(msg)
          showToast('error', msg)
        }
      }),
      // Per-integration runtime config (schema-driven; works for every
      // integration that declares config_class on its handler).
      onMessage('integration_config', (data: unknown) => {
        const d = data as {
          id: string; success: boolean
          schema?: ConfigField[]; values?: Record<string, any>
          error?: string
        }
        setConfigLoading(false)
        if (d.success) {
          const loaded = d.values || {}
          setConfigValues(loaded)
          setConfigBaseline(loaded)
        } else if (d.error) {
          showToast('error', d.error)
        }
      }),
      onMessage('integration_config_updated', (data: unknown) => {
        const d = data as {
          id: string; success: boolean
          message?: string; values?: Record<string, any>; error?: string
        }
        setConfigSaving(false)
        if (d.success) {
          showToast('success', d.message || 'Settings saved')
          if (d.values) {
            setConfigValues(d.values)
            setConfigBaseline(d.values)
          }
        } else {
          showToast('error', d.error || d.message || 'Failed to save settings')
        }
      }),
      // WhatsApp QR code handlers
      onMessage('whatsapp_qr_result', (data: unknown) => {
        const d = data as { success: boolean; session_id?: string; qr_code?: string; status?: string; message?: string; expires_in?: number }
        if (d.success && d.qr_code) {
          setWhatsappQrCode(d.qr_code)
          setWhatsappSessionId(d.session_id || null)
          setWhatsappStatus('qr_ready')
          setWhatsappError(null)
          setWhatsappExpiresIn(typeof d.expires_in === 'number' ? d.expires_in : null)
        } else {
          setWhatsappStatus('error')
          setWhatsappError(d.message || 'Failed to get QR code')
        }
      }),
      onMessage('whatsapp_status_result', (data: unknown) => {
        const d = data as { success: boolean; status?: string; connected?: boolean; message?: string; qr_code?: string; expires_in?: number }
        const stopPolling = () => {
          if (whatsappPollRef.current) {
            clearInterval(whatsappPollRef.current)
            whatsappPollRef.current = null
          }
        }
        if (d.connected) {
          setWhatsappStatus('connected')
          setShowConnectModal(false)
          showToast('success', d.message || 'WhatsApp connected successfully')
          stopPolling()
          setWhatsappQrCode(null)
          setWhatsappSessionId(null)
          setWhatsappStatus('idle')
          setWhatsappExpiresIn(null)
          const just = selectedIntegrationRef.current
          if (just && just.has_config && (just.config_fields?.length ?? 0) > 0) {
            // Deliberate modal open: follow-up to the user's own connect.
            manageRequestedRef.current = true
            send('integration_info', { id: just.id })
          }
        } else if (d.status === 'qr_ready') {
          // The backend recycles the QR in cycles — always show the newest
          // code and window.
          if (d.qr_code) setWhatsappQrCode(d.qr_code)
          if (typeof d.expires_in === 'number') setWhatsappExpiresIn(d.expires_in)
          setWhatsappStatus('qr_ready')
        } else if (d.status === 'scanned' || d.status === 'promoting') {
          // Keep polling — completion arrives as `connected`.
          setWhatsappStatus(d.status)
        } else if (d.status === 'timeout' || d.status === 'cancelled') {
          setWhatsappStatus('timeout')
          setWhatsappError(d.message || 'QR code expired — try again.')
          stopPolling()
        } else if (d.status === 'error' || d.status === 'disconnected') {
          setWhatsappStatus('error')
          setWhatsappError(d.message || 'Session failed')
          stopPolling()
        }
      }),
      onMessage('whatsapp_cancel_result', (_data: unknown) => {
        setWhatsappQrCode(null)
        setWhatsappSessionId(null)
        setWhatsappStatus('idle')
        setWhatsappError(null)
      }),
    ]

    // Fetch list only on first mount (cached across re-mounts thereafter).
    if (!hasLoaded) {
      send('integration_list')
    }

    return () => cleanups.forEach(c => c())
  }, [isConnected, send, onMessage, hasLoaded, showToast, closeManageModal, pruneStagedFor, refreshManagedAccounts])

  // Poll while a link flow is live (QR pending, scanned, or promoting).
  useEffect(() => {
    const live = whatsappStatus === 'qr_ready' || whatsappStatus === 'scanned' || whatsappStatus === 'promoting'
    if (live && whatsappSessionId) {
      startWhatsAppPolling(whatsappSessionId)
    }
    return () => {
      if (whatsappPollRef.current) {
        clearInterval(whatsappPollRef.current)
        whatsappPollRef.current = null
      }
    }
  }, [whatsappStatus, whatsappSessionId])

  // Handlers
  const handleReload = () => {
    setIsReloading(true)
    isReloadingRef.current = true
    send('integration_list')
  }

  const handleOpenConnect = (integration: Integration) => {
    setSelectedIntegration(integration)
    setCredentials({})
    setConnectError('')
    setShowConnectHelp(false)
    setShowConnectModal(true)

    if (integration.auth_type === 'interactive' && integration.id === 'whatsapp_web') {
      handleStartWhatsAppQR()
    }
  }

  const handleStartWhatsAppQR = () => {
    setWhatsappStatus('loading')
    setWhatsappQrCode(null)
    setWhatsappSessionId(null)
    setWhatsappError(null)
    setWhatsappExpiresIn(null)
    // force: an explicit user click may always start a flow — the backend
    // guard only blocks non-user-initiated (ghost) starts after a connect.
    send('whatsapp_start_qr', { force: true })
  }

  const startWhatsAppPolling = (sessionId: string) => {
    if (whatsappPollRef.current) {
      clearInterval(whatsappPollRef.current)
    }
    whatsappPollRef.current = setInterval(() => {
      send('whatsapp_check_status', { session_id: sessionId })
    }, 2000)
  }

  const handleCancelWhatsApp = () => {
    if (whatsappPollRef.current) {
      clearInterval(whatsappPollRef.current)
      whatsappPollRef.current = null
    }
    if (whatsappSessionId) {
      send('whatsapp_cancel', { session_id: whatsappSessionId })
    }
    setWhatsappQrCode(null)
    setWhatsappSessionId(null)
    setWhatsappStatus('idle')
    setWhatsappError(null)
    setWhatsappExpiresIn(null)
    setShowConnectModal(false)
  }

  const handleOpenManage = (integration: Integration) => {
    // Explicit user click — the only gesture allowed to open the Manage
    // modal. The flag lets the integration_info handler distinguish this
    // response from unsolicited broadcasts.
    manageRequestedRef.current = true
    send('integration_info', { id: integration.id })
  }

  // --- Multi-account staging + requests ------------------------------------

  // Update one integration's staged edits; drops the entry entirely when it
  // becomes a no-op so "has staged changes" stays accurate.
  const updateStaged = (
    integrationId: string,
    fn: (s: StagedAccountEdits) => StagedAccountEdits,
  ) => {
    setStagedEdits(prev => {
      const next = fn(prev[integrationId] ?? emptyStaged())
      if (stagedIsEmpty(next)) {
        const { [integrationId]: _gone, ...rest } = prev
        return rest
      }
      return { ...prev, [integrationId]: next }
    })
  }

  const stageAlias = (integrationId: string, account: ManagedAccount, value: string) => {
    const alias = value.trim() === '' ? null : value
    updateStaged(integrationId, s => {
      const aliases = { ...s.aliases }
      if (alias === (account.alias ?? null)) {
        delete aliases[account.identity] // back to the real value → no-op
      } else {
        aliases[account.identity] = alias
      }
      return { ...s, aliases }
    })
  }

  const stagePrimary = (integrationId: string, account: ManagedAccount) => {
    const realPrimary = managedAccounts?.find(a => a.isPrimary)?.identity ?? null
    updateStaged(integrationId, s => ({
      ...s,
      // Picking the real primary again = clearing the staged override.
      primary: account.identity === realPrimary ? null : account.identity,
    }))
  }

  const stageListen = (integrationId: string, account: ManagedAccount, value: boolean) => {
    updateStaged(integrationId, s => {
      const listen = { ...s.listen }
      if (value === account.listen) {
        delete listen[account.identity]
      } else {
        listen[account.identity] = value
      }
      return { ...s, listen }
    })
  }

  const stageDisconnect = (integrationId: string, identity: string, marked: boolean) => {
    updateStaged(integrationId, s => ({
      ...s,
      disconnect: marked
        ? (s.disconnect.includes(identity) ? s.disconnect : [...s.disconnect, identity])
        : s.disconnect.filter(i => i !== identity),
    }))
  }

  // "Add account" — immediate real OAuth, no staging. ``send`` goes through
  // the shared SocketClient outbox (queued while disconnected, drained on
  // reconnect), so the request is never dropped behind a connection guard.
  // The spinner is cleared ONLY by the matching result broadcast — OAuth can
  // take minutes and we use no wall-clock timers.
  // Only OAuth-capable integrations ('oauth'/'both') have the backend
  // add-account flow. For everything else — token entry, interactive/QR,
  // token_with_interactive — adding an account IS the regular Connect
  // modal (token connect is additive per identity; whatsapp's QR
  // auto-start lives in handleOpenConnect), so reuse it.
  const handleAddAccount = () => {
    if (!managingIntegration) return
    if (managingIntegration.auth_type !== 'oauth' && managingIntegration.auth_type !== 'both') {
      const target = managingIntegration
      setManagingIntegration(null)
      handleOpenConnect(target)
      return
    }
    const requestId = crypto.randomUUID()
    pendingAddRef.current.set(requestId, managingIntegration.id)
    setAddingAccountFor(managingIntegration.id)
    send('integration_accounts_add', {
      integration_id: managingIntegration.id,
      request_id: requestId,
    })
  }

  // One batched save for all staged edits. Same queued transport as above.
  // Edits referring to accounts that are ALSO marked for disconnect are
  // stripped from the payload: the backend applies disconnects first, so a
  // stale alias/listen/primary entry for a removed identity would make the
  // whole batch fail resolution. (The staged entries themselves are kept
  // until the result arrives, so an Undo before save loses nothing.)
  const handleSaveAccountChanges = () => {
    if (!managingIntegration) return
    const staged = stagedEdits[managingIntegration.id]
    if (!staged || stagedIsEmpty(staged)) return
    const requestId = crypto.randomUUID()
    const removing = new Set(staged.disconnect)
    const changes: AccountChanges = {
      disconnect: staged.disconnect,
      primary:
        staged.primary !== null && removing.has(staged.primary)
          ? null
          : staged.primary,
      aliases: Object.fromEntries(
        Object.entries(staged.aliases).filter(([identity]) => !removing.has(identity)),
      ),
      listen: Object.fromEntries(
        Object.entries(staged.listen).filter(([identity]) => !removing.has(identity)),
      ),
    }
    pendingApplyRef.current.set(requestId, managingIntegration.id)
    setAccountsSaving(true)
    setAccountsError('')
    send('integration_apply_account_changes', {
      integration_id: managingIntegration.id,
      request_id: requestId,
      changes,
    })
  }

  const handleConnectToken = () => {
    if (!selectedIntegration) return
    setIsConnecting(true)
    setConnectError('')
    send('integration_connect_token', {
      id: selectedIntegration.id,
      credentials,
    })
  }

  const handleConnectOAuth = () => {
    if (!selectedIntegration) return
    setIsConnecting(true)
    setConnectError('')
    send('integration_connect_oauth', { id: selectedIntegration.id })
  }

  const handleConnectInteractive = () => {
    if (!selectedIntegration) return
    setIsConnecting(true)
    setConnectError('')
    send('integration_connect_interactive', { id: selectedIntegration.id })
  }

  // Slow integrations show a "working…" overlay during disconnect so the
  // user gets visible feedback during the bridge teardown (which can take
  // 20–30 seconds per WhatsApp Web account). Add other slow integrations here.
  const SLOW_DISCONNECT_IDS = new Set(['whatsapp_web'])

  // Disconnect ALL accounts of an integration (list-row Power button).
  // Optimistic: the list flips immediately; the authoritative
  // ``integration_list`` broadcast overwrites it when teardown finishes,
  // and ``integration_disconnect_result`` clears the slow-op overlay.
  const handleDisconnectAll = (integration: Integration) => {
    dispatch(setDisconnected(integration.id))
    if (SLOW_DISCONNECT_IDS.has(integration.id)) {
      setPendingOp({ kind: 'disconnect', id: integration.id, label: integration.name })
    }
    send('integration_disconnect', { id: integration.id })
  }

  const filteredIntegrations = integrations
    .filter(integration => {
      if (!searchQuery) return true
      const query = searchQuery.toLowerCase()
      return integration.name.toLowerCase().includes(query) ||
        integration.description.toLowerCase().includes(query)
    })
    .sort((a, b) => a.name.localeCompare(b.name))

  if (isLoading) {
    return (
      <div className={styles.settingsSection}>
        <div className={styles.loadingState}>
          <Loader2 className={styles.spinner} />
          <span>Loading integrations...</span>
        </div>
      </div>
    )
  }

  return (
    <div className={styles.settingsSection}>
      {/* Header */}
      {!hideHeader && (
        <div className={styles.sectionHeader}>
          <div className={styles.sectionTitleRow}>
            <h3>External Integrations</h3>
            <Badge variant="default">{connectedCount}/{totalIntegrations} connected</Badge>
          </div>
          <p>Connect to external services and tools</p>
        </div>
      )}

      {/* Toolbar */}
      <div className={styles.integrationsToolbar}>
        <div className={styles.integrationsSearch}>
          <input
            type="text"
            className={styles.searchInput}
            placeholder="Search integrations..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>
        <Button
          variant="secondary"
          size="sm"
          onClick={handleReload}
          disabled={isReloading}
          icon={<RotateCcw size={14} className={isReloading ? styles.spinning : ''} />}
        >
          Reload
        </Button>
      </div>

      {/* Integrations list */}
      <div className={styles.integrationsList}>
        {filteredIntegrations.length === 0 ? (
          <div className={styles.emptyState}>
            <Package size={24} />
            <span>
              {searchQuery ? 'No integrations match your search' : 'No integrations available'}
            </span>
          </div>
        ) : (
          filteredIntegrations.map(integration => (
            <div
              key={integration.id}
              className={`${styles.integrationItem} ${!integration.connected ? styles.integrationItemDisabled : ''}`}
            >
              <div className={styles.integrationItemIcon}>
                <IntegrationIcon id={integration.id} icon={integration.icon} size={24} />
              </div>
              <div className={styles.integrationItemMain}>
                <div className={styles.integrationItemHeader}>
                  <span className={styles.integrationItemName}>{integration.name}</span>
                  <Badge variant={integration.connected ? 'success' : 'default'}>
                    {integration.connected ? 'Connected' : 'Not connected'}
                  </Badge>
                  {integration.connected && integration.accounts.length > 0 && (
                    <Badge variant="info">{integration.accounts.length} account{integration.accounts.length > 1 ? 's' : ''}</Badge>
                  )}
                </div>
                <p className={styles.integrationItemDesc}>{integration.description}</p>
              </div>
              <div className={styles.integrationItemActions}>
                {integration.connected ? (
                  <>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleOpenManage(integration)}
                      icon={<Wrench size={14} />}
                      title="Manage accounts"
                    />
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        confirm({
                          title: 'Disconnect Integration',
                          message: `Disconnect all accounts from ${integration.name}?`,
                          confirmText: 'Disconnect',
                          variant: 'danger',
                        }, () => {
                          handleDisconnectAll(integration)
                        })
                      }}
                      icon={<Power size={14} />}
                      title="Disconnect"
                    />
                  </>
                ) : (
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={() => handleOpenConnect(integration)}
                    icon={<Plus size={14} />}
                  >
                    Connect
                  </Button>
                )}
              </div>
            </div>
          ))
        )}
      </div>

      {/* Connect Modal */}
      {showConnectModal && selectedIntegration && (
        <div className={styles.modalOverlay} onClick={() => setShowConnectModal(false)}>
          <div className={styles.modalContent} onClick={e => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h3>Connect {selectedIntegration.name}</h3>
              <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                {(selectedIntegration.connect_help?.length ?? 0) > 0 && (
                  <button
                    className={styles.modalClose}
                    onClick={() => setShowConnectHelp(v => !v)}
                    title={`Where to find ${selectedIntegration.name} credentials`}
                    aria-expanded={showConnectHelp}
                  >
                    <HelpCircle size={18} />
                  </button>
                )}
                <button className={styles.modalClose} onClick={() => setShowConnectModal(false)}>
                  <X size={18} />
                </button>
              </div>
            </div>
            {showConnectHelp && (selectedIntegration.connect_help?.length ?? 0) > 0 && (
              <div
                style={{
                  margin: '0 var(--space-4, 1rem)',
                  marginTop: '12px',
                  padding: 'var(--space-3, 0.75rem) var(--space-4, 1rem)',
                  background: 'var(--bg-tertiary)',
                  border: '1px solid var(--border-primary)',
                  borderRadius: 'var(--radius-md, 6px)',
                  color: 'var(--text-primary)',
                  fontSize: 'var(--text-sm, 0.85rem)',
                  lineHeight: 1.5,
                }}
              >
                <div style={{ fontWeight: 600, marginBottom: 6, color: 'var(--text-primary)' }}>
                  Where to find {selectedIntegration.name} credentials
                </div>
                <ol style={{ margin: 0, paddingLeft: '1.25rem', color: 'var(--text-secondary)' }}>
                  {selectedIntegration.connect_help!.map((step, i) => (
                    <li key={i} style={{ marginBottom: 2 }}>{step}</li>
                  ))}
                </ol>
              </div>
            )}
            <div className={styles.modalBody}>
              {/* OAuth-only integrations */}
              {selectedIntegration.auth_type === 'oauth' && (
                <div className={styles.connectForm}>
                  <p className={styles.connectDesc}>
                    Click the button below to sign in with {selectedIntegration.name}.
                    A browser window will open for authentication.
                  </p>
                  {connectError && (
                    <div className={styles.formError}>{connectError}</div>
                  )}
                  <Button
                    variant="primary"
                    onClick={handleConnectOAuth}
                    disabled={isConnecting}
                  >
                    {isConnecting ? (
                      <>
                        <Loader2 size={16} className={styles.spinning} />
                        Connecting...
                      </>
                    ) : (
                      <>Sign in with {selectedIntegration.name}</>
                    )}
                  </Button>
                </div>
              )}

              {/* Token-only integrations */}
              {selectedIntegration.auth_type === 'token' && (
                <div className={styles.connectForm}>
                  {selectedIntegration.fields.map(field => (
                    <div key={field.key} className={styles.formGroup}>
                      <label className={styles.formLabel}>{field.label}</label>
                      <input
                        type={field.password ? 'password' : 'text'}
                        className={styles.formInput}
                        placeholder={field.placeholder}
                        value={credentials[field.key] || ''}
                        onChange={(e) => setCredentials(prev => ({
                          ...prev,
                          [field.key]: e.target.value
                        }))}
                      />
                    </div>
                  ))}
                  {connectError && (
                    <div className={styles.formError}>{connectError}</div>
                  )}
                  <Button
                    variant="primary"
                    onClick={handleConnectToken}
                    disabled={isConnecting}
                  >
                    {isConnecting ? (
                      <>
                        <Loader2 size={16} className={styles.spinning} />
                        Connecting...
                      </>
                    ) : (
                      'Connect'
                    )}
                  </Button>
                </div>
              )}

              {/* Both OAuth and Token integrations */}
              {selectedIntegration.auth_type === 'both' && (
                <div className={styles.connectForm}>
                  {selectedIntegration.fields.map(field => (
                    <div key={field.key} className={styles.formGroup}>
                      <label className={styles.formLabel}>{field.label}</label>
                      <input
                        type={field.password ? 'password' : 'text'}
                        className={styles.formInput}
                        placeholder={field.placeholder}
                        value={credentials[field.key] || ''}
                        onChange={(e) => setCredentials(prev => ({
                          ...prev,
                          [field.key]: e.target.value
                        }))}
                      />
                    </div>
                  ))}
                  {connectError && (
                    <div className={styles.formError}>{connectError}</div>
                  )}
                  <Button
                    variant="primary"
                    onClick={handleConnectToken}
                    disabled={isConnecting}
                  >
                    {isConnecting ? (
                      <>
                        <Loader2 size={16} className={styles.spinning} />
                        Connecting...
                      </>
                    ) : (
                      'Connect with Token'
                    )}
                  </Button>
                  <div className={styles.connectFormDivider}>or</div>
                  <Button
                    variant="secondary"
                    onClick={handleConnectOAuth}
                    disabled={isConnecting}
                  >
                    Use OAuth Instead
                  </Button>
                </div>
              )}

              {/* Token + Interactive QR integrations (Telegram) */}
              {selectedIntegration.auth_type === 'token_with_interactive' && (
                <div className={styles.connectForm}>
                  {selectedIntegration.fields.map(field => (
                    <div key={field.key} className={styles.formGroup}>
                      <label className={styles.formLabel}>{field.label}</label>
                      <input
                        type={field.password ? 'password' : 'text'}
                        className={styles.formInput}
                        placeholder={field.placeholder}
                        value={credentials[field.key] || ''}
                        onChange={(e) => setCredentials(prev => ({
                          ...prev,
                          [field.key]: e.target.value
                        }))}
                      />
                    </div>
                  ))}
                  {connectError && (
                    <div className={styles.formError}>{connectError}</div>
                  )}
                  <Button
                    variant="primary"
                    onClick={handleConnectToken}
                    disabled={isConnecting}
                  >
                    {isConnecting ? (
                      <>
                        <Loader2 size={16} className={styles.spinning} />
                        Connecting...
                      </>
                    ) : (
                      'Connect Bot'
                    )}
                  </Button>
                  <div className={styles.connectFormDivider}>or</div>
                  <p className={styles.connectDesc}>
                    Connect a personal account via QR code. A QR code window will open separately on your machine.
                  </p>
                  <Button
                    variant="secondary"
                    onClick={handleConnectInteractive}
                    disabled={isConnecting}
                  >
                    {isConnecting ? (
                      <>
                        <Loader2 size={16} className={styles.spinning} />
                        Waiting for QR scan...
                      </>
                    ) : (
                      'Connect User Account (QR Code)'
                    )}
                  </Button>
                </div>
              )}

              {/* Interactive integrations: generic dispatcher for non-WhatsApp */}
              {selectedIntegration.auth_type === 'interactive' && selectedIntegration.id !== 'whatsapp_web' && (
                <div className={styles.connectForm}>
                  <p className={styles.connectDesc}>
                    {selectedIntegration.description}
                  </p>
                  <Button
                    variant="primary"
                    onClick={handleConnectInteractive}
                    disabled={isConnecting}
                  >
                    {isConnecting ? (
                      <><Loader2 size={16} className={styles.spinning} /> Connecting...</>
                    ) : (
                      <>Connect {selectedIntegration.name}</>
                    )}
                  </Button>
                  {connectError && (
                    <div className={styles.connectError}>{connectError}</div>
                  )}
                </div>
              )}

              {/* WhatsApp Web QR-specific interactive flow */}
              {selectedIntegration.auth_type === 'interactive' && selectedIntegration.id === 'whatsapp_web' && (
                <div className={styles.connectForm}>
                  {whatsappStatus === 'loading' && (
                    <div className={styles.whatsappLoading}>
                      <Loader2 size={32} className={styles.spinning} />
                      <p>Starting WhatsApp Web session...</p>
                    </div>
                  )}

                  {whatsappStatus === 'qr_ready' && whatsappQrCode && (
                    <div className={styles.whatsappQrContainer}>
                      <p className={styles.connectDesc}>
                        Scan this QR code with your WhatsApp mobile app to connect.
                      </p>
                      <div className={styles.whatsappQrCode}>
                        <img src={whatsappQrCode} alt="WhatsApp QR Code" />
                      </div>
                      <p className={styles.whatsappQrHint}>
                        Open WhatsApp &rarr; Settings &rarr; Linked Devices &rarr; Link a Device
                      </p>
                      {whatsappExpiresIn !== null && (
                        <p className={styles.whatsappQrHint}>
                          {whatsappExpiresIn > 0
                            ? `Code refreshes in ${Math.floor(whatsappExpiresIn / 60)}:${String(whatsappExpiresIn % 60).padStart(2, '0')}`
                            : 'Refreshing code…'}
                        </p>
                      )}
                    </div>
                  )}

                  {(whatsappStatus === 'scanned' || whatsappStatus === 'promoting') && (
                    <div className={styles.whatsappLoading}>
                      <Loader2 size={32} className={styles.spinning} />
                      <p>
                        {whatsappStatus === 'scanned'
                          ? 'QR scanned — connecting to WhatsApp…'
                          : 'Almost done — finishing the connection…'}
                      </p>
                    </div>
                  )}

                  {whatsappStatus === 'timeout' && (
                    <div className={styles.whatsappError}>
                      <AlertTriangle size={24} />
                      <p>{whatsappError || 'The QR code expired before it was scanned.'}</p>
                      <Button variant="primary" onClick={handleStartWhatsAppQR}>
                        Start Again
                      </Button>
                    </div>
                  )}

                  {whatsappStatus === 'error' && (
                    <div className={styles.whatsappError}>
                      <AlertTriangle size={24} />
                      <p>{whatsappError || 'Failed to connect to WhatsApp'}</p>
                      <Button variant="primary" onClick={handleStartWhatsAppQR}>
                        Try Again
                      </Button>
                    </div>
                  )}

                  {whatsappStatus === 'idle' && (
                    <div className={styles.whatsappIdle}>
                      <p className={styles.connectDesc}>
                        Click the button below to generate a QR code for WhatsApp Web.
                      </p>
                      <Button variant="primary" onClick={handleStartWhatsAppQR}>
                        Generate QR Code
                      </Button>
                    </div>
                  )}

                  {(whatsappStatus === 'loading' || whatsappStatus === 'qr_ready' || whatsappStatus === 'scanned') && (
                    <Button variant="secondary" onClick={handleCancelWhatsApp}>
                      Cancel
                    </Button>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Manage Modal — the accounts list + integration settings live on the
          main page; tapping an account opens its own detail page. One Save in
          the footer commits everything that's changed. */}
      {showManageModal && managingIntegration && (() => {
        const integration = managingIntegration
        const accounts = managedAccounts ?? []
        const staged = stagedEdits[integration.id]
        const accountsDirty = staged !== undefined && !stagedIsEmpty(staged)
        const settingsDirty =
          JSON.stringify(configValues) !== JSON.stringify(configBaseline)
        const anyDirty = accountsDirty || settingsDirty
        const busy = accountsSaving || configSaving
        const hasConfig =
          integration.has_config && (integration.config_fields?.length ?? 0) > 0

        // Effective primary = staged override falling back to the real one.
        const realPrimary = accounts.find(a => a.isPrimary)?.identity ?? null
        const stagedPrimary =
          staged && staged.primary !== null && !staged.disconnect.includes(staged.primary)
            ? staged.primary
            : null
        const effectivePrimary = stagedPrimary ?? realPrimary

        // Plain-language session labels (only whatsapp_web carries state).
        const stateLabel = (a: ManagedAccount): string => {
          switch (a.sessionState) {
            case 'needs_relink': return 'Signed out'
            case 'reconnecting': return 'Reconnecting…'
            case 'failed': return 'Connection problem'
            case 'launching': return 'Connecting…'
            default: return 'Connected'
          }
        }
        const isProblem = (a: ManagedAccount): boolean =>
          a.sessionState === 'needs_relink' || a.sessionState === 'failed'
        // Status dot color: green = live, amber = transient, red = needs you.
        const dotClass = (a: ManagedAccount): string => {
          if (isProblem(a)) return styles.mLiveBad
          if (a.sessionState === 'reconnecting' || a.sessionState === 'launching') return styles.mLiveWarn
          return styles.mLiveOk
        }

        const selectedAccount =
          accounts.find(a => a.identity === selectedAccountIdentity) ?? null
        // Guard: a detail page for an account that vanished falls back to list.
        const page: 'list' | 'account' =
          managePage === 'account' && !selectedAccount ? 'list' : managePage
        const selectedMarked =
          selectedAccount ? (staged?.disconnect.includes(selectedAccount.identity) ?? false) : false

        const goList = () => {
          setManagePage('list')
          setSelectedAccountIdentity(null)
        }
        const relink = () => {
          // QR integrations: the Connect modal starts a fresh link flow;
          // scanning with the same phone replaces the dead session in place.
          setManagingIntegration(null)
          handleOpenConnect(integration)
        }
        const saveAll = () => {
          if (accountsDirty) handleSaveAccountChanges()
          if (settingsDirty) {
            setConfigSaving(true)
            send('integration_update_config', { id: integration.id, values: configValues })
          }
        }
        const discardAll = () => {
          setStagedEdits(prev => {
            const { [integration.id]: _gone, ...rest } = prev
            return rest
          })
          setAccountsError('')
          setConfigValues(configBaseline)
        }

        return (
        <div className={styles.modalOverlay} onClick={requestCloseManage}>
          <div className={styles.modalContent} onClick={e => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              {page === 'list' ? (
                <div className={styles.mHeaderTitle}>
                  <IntegrationIcon id={integration.id} icon={integration.icon} size={22} />
                  <h3>{integration.name}</h3>
                </div>
              ) : (
                <button className={styles.mBack} onClick={goList}>
                  <ChevronLeft size={18} />
                  <IntegrationIcon id={integration.id} icon={integration.icon} size={18} />
                  {integration.name}
                </button>
              )}
              <button className={styles.modalClose} onClick={requestCloseManage}>
                <X size={18} />
              </button>
            </div>

            <div className={styles.modalBody}>
              {managedAccounts === null ? (
                <p className={styles.noAccounts}>
                  Couldn&apos;t load accounts — close and reopen Manage, or check
                  the backend logs.
                </p>
              ) : page === 'list' ? (
                /* ---- Main page: account list + integration settings ---- */
                <>
                  <div className={styles.mList}>
                    {accounts.length === 0 && (
                      <p className={styles.noAccounts}>No accounts connected</p>
                    )}
                    {accounts.map(account => {
                      const marked = staged?.disconnect.includes(account.identity) ?? false
                      const meta = account.identity === effectivePrimary
                        ? 'Default'
                        : marked
                          ? 'Will disconnect'
                          : isProblem(account) || account.sessionState === 'reconnecting'
                            ? stateLabel(account)
                            : ''
                      return (
                        <button
                          key={account.identity}
                          className={styles.mRow}
                          onClick={() => {
                            setSelectedAccountIdentity(account.identity)
                            setManagePage('account')
                          }}
                        >
                          <span className={`${styles.mLive} ${dotClass(account)}`} />
                          <span className={styles.mRowId} title={account.identity}>
                            {account.identity}
                          </span>
                          <span className={styles.mRowSpacer} />
                          {meta && <span className={styles.mRowMeta}>{meta}</span>}
                          <ChevronRight size={16} className={styles.mChev} />
                        </button>
                      )
                    })}

                    <button
                      className={styles.mAddRow}
                      onClick={handleAddAccount}
                      disabled={addingAccountFor === integration.id}
                    >
                      {addingAccountFor === integration.id
                        ? <Loader2 size={15} className={styles.spinning} />
                        : <Plus size={16} />}
                      <span>
                        {addingAccountFor === integration.id
                          ? 'Waiting for sign-in…'
                          : 'Add account'}
                      </span>
                    </button>

                    {accountsError && <div className={styles.formError}>{accountsError}</div>}
                  </div>

                  {hasConfig && (
                    <div className={styles.mSettings}>
                      <div>
                        <h4 className={styles.mSettingsHeading}>{integration.name} settings</h4>
                        <p className={styles.mSettingsScope}>
                          Applies to every {integration.name} account you&apos;ve connected.
                        </p>
                      </div>
                      {configLoading ? (
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, opacity: 0.7 }}>
                          <Loader2 size={16} className={styles.spinning} />
                          <span>Loading settings…</span>
                        </div>
                      ) : (
                        <ConfigFields
                          integrationId={integration.id}
                          schema={integration.config_fields ?? []}
                          values={configValues}
                          onChange={setConfigValues}
                        />
                      )}
                    </div>
                  )}
                </>
              ) : selectedAccount ? (
                /* ---- Account detail page ---- */
                (() => {
                  const aliasValue =
                    staged && selectedAccount.identity in staged.aliases
                      ? (staged.aliases[selectedAccount.identity] ?? '')
                      : (selectedAccount.alias ?? '')
                  const listenValue =
                    staged && selectedAccount.identity in staged.listen
                      ? staged.listen[selectedAccount.identity]
                      : selectedAccount.listen
                  const isDefault = selectedAccount.identity === effectivePrimary
                  return (
                    <div className={styles.mDetail}>
                      <div className={styles.mDetailHead}>
                        <div className={styles.mDetailHeadMain}>
                          <div className={styles.mDetailId}>{selectedAccount.identity}</div>
                          <div className={styles.mDetailState}>{stateLabel(selectedAccount)}</div>
                        </div>
                        {isDefault ? (
                          <span className={styles.mDefaultTag}>Default</span>
                        ) : !selectedMarked ? (
                          <button
                            className={styles.mMakeDefault}
                            onClick={() => stagePrimary(integration.id, selectedAccount)}
                          >
                            Make default
                          </button>
                        ) : null}
                      </div>

                      {selectedAccount.sessionState === 'needs_relink' && (
                        <div className={styles.mNotice}>
                          <span>This account was signed out. Scan the QR code again to reconnect it.</span>
                          <Button variant="primary" size="sm" onClick={relink}>Re-link</Button>
                        </div>
                      )}

                      <div className={styles.formGroup}>
                        <label htmlFor={`alias-${selectedAccount.identity}`}>Nickname</label>
                        <input
                          id={`alias-${selectedAccount.identity}`}
                          type="text"
                          className={styles.input}
                          placeholder="e.g. work"
                          value={aliasValue}
                          onChange={e => stageAlias(integration.id, selectedAccount, e.target.value)}
                        />
                        <p className={styles.hint}>
                          A short name to use instead of the full address.
                        </p>
                      </div>

                      <label
                        className={styles.toggleGroup}
                        htmlFor={`listen-${selectedAccount.identity}`}
                      >
                        <div className={styles.toggleInfo}>
                          <span className={styles.toggleLabel}>Send new activity to the agent</span>
                          <span className={styles.toggleDesc}>
                            When on, new messages and events from this account are handed
                            to the agent to act on. When off, it&apos;s used only for sending.
                          </span>
                        </div>
                        <input
                          id={`listen-${selectedAccount.identity}`}
                          type="checkbox"
                          className={styles.toggle}
                          checked={listenValue}
                          onChange={e => stageListen(integration.id, selectedAccount, e.target.checked)}
                        />
                      </label>

                      {selectedMarked && (
                        <p className={styles.mRemovalNote}>
                          This account will be disconnected when you save.
                        </p>
                      )}
                    </div>
                  )
                })()
              ) : null}
            </div>

            {/* One footer for the whole modal: Save commits account changes and
                settings together. On an account page, Disconnect sits between
                Discard and Save. */}
            {managedAccounts !== null && (
              <div className={styles.modalFooter}>
                <span className={styles.mFootStatus}>
                  {anyDirty ? 'Unsaved changes' : 'All changes saved'}
                </span>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={discardAll}
                  disabled={!anyDirty || busy}
                >
                  Discard
                </Button>
                {page === 'account' && selectedAccount && (
                  selectedMarked ? (
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => stageDisconnect(integration.id, selectedAccount.identity, false)}
                      disabled={busy}
                    >
                      Keep account
                    </Button>
                  ) : (
                    <Button
                      variant="secondary"
                      size="sm"
                      className={styles.mDisconnectBtn}
                      onClick={() => stageDisconnect(integration.id, selectedAccount.identity, true)}
                      disabled={busy}
                    >
                      Disconnect
                    </Button>
                  )
                )}
                <Button
                  variant="primary"
                  size="sm"
                  onClick={saveAll}
                  disabled={!anyDirty || busy}
                >
                  {busy ? <><Loader2 size={14} className={styles.spinning} /> Saving…</> : 'Save'}
                </Button>
              </div>
            )}
          </div>
        </div>
        )
      })()}

      {/* Confirm Modal */}
      {/* Slow-disconnect overlay — shown until the backend confirms via
          ``integration_disconnect_result``. */}
      {pendingOp && (
        <div className={styles.modalOverlay}>
          <div className={styles.modalContent} style={{ minWidth: 320, maxWidth: 400 }}>
            <div className={styles.whatsappLoading}>
              <Loader2 size={48} className={styles.spinning} />
              <p style={{ marginTop: 16, fontWeight: 500 }}>
                {pendingOp.kind === 'disconnect' ? `Disconnecting ${pendingOp.label}…` : `Connecting ${pendingOp.label}…`}
              </p>
              <p style={{ marginTop: 8, fontSize: 12, opacity: 0.7 }}>
                This can take up to 30 seconds.
              </p>
            </div>
          </div>
        </div>
      )}

      <ConfirmModal {...confirmModalProps} />
    </div>
  )
}
