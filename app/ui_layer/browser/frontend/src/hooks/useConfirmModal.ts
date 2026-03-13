import { useState, useCallback } from 'react'

export interface ConfirmModalState {
  isOpen: boolean
  title: string
  message: string
  confirmText: string
  cancelText: string
  variant: 'default' | 'danger'
  onConfirm: () => void
}

const initialState: ConfirmModalState = {
  isOpen: false,
  title: '',
  message: '',
  confirmText: 'Confirm',
  cancelText: 'Cancel',
  variant: 'default',
  onConfirm: () => {},
}

export interface ConfirmOptions {
  title: string
  message: string
  confirmText?: string
  cancelText?: string
  variant?: 'default' | 'danger'
}

export function useConfirmModal() {
  const [state, setState] = useState<ConfirmModalState>(initialState)

  const confirm = useCallback((options: ConfirmOptions, onConfirm: () => void) => {
    setState({
      isOpen: true,
      title: options.title,
      message: options.message,
      confirmText: options.confirmText || 'Confirm',
      cancelText: options.cancelText || 'Cancel',
      variant: options.variant || 'default',
      onConfirm,
    })
  }, [])

  const handleConfirm = useCallback(() => {
    state.onConfirm()
    setState(initialState)
  }, [state.onConfirm])

  const handleCancel = useCallback(() => {
    setState(initialState)
  }, [])

  return {
    modalProps: {
      isOpen: state.isOpen,
      title: state.title,
      message: state.message,
      confirmText: state.confirmText,
      cancelText: state.cancelText,
      variant: state.variant,
      onConfirm: handleConfirm,
      onCancel: handleCancel,
    },
    confirm,
  }
}
