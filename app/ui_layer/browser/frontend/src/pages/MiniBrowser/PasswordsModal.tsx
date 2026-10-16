import { Modal, ModalBody } from '../../components/ui'
import { CredentialsSettings } from '../Settings/CredentialsSettings'

/** Compatibility entry point; credential management belongs to shared Settings. */
export function PasswordsModal({ isOpen, onClose }: { isOpen: boolean; onClose(): void }) {
  return <Modal isOpen={isOpen} onClose={onClose} size="lg" title="Credentials">
    <ModalBody><CredentialsSettings /></ModalBody>
  </Modal>
}
