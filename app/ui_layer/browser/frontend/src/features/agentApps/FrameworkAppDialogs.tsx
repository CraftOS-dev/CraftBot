import { useRef, useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button } from '../../components/ui/Button'
import { Modal, ModalBody, ModalFooter } from '../../components/ui/Modal'
import { useToast } from '../../contexts/ToastContext'
import { useAppDispatch, useAppSelector } from '../../store/hooks'
import { frameworkAppKey, receiveFrameworkTheme } from '../../store/slices/agentAppSlice'
import type { FrameworkRegistryApp } from '../../types'
import { frameworkRequest, type FrameworkAttachment } from './frameworkApi'
import { AgentAppThemeModal } from '../../pages/AgentApp/AgentAppThemeModal'
import { DEFAULT_CUSTOM_COLORS, type AgentAppThemeId, type AgentAppCustomColors } from '../../pages/AgentApp/themeCatalog'
import { frameworkFrameId, removeIframe } from './frameHost'
import confirmStyles from '../../components/ui/ConfirmModal.module.css'

interface RemovalResult {
  status: string
  stderr?: string
  data?: { ok?: boolean; reason?: string; removed?: { id: string; path: string }; forgot?: { id: string; path: string }; dataBackup?: string | null; backups?: string | null }
}

export function FrameworkAppTheme({ app, onClose }: { app: FrameworkRegistryApp; onClose: () => void }) {
  const dispatch = useAppDispatch()
  const current = useAppSelector(state => state.agentApp.framework.apps.find(item => item.path === app.path && item.id === app.id))
  const connected = useAppSelector(state => state.connection.connected)
  const pending = useRef(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const select = async (themeId: AgentAppThemeId, customColors?: AgentAppCustomColors) => {
    if (!connected || !current || pending.current) return
    pending.current = true; setBusy(true); setError('')
    try {
      const result = await frameworkRequest<FrameworkAttachment>({
        operation: 'preference', path: app.path, appId: app.id,
        uiTheme: { themeId, ...(themeId === 'custom' ? { customColors } : {}) },
      })
      dispatch(receiveFrameworkTheme({ path: app.path, id: app.id, uiTheme: result.uiTheme }))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally { pending.current = false; setBusy(false) }
  }
  return <AgentAppThemeModal isOpen activeTheme={current?.uiTheme?.themeId || 'craftbot'}
    customColors={current?.uiTheme?.customColors || DEFAULT_CUSTOM_COLORS}
    disabled={!connected || !current || current.status === 'missing' || busy} error={error}
    onSelect={(id, colors) => { void select(id, colors) }} onClose={onClose} />
}

export function FrameworkAppDelete({ app, onClose, onDeleted }: {
  app: FrameworkRegistryApp
  onClose: () => void
  onDeleted: () => void
}) {
  const { t } = useTranslation(['agentapp', 'common'])
  const { showToast } = useToast()
  const connected = useAppSelector(state => state.connection.connected)
  const fresh = useAppSelector(state => state.agentApp.framework.status === 'success')
  const current = useAppSelector(state => state.agentApp.framework.apps.find(item => item.path === app.path && item.id === app.id))
  const lifecycleBusy = useAppSelector(state => state.agentApp.frameworkLifecycle[frameworkAppKey(app.path, app.id)]?.status === 'running')
  const pending = useRef(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [keepFiles, setKeepFiles] = useState(false)
  const missing = app.status === 'missing'
  const allowed = connected && fresh && !!current && (current.status === 'missing') === missing && !lifecycleBusy
  const remove = async () => {
    if (!allowed || pending.current) return
    pending.current = true
    setBusy(true)
    setError('')
    try {
      const result = await frameworkRequest<RemovalResult>({
        operation: app.connection ? 'disconnect' : 'manage', path: app.path, appId: app.id, verb: missing || keepFiles ? 'forget' : 'remove', confirm: app.id, stopFirst: !missing,
        ...(keepFiles ? { keepFiles: true } : {}),
      }, 1_250_000)
      if (!keepFiles && !missing && result.data?.reason === 'no-canon') {
        setKeepFiles(true)
        return
      }
      const removed = missing || keepFiles ? result.data?.forgot : result.data?.removed
      if (result.status !== 'success' || result.data?.ok !== true
        || removed?.id !== app.id || removed.path !== app.path) {
        throw new Error(result.stderr?.trim() || t('registry.deleteFailed'))
      }
      removeIframe(frameworkFrameId(app.path, app.id))
      showToast('success', app.connection ? `Disconnected ${app.name}` : t(keepFiles ? 'registry.unregistered' : 'registry.deleted', { name: app.name }))
      onDeleted()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      pending.current = false
      setBusy(false)
    }
  }
  return <div onMouseDown={event => event.stopPropagation()}>
    <Modal isOpen onClose={onClose} closeDisabled={busy} title={app.connection ? 'Disconnect app' : t('page.deleteModalTitle')} size="sm">
      <ModalBody className={confirmStyles.body}>
        <div className={confirmStyles.warningIcon}><AlertTriangle size={24} /></div>
        <p className={confirmStyles.message}>{app.connection ? `Disconnect ${app.name} from CraftBot? The app and its data will stay on its host.` : keepFiles ? t('registry.keepFilesMessage', { name: app.name }) : missing ? t('registry.forgetMessage', { name: app.name }) : t('registry.deleteMessage', { name: app.name })}</p>
        {!connected && <p role="status">{t('registry.disconnected')}</p>}
        {error && <p role="alert" className={confirmStyles.message}>{error}</p>}
      </ModalBody>
      <ModalFooter>
        <Button variant="secondary" disabled={busy} onClick={onClose}>{t('common:actions.cancel')}</Button>
        <Button variant="danger" loading={busy} disabled={!allowed || busy} onClick={() => void remove()}>
          {app.connection ? (busy ? 'Disconnecting...' : 'Disconnect') : t(busy ? 'registry.deleting' : keepFiles ? 'registry.removeFromList' : 'common:actions.delete')}
        </Button>
      </ModalFooter>
    </Modal>
  </div>
}
