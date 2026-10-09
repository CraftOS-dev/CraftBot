import type { GenerativeUIArtifact } from '../../types'
import { parse, parseFragment, serializeOuter, type DefaultTreeAdapterTypes } from 'parse5'

export const MAX_STATE_BYTES = 65_536
export const BRIDGE_CHANNEL = 'craftbot-generative-ui'

/** A small visual contract, containing only the host's public design tokens. */
export function readHostTheme() {
  const root = document.documentElement
  const css = getComputedStyle(root)
  const token = (name: string, fallback: string) => css.getPropertyValue(name).trim() || fallback
  return {
    mode: root.dataset.theme === 'light' ? 'light' : 'dark',
    '--cb-bg': token('--bg-primary', '#191919'),
    '--cb-surface': token('--bg-secondary', '#202020'),
    '--cb-text': token('--text-primary', '#e6e6e4'),
    '--cb-muted': token('--text-secondary', '#9b9a97'),
    '--cb-border': token('--border-primary', 'rgba(255,255,255,.1)'),
    '--cb-accent': token('--color-primary', '#ff4f18'),
    '--cb-font': token('--font-sans', 'system-ui, sans-serif'),
  }
}

/** Only JSON objects can cross the bridge; bound both storage and message size. */
export function validState(value: unknown): value is Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  try { return new TextEncoder().encode(JSON.stringify(value)).length <= MAX_STATE_BYTES } catch { return false }
}

function scriptJSON(value: unknown): string {
  return JSON.stringify(value).replace(/</g, '\\u003c').replace(/\u2028/g, '\\u2028').replace(/\u2029/g, '\\u2029')
}

/** Revalidate persisted/untrusted metadata before inserting it into a CSP. */
function connectOrigins(value: unknown): string[] {
  if (!Array.isArray(value) || value.length > 8) return []
  const blocked = new Set(['localhost', 'local', 'internal', 'lan', 'home', 'corp', 'arpa', 'onion', 'test', 'invalid'])
  const origins = new Set<string>()
  for (const origin of value) {
    const match = typeof origin === 'string' && /^https:\/\/([A-Za-z0-9.-]+)(?::443)?\/?$/.exec(origin)
    if (!match || match[0] !== origin) return []
    const host = match[1].toLowerCase(), labels = host.split('.')
    const suffix = labels[labels.length - 1]
    if (host.length > 253 || labels.length < 2 || !/^[a-z]{2,63}$/.test(suffix) || blocked.has(suffix) ||
      labels.some(label => !/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(label))) return []
    origins.add('https://' + host)
  }
  return [...origins].sort()
}

/** Build a fresh opaque-origin document. Never insert generated code into the host DOM. */
export function buildDocument(artifact: GenerativeUIArtifact, state: Record<string, unknown>, token: string, parentOrigin: string): string {
  // A pure parser preserves document/body attributes without starting any host
  // image/frame requests (DOMParser's inert HTML documents can still fetch them).
  const parsed = parse(artifact.html)
  const pending: DefaultTreeAdapterTypes.ParentNode[] = [parsed]
  // Host policy and bootstrap must precede every user element/script. Strip policy
  // overrides, nested browsing contexts, and external dependencies while inert.
  const forbidden = new Set(['meta', 'base', 'link', 'iframe', 'frame', 'frameset', 'object', 'embed'])
  while (pending.length) {
    const parent = pending.pop()!
    parent.childNodes = parent.childNodes.filter(node => !('tagName' in node) || (
      !forbidden.has(node.tagName) && !(node.tagName === 'script' && node.attrs.some(attr => ['src', 'href'].includes(attr.name)))
    ))
    for (const node of parent.childNodes) {
      if (!('tagName' in node)) continue
      node.attrs = node.attrs.filter(attr => !/^on/i.test(attr.name) && !['nonce', 'integrity', 'srcdoc', 'target', 'ping'].includes(attr.name))
      pending.push(node)
      if ('content' in node) pending.push((node as DefaultTreeAdapterTypes.Template).content)
    }
  }
  const connect = connectOrigins(artifact.connect_origins).join(' ') || "'none'"
  const policy = [
    "default-src 'none'", "script-src 'unsafe-inline'", "script-src-attr 'none'",
    "style-src 'unsafe-inline'", "img-src data: blob:", `connect-src ${connect}`,
    "form-action 'none'", "base-uri 'none'", "object-src 'none'", "frame-src 'none'", "worker-src 'none'",
  ].join('; ')
  const csp = document.createElement('meta')
  csp.httpEquiv = 'Content-Security-Policy'
  csp.content = policy
  const viewport = document.createElement('meta')
  viewport.name = 'viewport'
  viewport.content = 'width=device-width, initial-scale=1'
  const bootstrap = document.createElement('script')
  bootstrap.textContent = `(() => {
    const token = ${scriptJSON(token)}, origin = ${scriptJSON(parentOrigin)};
    const send = (type, data = {}) => parent.postMessage({ channel: '${BRIDGE_CHANNEL}', token, type, ...data }, origin);
    let state = ${scriptJSON(state)};
    let theme;
    const applyTheme = next => {
      if (!next || typeof next !== 'object') return;
      theme = Object.freeze({ ...next });
      for (const key of ['--cb-bg','--cb-surface','--cb-text','--cb-muted','--cb-border','--cb-accent','--cb-font']) {
        if (typeof next[key] === 'string') document.documentElement.style.setProperty(key, next[key]);
      }
      document.documentElement.style.colorScheme = next.mode === 'light' ? 'light' : 'dark';
    };
    applyTheme(${scriptJSON(readHostTheme())});
    Object.defineProperty(window, 'craftbot', { value: Object.freeze({
      get state() { return state; },
      get theme() { return theme; },
      saveState(value) {
        if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('State must be a JSON object');
        const json = JSON.stringify(value);
        if (new TextEncoder().encode(json).length > ${MAX_STATE_BYTES}) throw new Error('State exceeds 64 KB');
        state = JSON.parse(json); send('state', { state });
      }
    }), writable: false, configurable: false });
    addEventListener('error', e => send('error', { message: String(e.message || 'Script error').slice(0, 1000) }));
    addEventListener('unhandledrejection', e => send('error', { message: String(e.reason?.message || e.reason || 'Promise rejected').slice(0, 1000) }));
    addEventListener('securitypolicyviolation', e => send('error', { message: 'Blocked resource: ' + e.violatedDirective }));
    // Links/forms are UI controls, never a way to leave the runtime.
    addEventListener('click', e => { if (e.target?.closest?.('a, area')) e.preventDefault(); }, true);
    addEventListener('submit', e => e.preventDefault(), true);
    // A host load handshake recovers a ready message sent before registration,
    // including quick history hydration that replaces the initial frame.
    addEventListener('message', e => {
      if (e.source !== parent || e.data?.channel !== '${BRIDGE_CHANNEL}' || e.data?.token !== token) return;
      if (e.data.type === 'theme' || e.data.type === 'initialize') applyTheme(e.data.theme);
      if (e.data.type !== 'initialize' || document.readyState === 'loading') return;
      send('ready');
    });
    addEventListener('DOMContentLoaded', () => send('ready'));
  })();`
  const html = parsed.childNodes.find((node): node is DefaultTreeAdapterTypes.Element => 'tagName' in node && node.tagName === 'html')!
  const head = html.childNodes.find((node): node is DefaultTreeAdapterTypes.Element => 'tagName' in node && node.tagName === 'head')!
  const baseStyles = '<style>*,*::before,*::after{box-sizing:border-box}html{font-family:var(--cb-font);color:var(--cb-text);background:var(--cb-bg)}body{margin:0;font-size:15px;line-height:1.6}button,input,select,textarea{font:inherit;color:inherit}button{cursor:pointer}h1,h2,h3{line-height:1.2;letter-spacing:-.025em}h1{font-size:26px}h2{font-size:18px}p{color:var(--cb-muted)}button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible{outline:2px solid var(--cb-accent);outline-offset:3px}</style>'
  const prefix = parseFragment('<meta charset="utf-8">' + csp.outerHTML + viewport.outerHTML + baseStyles + bootstrap.outerHTML)
  for (const node of prefix.childNodes) node.parentNode = head
  head.childNodes.unshift(...prefix.childNodes)
  return '<!doctype html>\n' + serializeOuter(html)
}
