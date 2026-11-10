import { useEffect, useRef, useState } from 'react'
import { Check, Copy, MessageSquareText } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button } from '../../components/ui/Button'
import { useAppSelector } from '../../store/hooks'
import type { FrameworkRegistryApp } from '../../types'
import { frameworkRequest, type FrameworkAttachment, type FrameworkHostSnapshot } from './frameworkApi'
import { AppSettingsSection, AppSettingsToggle, appSettingHintStyle, appSettingRowStyle } from '../../pages/Settings/AgentAppSettingsCard'
import { FrameworkMaintenanceControls, type MaintenanceInfo } from './FrameworkMaintenanceControls'
import styles from '../../pages/Settings/SettingsPage.module.css'

interface AppDetails {
  capabilities: { declared: Record<string, { description?: string }> }
}
interface CommandResult { status: string; stderr?: string; data?: { ok?: boolean; file?: string; path?: string; url?: string; backup?: string } }

export function useFrameworkAppSettings(path: string, appId: string, expanded: boolean, status: FrameworkRegistryApp['status']) {
  const connected = useAppSelector(s => s.connection.connected)
  const [attachment, setAttachment] = useState<FrameworkAttachment>()
  const [loaded, setLoaded] = useState(false)
  const [maintenance, setMaintenance] = useState<MaintenanceInfo | null>(null)
  const [links, setLinks] = useState<MaintenanceInfo['links']>({})
  const [maintenanceError, setMaintenanceError] = useState('')
  const [busy, setBusy] = useState(false)
  const pending = useRef(false)
  const actionVersion = useRef(0)
  const [output, setOutput] = useState<CommandResult | null>(null)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [details, setDetails] = useState<AppDetails | null>(null)
  useEffect(() => {
    if (!connected || !expanded) return
    let active = true
    setLoaded(false)
    void frameworkRequest<FrameworkHostSnapshot>({ operation: 'snapshot' }).then(value => {
      if (active) { setAttachment(value.attachments.find(a => a.path === path && a.appId === appId)); setLoaded(true) }
    }).catch(e => { if (active) setError(String(e)) })
    void frameworkRequest<AppDetails>({ operation: 'details', path, appId }).then(value => { if (active) setDetails(value) }).catch(e => { if (active) setError(String(e)) })
    const refresh = () => frameworkRequest<MaintenanceInfo>({ operation: 'maintenance', path, appId }).then(value => { if (active) { setMaintenance(value); setMaintenanceError('') } }).catch(e => { if (active) setMaintenanceError(String(e)) })
    void refresh()
    const timer = window.setInterval(() => { if (!pending.current) void refresh() }, 30_000)
    return () => { active = false; window.clearInterval(timer) }
  }, [path, appId, connected, expanded])
  useEffect(() => {
    if (!connected || !expanded) return
    let active = true
    const refresh = () => {
      const version = actionVersion.current
      return frameworkRequest<MaintenanceInfo['links']>({ operation: 'sharing', path, appId, action: 'info' })
        .then(value => { if (active && version === actionVersion.current && !pending.current) setLinks(value) })
        .catch(e => { if (active && version === actionVersion.current && !pending.current) setError(String(e)) })
    }
    void refresh()
    const timer = window.setInterval(() => { if (!pending.current) void refresh() }, 30_000)
    return () => { active = false; window.clearInterval(timer) }
  }, [path, appId, connected, expanded, status])
  const act = async (fn: () => Promise<unknown>) => {
    if (!connected || pending.current) return
    pending.current = true; actionVersion.current++; setBusy(true); setError(''); setNotice('')
    try { await fn() } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { pending.current = false; setBusy(false) }
  }
  const manage = (verb: string, backupId?: string) => act(async () => {
    const result = await frameworkRequest<CommandResult>({ operation: 'manage', path, appId, verb, ...(backupId ? { backupId } : {}) }, 1_250_000)
    setOutput(result)
    if (result.status !== 'success' || result.data?.ok === false) throw new Error(result.stderr || 'The app could not complete this action.')
    if (verb === 'backup' || verb === 'restore') setMaintenance(await frameworkRequest({ operation: 'maintenance', path, appId }))
    setNotice(({ backup: 'Backup created', export: 'Package exported', restore: 'Backup restored' } as Record<string, string>)[verb] || 'Completed')
  })
  const preference = (setting: string, value: boolean | string | number) => act(async () => setAttachment(await frameworkRequest({ operation: 'preference', path, appId, [setting]: value })))
  const autoStart = (value: boolean) => preference('autoStart', value)
  const deleteBackup = (backupId: string) => act(async () => {
    await frameworkRequest({ operation: 'backup_delete', path, appId, backupId })
    setMaintenance(await frameworkRequest({ operation: 'maintenance', path, appId }))
  })
  const share = (action: 'open' | 'close', channel: 'lan' | 'tunnel') => act(async () => {
    const links = await frameworkRequest<MaintenanceInfo['links']>({ operation: 'sharing', path, appId, action, channel }, 180_000)
    setLinks(links)
  })
  const consent = (allow: boolean, ownerTools: boolean) => act(async () => setAttachment(await frameworkRequest({ operation: 'consent', path, appId, allow, ownerTools })))
  const refreshMaintenance = () => act(async () => { setMaintenance(await frameworkRequest({ operation: 'maintenance', path, appId })); setMaintenanceError('') })
  return { attachment, details, maintenance, links, maintenanceError, refreshMaintenance, preference, deleteBackup, share, loaded, busy, connected, output, notice, error, manage, autoStart, consent }
}

export function FrameworkAppActions({ app, settings }: { app: FrameworkRegistryApp; settings: ReturnType<typeof useFrameworkAppSettings> }) {
  const { t } = useTranslation(['settings', 'agentapp'])
  const { attachment, details, loaded, busy, connected, output, notice, error } = settings
  const [requestsOpen, setRequestsOpen] = useState(false)
  const [copied, setCopied] = useState(false)
  const disabled = !connected || busy
  const declaredRequests = Object.entries(details?.capabilities.declared || {})
  const resultValue = notice && (output?.data?.file || output?.data?.url || output?.data?.path)
  return <>
    <AppSettingsSection title={t('settings:agentApp.preferences')}>
      <AppSettingsToggle label={t('settings:agentApp.autoLaunchLabel')} description={t('settings:agentApp.autoLaunchDesc')}
        checked={attachment?.autoStart === true} disabled={disabled || !loaded} onChange={value => void settings.autoStart(value)} />
      <AppSettingsToggle label={t('settings:agentApp.logCleanupLabel')} description={t('settings:agentApp.logCleanupDesc')}
        checked={attachment?.logCleanup === true} disabled={disabled || !loaded} divider onChange={value => void settings.preference('logCleanup', value)} />
      {attachment?.startError && <p role="alert" style={{ ...appSettingHintStyle, color: 'var(--color-error)' }}>{attachment.startError}</p>}
    </AppSettingsSection>
    <AppSettingsSection title={t('agentapp:triggerConsent.settingsTitle')}>
      <AppSettingsToggle label={t('agentapp:triggerConsent.settingsLabel')}
        checked={attachment?.tasksAllowed === true} disabled={disabled || !loaded || !details}
        onChange={allow => void settings.consent(allow, attachment?.ownerToolsAllowed === true)}>
      <button type="button" className={styles.requestsLink} aria-expanded={requestsOpen} onClick={() => setRequestsOpen(value => !value)}>
        {requestsOpen ? t('agentapp:triggerConsent.hideRequests') : declaredRequests.length ? t('agentapp:triggerConsent.viewRequests', { count: declaredRequests.length }) : t('agentapp:triggerConsent.aboutRequests')}
      </button>
      </AppSettingsToggle>
      {requestsOpen && !declaredRequests.length && <p style={appSettingHintStyle}>{t('agentapp:triggerConsent.runtimeRequests')}</p>}
      {requestsOpen && declaredRequests.length > 0 && <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>{declaredRequests.map(([name, capability]) =>
        <li key={name} style={{ ...appSettingRowStyle, borderTop: '1px solid var(--border-primary)', justifyContent: 'flex-start' }}><MessageSquareText size={14} /><span style={{ fontSize: 'var(--text-sm)' }}>{capability?.description || name}</span></li>)}</ul>}
      <AppSettingsToggle label="Owner access to local tools" description="Allow the app owner to read and write local files and run commands with CraftBot's permissions."
        checked={attachment?.ownerToolsAllowed === true} disabled={disabled || !loaded || !details || !attachment?.tasksAllowed} divider
        onChange={allow => void settings.consent(true, allow)} />
      {attachment?.bridgeError && <p role="alert" style={{ ...appSettingHintStyle, color: 'var(--color-error)' }}>{attachment.bridgeError}</p>}
    </AppSettingsSection>
    <FrameworkMaintenanceControls app={app} settings={settings} />
    {(error || notice) && <div style={{ padding: 'var(--space-3)', borderTop: '1px solid var(--border-primary)' }}>
      <p role={error ? 'alert' : 'status'} style={{ ...appSettingHintStyle, color: error ? 'var(--color-error)' : 'var(--color-success)' }}>{error || notice}</p>
      {resultValue && <div style={{ ...appSettingRowStyle, gap: 'var(--space-2)' }}>
        <span style={{ ...appSettingHintStyle, overflowWrap: 'anywhere', minWidth: 0 }}>{resultValue}</span>
        <Button size="sm" variant="ghost" title="Copy result" icon={copied ? <Check size={12} /> : <Copy size={12} />} onClick={() => void navigator.clipboard.writeText(resultValue).then(() => setCopied(true))} />
      </div>}
    </div>}
  </>
}
