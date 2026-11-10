/** App presentation and transport. Authentication/approval remain upstream. */
import { useEffect, useState } from 'react';
import PocketBase from 'pocketbase';
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export const cn = (...values: ClassValue[]): string => twMerge(clsx(values));
type Notice = { id: number; kind: string; message: string };
const show = (kind: string, message: string): void => { window.dispatchEvent(new CustomEvent('kb-notice', { detail: { id: Date.now() + Math.random(), kind, message } })); };
export const toast = { info: (s: string) => show('info', s), error: (s: string) => show('error', s), success: (s: string) => show('success', s) };
export function Notices(): React.JSX.Element {
  const [items, setItems] = useState<Notice[]>([]);
  useEffect(() => {
    const timers = new Set<ReturnType<typeof setTimeout>>();
    const listener = (event: Event): void => {
      const item = (event as CustomEvent<Notice>).detail;
      setItems(previous => [...previous.slice(-3), item]);
      const timer = setTimeout(() => { timers.delete(timer); setItems(previous => previous.filter(n => n.id !== item.id)); }, 6500);
      timers.add(timer);
    };
    window.addEventListener('kb-notice', listener);
    return () => { window.removeEventListener('kb-notice', listener); for (const timer of timers) clearTimeout(timer); };
  }, []);
  return <div className="toast-region" role="status" aria-live="polite">{items.map(n => <div className={`toast ${n.kind}`} key={n.id}>{n.message}</div>)}</div>;
}

const pb = new PocketBase(window.location.origin);
pb.autoCancellation(false);
export const getPbClient = () => ({ call: <T,>(fn: (client: PocketBase) => Promise<T>, _options?: { silent?: boolean }): Promise<T> => fn(pb) });

type Approval = { operation: string; resolve: (value: boolean) => void };
export function ApprovalDialog(): React.JSX.Element | null {
  const [approval, setApproval] = useState<Approval | null>(null);
  useEffect(() => {
    let pending: Approval | null = null;
    const listener = (event: Event): void => {
      pending?.resolve(false);
      pending = (event as CustomEvent<Approval>).detail;
      setApproval(pending);
    };
    window.addEventListener('kb-approval', listener);
    return () => { window.removeEventListener('kb-approval', listener); pending?.resolve(false); };
  }, []);
  if (!approval) return null;
  const finish = (yes: boolean): void => { approval.resolve(yes); setApproval(null); };
  return <div className="kb-confirm-backdrop"><section role="dialog" aria-modal="true" aria-labelledby="kb-approval-title" className="kb-confirm" onKeyDown={e => { if (e.key === 'Escape') finish(false); }}>
    <h2 id="kb-approval-title">Confirm destructive change</h2><p>{approval.operation.replaceAll('-', ' ')} changes or deletes data. Continue?</p>
    <button autoFocus onClick={() => finish(false)}>Cancel</button><button onClick={() => finish(true)}>Continue</button>
  </section></div>;
}

export async function operation<T>(path: string, body: Record<string, unknown>, _silent = false): Promise<T> {
  const name = path.replaceAll('/', '-').replaceAll('_', '-');
  const send = async (approval?: string) => fetch(`/api/ops/${name}`, {
    method: 'POST', credentials: 'same-origin', signal: AbortSignal.timeout(15000),
    headers: { 'Content-Type': 'application/json', ...(approval ? { 'X-A2App-Approval': approval } : {}) }, body: JSON.stringify(body),
  });
  try {
    let response = await send();
    let value = await response.json() as { result: T; message?: string; approvalKey?: string };
    if (response.status === 428 && value.approvalKey) {
      const confirmed = await new Promise<boolean>(resolve => window.dispatchEvent(new CustomEvent<Approval>('kb-approval', { detail: { operation: name, resolve } })));
      if (!confirmed) throw new Error('Change canceled.');
      response = await send(value.approvalKey);
      value = await response.json() as typeof value;
    }
    if (!response.ok) throw new Error(value.message || `The app returned HTTP ${response.status}.`);
    if (name === 'cards-stop' || (name === 'settings-update' && body.paused === true)) {
      // This app queues a worker for the board queue. Stopping a card or pausing
      // the board also stops that worker's delegated authority. Other held cards
      // return through their existing lease rules; no task is silently replayed.
      await cancelBoardWorker();
    }
    return value.result;
  } catch (error) {
    // The caller owns the inline error/notice; never emit a second toast here.
    if (error instanceof TypeError) throw new Error('Could not reach the app. Your input is kept. Try again when the app is running.');
    if (error instanceof DOMException && error.name === 'TimeoutError') throw new Error('The app took too long to answer. Check whether the change was saved before retrying.');
    throw error;
  }
}

async function cancelBoardWorker(): Promise<void> {
  const response = await fetch('/api/_a2app/tasks', { credentials: 'same-origin', signal: AbortSignal.timeout(15000) });
  if (!response.ok) throw new Error('Board work stopped, but its agent worker could not be checked. Disable app tasks in CraftBot before continuing.');
  const value = await response.json() as { tasks: { id: string; status: string; request: { capability: string } }[] };
  for (const task of value.tasks) {
    if (task.request.capability !== 'kanban-work' || ['completed', 'failed', 'canceled'].includes(task.status)) continue;
    const canceled = await fetch(`/api/_a2app/tasks/${encodeURIComponent(task.id)}/cancel`, {
      method: 'POST', credentials: 'same-origin', signal: AbortSignal.timeout(15000),
      headers: { 'Content-Type': 'application/json' }, body: '{}',
    });
    if (!canceled.ok) throw new Error('Board work stopped, but its agent worker could not be canceled. Disable app tasks in CraftBot before continuing.');
  }
}
