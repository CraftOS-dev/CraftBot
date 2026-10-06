import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '../../components/ui'
import { useSettingsWebSocket } from './useSettingsWebSocket'
import type { ManagedAccount } from './types'
import styles from './SettingsPage.module.css'

const PLUGIN_URL = 'https://www.figma.com/community/plugin/1485687494525374295/talk-to-figma-mcp-plugin'
type CanvasState = { started?: boolean; connected?: boolean; channel?: string; page_id?: string; page_name?: string }
type Reply = CanvasState & { request_id: string; account: string; success: boolean; error?: string }

export function FigmaCanvasSettings({ accounts }: { accounts: ManagedAccount[] }) {
  const { t } = useTranslation()
  const { send, onMessage, isConnected } = useSettingsWebSocket()
  const [account, setAccount] = useState(() => accounts.find(a => a.isPrimary)?.identity ?? accounts[0]?.identity ?? '')
  const [channel, setChannel] = useState('')
  const [state, setState] = useState<CanvasState>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const pending = useRef<{ id: string; action: string; timer: ReturnType<typeof setTimeout> } | null>(null)

  const request = useCallback((action: 'start' | 'connect' | 'status' | 'stop') => {
    if (!account || !isConnected || pending.current) return
    const id = crypto.randomUUID()
    setBusy(true)
    if (action !== 'status') setError('')
    const timer = setTimeout(() => {
      pending.current = null
      setBusy(false)
      setError(t('settings:integrations.figma.canvasTimeout', { defaultValue: 'Connection check timed out. Refresh the status before trying again.' }))
    }, 45000)
    pending.current = { id, action, timer }
    send('figma_canvas_control', { action, account, channel: channel.trim(), request_id: id })
  }, [account, channel, isConnected, send, t])

  useEffect(() => onMessage('figma_canvas_result', (data: unknown) => {
    const reply = data as Reply
    if (reply.account !== account || reply.request_id !== pending.current?.id) return
    const action = pending.current.action
    clearTimeout(pending.current.timer)
    pending.current = null
    setBusy(false)
    if (!reply.success) {
      setError(reply.error ?? 'Canvas setup failed.')
      return
    }
    if (action !== 'status') setError('')
    setState(previous => ({ ...reply, page_name: reply.page_name ?? (reply.channel === previous.channel ? previous.page_name : undefined) }))
  }), [account, onMessage])

  useEffect(() => {
    setState({})
    setError('')
    setChannel('')
    if (pending.current) clearTimeout(pending.current.timer)
    pending.current = null
    setBusy(false)
    // Request current runtime state without starting a server automatically.
    request('status')
    return () => {
      if (pending.current) clearTimeout(pending.current.timer)
      pending.current = null
    }
    // Changing input text must not reset the connection.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [account, isConnected])

  useEffect(() => {
    if (!state.started) return
    const timer = setInterval(() => request('status'), 5000)
    return () => clearInterval(timer)
  }, [request, state.started])

  useEffect(() => {
    if (!accounts.some(a => a.identity === account)) {
      setAccount(accounts.find(a => a.isPrimary)?.identity ?? accounts[0]?.identity ?? '')
    }
  }, [account, accounts])

  if (!accounts.length) return null
  return (
    <section className={styles.mSettings} aria-label={t('settings:integrations.figma.canvasTitle', { defaultValue: 'Design in Figma' })}>
      <div>
        <h4 className={styles.mSettingsHeading}>{t('settings:integrations.figma.canvasTitle', { defaultValue: 'Design in Figma' })}</h4>
        <p className={styles.mSettingsScope}>{t('settings:integrations.figma.canvasIntro', { defaultValue: 'Use Talk to Figma in your browser. CraftBot runs the connection for you—no Desktop app or extra server to install.' })}</p>
      </div>
      {accounts.length > 1 && <div className={styles.formGroup}>
        <label htmlFor="figma-canvas-account">{t('settings:integrations.figma.canvasAccount', { defaultValue: 'CraftBot account' })}</label>
        <select id="figma-canvas-account" className={styles.input} value={account} disabled={busy} onChange={event => setAccount(event.target.value)}>
          {accounts.map(item => <option key={item.identity} value={item.identity}>{item.alias || item.identity}</option>)}
        </select>
      </div>}
      <ol style={{ paddingLeft: 20, margin: 0, lineHeight: 1.7 }}>
        <li>{t('settings:integrations.figma.canvasStepStart', { defaultValue: 'Start the connection below.' })}</li>
        <li><a href={PLUGIN_URL} target="_blank" rel="noopener noreferrer">{t('settings:integrations.figma.canvasPluginLink', { defaultValue: 'Open Talk to Figma MCP Plugin' })}</a>{' '}{t('settings:integrations.figma.canvasStepPlugin', { defaultValue: 'in your target Figma design, then click Connect on port 3055.' })}</li>
        <li>{t('settings:integrations.figma.canvasStepChannel', { defaultValue: 'Paste the channel shown by the plugin and connect it to CraftBot.' })}</li>
      </ol>
      <p role="status" className={styles.hint}>{state.connected
        ? t('settings:integrations.figma.canvasConnected', { defaultValue: 'Connected to {{page}} · channel {{channel}}', page: state.page_name || state.page_id, channel: state.channel })
        : state.started
          ? t('settings:integrations.figma.canvasWaiting', { defaultValue: 'Connection running · waiting for a plugin channel' })
          : t('settings:integrations.figma.canvasStopped', { defaultValue: 'Canvas connection stopped' })}</p>
      {!state.started && <Button variant="primary" disabled={busy || !isConnected} onClick={() => request('start')}>
        {t('settings:integrations.figma.canvasStart', { defaultValue: 'Start canvas connection' })}
      </Button>}
      {state.started && <>
        <div className={styles.formGroup}>
          <label htmlFor="figma-canvas-channel">{t('settings:integrations.figma.canvasChannel', { defaultValue: 'Plugin channel' })}</label>
          <input id="figma-canvas-channel" className={styles.input} value={channel} maxLength={128} autoComplete="off" placeholder="e.g. ab12cd34" onChange={event => { setChannel(event.target.value); setError('') }} />
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          <Button variant="primary" disabled={busy || !isConnected || !channel.trim()} onClick={() => request('connect')}>
            {t('settings:integrations.figma.canvasConnect', { defaultValue: 'Connect channel' })}
          </Button>
          <Button variant="secondary" disabled={busy || !isConnected} onClick={() => request('stop')}>
            {t('settings:integrations.figma.canvasStop', { defaultValue: 'Stop connection' })}
          </Button>
        </div>
      </>}
      <Button variant="ghost" size="sm" disabled={busy || !isConnected} onClick={() => request('status')}>
        {t('settings:integrations.figma.canvasRefresh', { defaultValue: 'Refresh status' })}
      </Button>
      {error && <p role="alert" className={styles.formError}>{error}</p>}
      <p className={styles.hint}>{t('settings:integrations.figma.canvasTarget', { defaultValue: 'Edits use the plugin’s open file and page. Keep it open while CraftBot works; reconnect after changing pages or restarting. Your default REST file does not choose the canvas.' })}</p>
      <p className={styles.hint}>{t('settings:integrations.figma.canvasPrivacy', { defaultValue: 'This community plugin can read and edit the open design and declares usage analytics. CraftBot keeps your Figma token local. Both CraftBot and Figma must run on this computer.' })}</p>
    </section>
  )
}
