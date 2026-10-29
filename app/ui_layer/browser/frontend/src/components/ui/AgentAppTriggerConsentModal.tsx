import { useTranslation } from 'react-i18next'
import { useAppDispatch, useAppSelector } from '../../store/hooks'
import { dismissTriggerReview, savingTriggerConsent } from '../../store/slices/agentAppSlice'
import { selectTriggerReviewProject } from '../../store/selectors/agentApp'
import { getSocketClient } from '../../store/socket/socketInstance'
import { Button } from './Button'
import { Modal, ModalBody, ModalFooter } from './Modal'
import styles from './AgentAppTriggerConsentModal.module.css'

function RequestInputs({ params }: { params?: Record<string, unknown> }) {
  const { t } = useTranslation('agentapp')
  const entries = Object.entries(params || {})
  if (!entries.length) return null
  const valueText = (value: unknown): string => typeof value === 'string'
    ? value || t('triggerConsent.emptyText')
    : JSON.stringify(value) ?? String(value)

  return (
    <section aria-label={t('triggerConsent.inputs')} className={styles.inputs}>
      <h4>{t('triggerConsent.inputs')}</h4>
      <p className={styles.note}>{t('triggerConsent.defaultsHint')}</p>
      <dl className={styles.parameters}>
        {entries.map(([name, definition]) => {
          if (!definition || typeof definition !== 'object' || Array.isArray(definition)) {
            return <div key={name}><dt>{name}</dt><dd>{valueText(definition)}</dd></div>
          }
          const parameter = definition as Record<string, unknown>
          const type = typeof parameter.type === 'string' ? parameter.type : 'string'
          return (
            <div key={name}>
              <dt>{name}</dt>
              <dd>
                {typeof parameter.description === 'string' && <p>{parameter.description}</p>}
                <p className={styles.note}>
                  {t(`triggerConsent.inputTypes.${type}`, { defaultValue: type })}
                  {' · '}{t(parameter.required ? 'triggerConsent.required' : 'triggerConsent.optional')}
                </p>
                {'default' in parameter && <p>{t('triggerConsent.defaultValue')}{' '}
                  <span className={styles.value}>{valueText(parameter.default)}</span>
                </p>}
                {Array.isArray(parameter.enum) && parameter.enum.length > 0 && <p>
                  {t('triggerConsent.allowedValues')}{' '}
                  <span className={styles.value}>{parameter.enum.map(value => JSON.stringify(value)).join(', ')}</span>
                </p>}
                {Object.entries(parameter).filter(([key]) => !['type', 'required', 'description', 'default', 'enum'].includes(key))
                  .map(([key, value]) => <p key={key}>{key}: <span className={styles.value}>{valueText(value)}</span></p>)}
              </dd>
            </div>
          )
        })}
      </dl>
    </section>
  )
}

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
    if (allow && consent.error) return
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
              <RequestInputs params={trigger.params} />
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
