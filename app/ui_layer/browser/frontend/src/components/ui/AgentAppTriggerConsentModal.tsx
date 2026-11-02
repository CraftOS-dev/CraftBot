import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { MessageSquareText } from 'lucide-react'
import { useToast } from '../../contexts/ToastContext'
import { useAppDispatch, useAppSelector } from '../../store/hooks'
import { dismissTriggerReview, savingTriggerConsent } from '../../store/slices/agentAppSlice'
import { selectTriggerReviewProject } from '../../store/selectors/agentApp'
import { newTriggerConsentRequestId, sendTriggerConsent } from '../../features/agentApps/triggerConsent'
import type { AgentAppTriggerConsent } from '../../types'
import { AgentAppIcon } from './AgentAppIcon'
import { Badge, type BadgeVariant } from './Badge'
import { Button } from './Button'
import { Modal, ModalBody, ModalFooter } from './Modal'
import styles from './AgentAppTriggerConsentModal.module.css'

type TriggerChange = AgentAppTriggerConsent['triggers'][number]['change']

const CHANGE_BADGE: Record<TriggerChange, BadgeVariant> = { new: 'info', changed: 'warning', approved: 'success' }
const COLLAPSED_COUNT = 3

function RequestList({ triggers }: { triggers: AgentAppTriggerConsent['triggers'] }) {
  const { t } = useTranslation('agentapp')
  const [expanded, setExpanded] = useState(false)
  // A first review marks every request new; the badge only means something
  // once some requests were already allowed. Those that still need a choice
  // come first so the collapsed list never hides them.
  const showChange = triggers.some(trigger => trigger.change !== 'new')
  const ordered = showChange
    ? [...triggers.filter(trigger => trigger.change !== 'approved'), ...triggers.filter(trigger => trigger.change === 'approved')]
    : triggers
  const hidden = expanded ? 0 : Math.max(0, ordered.length - COLLAPSED_COUNT)
  const shown = hidden ? ordered.slice(0, COLLAPSED_COUNT) : ordered

  return <>
    <ul className={styles.list}>
      {shown.map(trigger => (
        <li key={trigger.name} className={styles.item}>
          <MessageSquareText size={16} className={styles.icon} aria-hidden />
          <span className={styles.label}>{trigger.description || trigger.name}</span>
          {showChange && <Badge variant={CHANGE_BADGE[trigger.change]}>{t(`triggerConsent.${trigger.change}`)}</Badge>}
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

// Global so imports, agent-driven builds and updates can request review even
// while the user is in a different chat. The app's server runs in the background.
export function AgentAppTriggerConsentModal() {
  const { t } = useTranslation('agentapp')
  const dispatch = useAppDispatch()
  const { triggerConsentRequest, triggerConsentError, triggerConsentApproval } = useAppSelector(s => s.agentApp)
  const { showToast, dismissToastKey } = useToast()
  const announcedApproval = useRef<string | null>(null)
  const lastChoice = useRef<boolean | null>(null)
  useEffect(() => {
    if (!triggerConsentApproval) {
      dismissToastKey('agent-app-trigger-approved')
      return
    }
    if (announcedApproval.current === triggerConsentApproval.requestId) return
    announcedApproval.current = triggerConsentApproval.requestId
    showToast('success', t('triggerConsent.approvalSaved'), undefined, { key: 'agent-app-trigger-approved' })
  }, [triggerConsentApproval, showToast, dismissToastKey, t])
  const connected = useAppSelector(s => s.connection.connected)
  const project = useAppSelector(selectTriggerReviewProject)
  const consent = project?.triggerConsent
  if (!project || !consent) return null
  const saving = triggerConsentRequest?.projectId === project.id
  const error = triggerConsentError?.projectId === project.id ? triggerConsentError.message : null
  const dismiss = () => dispatch(dismissTriggerReview({ projectId: project.id, revision: consent.revision }))

  const choose = (allow: boolean) => {
    if (allow && consent.error) return
    const requestId = newTriggerConsentRequestId()
    lastChoice.current = allow
    dispatch(savingTriggerConsent({ projectId: project.id, requestId, allow }))
    sendTriggerConsent(project.id, consent.revision, allow, requestId)
  }

  // Closing is "Don't allow". When that can't be saved (offline, or the same
  // choice just failed), close without a change so the dialog never traps.
  const close = () => {
    if (!connected || (error && lastChoice.current === false)) dismiss()
    else choose(false)
  }

  return (
    <Modal key={project.id} isOpen title={t('triggerConsent.title')} size="md"
      onClose={close} closeDisabled={saving} closeOnOverlayClick={false} closeOnEsc={false}>
      <ModalBody className={styles.body}>
        <div className={styles.app}>
          <h4 className={styles.appName}>
            <AgentAppIcon icon={project.icon} projectId={project.id} size={16} className={styles.appIcon} />
            {project.name}
          </h4>
          {consent.triggers.length > 0 && <p className={styles.intro}>{t('triggerConsent.intro', { name: project.name })}</p>}
        </div>
        {consent.triggers.length > 0 && <RequestList key={consent.revision} triggers={consent.triggers} />}
        {(error || consent.error) && <p role="alert" className={styles.error}>{error || consent.error}</p>}
        {!connected && <p role="alert" className={styles.error}>{t('triggerConsent.disconnected')}</p>}
      </ModalBody>
      <ModalFooter>
        <Button variant="secondary" disabled={saving || !connected} onClick={() => choose(false)}>
          {t('triggerConsent.decline')}
        </Button>
        <Button variant="primary" loading={saving} disabled={!connected || !!consent.error} onClick={() => choose(true)}>
          {t('triggerConsent.allow')}
        </Button>
      </ModalFooter>
    </Modal>
  )
}
