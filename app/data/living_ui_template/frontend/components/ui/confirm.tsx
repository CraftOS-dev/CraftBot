/**
 * Confirmation dialog preset (SYSTEM-MANAGED — do not edit)
 *
 * NEVER use browser confirm()/alert(). Use this instead:
 *
 *   const [confirmEl, confirm] = useConfirm()
 *   ...
 *   <Button variant="danger" onClick={async () => {
 *     if (await confirm('Delete this card?')) await cards.remove(card.id)
 *   }}>Delete</Button>
 *   ...
 *   {confirmEl}   // render once, anywhere in the component
 */

import React, { useCallback, useRef, useState } from 'react'
import { Modal } from './index'
import { Button } from './index'

export interface ConfirmDialogProps {
  open: boolean
  title?: string
  message: string
  confirmLabel?: string
  cancelLabel?: string
  danger?: boolean
  onConfirm: () => void
  onCancel: () => void
}

export function ConfirmDialog({
  open,
  title = 'Are you sure?',
  message,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  danger = true,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  return (
    <Modal
      open={open}
      onClose={onCancel}
      title={title}
      size="sm"
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onCancel}>{cancelLabel}</Button>
          <Button variant={danger ? 'danger' : 'primary'} onClick={onConfirm}>
            {confirmLabel}
          </Button>
        </div>
      }
    >
      <p className="text-ink-secondary m-0">{message}</p>
    </Modal>
  )
}

/** Imperative confirmation: `const [el, confirm] = useConfirm()`. */
export function useConfirm(): [
  React.ReactNode,
  (message: string, title?: string) => Promise<boolean>,
] {
  const [state, setState] = useState<{ message: string; title?: string } | null>(null)
  const resolveRef = useRef<(ok: boolean) => void>()

  const confirm = useCallback((message: string, title?: string) => {
    return new Promise<boolean>(resolve => {
      resolveRef.current = resolve
      setState({ message, title })
    })
  }, [])

  const settle = (ok: boolean) => {
    resolveRef.current?.(ok)
    setState(null)
  }

  const element = state ? (
    <ConfirmDialog
      open
      title={state.title}
      message={state.message}
      onConfirm={() => settle(true)}
      onCancel={() => settle(false)}
    />
  ) : null

  return [element, confirm]
}
