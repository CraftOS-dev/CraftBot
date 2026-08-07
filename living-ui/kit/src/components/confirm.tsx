/**
 * Confirmation dialog preset. NEVER use the browser's confirm()/alert().
 *
 *   const [confirmEl, confirm] = useConfirm();
 *   ...
 *   <Button variant="danger" onClick={async () => {
 *     if (await confirm('Delete this card?')) await remove(card.id);
 *   }}>Delete</Button>
 *   ...
 *   {confirmEl}   // render once, anywhere in the component
 */
import { useCallback, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { Button } from './Button.tsx';
import { Dialog } from './Dialog.tsx';

export interface ConfirmDialogProps {
  open: boolean;
  title?: string | undefined;
  message: string;
  confirmLabel?: string | undefined;
  cancelLabel?: string | undefined;
  danger?: boolean | undefined;
  onConfirm: () => void;
  onCancel: () => void;
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
}: ConfirmDialogProps): React.JSX.Element {
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) onCancel();
      }}
      title={title}
      footer={
        <>
          <Button variant="secondary" onClick={onCancel}>
            {cancelLabel}
          </Button>
          <Button variant={danger ? 'danger' : 'primary'} onClick={onConfirm}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      <p className="text-sm text-[var(--lui-muted)]">{message}</p>
    </Dialog>
  );
}

/** Imperative confirmation: `const [el, confirm] = useConfirm()`. */
export function useConfirm(): [
  ReactNode,
  (message: string, title?: string) => Promise<boolean>,
] {
  const [state, setState] = useState<{ message: string; title?: string | undefined } | null>(null);
  const resolveRef = useRef<((ok: boolean) => void) | null>(null);

  const confirm = useCallback(
    (message: string, title?: string): Promise<boolean> =>
      new Promise<boolean>((resolve) => {
        resolveRef.current = resolve;
        setState({ message, title });
      }),
    [],
  );

  const settle = (ok: boolean): void => {
    resolveRef.current?.(ok);
    setState(null);
  };

  const element =
    state !== null ? (
      <ConfirmDialog
        open
        title={state.title}
        message={state.message}
        onConfirm={() => settle(true)}
        onCancel={() => settle(false)}
      />
    ) : null;

  return [element, confirm];
}
