import { useEffect, useRef, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Modal } from '../ui/Modal'
import styles from './References.module.css'

/** Focus lifecycle for the captured-context preview. */
export function ReferenceDialog({ open, title, onClose, children }: {
  open: boolean; title: string; onClose: () => void; children: ReactNode
}) {
  const { t } = useTranslation('chat')
  const root = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const previous = document.activeElement as HTMLElement | null
    const timer = window.setTimeout(() => root.current?.querySelector<HTMLElement>('input,button:not(:disabled)')?.focus(), 0)
    return () => { clearTimeout(timer); if (previous?.isConnected) previous.focus() }
  }, [open])
  return <Modal isOpen={open} onClose={onClose} title={title} size="md" showCloseButton={false}>
    <div ref={root} role="dialog" aria-label={title} aria-modal="true" className={styles.picker}
      onKeyDown={e => {
        if (e.key !== 'Tab') return
        const nodes = Array.from(root.current?.querySelectorAll<HTMLElement>('input,select,button:not(:disabled)') || [])
        const first = nodes[0], last = nodes[nodes.length - 1]
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last?.focus() }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus() }
      }}>
      {children}
      <button type="button" onClick={onClose}>{t('references.done')}</button>
    </div>
  </Modal>
}
