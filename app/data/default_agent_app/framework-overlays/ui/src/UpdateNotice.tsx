import { useEffect, useState } from 'react';

/** The PB adapter has no View appVersion marker at this pin. Detect its Vite
 * asset change in app-owned presentation code; only the person can reload. */
export function UpdateNotice(): React.JSX.Element | null {
  const [available, setAvailable] = useState(false);
  useEffect(() => {
    const script = (doc: Document) => doc.querySelector('script[type="module"][src*="/assets/"]')?.getAttribute('src');
    const loaded = script(document);
    let active = true, pending = false;
    let stopWatcher = () => {};
    const watcherUrl = '/a2app-update.js';
    void import(/* @vite-ignore */ watcherUrl).then(watcher => {
      if (!active) return;
      const shared = globalThis as typeof globalThis & { __a2appUpdateWatch?: () => void };
      shared.__a2appUpdateWatch?.();
      // Use the upstream public callback API. This board always asks before
      // reloading, including React-controlled forms and schema changes.
      stopWatcher = watcher.watchForUpdates({ onUpdate: () => { if (active) setAvailable(true); } });
      shared.__a2appUpdateWatch = stopWatcher;
    }).catch(() => { /* Asset checking still provides the explicit notice. */ });
    const check = async (): Promise<void> => {
      if (!loaded || pending || document.visibilityState === 'hidden') return;
      pending = true;
      try {
        const response = await fetch('/', { cache: 'no-cache', signal: AbortSignal.timeout(8000) });
        if (response.ok) {
          const served = script(new DOMParser().parseFromString(await response.text(), 'text/html'));
          if (active && served && served !== loaded) setAvailable(true);
        }
      } catch { /* A stopped server is not evidence of a new version. */ }
      finally { pending = false; }
    };
    const timer = setInterval(() => void check(), 20000);
    const visible = () => void check();
    document.addEventListener('visibilitychange', visible);
    return () => { active = false; stopWatcher(); clearInterval(timer); document.removeEventListener('visibilitychange', visible); };
  }, []);
  return available ? <aside className="kb-update" role="status">An app update is ready. Save your changes before reloading. <button onClick={() => window.location.reload()}>Reload app</button><button onClick={() => setAvailable(false)}>Later</button></aside> : null;
}
