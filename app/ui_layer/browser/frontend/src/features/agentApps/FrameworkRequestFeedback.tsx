import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { AlertCircle, MessageSquareText } from 'lucide-react'
import { Button } from '../../components/ui/Button'
import { Modal, ModalBody, ModalFooter } from '../../components/ui/Modal'
import { useToast } from '../../contexts/ToastContext'
import { frameworkRequest } from './frameworkApi'
import styles from '../../components/ui/AgentAppTriggerConsentModal.module.css'

interface RequestStatus {
  permissionRequired: boolean; needsReview: boolean; revision?: string; reviewId?: string
  requests?: string[]; error?: string; retryNeeded?: boolean
}

export function useFrameworkRequests(path: string, appId: string, enabled: boolean) {
  const [status, setStatus] = useState<RequestStatus | null>(null)
  const [review, setReview] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const saving = useRef(false)
  const version = useRef(0)
  const { showToast } = useToast()
  const { t } = useTranslation('agentapp')
  useEffect(() => {
    if (!enabled) return
    let active = true, timer: number
    const poll = async () => {
      if (!saving.current) {
        const started = version.current
        try {
          const value = await frameworkRequest<RequestStatus>({ operation: 'task_status', path, appId }, 20_000)
          if (active && !saving.current && started === version.current) {
            setStatus(value)
            if (!value.permissionRequired) setReview(false)
          }
        } catch {
          // Keep the last known state; a background read never replaces the app.
        }
      }
      if (active) timer = window.setTimeout(poll, 5000)
    }
    timer = window.setTimeout(poll, 0)
    return () => { active = false; window.clearTimeout(timer) }
  }, [path, appId, enabled])
  const choose = async (allow: boolean) => {
    if (!enabled || saving.current || !status) return
    saving.current = true; version.current++; setBusy(true); setError('')
    try {
      await frameworkRequest({ operation: 'consent', path, appId, allow, revision: status.revision, reviewId: status.reviewId })
      setStatus(value => value ? { ...value, needsReview: false, permissionRequired: !allow, error: undefined } : value)
      setReview(false)
      if (allow) showToast('success', t(status.retryNeeded ? 'triggerConsent.approvalSaved' : 'registry.requests.allowed'))
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
    finally { saving.current = false; setBusy(false) }
  }
  return { status, error, busy, choose, review: () => setReview(true), open: enabled && !!status?.permissionRequired && (review || status.needsReview) }
}

export function FrameworkRequestFeedback({ name, state, remote = false }: { name: string; state: ReturnType<typeof useFrameworkRequests>; remote?: boolean }) {
  const { t } = useTranslation('agentapp')
  const { status, error, busy, choose, open } = state
  return <>
    {status?.permissionRequired && <div className={styles.feedback} role="status">
      <MessageSquareText size={16} /><span>{t('triggerConsent.off')}</span>
      <Button variant="secondary" onClick={state.review}>{t('triggerConsent.review')}</Button>
    </div>}
    {status?.error && <div className={styles.feedback} role="alert"><AlertCircle size={16} /><span>{status.error}</span></div>}
    <Modal isOpen={open} title={t('triggerConsent.title')} size="md" onClose={() => void choose(false)} closeDisabled={busy} closeOnOverlayClick={false} closeOnEsc={false}>
      <ModalBody className={styles.body}>
        <div className={styles.app}><h4 className={styles.appName}>{name}</h4></div>
        <p className={styles.intro}>{t('registry.requests.intro', { name })}</p>
        <ul className={styles.list}>{status?.requests?.map(request => <li key={request} className={styles.item}>
          <MessageSquareText size={16} className={styles.icon} aria-hidden /><span className={styles.label}>{request.replace(/_/g, ' ')}</span>
        </li>)}</ul>
        <p className={styles.intro}>{remote ? 'CraftBot can use this app within your approved access. App requests cannot access local files or run commands on your computer.' : t('registry.requests.scope')}</p>
        {error && <p role="alert" className={styles.error}>{error}</p>}
      </ModalBody>
      <ModalFooter>
        <Button variant="secondary" disabled={busy} onClick={() => void choose(false)}>{t('triggerConsent.decline')}</Button>
        <Button variant="primary" loading={busy} onClick={() => void choose(true)}>{t('triggerConsent.allow')}</Button>
      </ModalFooter>
    </Modal>
  </>
}
