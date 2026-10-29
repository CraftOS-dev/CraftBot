import { useTranslation } from 'react-i18next'
import { useAppDispatch, useAppSelector } from '../../store/hooks'
import { dismissTriggerReview, savingTriggerConsent } from '../../store/slices/agentAppSlice'
import { selectTriggerReviewProject } from '../../store/selectors/agentApp'
import { getSocketClient } from '../../store/socket/socketInstance'
import { Button } from './Button'
import { Modal, ModalBody, ModalFooter } from './Modal'
import styles from './AgentAppTriggerConsentModal.module.css'

// Global so imports, agent-driven builds and updates can request review even
// while the user is in a different chat. The app's server runs in the background.
export function AgentAppTriggerConsentModal() {
  const { t } = useTranslation('agentapp')
  const dispatch = useAppDispatch()
  const { triggerConsentRequest, triggerConsentError } = useAppSelector(s => s.agentApp)
  const connected = useAppSelector(s => s.connection.connected)
  const project = useAppSelector(selectTriggerReviewProject)
  const consent = project?.triggerConsent
  if (!project || !consent) return null
  const saving = triggerConsentRequest?.projectId === project.id
  const error = triggerConsentError?.projectId === project.id ? triggerConsentError.message : null
  const dismiss = () => dispatch(dismissTriggerReview({ projectId: project.id, revision: consent.revision }))

  const choose = (allow: boolean) => {
    if (consent.error) { dismiss(); return }
    const requestId = typeof crypto?.randomUUID === 'function'
      ? crypto.randomUUID()
      : `trigger-consent-${Date.now()}-${Math.random().toString(36).slice(2)}`
    dispatch(savingTriggerConsent({ projectId: project.id, requestId }))
    getSocketClient().send('agent_app_trigger_consent', {
      projectId: project.id, revision: consent.revision, allow, requestId,
    })
  }

  return (
    <Modal key={project.id} isOpen title={t('triggerConsent.title', { name: project.name })} size="md"
      onClose={dismiss} closeDisabled={saving}>
      <ModalBody>
        <p className={styles.intro}>{t('triggerConsent.intro', { name: project.name })}</p>
        <p className={styles.note}>{t('triggerConsent.scope')}</p>
        <ul className={styles.requests}>
          {consent.triggers.map(trigger => (
            <li key={trigger.name} className={styles.request}>
              <div className={styles.heading}>
                <strong>{trigger.description || trigger.name}</strong>
                <span className={styles.badge}>{t(`triggerConsent.${trigger.change}`)}</span>
              </div>
              <details>
                <summary>{t('triggerConsent.details')}</summary>
                <p className={styles.instruction}>{trigger.instruction}</p>
              </details>
            </li>
          ))}
        </ul>
        <p className={styles.note}>{t('triggerConsent.later')}</p>
        {(error || consent.error) && <p role="alert">{error || consent.error}</p>}
        {!connected && <p role="alert">{t('triggerConsent.disconnected')}</p>}
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
