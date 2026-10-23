import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Copy, Eye, EyeOff } from 'lucide-react'
import { Button, Modal, ModalBody, ModalFooter } from '../../components/ui'
import { getSocketClient } from '../../store/socket/socketInstance'
import { sendLive } from './useMiniBrowserSocket'
import { useToast } from '../../contexts/ToastContext'
import type { MiniBrowserVaultEntry } from '../../types'
import styles from './PasswordsModal.module.css'

/** Explicit reveal lives only in this dialog, never Redux or persisted UI state. */
export function CredentialValueModal({ entry, onClose }: {
  entry: MiniBrowserVaultEntry
  onClose(): void
}) {
  const { t } = useTranslation(['minibrowser', 'common'])
  const { showToast } = useToast()
  const [value, setValue] = useState<string | null>(null)
  const [waiting, setWaiting] = useState(false)
  const [error, setError] = useState(false)
  const token = useRef<string | null>(null)

  const hide = useCallback(() => { token.current = null; setValue(null); setWaiting(false) }, [])
  const reveal = () => {
    const next = crypto.randomUUID()
    token.current = next
    setValue(null)
    setError(false)
    setWaiting(true)
    if (!sendLive('mini_browser_vault_reveal', { id: entry.id, token: next })) {
      hide()
      setError(true)
    }
  }

  useEffect(() => {
    const client = getSocketClient()
    const offValue = client.onMessage('mini_browser_vault_value', (raw) => {
      const data = raw as { id?: string; token?: string; value?: string }
      if (!token.current || data.id !== entry.id || data.token !== token.current) return
      token.current = null
      setWaiting(false)
      if (typeof data.value === 'string') setValue(data.value)
      else setError(true)
    })
    const offError = client.onMessage('mini_browser_vault_result', (raw) => {
      const data = raw as { op?: string; ok?: boolean }
      if (token.current && data.op === 'reveal' && data.ok === false) {
        hide()
        setError(true)
      }
    })
    const offClose = client.onClose(hide)
    const onVisibility = () => { if (document.hidden) hide() }
    window.addEventListener('blur', hide)
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      token.current = null
      offValue(); offError(); offClose()
      window.removeEventListener('blur', hide)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [entry.id, hide])

  useEffect(() => {
    if (!waiting && value === null) return
    const timer = window.setTimeout(() => {
      hide()
      if (waiting) setError(true)
    }, waiting ? 15000 : 30000)
    return () => window.clearTimeout(timer)
  }, [waiting, value, hide])

  const copy = async () => {
    if (value === null) return
    try {
      await navigator.clipboard.writeText(value)
      showToast('success', t('minibrowser:credentials.copied'))
    } catch {
      showToast('error', t('minibrowser:credentials.copyFailed'))
    }
  }

  return (
    <Modal isOpen onClose={onClose} size="md" title={entry.label}>
      <ModalBody>
        <p className={styles.intro}>{t('minibrowser:credentials.revealHint')}</p>
        {error && <p role="alert" className={styles.fieldError}>{t('minibrowser:credentials.revealFailed')}</p>}
        {value !== null && <pre className={styles.revealedValue}>{value}</pre>}
        <div className={styles.valueActions}>
          <Button variant="secondary" loading={waiting} onClick={value === null ? reveal : hide}>
            {value === null ? <Eye size={16} /> : <EyeOff size={16} />}
            {t(value === null ? 'minibrowser:credentials.reveal' : 'minibrowser:credentials.hide')}
          </Button>
          <Button variant="secondary" disabled={value === null} onClick={copy}>
            <Copy size={16} /> {t('minibrowser:credentials.copy')}
          </Button>
        </div>
      </ModalBody>
      <ModalFooter><Button variant="secondary" onClick={onClose}>{t('common:actions.close')}</Button></ModalFooter>
    </Modal>
  )
}
