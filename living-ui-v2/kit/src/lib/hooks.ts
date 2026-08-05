/**
 * Preset hooks.
 *
 *   useDebounce(value, ms)         debounced copy of a changing value
 *   useHotkey('ctrl+k', handler)   global keyboard shortcut. Plain-letter
 *                                  combos are ignored while the user types in
 *                                  an input/textarea; modifier combos always
 *                                  fire.
 */
import { useEffect, useRef, useState } from 'react';

export function useDebounce<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return debounced;
}

export function useHotkey(combo: string, handler: () => void): void {
  const handlerRef = useRef(handler);
  handlerRef.current = handler;

  useEffect(() => {
    const parts = combo.toLowerCase().split('+');
    const key = parts[parts.length - 1] ?? '';
    const wantCtrl = parts.includes('ctrl') || parts.includes('cmd');
    const wantShift = parts.includes('shift');
    const wantAlt = parts.includes('alt');

    const onKey = (e: KeyboardEvent): void => {
      const typing =
        e.target instanceof HTMLElement &&
        (e.target.tagName === 'INPUT' ||
          e.target.tagName === 'TEXTAREA' ||
          e.target.isContentEditable);
      if (typing && !wantCtrl && !wantAlt) return;
      if (e.key.toLowerCase() !== key) return;
      if (wantCtrl !== (e.ctrlKey || e.metaKey)) return;
      if (wantShift !== e.shiftKey) return;
      if (wantAlt !== e.altKey) return;
      e.preventDefault();
      handlerRef.current();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [combo]);
}
