import { useTranslation } from 'react-i18next'
import { useAppDispatch, useAppSelector } from '../../store/hooks'
import { openTriggerReview, savingTriggerConsent } from '../../store/slices/agentAppSlice'
import { getSocketClient } from '../../store/socket/socketInstance'
import { Button } from './Button'
import { Modal, ModalBody, ModalFooter } from './Modal'
import styles from './AgentAppTriggerConsentModal.module.css'

// Global so imports, agent-driven builds and updates can request review even
// while the user is in a different chat. The app's server runs in the background.
export function AgentAppTriggerConsentModal() {
  const { t } = useTranslation('agentapp')
  const dispatch = useAppDispatch()
  const { projects, triggerReviewId, triggerConsentSaving, triggerConsentError } = useAppSelector(s => s.agentApp)
  const connected = useAppSelector(s => s.connection.connected)
  const project = projects.find(p => p.id === triggerReviewId)
    || projects.find(p => p.status === 'running' && p.triggerConsent?.needsReview)
  const consent = project?.triggerConsent
  if (!project || !consent) return null

  const choose = (allow: boolean) => {
    if (consent.error) { dispatch(openTriggerReview(null)); return }
    dispatch(savingTriggerConsent())
    getSocketClient().send('agent_app_trigger_consent', {
      projectId: project.id, revision: consent.revision, allow,
    })
  }

  return (
    <Modal isOpen title={t('triggerConsent.title', { name: project.name })} size="md"
      onClose={() => choose(false)} closeDisabled={triggerConsentSaving || !connected}>
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
        {(triggerConsentError || consent.error) && <p role="alert">{triggerConsentError || consent.error}</p>}
        {!connected && <p role="alert">{t('triggerConsent.disconnected')}</p>}
      </ModalBody>
      <ModalFooter>
        <Button variant="secondary" disabled={triggerConsentSaving || !connected} onClick={() => choose(false)}>
          {t('triggerConsent.decline')}
        </Button>
        <Button variant="primary" loading={triggerConsentSaving} disabled={!connected || !!consent.error} onClick={() => choose(true)}>
          {t('triggerConsent.allow')}
        </Button>
      </ModalFooter>
    </Modal>
  )
}
