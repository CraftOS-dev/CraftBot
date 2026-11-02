import { useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { useToast } from '../../contexts/ToastContext'
import { useAppDispatch, useAppSelector } from '../../store/hooks'
import { selectTriggerReviewProject } from '../../store/selectors/agentApp'
import { openTriggerReview } from '../../store/slices/agentAppSlice'
import { getSocketClient } from '../../store/socket/socketInstance'

const toastKey = (projectId: string) => `agent-app-trigger-blocked:${projectId}`

/** Group repeat refusals by app/revision, including after toast dismissal. */
export function AgentAppTriggerBlockedToast() {
  const { t } = useTranslation('agentapp')
  const dispatch = useAppDispatch()
  const blocked = useAppSelector(state => state.agentApp.blockedTriggerRequests)
  const reviewProject = useAppSelector(selectTriggerReviewProject)
  const { showToast, dismissToastKey } = useToast()
  const shown = useRef(new Map<string, string>())

  useEffect(() => {
    for (const projectId of shown.current.keys()) {
      if (!blocked[projectId]) {
        dismissToastKey(toastKey(projectId))
        shown.current.delete(projectId)
      }
    }
    for (const event of Object.values(blocked)) {
      if (reviewProject?.id === event.projectId) {
        // The approval dialog already explains the missing permission.
        dismissToastKey(toastKey(event.projectId))
        shown.current.set(event.projectId, event.consent.revision)
        continue
      }
      if (shown.current.get(event.projectId) === event.consent.revision) continue
      shown.current.set(event.projectId, event.consent.revision)
      showToast('warning', t('triggerConsent.blocked', { name: event.projectName }), undefined, {
        key: toastKey(event.projectId),
        detail: t('triggerConsent.blockedHint'),
        actions: [{ label: t('triggerConsent.review'), onClick: () => {
          dispatch(openTriggerReview(event.projectId))
          // Refresh definitions, including apps not yet in this client's catalog.
          getSocketClient().send('agent_app_list')
        } }],
      })
    }
  }, [blocked, reviewProject?.id, dispatch, showToast, dismissToastKey, t])

  useEffect(() => () => {
    for (const projectId of shown.current.keys()) dismissToastKey(toastKey(projectId))
    shown.current.clear()
  }, [dismissToastKey])
  return null
}
