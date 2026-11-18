import React, { useState, useEffect, useCallback } from 'react'
import {
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
import { IntegrationIcon } from '../../components/integrations/IntegrationIcon'
import { useTranslation } from 'react-i18next'
import { Button, Badge, ConfirmModal } from '../../components/ui'
import { useToast } from '../../contexts/ToastContext'
import { useConfirmModal, usePersistedState } from '../../hooks'
import { UI_STATE } from '../../store/uiState'
import { RESOURCES, useResource } from '../../store/resources'
import { formatNumber, localeCompare } from '../../i18n/format'
import styles from './SettingsPage.module.css'
import { useSettingsWebSocket } from './useSettingsWebSocket'
import { FigmaCanvasSettings } from './FigmaCanvasSettings'
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
  const { t } = useTranslation(['settings', 'common'])
  const { send, onMessage } = useSettingsWebSocket()
  const { showToast } = useToast()
  const dispatch = useAppDispatch()

  // The slice caches the list; ResourceSync fetches it when unloaded or stale
  // and refetches it whenever integrations change (connect, disconnect,
  // account or config edits from any tab).
  useResource(RESOURCES.integrations)

  // Slice-backed: list state cached across remounts.
  const integrations = useAppSelector(selectIntegrations)
  const totalIntegrations = useAppSelector(selectIntegrationsTotal)
  const connectedCount = useAppSelector(selectIntegrationsConnected)
  const hasLoaded = useAppSelector(selectIntegrationsHasLoaded)
  const isLoading = !hasLoaded

  // Search
  const [searchQuery, setSearchQuery] = usePersistedState(UI_STATE.settings.integrationsSearch)

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

  // Manage modal state. The modal opens with the integration_info snapshot,
  // then reads the integration from the slice by id, so a refreshed list
  // (another tab, the agent) keeps it current instead of a stale copy.
  const [showManageModal, setShowManageModal] = useState(false)
  const [managingSnapshot, setManagingIntegration] = useState<Integration | null>(null)
  const managingIntegration = React.useMemo(() => {
    if (!managingSnapshot) return null
    const listed = integrations.find(i => i.id === managingSnapshot.id)
    return listed ? { ...managingSnapshot, ...listed } : managingSnapshot
  }, [managingSnapshot, integrations])
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
    managingIntegrationRef.current = null
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
  const configLoadRequestRef = React.useRef<string | null>(null)
  const configSaveRequestRef = React.useRef<string | null>(null)

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
        title: t('settings:integrations.discardConfirmTitle'),
        message: t('settings:integrations.discardConfirmMessage', { name: managingIntegration.name }),
        confirmText: t('settings:integrations.discardConfirmButton'),
        cancelText: t('settings:integrations.keepEditing'),
        variant: 'danger',
      }, closeManageModal)
      return
    }
    closeManageModal()
  }

  // Subscribe to side-effect messages (toasts, modal close). The integrations
  // list itself is updated by the slice via the registry.
  useEffect(() => {
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
            showToast('success', t('settings:integrations.toast.reloaded'))
          }
        } else if (d.error) {
          showToast('error', d.error)
        }
      }),
      onMessage('integration_connect_result', (data: unknown) => {
        const d = data as { success: boolean; message?: string; error?: string; id?: string }
        setIsConnecting(false)
        if (d.success) {
          showToast('success', d.message || t('settings:integrations.toast.connected'))
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
          setConnectError(d.error || d.message || t('settings:integrations.toast.connectionFailed'))
        }
      }),
      onMessage('integration_disconnect_result', (data: unknown) => {
        const d = data as { success: boolean; message?: string; error?: string; id?: string }
        // Clear the slow-disconnect overlay if this result is for the
        // operation it was tracking.
        setPendingOp(prev => (prev && d.id && prev.id === d.id) ? null : prev)
        if (d.success) {
          showToast('success', d.message || t('settings:integrations.toast.disconnected'))
          // Only a disconnect of the integration on screen closes the modal.
          if (d.id && d.id === managingIntegrationRef.current?.id) closeManageModal()
        } else {
          showToast('error', d.error || t('settings:integrations.toast.disconnectFailed'))
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
            // Publish the active integration before requesting config: a fast
            // response can arrive before the effect mirrors React state.
            managingIntegrationRef.current = d.integration
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
              const requestId = crypto.randomUUID()
              configLoadRequestRef.current = requestId
              send('integration_get_config', { id: d.integration.id, requestId })
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
          showToast('error', d.error || t('settings:integrations.toast.infoFailed'))
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
          showToast('success', d.message || t('settings:integrations.toast.accountAdded'))
        } else {
          showToast('error', d.message || t('settings:integrations.toast.accountAddFailed'))
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
          showToast('success', t('settings:integrations.toast.accountChangesSaved'))
        } else {
          // Failure keeps the staged edits (nothing cleared above) so the
          // user can retry; surface the error inline and as a toast.
          const msg = d.error || t('settings:integrations.toast.accountChangesFailed')
          setAccountsError(msg)
          showToast('error', msg)
        }
      }),
      // Per-integration runtime config (schema-driven; works for every
      // integration that declares config_class on its handler).
      onMessage('integration_config', (data: unknown) => {
        const d = data as {
          id: string; success: boolean
          requestId?: string
          schema?: ConfigField[]; values?: Record<string, any>
          error?: string
        }
        // Another integration's config must not replace the open form.
        if (d.id !== managingIntegrationRef.current?.id) return
        if (!d.requestId || d.requestId !== configLoadRequestRef.current) return
        configLoadRequestRef.current = null
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
          requestId?: string
          message?: string; values?: Record<string, any>; error?: string
        }
        if (d.id !== managingIntegrationRef.current?.id) return
        if (!d.requestId || d.requestId !== configSaveRequestRef.current) return
        configSaveRequestRef.current = null
        setConfigSaving(false)
        if (d.success) {
          showToast('success', d.message || t('settings:integrations.toast.settingsSaved'))
          if (d.values) {
            setConfigValues(d.values)
            setConfigBaseline(d.values)
          }
        } else {
          showToast('error', d.error || d.message || t('settings:integrations.toast.settingsFailed'))
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
          setWhatsappError(d.message || t('settings:integrations.toast.qrFailed'))
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
          showToast('success', d.message || t('settings:integrations.toast.whatsappConnected'))
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
          setWhatsappError(d.message || t('settings:integrations.toast.qrExpired'))
          stopPolling()
        } else if (d.status === 'error' || d.status === 'disconnected') {
          setWhatsappStatus('error')
          setWhatsappError(d.message || t('settings:integrations.toast.sessionFailed'))
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

    return () => cleanups.forEach(c => c())
  }, [send, onMessage, showToast, closeManageModal, pruneStagedFor, refreshManagedAccounts])

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
    .sort((a, b) => localeCompare(a.name, b.name))

  if (isLoading) {
    return (
      <div className={styles.settingsSection}>
        <div className={styles.loadingState}>
          <Loader2 className={styles.spinner} />
          <span>{t('settings:integrations.loading')}</span>
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
            <h3>{t('settings:integrations.title')}</h3>
            <Badge variant="default">{t('settings:integrations.connectedBadge', { connected: formatNumber(connectedCount), total: formatNumber(totalIntegrations) })}</Badge>
          </div>
          <p>{t('settings:integrations.subtitle')}</p>
        </div>
      )}

      {/* Toolbar */}
      <div className={styles.integrationsToolbar}>
        <div className={styles.integrationsSearch}>
          <input
            type="text"
            className={styles.searchInput}
            placeholder={t('settings:integrations.search')}
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
          {t('settings:integrations.reload')}
        </Button>
      </div>

      {/* Integrations list */}
      <div className={styles.integrationsList}>
        {filteredIntegrations.length === 0 ? (
          <div className={styles.emptyState}>
            <Package size={24} />
            <span>
              {searchQuery ? t('settings:integrations.noMatch') : t('settings:integrations.noneAvailable')}
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
                    {integration.connected ? t('settings:integrations.connected') : t('settings:integrations.notConnected')}
                  </Badge>
                  {integration.connected && integration.accounts.length > 0 && (
                    <Badge variant="info">{t('settings:integrations.accountCount', { count: integration.accounts.length })}</Badge>
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
                      title={t('settings:integrations.manageAccounts')}
                    />
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        confirm({
                          title: t('settings:integrations.disconnectConfirmTitle'),
                          message: t('settings:integrations.disconnectConfirmMessage', { name: integration.name }),
                          confirmText: t('common:actions.disconnect'),
                          variant: 'danger',
                        }, () => {
                          handleDisconnectAll(integration)
                        })
                      }}
                      icon={<Power size={14} />}
                      title={t('settings:integrations.disconnectTitle')}
                    />
                  </>
                ) : (
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={() => handleOpenConnect(integration)}
                    icon={<Plus size={14} />}
                  >
                    {t('settings:integrations.connect.connect')}
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
              <h3>{t('settings:integrations.connect.title', { name: selectedIntegration.name })}</h3>
              <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                {(selectedIntegration.connect_help?.length ?? 0) > 0 && (
                  <button
                    className={styles.modalClose}
                    onClick={() => setShowConnectHelp(v => !v)}
                    title={t('settings:integrations.connect.helpTitle', { name: selectedIntegration.name })}
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
                  {t('settings:integrations.connect.helpTitle', { name: selectedIntegration.name })}
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
                    {t('settings:integrations.connect.oauthDesc', { name: selectedIntegration.name })}
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
                        {t('common:status.connecting')}
                      </>
                    ) : (
                      <>{t('settings:integrations.connect.signInWith', { name: selectedIntegration.name })}</>
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
                        {t('common:status.connecting')}
                      </>
                    ) : (
                      t('settings:integrations.connect.connect')
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
                        {t('common:status.connecting')}
                      </>
                    ) : (
                      t('settings:integrations.connect.connectWithToken')
                    )}
                  </Button>
                  <div className={styles.connectFormDivider}>{t('settings:integrations.or')}</div>
                  <Button
                    variant="secondary"
                    onClick={handleConnectOAuth}
                    disabled={isConnecting}
                  >
                    {t('settings:integrations.connect.useOAuth')}
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
                        {t('common:status.connecting')}
                      </>
                    ) : (
                      t('settings:integrations.connect.connectBot')
                    )}
                  </Button>
                  <div className={styles.connectFormDivider}>{t('settings:integrations.or')}</div>
                  <p className={styles.connectDesc}>
                    {t('settings:integrations.connect.qrDesc')}
                  </p>
                  <Button
                    variant="secondary"
                    onClick={handleConnectInteractive}
                    disabled={isConnecting}
                  >
                    {isConnecting ? (
                      <>
                        <Loader2 size={16} className={styles.spinning} />
                        {t('settings:integrations.connect.waitingQrScan')}
                      </>
                    ) : (
                      t('settings:integrations.connect.connectUserQr')
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
                      <><Loader2 size={16} className={styles.spinning} /> {t('common:status.connecting')}</>
                    ) : (
                      <>{t('settings:integrations.connect.connectNamed', { name: selectedIntegration.name })}</>
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
                      <p>{t('settings:integrations.whatsapp.starting')}</p>
                    </div>
                  )}

                  {whatsappStatus === 'qr_ready' && whatsappQrCode && (
                    <div className={styles.whatsappQrContainer}>
                      <p className={styles.connectDesc}>
                        {t('settings:integrations.whatsapp.scanDesc')}
                      </p>
                      <div className={styles.whatsappQrCode}>
                        <img src={whatsappQrCode} alt={t('settings:integrations.whatsapp.qrAlt')} />
                      </div>
                      <p className={styles.whatsappQrHint}>
                        {t('settings:integrations.whatsapp.linkHint')}
                      </p>
                      {whatsappExpiresIn !== null && (
                        <p className={styles.whatsappQrHint}>
                          {whatsappExpiresIn > 0
                            ? t('settings:integrations.whatsapp.refreshIn', { time: `${Math.floor(whatsappExpiresIn / 60)}:${String(whatsappExpiresIn % 60).padStart(2, '0')}` })
                            : t('settings:integrations.whatsapp.refreshing')}
                        </p>
                      )}
                    </div>
                  )}

                  {(whatsappStatus === 'scanned' || whatsappStatus === 'promoting') && (
                    <div className={styles.whatsappLoading}>
                      <Loader2 size={32} className={styles.spinning} />
                      <p>
                        {whatsappStatus === 'scanned'
                          ? t('settings:integrations.whatsapp.scanned')
                          : t('settings:integrations.whatsapp.promoting')}
                      </p>
                    </div>
                  )}

                  {whatsappStatus === 'timeout' && (
                    <div className={styles.whatsappError}>
                      <AlertTriangle size={24} />
                      <p>{whatsappError || t('settings:integrations.whatsapp.expired')}</p>
                      <Button variant="primary" onClick={handleStartWhatsAppQR}>
                        {t('settings:integrations.whatsapp.startAgain')}
                      </Button>
                    </div>
                  )}

                  {whatsappStatus === 'error' && (
                    <div className={styles.whatsappError}>
                      <AlertTriangle size={24} />
                      <p>{whatsappError || t('settings:integrations.whatsapp.connectFailed')}</p>
                      <Button variant="primary" onClick={handleStartWhatsAppQR}>
                        {t('settings:integrations.whatsapp.tryAgain')}
                      </Button>
                    </div>
                  )}

                  {whatsappStatus === 'idle' && (
                    <div className={styles.whatsappIdle}>
                      <p className={styles.connectDesc}>
                        {t('settings:integrations.whatsapp.idleDesc')}
                      </p>
                      <Button variant="primary" onClick={handleStartWhatsAppQR}>
                        {t('settings:integrations.whatsapp.generateQr')}
                      </Button>
                    </div>
                  )}

                  {(whatsappStatus === 'loading' || whatsappStatus === 'qr_ready' || whatsappStatus === 'scanned') && (
                    <Button variant="secondary" onClick={handleCancelWhatsApp}>
                      {t('common:actions.cancel')}
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
            case 'needs_relink': return t('settings:integrations.manage.state.signedOut')
            case 'reconnecting': return t('settings:integrations.manage.state.reconnecting')
            case 'failed': return t('settings:integrations.manage.state.problem')
            case 'launching': return t('settings:integrations.manage.state.connecting')
            default: return t('settings:integrations.manage.state.connected')
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
            // Preserve fields changed by chat actions or another tab while
            // this form was open; reject concurrent edits to the same field.
            const values = Object.fromEntries(
              Object.entries(configValues).filter(
                ([key, value]) => JSON.stringify(value) !== JSON.stringify(configBaseline[key])
              )
            )
            const expectedValues = Object.fromEntries(
              Object.keys(values).map(key => [key, configBaseline[key]])
            )
            const requestId = crypto.randomUUID()
            configSaveRequestRef.current = requestId
            send('integration_update_config', {
              id: integration.id, values, expected_values: expectedValues, requestId,
            })
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
                  {t('settings:integrations.manage.loadFailed')}
                </p>
              ) : page === 'list' ? (
                /* ---- Main page: account list + integration settings ---- */
                <>
                  <div className={styles.mList}>
                    {accounts.length === 0 && (
                      <p className={styles.noAccounts}>{t('settings:integrations.manage.noAccounts')}</p>
                    )}
                    {accounts.map(account => {
                      const marked = staged?.disconnect.includes(account.identity) ?? false
                      const meta = account.identity === effectivePrimary
                        ? t('settings:integrations.manage.default')
                        : marked
                          ? t('settings:integrations.manage.willDisconnect')
                          : isProblem(account) || account.sessionState === 'reconnecting'
                            ? stateLabel(account)
                            : ''
                      // Nickname first (staged edit wins); the identity can be an
                      // opaque id (e.g. a token fingerprint), so it stays in the tooltip.
                      const nickname = staged && account.identity in staged.aliases
                        ? staged.aliases[account.identity]
                        : account.alias
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
                            {nickname || account.identity}
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
                          ? t('settings:integrations.manage.waitingSignIn')
                          : t('settings:integrations.manage.addAccount')}
                      </span>
                    </button>

                    {accountsError && <div className={styles.formError}>{accountsError}</div>}
                  </div>

                  {integration.id === 'figma' && <FigmaCanvasSettings accounts={accounts.filter(a => !staged?.disconnect.includes(a.identity))} />}

                  {hasConfig && (
                    <div className={styles.mSettings}>
                      <div>
                        <h4 className={styles.mSettingsHeading}>{t('settings:integrations.manage.settingsHeading', { name: integration.name })}</h4>
                        <p className={styles.mSettingsScope}>
                          {t('settings:integrations.manage.settingsScope', { name: integration.name })}
                        </p>
                      </div>
                      {configLoading ? (
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, opacity: 0.7 }}>
                          <Loader2 size={16} className={styles.spinning} />
                          <span>{t('settings:integrations.manage.loadingSettings')}</span>
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
                          <span className={styles.mDefaultTag}>{t('settings:integrations.manage.default')}</span>
                        ) : !selectedMarked ? (
                          <button
                            className={styles.mMakeDefault}
                            onClick={() => stagePrimary(integration.id, selectedAccount)}
                          >
                            {t('settings:integrations.manage.makeDefault')}
                          </button>
                        ) : null}
                      </div>

                      {selectedAccount.sessionState === 'needs_relink' && (
                        <div className={styles.mNotice}>
                          <span>{t('settings:integrations.manage.relinkNotice')}</span>
                          <Button variant="primary" size="sm" onClick={relink}>{t('settings:integrations.manage.relink')}</Button>
                        </div>
                      )}

                      <div className={styles.formGroup}>
                        <label htmlFor={`alias-${selectedAccount.identity}`}>{t('settings:integrations.manage.nickname')}</label>
                        <input
                          id={`alias-${selectedAccount.identity}`}
                          type="text"
                          className={styles.input}
                          placeholder={t('settings:integrations.manage.nicknamePlaceholder')}
                          value={aliasValue}
                          onChange={e => stageAlias(integration.id, selectedAccount, e.target.value)}
                        />
                        <p className={styles.hint}>
                          {t('settings:integrations.manage.nicknameHint')}
                        </p>
                      </div>

                      {integration.supports_listening !== false && <label
                        className={styles.toggleGroup}
                        htmlFor={`listen-${selectedAccount.identity}`}
                      >
                        <div className={styles.toggleInfo}>
                          <span className={styles.toggleLabel}>{t('settings:integrations.manage.listenLabel')}</span>
                          <span className={styles.toggleDesc}>
                            {t('settings:integrations.manage.listenDesc')}
                          </span>
                        </div>
                        <input
                          id={`listen-${selectedAccount.identity}`}
                          type="checkbox"
                          className={styles.toggle}
                          checked={listenValue}
                          onChange={e => stageListen(integration.id, selectedAccount, e.target.checked)}
                        />
                      </label>}

                      {selectedMarked && (
                        <p className={styles.mRemovalNote}>
                          {t('settings:integrations.manage.willDisconnectNote')}
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
                  {anyDirty ? t('settings:integrations.manage.unsavedChanges') : t('settings:integrations.manage.allSaved')}
                </span>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={discardAll}
                  disabled={!anyDirty || busy}
                >
                  {t('settings:integrations.manage.discard')}
                </Button>
                {page === 'account' && selectedAccount && (
                  selectedMarked ? (
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => stageDisconnect(integration.id, selectedAccount.identity, false)}
                      disabled={busy}
                    >
                      {t('settings:integrations.manage.keepAccount')}
                    </Button>
                  ) : (
                    <Button
                      variant="secondary"
                      size="sm"
                      className={styles.mDisconnectBtn}
                      onClick={() => stageDisconnect(integration.id, selectedAccount.identity, true)}
                      disabled={busy}
                    >
                      {t('settings:integrations.manage.disconnect')}
                    </Button>
                  )
                )}
                <Button
                  variant="primary"
                  size="sm"
                  onClick={saveAll}
                  disabled={!anyDirty || busy}
                >
                  {busy ? <><Loader2 size={14} className={styles.spinning} /> {t('common:status.saving')}</> : t('common:actions.save')}
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
                {pendingOp.kind === 'disconnect' ? t('settings:integrations.overlay.disconnecting', { label: pendingOp.label }) : t('settings:integrations.overlay.connecting', { label: pendingOp.label })}
              </p>
              <p style={{ marginTop: 8, fontSize: 12, opacity: 0.7 }}>
                {t('settings:integrations.overlay.takesTime')}
              </p>
            </div>
          </div>
        </div>
      )}

      <ConfirmModal {...confirmModalProps} />
    </div>
  )
}
