import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { AlertTriangle, Globe, MessageSquareText } from 'lucide-react'
import { AgentAppIcon } from '../../components/ui/AgentAppIcon'
import { Button } from '../../components/ui/Button'
import { Modal, ModalBody, ModalFooter } from '../../components/ui/Modal'
import { useToast } from '../../contexts/ToastContext'
import { useAppSelector } from '../../store/hooks'
import { frameworkRequest } from './frameworkApi'
import styles from '../../components/ui/AgentAppTriggerConsentModal.module.css'
import bannerStyles from './AgentAppTriggerConsentBanner.module.css'

interface RequestStatus {
  permissionRequired: boolean; needsReview: boolean; changed?: boolean; revision?: string; reviewId?: string
  requests?: string[]; error?: string; retryNeeded?: boolean
}

const COLLAPSED_COUNT = 3

export function useFrameworkRequests(path: string, appId: string, enabled: boolean) {
  const [status, setStatus] = useState<RequestStatus | null>(null)
  const [review, setReview] = useState(false)
  // A review closed without a saved choice (offline, or the same choice failed)
  // stays closed until the app's requests change.
  const [dismissed, setDismissed] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const connected = useAppSelector(state => state.connection.connected)
  const saving = useRef(false)
  const version = useRef(0)
  const lastChoice = useRef<boolean | null>(null)
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
            if (!value.permissionRequired && !value.error) setReview(false)
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
    saving.current = true; version.current++; lastChoice.current = allow; setBusy(true); setError('')
    try {
      await frameworkRequest({ operation: 'consent', path, appId, allow, revision: status.revision, reviewId: status.reviewId })
      setStatus(value => value ? { ...value, needsReview: false, permissionRequired: !allow, changed: false, error: undefined } : value)
      setReview(false)
      if (allow) showToast('success', t(status.retryNeeded ? 'triggerConsent.approvalSaved' : 'registry.requests.allowed'))
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
    finally { saving.current = false; setBusy(false) }
  }
  // Closing is "Don't allow". When that can't be saved (offline, or the same
  // choice just failed), close without a change so the dialog never traps.
  const close = () => {
    if (!connected || (error && lastChoice.current === false)) {
      setReview(false)
      setDismissed(status?.reviewId ?? null)
    } else void choose(false)
  }
  const waiting = !!status?.permissionRequired && status.needsReview && status.reviewId !== dismissed
  return {
    status, error, busy, connected, choose, close,
    review: () => { setDismissed(null); setReview(true) },
    // Stays up across a dropped connection, which it explains; not for a stopped app.
    open: (enabled || !connected) && !!status && (review || waiting),
  }
}

function RequestList({ requests }: { requests: string[] }) {
  const { t } = useTranslation('agentapp')
  const [expanded, setExpanded] = useState(false)
  const hidden = expanded ? 0 : Math.max(0, requests.length - COLLAPSED_COUNT)
  const shown = hidden ? requests.slice(0, COLLAPSED_COUNT) : requests
  return <>
    <ul className={styles.list}>
      {shown.map(request => (
        <li key={request} className={styles.item}>
          <MessageSquareText size={16} className={styles.icon} aria-hidden />
          <span className={styles.label}>{request.replace(/_/g, ' ')}</span>
        </li>
      ))}
    </ul>
    {hidden > 0 && (
      <button type="button" className={styles.seeMore} onClick={() => setExpanded(true)}>
        {t('triggerConsent.seeMore', { count: hidden })}
      </button>
    )}
  </>
}

export function FrameworkRequestFeedback({ name, state, remote = false }: { name: string; state: ReturnType<typeof useFrameworkRequests>; remote?: boolean }) {
  const { t } = useTranslation('agentapp')
  const { status, error, busy, connected, choose, close, open } = state
  const requests = status?.requests ?? []
  return <>
    {/* Only an undecided review, or an error, needs attention. "Don't allow"
        is a decision; it can be changed in Settings. */}
    {status && (status.needsReview || status.error) && <div className={bannerStyles.banner} role="status" aria-label={t('triggerConsent.permissions')}>
      <AlertTriangle size={14} className={bannerStyles.icon} aria-hidden />
      {/* A blocked request's error only repeats what the review says. */}
      <span className={bannerStyles.message}>{status.needsReview ? t(status.changed ? 'triggerConsent.pendingChanges' : 'triggerConsent.off') : status.error}</span>
      <button type="button" className={bannerStyles.review} onClick={state.review}>
        {t('triggerConsent.review')}
      </button>
    </div>}
    <Modal isOpen={open} title={t('triggerConsent.title')} size="md"
      onClose={close} closeDisabled={busy} closeOnOverlayClick={false} closeOnEsc={false}>
      <ModalBody className={styles.body}>
        <div className={styles.app}>
          <h4 className={styles.appName}>
            {remote ? <Globe size={16} className={styles.appIcon} /> : <AgentAppIcon size={16} className={styles.appIcon} />}
            {name}
          </h4>
          {requests.length > 0 && <p className={styles.intro}>{t('triggerConsent.intro', { name })}</p>}
        </div>
        {requests.length > 0 && <RequestList key={status?.reviewId} requests={requests} />}
        {error && <p role="alert" className={styles.error}>{error}</p>}
        {!connected && <p role="alert" className={styles.error}>{t('triggerConsent.disconnected')}</p>}
      </ModalBody>
      <ModalFooter>
        <Button variant="secondary" disabled={busy || !connected} onClick={() => void choose(false)}>
          {t('triggerConsent.decline')}
        </Button>
        <Button variant="primary" loading={busy} disabled={!connected} onClick={() => void choose(true)}>
          {t('triggerConsent.allow')}
        </Button>
      </ModalFooter>
    </Modal>
  </>
}
