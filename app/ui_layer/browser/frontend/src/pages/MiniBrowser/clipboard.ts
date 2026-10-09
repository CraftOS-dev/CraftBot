// Clipboard helpers for the Mini Browser.
//
// Browsers only allow clipboard writes during a user gesture (Safari strictly
// inside the event handler). Copying the page's selection needs a round trip
// to the backend, so the write is STARTED inside the key press with a
// ClipboardItem whose content is a promise of the backend's reply; browsers
// without promise support fall back to writeText once the reply is in.

export type ClipboardOutcome = 'copied' | 'empty' | 'failed'

const hasClipboard = (): boolean =>
  typeof navigator !== 'undefined' && !!navigator.clipboard

/** Last resort for non-secure origins (e.g. CraftBot opened over a LAN IP),
 *  where navigator.clipboard does not exist. Needs a live user gesture. */
function execCommandCopy(text: string): boolean {
  if (typeof document === 'undefined') return false
  const active = document.activeElement as HTMLElement | null
  const area = document.createElement('textarea')
  area.value = text
  area.setAttribute('readonly', '')
  area.style.position = 'fixed'
  area.style.top = '0'
  area.style.left = '0'
  area.style.opacity = '0'
  area.style.pointerEvents = 'none'
  document.body.appendChild(area)
  area.select()
  let ok = false
  try {
    ok = document.execCommand('copy')
  } catch {
    ok = false
  }
  area.remove()
  active?.focus?.({ preventScroll: true })
  return ok
}

/** Copy text that is already known (e.g. the page URL). */
export async function copyText(text: string): Promise<boolean> {
  if (hasClipboard()) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      // Permission or focus problem: try the legacy path below.
    }
  }
  return execCommandCopy(text)
}

/**
 * Copy text that will only be known later. Must be CALLED synchronously from
 * the user's key/pointer handler; `pending` may resolve afterwards. An empty
 * reply (nothing selected) leaves the clipboard untouched.
 */
export function copyTextWhenReady(pending: Promise<string>): Promise<ClipboardOutcome> {
  const fallback = (): Promise<ClipboardOutcome> =>
    pending.then(
      async (text): Promise<ClipboardOutcome> => {
        if (!text) return 'empty'
        return (await copyText(text)) ? 'copied' : 'failed'
      },
      (): ClipboardOutcome => 'failed',
    )

  if (hasClipboard() && typeof ClipboardItem !== 'undefined' && typeof navigator.clipboard.write === 'function') {
    let empty = false
    const blob = pending.then(text => {
      if (!text) {
        empty = true
        throw new Error('empty selection')
      }
      return new Blob([text], { type: 'text/plain' })
    })
    // Keep a rejected blob promise from surfacing as "unhandled".
    blob.catch(() => undefined)
    try {
      return navigator.clipboard.write([new ClipboardItem({ 'text/plain': blob })]).then(
        (): ClipboardOutcome => 'copied',
        () => (empty ? 'empty' : fallback()),
      )
    } catch {
      // ClipboardItem without promise support: fall through.
    }
  }
  return fallback()
}
