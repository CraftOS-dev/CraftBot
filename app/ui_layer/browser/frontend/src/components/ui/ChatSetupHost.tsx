import { Sparkles } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { usePersistedState } from '../../hooks'
import { useAppDispatch, useAppSelector } from '../../store/hooks'
import { selectSetupPendingCancel, selectShownSetup } from '../../store/selectors/agentAppSetup'
import {
  cancelSetup,
  clearSetupProgress,
  dismissCancelSetup,
  hideSetup,
  requestCancelSetup,
} from '../../store/slices/agentAppSetupSlice'
import { UI_STATE } from '../../store/uiState'
import type { PendingAgentAppSetup } from '../../types'
import { useSettingsWebSocket } from '../../pages/Settings/useSettingsWebSocket'
import { ConfirmModal } from './ConfirmModal'
import { CreateCustomWizard } from './CreateCustomWizard'
import { Modal } from './Modal'
import styles from './CreateAgentAppModal.module.css'

export interface ChatSetupHostProps {
  /** A setup finished and its project exists (the caller navigates to it). */
  onCreated: (projectId: string) => void
}

/**
 * Presents pending chat-started Agent App setups (agentAppSetupSlice).
 *
 * Always mounted, so a setup the agent summons pops up wherever the user is.
 * The X only hides the popup: the setup stays pending and the Resume card in
 * its chat reopens it with the answers given so far. Cancelling asks for
 * confirmation here, whichever surface (wizard or card) asked for it.
 */
export function ChatSetupHost({ onCreated }: ChatSetupHostProps) {
  const { t } = useTranslation(['components'])
  const dispatch = useAppDispatch()
  const shown = useAppSelector(selectShownSetup)
  const pendingCancel = useAppSelector(selectSetupPendingCancel)

  return (
    <>
      {shown && <ChatSetupModal key={shown.wizardId} setup={shown} onCreated={onCreated} />}
      <ConfirmModal
        isOpen={pendingCancel !== undefined}
        title={t('components:createAgentApp.cancelSetupTitle')}
        message={t('components:createAgentApp.cancelSetupMessage', { name: pendingCancel?.name ?? '' })}
        confirmText={t('components:createAgentApp.cancelSetupConfirm')}
        cancelText={t('components:createAgentApp.keepSetup')}
        variant="danger"
        onConfirm={() => { if (pendingCancel) dispatch(cancelSetup(pendingCancel.wizardId)) }}
        onCancel={() => dispatch(dismissCancelSetup())}
      />
    </>
  )
}

interface ChatSetupModalProps {
  setup: PendingAgentAppSetup
  onCreated: (projectId: string) => void
}

/** One setup's wizard, entered at the interview step. Mount with key={wizardId}. */
function ChatSetupModal({ setup, onCreated }: ChatSetupModalProps) {
  const { t } = useTranslation(['components'])
  const dispatch = useAppDispatch()
  const { send, onMessage } = useSettingsWebSocket()
  // The wizard reads `progress` only when it mounts, then reports changes back.
  const [progress, setProgress] = usePersistedState(UI_STATE.agentApp.setupProgress(setup.wizardId))

  const hide = () => dispatch(hideSetup())

  return (
    <Modal
      isOpen={true}
      onClose={hide}
      size="full"
      closeOnOverlayClick={false}
      closeOnEsc={false}
      title={
        <>
          <Sparkles size={20} className={styles.headerIcon} />
          {t('components:createAgentApp.setupQuestions', { name: setup.name || String(setup.config?.name || 'Agent App') })}
        </>
      }
    >
      <CreateCustomWizard
        send={send}
        onMessage={onMessage}
        initial={setup}
        progress={progress}
        onProgress={setProgress}
        onClose={hide}
        onCancel={() => dispatch(requestCancelSetup(setup.wizardId))}
        onCreated={(projectId: string) => {
          dispatch(clearSetupProgress(setup.wizardId))
          onCreated(projectId)
        }}
      />
    </Modal>
  )
}
