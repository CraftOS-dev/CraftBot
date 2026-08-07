/** Minimal toast system — no dependency, composable, token-styled. */
import { useEffect, useState } from 'react';
import { cn } from '../lib/cn.ts';

export type ToastKind = 'success' | 'error' | 'info';

export interface Toast {
  id: number;
  kind: ToastKind;
  message: string;
}

type Listener = (toasts: Toast[]) => void;

class ToastStore {
  private toasts: Toast[] = [];
  private listeners: Listener[] = [];
  private nextId = 1;

  subscribe(listener: Listener): () => void {
    this.listeners.push(listener);
    listener(this.toasts);
    return () => {
      this.listeners = this.listeners.filter((l) => l !== listener);
    };
  }

  show(kind: ToastKind, message: string, ttlMs = 4000): void {
    const toast: Toast = { id: this.nextId++, kind, message };
    this.toasts = [...this.toasts, toast];
    this.emit();
    setTimeout(() => this.dismiss(toast.id), ttlMs);
  }

  dismiss(id: number): void {
    this.toasts = this.toasts.filter((t) => t.id !== id);
    this.emit();
  }

  private emit(): void {
    for (const l of this.listeners) l(this.toasts);
  }
}

const store = new ToastStore();

export const toast = {
  success: (msg: string): void => store.show('success', msg),
  error: (msg: string): void => store.show('error', msg),
  info: (msg: string): void => store.show('info', msg),
};

const KIND_CLASSES: Record<ToastKind, string> = {
  success: 'border-emerald-500/40 text-emerald-700 dark:text-emerald-300',
  error: 'border-red-500/40 text-red-700 dark:text-red-300',
  info: 'border-sky-500/40 text-sky-700 dark:text-sky-300',
};

export function Toaster(): React.JSX.Element {
  const [toasts, setToasts] = useState<Toast[]>([]);
  useEffect(() => store.subscribe(setToasts), []);

  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-80 flex-col gap-2">
      {toasts.map((t) => (
        <button
          key={t.id}
          type="button"
          onClick={() => store.dismiss(t.id)}
          className={cn(
            'pointer-events-auto rounded-lg border bg-[var(--lui-surface)] px-4 py-3 text-left text-sm shadow-lg',
            KIND_CLASSES[t.kind],
          )}
        >
          {t.message}
        </button>
      ))}
    </div>
  );
}
