import React, { useId, useLayoutEffect, useRef } from 'react'
import ReactDOM from 'react-dom'
import { X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import styles from './Modal.module.css'

export type ModalSize = 'sm' | 'md' | 'lg' | 'full' | 'auto'

// Only the top modal is interactive, including when another modal is opened
// from it. Remember existing inert state so closing restores the host page.
const openDialogs: HTMLElement[] = []
const previousInert = new Map<HTMLElement, boolean>()
let bodyObserver: MutationObserver | undefined

function syncModalBackground() {
  const active = openDialogs[openDialogs.length - 1]
  if (!active) {
    previousInert.forEach((inert, element) => { element.inert = inert })
    previousInert.clear()
    bodyObserver?.disconnect()
    bodyObserver = undefined
    return
  }
  for (const element of document.body.children) {
    if (!(element instanceof HTMLElement)) continue
    if (!previousInert.has(element)) previousInert.set(element, element.inert)
    element.inert = !element.contains(active)
  }
}

function tabStops(dialog: HTMLElement) {
  return Array.from(dialog.querySelectorAll<HTMLElement>(
    'a[href], area[href], button, input, select, textarea, summary, iframe, [tabindex], [contenteditable="true"]',
  )).filter(element => element.tabIndex >= 0 && !element.matches(':disabled')
    && !element.closest('[inert]') && element.getClientRects().length > 0)
}

export interface ModalProps {
  isOpen: boolean
  onClose: () => void
  title?: React.ReactNode
  size?: ModalSize
  children: React.ReactNode
  closeOnOverlayClick?: boolean
  closeOnEsc?: boolean
  showCloseButton?: boolean
  closeDisabled?: boolean
  contentClassName?: string
}

export function Modal({
  isOpen,
  onClose,
  title,
  size = 'sm',
  children,
  closeOnOverlayClick = true,
  closeOnEsc = true,
  showCloseButton = true,
  closeDisabled = false,
  contentClassName,
}: ModalProps) {
  const { t } = useTranslation('common')
  const titleId = useId()
  const contentRef = useRef<HTMLDivElement>(null)
  const closeOptions = useRef({ onClose, closeOnEsc, closeDisabled })
  closeOptions.current = { onClose, closeOnEsc, closeDisabled }

  useLayoutEffect(() => {
    const dialog = contentRef.current
    if (!isOpen || !dialog) return
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    openDialogs.push(dialog)
    syncModalBackground()
    if (!bodyObserver) {
      bodyObserver = new MutationObserver(syncModalBackground)
      bodyObserver.observe(document.body, { childList: true })
    }
    dialog.focus({ preventScroll: true })

    const handler = (e: KeyboardEvent) => {
      if (openDialogs[openDialogs.length - 1] !== dialog) return
      if (e.key === 'Escape') {
        e.preventDefault()
        e.stopPropagation()
        const options = closeOptions.current
        if (options.closeOnEsc && !options.closeDisabled) options.onClose()
      } else if (e.key === 'Tab') {
        const stops = tabStops(dialog)
        const first = stops[0]
        const last = stops[stops.length - 1]
        if (!first) {
          e.preventDefault()
          dialog.focus()
        } else if (!dialog.contains(document.activeElement) || document.activeElement === dialog) {
          e.preventDefault()
          const target = e.shiftKey ? last : first
          target.focus()
        } else if (e.shiftKey && document.activeElement === first) {
          e.preventDefault()
          last.focus()
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault()
          first.focus()
        }
      }
    }
    const containFocus = (e: FocusEvent) => {
      if (openDialogs[openDialogs.length - 1] === dialog && e.target instanceof Node && !dialog.contains(e.target)) {
        dialog.focus({ preventScroll: true })
      }
    }
    document.addEventListener('keydown', handler, true)
    document.addEventListener('focusin', containFocus, true)
    return () => {
      document.removeEventListener('keydown', handler, true)
      document.removeEventListener('focusin', containFocus, true)
      const wasTop = openDialogs[openDialogs.length - 1] === dialog
      openDialogs.splice(openDialogs.indexOf(dialog), 1)
      syncModalBackground()
      if (!wasTop) return
      if (previousFocus?.isConnected && !previousFocus.closest('[inert]')) {
        previousFocus.focus({ preventScroll: true })
      } else {
        openDialogs[openDialogs.length - 1]?.focus({ preventScroll: true })
      }
    }
  }, [isOpen])

  if (!isOpen) return null

  const handleOverlayClick = () => {
    if (closeOnOverlayClick && !closeDisabled) onClose()
  }

  const showHeader = title !== undefined || showCloseButton

  // Render via a portal so the modal escapes any ancestor stacking context
  // (e.g. virtualized chat rows that use CSS `transform`, which would otherwise
  // pin a `position: fixed` modal inside that ancestor's stacking layer).
  return ReactDOM.createPortal(
    <div className={styles.overlay} onClick={handleOverlayClick}>
      <div
        ref={contentRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={title !== undefined ? titleId : undefined}
        tabIndex={-1}
        className={`${styles.content} ${styles[`size_${size}`]} ${contentClassName ?? ''}`}
        onClick={e => e.stopPropagation()}
      >
        {showHeader && (
          <div className={styles.header}>
            {title !== undefined ? <h3 id={titleId} className={styles.title}>{title}</h3> : <span />}
            {showCloseButton && (
              <button
                type="button"
                className={styles.close}
                onClick={onClose}
                disabled={closeDisabled}
                aria-label={t('actions.close')}
              >
                <X size={16} />
              </button>
            )}
          </div>
        )}
        {children}
      </div>
    </div>,
    document.body
  )
}

export interface ModalSectionProps {
  children: React.ReactNode
  className?: string
}

export function ModalBody({ children, className }: ModalSectionProps) {
  return <div className={`${styles.body} ${className ?? ''}`}>{children}</div>
}

export function ModalFooter({ children, className }: ModalSectionProps) {
  return <div className={`${styles.footer} ${className ?? ''}`}>{children}</div>
}
