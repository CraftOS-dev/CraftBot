// Client-side checks for the saved-login form. The backend is authoritative
// (it normalizes and validates again); these only give instant, localized
// feedback and spot an existing login before it is replaced.

export const USERNAME_MAX = 256
export const PASSWORD_MAX = 1024
export const LABEL_MAX = 100

export type SiteProblem = 'required' | 'invalid'

/** The host[:port] the user meant, from "example.com", "https://www.example.com/login", … */
export function siteHost(raw: string): string {
  let text = raw.trim()
  if (!text) return ''
  if (/^[a-z][a-z0-9+.-]*:\/\//i.test(text)) {
    try {
      text = new URL(text).host
    } catch {
      return text.toLowerCase()
    }
  }
  text = text.split(/[/?#]/)[0]
  const at = text.lastIndexOf('@')
  if (at !== -1) text = text.slice(at + 1)
  return text.toLowerCase().replace(/^www\./, '').replace(/\.$/, '')
}

/** null when the site looks like a host name (or localhost), else why not. */
export function validateSite(raw: string): SiteProblem | null {
  if (!raw.trim()) return 'required'
  if (/\s/.test(raw.trim())) return 'invalid'
  const host = siteHost(raw)
  if (!host) return 'invalid'
  // Bracketed IPv6 literal, optionally with a port.
  if (/^\[[0-9a-f:.]+\](?::\d{1,5})?$/i.test(host)) return null
  const match = /^([^:]+)(?::(\d{1,5}))?$/.exec(host)
  if (!match) return 'invalid'
  const name = match[1]
  if (name === 'localhost') return null
  if (!name.includes('.') || name.startsWith('.') || name.includes('..')) return 'invalid'
  // Letters (any script, for internationalized domains), digits, dots, hyphens.
  if (!/^[\p{L}\p{N}.-]+$/u.test(name)) return 'invalid'
  return null
}
