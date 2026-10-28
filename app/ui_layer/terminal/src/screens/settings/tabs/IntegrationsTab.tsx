/**
 * Settings > Integrations: every integration with its connection state and
 * accounts. Connect with a token (masked fields), with OAuth (CraftBot
 * opens the sign-in page in the system browser and waits for it), with an
 * interactive flow, or for WhatsApp with a QR code drawn in half blocks.
 * Connected integrations open their accounts: add another, make one the
 * default, nickname, listen on or off, disconnect one (confirm), disconnect
 * all (confirm), and the integration's own settings. Same messages as the
 * browser's tab.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { Box, Text } from 'ink'
import { useTranslation } from 'react-i18next'
import { useAppDispatch, useAppSelector, send } from '../../../state/hooks'
import {
  setDisconnected,
  type ConfigField,
  type Integration,
} from '../../../../../browser/frontend/src/store/slices/integrationsSettingsSlice'
import {
  selectIntegrations,
  selectIntegrationsConnected,
  selectIntegrationsHasLoaded,
  selectIntegrationsTotal,
} from '../../../../../browser/frontend/src/store/selectors/integrationsSettings'
import { RESOURCES, useResource } from '../../../../../browser/frontend/src/store/resources'
import { useTab } from '../tabContext'
import { clampList, listKey, LIST_START } from '../../../ui/list'
import { confirmKey, type PendingConfirm } from '../../../ui/Confirm'
import { TextField, fieldKey } from '../../../ui/TextField'
import * as TB from '../../../input/TextBuffer'
import { useTicker } from '../../../ui/useTicker'
import { glyphs, ink, paint } from '../../../theme/theme'
import { truncate, wrap } from '../../../text/width'
import { halfBlockLines, pngFromDataUrl, qrFootprint, qrMatrixFromDataUrl } from '../connectQr'
import { openExternal, writeTempFile } from '../connectOpen'
import { editorName, editText } from '../connectEditor'
import {
  FilterLine,
  filterKey,
  FormView,
  formInit,
  formKey,
  formSet,
  formTyping,
  formValues,
  newRequestId,
  NoticeLine,
  Row,
  str,
  useConnectKeys,
  useHints,
  useInbound,
  useNotice,
  useSpinner,
  useSuspend,
  useTextFocus,
  type FormField,
  type FormState,
  ConfirmBlock,
} from '../connectKit'

/** One account of a multi-account integration (integration_info.accounts). */
interface ManagedAccount {
  identity: string
  alias: string | null
  isPrimary: boolean
  listen: boolean
  sessionState?: string
}

interface AccountChanges {
  disconnect: string[]
  primary: string | null
  aliases: Record<string, string | null>
  listen: Record<string, boolean>
}

type ConnectAction = 'token' | 'oauth' | 'interactive'

type WhatsAppStatus = 'loading' | 'qr_ready' | 'scanned' | 'promoting' | 'timeout' | 'error'

type View =
  | { kind: 'list' }
  | { kind: 'connect'; id: string; form: FormState; index: number; busy: ConnectAction | null; startedAt: number; error: string }
  | { kind: 'whatsapp'; id: string; status: WhatsAppStatus; qr: string | null; sessionId: string | null; expiresIn: number | null; error: string }
  | { kind: 'manage'; id: string; accounts: ManagedAccount[] | null; loading: boolean; index: number; nick: TB.Buffer | null; error: string }
  | { kind: 'config'; id: string; fields: FormField[]; schema: ConfigField[]; form: FormState; baseline: Record<string, unknown>; loading: boolean; saving: boolean }

const WHATSAPP = 'whatsapp_web'
const LIVE_QR: WhatsAppStatus[] = ['qr_ready', 'scanned', 'promoting']

function connectActions(integration: Integration): ConnectAction[] {
  switch (integration.auth_type) {
    case 'token':
      return ['token']
    case 'oauth':
      return ['oauth']
    case 'both':
      return ['token', 'oauth']
    case 'token_with_interactive':
      return ['token', 'interactive']
    case 'interactive':
      return ['interactive']
    default:
      return []
  }
}

function credentialFields(integration: Integration): FormField[] {
  if (integration.auth_type === 'oauth' || integration.auth_type === 'interactive') return []
  return (integration.fields ?? []).map(f => ({ kind: 'text', key: f.key, label: f.label, placeholder: f.placeholder, masked: f.password }))
}

function configFormFields(schema: ConfigField[]): FormField[] {
  return schema.map(field => {
    if (field.type === 'checkbox') return { kind: 'toggle', key: field.key, label: field.label, hint: field.help }
    if (field.type === 'select') return { kind: 'select', key: field.key, label: field.label, options: field.options ?? [], hint: field.help }
    if (field.type === 'textarea') return { kind: 'editor', key: field.key, label: field.label, hint: field.help }
    return { kind: 'text', key: field.key, label: field.label, placeholder: field.placeholder, hint: field.help }
  })
}

function configInitial(schema: ConfigField[], values: Record<string, unknown>): Record<string, string | boolean> {
  const out: Record<string, string | boolean> = {}
  for (const field of schema) {
    const value = values[field.key]
    if (field.type === 'checkbox') out[field.key] = Boolean(value)
    else if (Array.isArray(value)) out[field.key] = value.join(', ')
    else out[field.key] = value === undefined || value === null ? '' : String(value)
  }
  return out
}

function emptyChanges(): AccountChanges {
  return { disconnect: [], primary: null, aliases: {}, listen: {} }
}

function minutesSeconds(total: number): string {
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
}

export function IntegrationsTab() {
  const { t } = useTranslation('settingsConnect')
  const dispatch = useAppDispatch()
  const { active, width, height } = useTab()
  const suspend = useSuspend()
  useResource(RESOURCES.integrations)
  const integrations = useAppSelector(selectIntegrations)
  const total = useAppSelector(selectIntegrationsTotal)
  const connectedCount = useAppSelector(selectIntegrationsConnected)
  const hasLoaded = useAppSelector(selectIntegrationsHasLoaded)

  const [view, setView] = useState<View>({ kind: 'list' })
  const [list, setList] = useState(LIST_START)
  const [filter, setFilter] = useState<TB.Buffer>(TB.EMPTY)
  const [filtering, setFiltering] = useState(false)
  const [confirm, setConfirm] = useState<PendingConfirm | null>(null)
  const [addingFor, setAddingFor] = useState<string | null>(null)
  const [disconnecting, setDisconnecting] = useState<string | null>(null)
  const [notice, showNotice] = useNotice()
  const reloading = useRef(false)
  const pendingAdd = useRef(new Map<string, string>())
  const pendingApply = useRef(new Set<string>())
  const configLoad = useRef<string | null>(null)
  const configSave = useRef<string | null>(null)
  // The integration whose connect flow this tab started (results after leaving its view).
  const connecting = useRef<string | null>(null)
  // Where the config view returns to.
  const configFrom = useRef<View>({ kind: 'list' })
  const waSession = useRef<string | null>(null)

  const query = filter.text.trim().toLowerCase()
  const items = integrations
    .filter(i => !query || i.name.toLowerCase().includes(query) || i.description.toLowerCase().includes(query))
    .slice()
    .sort((a, b) => a.name.localeCompare(b.name))
  const listHeight = Math.max(3, height - 6)
  const listView = clampList(list, items.length, listHeight)
  const selected = items[listView.index]
  const current = view.kind === 'list' ? null : integrations.find(i => i.id === view.id) ?? null

  // ── WhatsApp polling and cleanup ──
  const waLive = view.kind === 'whatsapp' && LIVE_QR.includes(view.status) && !!view.sessionId
  const waSessionId = view.kind === 'whatsapp' ? view.sessionId : null
  useEffect(() => {
    if (!waLive || !waSessionId) return
    const timer = setInterval(() => send('whatsapp_check_status', { session_id: waSessionId }), 2000)
    return () => clearInterval(timer)
  }, [waLive, waSessionId])
  useEffect(() => {
    waSession.current = view.kind === 'whatsapp' && view.status !== 'timeout' && view.status !== 'error' ? view.sessionId : null
  })
  useEffect(
    () => () => {
      if (waSession.current) send('whatsapp_cancel', { session_id: waSession.current })
    },
    [],
  )

  const connectBusy = view.kind === 'connect' && view.busy !== null
  useTicker(1000, connectBusy)
  const spinner = useSpinner(
    connectBusy ||
      (view.kind === 'whatsapp' && (view.status === 'loading' || view.status === 'scanned' || view.status === 'promoting')) ||
      (view.kind === 'manage' && (view.loading || addingFor === view.id)) ||
      (view.kind === 'config' && (view.loading || view.saving)) ||
      disconnecting !== null,
  )

  const connectFields = current && view.kind === 'connect' ? credentialFields(current) : []
  const actions = current && view.kind === 'connect' ? connectActions(current) : []
  const typing =
    filtering ||
    (view.kind === 'connect' && view.busy === null && view.index < connectFields.length) ||
    (view.kind === 'manage' && view.nick !== null) ||
    (view.kind === 'config' && !view.loading && formTyping(view.form, view.fields))
  useTextFocus(active && typing)

  // ── Flows ──
  const startWhatsApp = (id: string) => {
    setView({ kind: 'whatsapp', id, status: 'loading', qr: null, sessionId: null, expiresIn: null, error: '' })
    send('whatsapp_start_qr', { force: true })
  }

  const openConnect = (integration: Integration) => {
    if (integration.auth_type === 'interactive' && integration.id === WHATSAPP) {
      startWhatsApp(integration.id)
      return
    }
    setView({ kind: 'connect', id: integration.id, form: formInit(credentialFields(integration)), index: 0, busy: null, startedAt: 0, error: '' })
  }

  const openManage = (integration: Integration) => {
    setView({ kind: 'manage', id: integration.id, accounts: null, loading: true, index: 0, nick: null, error: '' })
    send('integration_info', { id: integration.id })
  }

  const openConfig = (integration: Integration, from: View) => {
    const schema = integration.config_fields ?? []
    if (!integration.has_config || schema.length === 0) {
      showNotice(t('integrations.noSettings'))
      return
    }
    const fields = configFormFields(schema)
    configFrom.current = from
    const requestId = newRequestId()
    configLoad.current = requestId
    setView({ kind: 'config', id: integration.id, fields, schema, form: formInit(fields), baseline: {}, loading: true, saving: false })
    send('integration_get_config', { id: integration.id, requestId })
  }

  const runConnect = (integration: Integration, action: ConnectAction, form: FormState) => {
    if (view.kind !== 'connect') return
    connecting.current = integration.id
    if (action === 'token') {
      const values = formValues(form)
      const credentials: Record<string, string> = {}
      for (const field of integration.fields ?? []) credentials[field.key] = String(values[field.key] ?? '').trim()
      // The backend validates; some fields are optional (a login code on the first step).
      const first = (integration.fields ?? [])[0]
      if (first && Object.values(credentials).every(v => !v)) {
        setView({ ...view, form, error: t('integrations.fieldRequired', { field: first.label }) })
        return
      }
      send('integration_connect_token', { id: integration.id, credentials })
    } else if (action === 'oauth') {
      send('integration_connect_oauth', { id: integration.id })
    } else {
      send('integration_connect_interactive', { id: integration.id })
    }
    setView({ ...view, form, busy: action, startedAt: Date.now(), error: '' })
  }

  const applyChanges = (integrationId: string, changes: Partial<AccountChanges>) => {
    const requestId = newRequestId()
    pendingApply.current.add(requestId)
    send('integration_apply_account_changes', {
      integration_id: integrationId,
      request_id: requestId,
      changes: { ...emptyChanges(), ...changes },
    })
  }

  const addAccount = (integration: Integration) => {
    if (integration.auth_type !== 'oauth' && integration.auth_type !== 'both') {
      openConnect(integration)
      return
    }
    const requestId = newRequestId()
    pendingAdd.current.set(requestId, integration.id)
    setAddingFor(integration.id)
    send('integration_accounts_add', { integration_id: integration.id, request_id: requestId })
  }

  const disconnectAll = (integration: Integration) => {
    setConfirm({
      message: t('integrations.confirmDisconnect', { name: integration.name }),
      onConfirm: () => {
        dispatch(setDisconnected(integration.id))
        setDisconnecting(integration.id)
        send('integration_disconnect', { id: integration.id })
        if (view.kind !== 'list' && view.id === integration.id) setView({ kind: 'list' })
      },
    })
  }

  const saveConfig = (state: FormState) => {
    if (view.kind !== 'config' || view.saving || view.loading) return
    const values = formValues(state)
    const initial = configInitial(view.schema, view.baseline)
    const changed: Record<string, unknown> = {}
    const expected: Record<string, unknown> = {}
    for (const field of view.schema) {
      if (JSON.stringify(values[field.key]) === JSON.stringify(initial[field.key])) continue
      changed[field.key] = values[field.key]
      expected[field.key] = view.baseline[field.key]
    }
    if (Object.keys(changed).length === 0) {
      showNotice(t('integrations.settingsUnchanged'))
      setView(configFrom.current)
      return
    }
    const requestId = newRequestId()
    configSave.current = requestId
    setView({ ...view, form: state, saving: true })
    send('integration_update_config', { id: view.id, values: changed, expected_values: expected, requestId })
  }

  const editConfigText = async (key: string, state: FormState) => {
    if (view.kind !== 'config') return
    const value = String(formValues(state)[key] ?? '')
    const result = await editText(suspend, value, `${view.id}-${key}`.replace(/[^A-Za-z0-9_-]+/g, '_'))
    if (result.text === null) {
      showNotice(t('common.editorFailed', { editor: editorName() }), 'error')
      return
    }
    const text = result.text.replace(/\r?\n$/, '')
    setView(v => (v.kind === 'config' ? { ...v, form: formSet(state, key, text) } : v))
  }

  const openQrImage = async (qr: string) => {
    const png = pngFromDataUrl(qr)
    if (!png) {
      showNotice(t('integrations.qrOpenFailed'), 'error')
      return
    }
    const opened = await openExternal(writeTempFile('whatsapp-qr.png', png))
    showNotice(opened ? t('integrations.qrOpened') : t('integrations.qrOpenFailed'), opened ? 'info' : 'error')
  }

  // ── Replies ──
  useInbound(
    [
      'integration_list',
      'integration_connect_result',
      'integration_disconnect_result',
      'integration_info',
      'integration_accounts_add_result',
      'integration_apply_account_changes_result',
      'integration_config',
      'integration_config_updated',
      'whatsapp_qr_result',
      'whatsapp_status_result',
    ],
    (type, d) => {
      const ok = d.success === true
      const id = str(d.id)
      const message = str(d.message)
      const error = str(d.error)
      if (type === 'integration_list') {
        if (!reloading.current) return
        reloading.current = false
        showNotice(ok ? t('integrations.reloaded') : error || t('integrations.reloadFailed'), ok ? 'success' : 'error')
      } else if (type === 'integration_connect_result') {
        const mine = connecting.current === id
        if (view.kind === 'connect' && view.id === id && view.busy !== null) {
          connecting.current = null
          if (ok) {
            showNotice(message || t('integrations.connected'), 'success')
            const integration = integrations.find(i => i.id === id)
            if (integration?.has_config && (integration.config_fields?.length ?? 0) > 0) openManage(integration)
            else setView({ kind: 'list' })
          } else {
            setView({ ...view, busy: null, error: error || message || t('integrations.connectFailed') })
          }
        } else if (mine) {
          connecting.current = null
          showNotice(ok ? message || t('integrations.connected') : error || message || t('integrations.connectFailed'), ok ? 'success' : 'error')
        }
      } else if (type === 'integration_disconnect_result') {
        if (disconnecting === id) setDisconnecting(null)
        showNotice(ok ? message || t('integrations.disconnected') : error || t('integrations.disconnectFailed'), ok ? 'success' : 'error')
      } else if (type === 'integration_info') {
        if (view.kind !== 'manage' || view.id !== id) return
        if (!ok) {
          setView({ ...view, loading: false, error: error || t('integrations.infoFailed') })
          return
        }
        const accounts = Array.isArray(d.accounts) ? (d.accounts as ManagedAccount[]) : view.loading ? null : view.accounts
        setView({ ...view, loading: false, accounts, error: '' })
      } else if (type === 'integration_accounts_add_result') {
        const requestId = str(d.requestId)
        const accounts = Array.isArray(d.accounts) ? (d.accounts as ManagedAccount[]) : null
        if (d.ok === true && accounts && view.kind === 'manage' && view.id === id) setView({ ...view, accounts })
        if (!pendingAdd.current.has(requestId)) return
        pendingAdd.current.delete(requestId)
        setAddingFor(prev => (prev === id ? null : prev))
        showNotice(d.ok === true ? message || t('integrations.accountAdded') : message || t('integrations.accountAddFailed'), d.ok === true ? 'success' : 'error')
      } else if (type === 'integration_apply_account_changes_result') {
        const requestId = str(d.requestId)
        const accounts = Array.isArray(d.accounts) ? (d.accounts as ManagedAccount[]) : null
        if (d.ok === true && accounts && view.kind === 'manage' && view.id === id) setView({ ...view, accounts })
        if (!pendingApply.current.has(requestId)) return
        pendingApply.current.delete(requestId)
        showNotice(d.ok === true ? t('integrations.accountSaved') : error || t('integrations.accountSaveFailed'), d.ok === true ? 'success' : 'error')
      } else if (type === 'integration_config') {
        if (view.kind !== 'config' || view.id !== id || str(d.requestId) !== configLoad.current) return
        configLoad.current = null
        if (!ok) {
          setView(configFrom.current)
          showNotice(error || t('integrations.settingsLoadFailed'), 'error')
          return
        }
        const schema = Array.isArray(d.schema) && d.schema.length ? (d.schema as ConfigField[]) : view.schema
        const values = (d.values as Record<string, unknown>) ?? {}
        const fields = configFormFields(schema)
        setView({ ...view, schema, fields, baseline: values, form: formInit(fields, configInitial(schema, values)), loading: false })
      } else if (type === 'integration_config_updated') {
        if (view.kind !== 'config' || view.id !== id || str(d.requestId) !== configSave.current) return
        configSave.current = null
        if (ok) {
          showNotice(message || t('integrations.settingsSaved'), 'success')
          setView(configFrom.current)
        } else {
          setView({ ...view, saving: false })
          showNotice(error || message || t('integrations.settingsFailed'), 'error')
        }
      } else if (type === 'whatsapp_qr_result') {
        if (view.kind !== 'whatsapp' || view.status !== 'loading') return
        if (ok && typeof d.qr_code === 'string' && d.qr_code) {
          setView({
            ...view,
            status: 'qr_ready',
            qr: d.qr_code,
            sessionId: str(d.session_id) || null,
            expiresIn: typeof d.expires_in === 'number' ? d.expires_in : null,
            error: '',
          })
        } else {
          setView({ ...view, status: 'error', error: message || t('integrations.qrFailed') })
        }
      } else if (type === 'whatsapp_status_result') {
        if (view.kind !== 'whatsapp') return
        const status = str(d.status)
        if (d.connected === true) {
          waSession.current = null
          showNotice(message || t('integrations.whatsappConnected'), 'success')
          const integration = integrations.find(i => i.id === view.id)
          if (integration?.has_config && (integration.config_fields?.length ?? 0) > 0) openManage(integration)
          else setView({ kind: 'list' })
        } else if (status === 'qr_ready') {
          setView({
            ...view,
            status: 'qr_ready',
            qr: typeof d.qr_code === 'string' && d.qr_code ? d.qr_code : view.qr,
            expiresIn: typeof d.expires_in === 'number' ? d.expires_in : view.expiresIn,
          })
        } else if (status === 'scanned' || status === 'promoting') {
          setView({ ...view, status })
        } else if (status === 'timeout' || status === 'cancelled') {
          setView({ ...view, status: 'timeout', error: message || t('integrations.qrExpired') })
        } else if (status === 'error' || status === 'disconnected') {
          setView({ ...view, status: 'error', error: message || t('integrations.qrSessionFailed') })
        }
      }
    },
  )

  // ── Keys ──
  useConnectKeys((input, key) => {
    if (confirmKey(confirm, input, key, () => setConfirm(null))) return true

    if (view.kind === 'connect' && current) {
      const rows = connectFields.length + actions.length
      if (view.busy !== null) {
        if (key.escape) {
          if (view.busy === 'oauth' || view.busy === 'interactive') send('integration_connect_cancel', { id: current.id })
          connecting.current = view.busy === 'token' ? current.id : null
          setView(view.busy === 'token' ? { kind: 'list' } : { ...view, busy: null, error: t('integrations.cancelled') })
        }
        return true
      }
      if (key.escape) {
        setView({ kind: 'list' })
        return true
      }
      const move = (delta: number) => setView({ ...view, index: (view.index + delta + rows) % rows })
      if (key.tab) {
        move(key.shift ? -1 : 1)
        return true
      }
      if (key.downArrow) {
        move(1)
        return true
      }
      if (key.upArrow) {
        move(-1)
        return true
      }
      if (key.ctrl && input === 's' && actions.includes('token')) {
        runConnect(current, 'token', view.form)
        return true
      }
      if (view.index < connectFields.length) {
        if (key.return) {
          // The last field submits the token; other fields move on.
          if (view.index === connectFields.length - 1 && actions[0] === 'token') runConnect(current, 'token', view.form)
          else move(1)
          return true
        }
        const field = connectFields[view.index]
        const next = fieldKey(view.form.text[field.key] ?? TB.EMPTY, input, key)
        if (next) setView({ ...view, form: { ...view.form, text: { ...view.form.text, [field.key]: next } }, error: '' })
        return true
      }
      if (key.return || input === ' ') {
        const action = actions[view.index - connectFields.length]
        if (action) runConnect(current, action, view.form)
        return true
      }
      return key.leftArrow ? (setView({ kind: 'list' }), true) : false
    }

    if (view.kind === 'whatsapp') {
      if (key.escape || key.leftArrow) {
        if (view.sessionId && view.status !== 'timeout' && view.status !== 'error') send('whatsapp_cancel', { session_id: view.sessionId })
        waSession.current = null
        setView({ kind: 'list' })
        return true
      }
      if (input === 'n' && (view.status === 'timeout' || view.status === 'error')) {
        startWhatsApp(view.id)
        return true
      }
      if (input === 'o' && view.qr) {
        void openQrImage(view.qr)
        return true
      }
      return false
    }

    if (view.kind === 'manage' && current) {
      const accounts = view.accounts ?? []
      if (view.nick !== null) {
        const account = accounts[view.index]
        if (key.escape) {
          setView({ ...view, nick: null })
          return true
        }
        if (key.return) {
          if (account) {
            const alias = view.nick.text.trim()
            applyChanges(current.id, { aliases: { [account.identity]: alias || null } })
          }
          setView({ ...view, nick: null })
          return true
        }
        const next = fieldKey(view.nick, input, key)
        if (next) setView({ ...view, nick: next })
        return true
      }
      if (key.escape || key.leftArrow) {
        setView({ kind: 'list' })
        return true
      }
      if (key.upArrow || input === 'k') {
        setView({ ...view, index: Math.max(0, view.index - 1) })
        return true
      }
      if (key.downArrow || input === 'j') {
        setView({ ...view, index: Math.min(Math.max(0, accounts.length - 1), view.index + 1) })
        return true
      }
      if (input === 'a') {
        if (addingFor !== current.id) addAccount(current)
        return true
      }
      if (input === 's') {
        openConfig(current, view)
        return true
      }
      if (input === 'D') {
        disconnectAll(current)
        return true
      }
      if (input === 'r') {
        setView({ ...view, loading: true })
        send('integration_info', { id: current.id })
        return true
      }
      const account = accounts[view.index]
      if (!account) return false
      if (input === 'p') {
        if (!account.isPrimary) applyChanges(current.id, { primary: account.identity })
        return true
      }
      if (input === 'l' && current.supports_listening !== false) {
        applyChanges(current.id, { listen: { [account.identity]: !account.listen } })
        return true
      }
      if (input === 'n') {
        setView({ ...view, nick: TB.fromText(account.alias ?? '') })
        return true
      }
      if (input === 'x') {
        setConfirm({
          message: t('integrations.confirmDisconnectAccount', { account: account.alias || account.identity, name: current.name }),
          onConfirm: () => applyChanges(current.id, { disconnect: [account.identity] }),
        })
        return true
      }
      return false
    }

    if (view.kind === 'config') {
      if (key.escape) {
        configLoad.current = null
        configSave.current = null
        setView(configFrom.current)
        return true
      }
      if (view.loading || view.saving) return true
      const out = formKey(view.form, view.fields, input, key)
      if (out?.submit) saveConfig(out.state)
      else if (out?.edit) void editConfigText(out.edit, out.state)
      else if (out) setView({ ...view, form: out.state })
      return true
    }

    // List.
    if (filtering && (key.upArrow || key.downArrow)) {
      const moved = listKey(listView, '', key, items.length, listHeight)
      if (moved) setList(moved)
      return true
    }
    const filtered = filterKey(filtering, filter, input, key)
    if (filtered) {
      setFiltering(filtered.filtering)
      setFilter(filtered.buffer)
      if (filtered.changed) setList(LIST_START)
      return true
    }
    const moved = listKey(listView, input, key, items.length, listHeight)
    if (moved) {
      setList(moved)
      return true
    }
    if (input === '/') {
      setFiltering(true)
      return true
    }
    if (input === 'r') {
      reloading.current = true
      showNotice(t('integrations.reloading'))
      send('integration_list')
      return true
    }
    if (!selected) return false
    if (key.return || input === 'l' || key.rightArrow) {
      if (selected.connected) openManage(selected)
      else openConnect(selected)
      return true
    }
    if (input === 'c') {
      openConnect(selected)
      return true
    }
    if (input === 'd' && selected.connected) {
      disconnectAll(selected)
      return true
    }
    if (input === 's' && selected.connected) {
      openConfig(selected, { kind: 'list' })
      return true
    }
    return false
  })

  // ── Hints ──
  const hints =
    view.kind === 'connect'
      ? view.busy !== null
        ? [{ keys: 'Esc', label: view.busy === 'token' ? t('hint.back') : t('hint.cancel') }]
        : [
            { keys: 'Tab', label: t('hint.nextField') },
            { keys: 'Enter', label: t('integrations.hintConnect') },
            { keys: 'Esc', label: t('hint.cancel') },
          ]
      : view.kind === 'whatsapp'
        ? [
            ...(view.qr ? [{ keys: 'o', label: t('integrations.hintOpenImage') }] : []),
            ...(view.status === 'timeout' || view.status === 'error' ? [{ keys: 'n', label: t('integrations.hintNewCode') }] : []),
            { keys: 'Esc', label: t('hint.cancel') },
          ]
        : view.kind === 'manage'
          ? view.nick !== null
            ? [
                { keys: 'Enter', label: t('hint.save') },
                { keys: 'Esc', label: t('hint.cancel') },
              ]
            : [
                { keys: 'a', label: t('integrations.hintAddAccount') },
                { keys: 'p', label: t('integrations.hintDefault') },
                ...(current?.supports_listening !== false ? [{ keys: 'l', label: t('integrations.hintListen') }] : []),
                { keys: 'n', label: t('integrations.hintNickname') },
                { keys: 'x', label: t('integrations.hintDisconnectOne') },
                ...(current?.has_config ? [{ keys: 's', label: t('integrations.hintSettings') }] : []),
                { keys: 'D', label: t('integrations.hintDisconnectAll') },
                { keys: 'Esc', label: t('hint.back') },
              ]
          : view.kind === 'config'
            ? [
                { keys: 'Tab', label: t('hint.nextField') },
                { keys: 'Space', label: t('hint.toggle') },
                { keys: 'Ctrl+S', label: t('hint.save') },
                { keys: 'Esc', label: t('hint.cancel') },
              ]
            : [
                { keys: 'Enter', label: selected?.connected ? t('integrations.hintManage') : t('integrations.hintConnect') },
                { keys: 'c', label: t('integrations.hintConnectKey') },
                { keys: 'd', label: t('integrations.hintDisconnectAll') },
                { keys: 's', label: t('integrations.hintSettings') },
                { keys: 'r', label: t('hint.reload') },
                { keys: '/', label: t('hint.filter') },
              ]
  useHints(hints)

  // ── WhatsApp QR (decoded once per code) ──
  const qrMatrix = useMemo(() => (view.kind === 'whatsapp' && view.qr ? qrMatrixFromDataUrl(view.qr) : null), [view.kind === 'whatsapp' ? view.qr : null])

  const g = glyphs()
  const footer = confirm ? <ConfirmBlock pending={confirm} width={width} hint={t('common.confirmHint')} /> : <NoticeLine notice={notice} width={width} />

  if (view.kind === 'connect' && current) {
    const elapsed = view.busy ? Math.max(0, Math.round((Date.now() - view.startedAt) / 1000)) : 0
    const help = current.connect_help ?? []
    const actionLabel = (action: ConnectAction): string =>
      action === 'token'
        ? current.auth_type === 'token_with_interactive'
          ? t('integrations.actionBot')
          : t('integrations.actionToken')
        : action === 'oauth'
          ? t('integrations.actionOAuth', { name: current.name })
          : current.auth_type === 'token_with_interactive'
            ? t('integrations.actionQrUser')
            : t('integrations.actionInteractive', { name: current.name })
    const used = 3 + connectFields.length + actions.length + 2
    const helpRoom = Math.max(0, height - used - 2)
    const helpLines = help.flatMap((step, i) => wrap(`${i + 1}. ${step}`, width - 3)).slice(0, helpRoom)
    return (
      <Box flexDirection="column">
        <Text bold color={ink.brand}>{truncate(t('integrations.connectTitle', { name: current.name }), width - 1)}</Text>
        <Text color={ink.muted}>{truncate(current.description, width - 1)}</Text>
        <Text> </Text>
        {connectFields.length > 0 ? (
          <FormView fields={connectFields} state={{ ...view.form, index: view.index }} width={width} focused={active && view.busy === null && view.index < connectFields.length} />
        ) : null}
        {actions.map((action, i) => {
          const on = active && view.busy === null && view.index === connectFields.length + i
          return (
            <Text key={action} color={on ? ink.focus : undefined} bold={on}>
              {on ? `${g.pointer} ` : '  '}
              {`[ ${actionLabel(action)} ]`}
            </Text>
          )
        })}
        <Text> </Text>
        {view.busy === 'oauth' ? (
          <Text color={ink.info}>{truncate(`${spinner} ${t('integrations.waitingOAuth', { name: current.name, elapsed: minutesSeconds(elapsed) })}`, width - 1)}</Text>
        ) : view.busy ? (
          <Text color={ink.muted}>{truncate(`${spinner} ${t('integrations.connecting', { elapsed: minutesSeconds(elapsed) })}`, width - 1)}</Text>
        ) : null}
        {view.error ? wrap(view.error, width - 1).slice(0, 3).map((line, i) => <Text key={i} color={ink.error}>{line}</Text>) : null}
        {helpLines.length > 0 ? (
          <Box flexDirection="column" marginTop={1}>
            <Text color={ink.muted}>{t('integrations.howTo', { name: current.name })}</Text>
            {helpLines.map((line, i) => (
              <Text key={i} color={ink.muted}>{` ${line}`}</Text>
            ))}
          </Box>
        ) : null}
      </Box>
    )
  }

  if (view.kind === 'whatsapp') {
    const name = current?.name ?? 'WhatsApp'
    const color = paint.level > 0 && !!ink.brand
    const room = { rows: height - 3, columns: width - 1 }
    let quiet = 2
    let size = qrMatrix ? qrFootprint(qrMatrix.length, quiet) : null
    if (qrMatrix && size && (size.rows > room.rows || size.columns > room.columns)) {
      quiet = 1
      size = qrFootprint(qrMatrix.length, quiet)
    }
    const fits = !!size && size.rows <= room.rows && size.columns <= room.columns
    const lines = qrMatrix && fits ? halfBlockLines(qrMatrix, quiet, !color) : []
    const status =
      view.status === 'loading'
        ? `${spinner} ${t('integrations.qrStarting')}`
        : view.status === 'scanned'
          ? `${spinner} ${t('integrations.qrScanned')}`
          : view.status === 'promoting'
            ? `${spinner} ${t('integrations.qrPromoting')}`
            : view.status === 'qr_ready'
              ? view.expiresIn !== null && view.expiresIn > 0
                ? t('integrations.qrRefreshIn', { time: minutesSeconds(view.expiresIn) })
                : t('integrations.qrRefreshing')
              : ''
    return (
      <Box flexDirection="column">
        <Text bold color={ink.brand}>{truncate(`${t('integrations.connectTitle', { name })}  `, width - 1)}<Text color={ink.muted} bold={false}>{status}</Text></Text>
        {view.status === 'qr_ready' ? <Text color={ink.muted}>{truncate(t('integrations.qrScanHelp'), width - 1)}</Text> : null}
        {view.status === 'qr_ready' && lines.length > 0
          ? lines.map((line, i) =>
              color ? (
                <Text key={i} color="#000000" backgroundColor="#FFFFFF">{line}</Text>
              ) : (
                <Text key={i}>{line}</Text>
              ),
            )
          : null}
        {view.status === 'qr_ready' && qrMatrix && !fits && size
          ? // The terminal around this tab: the frame (5 rows) and the tab list (21 columns).
            wrap(t('integrations.qrTooSmall', { rows: size.rows + 3 + 5, columns: size.columns + 21 }), width - 1).map((line, i) => (
              <Text key={i} color={ink.warn}>{line}</Text>
            ))
          : null}
        {view.status === 'qr_ready' && !qrMatrix ? (
          <Text color={ink.warn}>{truncate(t('integrations.qrUnreadable'), width - 1)}</Text>
        ) : null}
        {view.status === 'timeout' || view.status === 'error'
          ? wrap(view.error || t('integrations.qrFailed'), width - 1).map((line, i) => (
              <Text key={i} color={view.status === 'error' ? ink.error : ink.warn}>{line}</Text>
            ))
          : null}
        <NoticeLine notice={notice} width={width} />
      </Box>
    )
  }

  if (view.kind === 'manage' && current) {
    const accounts = view.accounts
    const legacy = !view.loading && accounts === null
    const stateLabel = (account: ManagedAccount): string => {
      switch (account.sessionState) {
        case 'needs_relink':
          return t('integrations.stateSignedOut')
        case 'reconnecting':
          return t('integrations.stateReconnecting')
        case 'failed':
          return t('integrations.stateProblem')
        case 'launching':
          return t('integrations.stateConnecting')
        default:
          return ''
      }
    }
    const rows = Math.max(3, height - 7)
    const top = Math.max(0, Math.min(view.index - rows + 1, (accounts?.length ?? 0) - rows))
    const selectedAccount = accounts?.[view.index]
    return (
      <Box flexDirection="column">
        <Text bold color={ink.brand}>{truncate(t('integrations.manageTitle', { name: current.name }), width - 1)}</Text>
        <Text color={ink.muted}>
          {truncate(view.loading ? `${spinner} ${t('common.loading')}` : t('integrations.accountCount', { count: accounts?.length ?? current.accounts.length }), width - 1)}
        </Text>
        {legacy
          ? (current.accounts as { display?: string; id?: string; identity?: string }[]).map((account, i) => (
              <Row key={i} selected={false} mark={g.done} markColor={ink.success} label={account.display || account.identity || account.id || ''} width={width} />
            ))
          : null}
        {(accounts ?? []).slice(Math.max(0, top), Math.max(0, top) + rows).map((account, i) => {
          const index = Math.max(0, top) + i
          const problem = account.sessionState === 'needs_relink' || account.sessionState === 'failed'
          const transient = account.sessionState === 'reconnecting' || account.sessionState === 'launching'
          const meta = [
            account.isPrimary ? t('integrations.default') : '',
            stateLabel(account),
            current.supports_listening !== false && account.listen ? t('integrations.listening') : '',
          ].filter(Boolean)
          const editing = view.nick !== null && index === view.index
          return editing ? (
            <Box key={account.identity}>
              <Text color={ink.focus}>{`${g.pointer} `}</Text>
              <TextField label={t('integrations.nickname')} buffer={view.nick!} focused width={width - 3} placeholder={account.identity} />
            </Box>
          ) : (
            <Row
              key={account.identity}
              selected={active && index === view.index}
              mark={problem ? g.failed : transient ? g.running : g.done}
              markColor={problem ? ink.error : transient ? ink.warn : ink.success}
              label={account.alias || account.identity}
              aside={meta.join(' · ')}
              width={width}
            />
          )
        })}
        {accounts && accounts.length === 0 && !view.loading ? <Text color={ink.muted}>{t('integrations.noAccounts')}</Text> : null}
        {selectedAccount && selectedAccount.alias ? (
          <Text color={ink.muted}>{truncate(`  ${selectedAccount.identity}`, width - 1)}</Text>
        ) : null}
        {selectedAccount?.sessionState === 'needs_relink' ? (
          <Text color={ink.warn}>{truncate(t('integrations.relinkHint'), width - 1)}</Text>
        ) : null}
        {addingFor === current.id ? <Text color={ink.info}>{truncate(`${spinner} ${t('integrations.waitingAddAccount')}`, width - 1)}</Text> : null}
        {view.error ? <Text color={ink.error}>{truncate(view.error, width - 1)}</Text> : null}
        {footer}
      </Box>
    )
  }

  if (view.kind === 'config' && current) {
    return (
      <Box flexDirection="column">
        <Text bold color={ink.brand}>{truncate(t('integrations.settingsTitle', { name: current.name }), width - 1)}</Text>
        <Text color={ink.muted}>{truncate(t('integrations.settingsScope', { name: current.name }), width - 1)}</Text>
        <Text> </Text>
        {view.loading ? (
          <Text color={ink.muted}>{`${spinner} ${t('common.loading')}`}</Text>
        ) : (
          <FormView fields={view.fields} state={view.form} width={width} focused={active && !view.saving} />
        )}
        {view.saving ? <Text color={ink.muted}>{`${spinner} ${t('common.saving')}`}</Text> : null}
        <NoticeLine notice={notice} width={width} />
      </Box>
    )
  }

  // List (also the fallback while an integration vanished from the list).
  const authLabel = (integration: Integration): string =>
    integration.auth_type === 'oauth'
      ? t('integrations.authOAuth')
      : integration.auth_type === 'interactive'
        ? integration.id === WHATSAPP
          ? t('integrations.authQr')
          : t('integrations.authInteractive')
        : t('integrations.authToken')
  const description = selected ? wrap(selected.description, width - 2).slice(0, 2) : []
  return (
    <Box flexDirection="column">
      <FilterLine
        buffer={filter}
        typing={filtering}
        width={width}
        placeholder={t('integrations.filterPlaceholder')}
        idle={hasLoaded ? t('integrations.summary', { connected: connectedCount, total }) : t('common.loading')}
      />
      {hasLoaded && items.length === 0 ? (
        <Text color={ink.muted}>{truncate(query ? t('integrations.noMatch') : t('integrations.none'), width - 1)}</Text>
      ) : null}
      {items.slice(listView.top, listView.top + listHeight).map((integration, i) => {
        const index = listView.top + i
        const count = integration.accounts?.length ?? 0
        return (
          <Row
            key={integration.id}
            selected={active && index === listView.index}
            mark={integration.connected ? g.unread : g.idle}
            markColor={integration.connected ? ink.success : ink.muted}
            label={integration.name}
            dim={!integration.connected}
            aside={
              integration.connected
                ? count > 1
                  ? t('integrations.accountCount', { count })
                  : t('integrations.statusConnected')
                : authLabel(integration)
            }
            asideColor={integration.connected ? ink.success : undefined}
            width={width}
          />
        )
      })}
      {selected ? (
        <Box flexDirection="column" marginTop={1}>
          {description.map((line, i) => (
            <Text key={i} color={ink.muted}>{line}</Text>
          ))}
        </Box>
      ) : null}
      {disconnecting ? (
        <Text color={ink.muted}>{truncate(`${spinner} ${t('integrations.disconnecting', { name: integrations.find(i => i.id === disconnecting)?.name ?? disconnecting })}`, width - 1)}</Text>
      ) : null}
      {footer}
    </Box>
  )
}
