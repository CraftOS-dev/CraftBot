/**
 * Style packs — programmatic API (SYSTEM-MANAGED — do not edit)
 *
 * The app's design language (default/modern/glass/classic — see
 * frontend/styles/themes.css) and its palette are chosen by the USER from
 * the Living UI top bar's theme picker in CraftBot, and dark/light mode
 * follows the browser interface's theme. NEVER render a theme picker
 * inside the app — the host owns theming.
 *
 * The one thing the app may do is declare its INTENDED look:
 *
 *   setDefaultStyle('glass')   // once, at the top of App.tsx
 *
 * It applies only until the host/user has expressed a choice, and never
 * overrides one.
 */

export type ThemeStyle =
  | 'default' | 'modern' | 'glass' | 'classic'
  | 'velvet' | 'ink' | 'acid' | 'blueprint'
  | 'brutalist' | 'drafting' | 'clay' | 'atelier'

const STYLES: ThemeStyle[] = ['default', 'modern', 'glass', 'classic', 'velvet', 'ink', 'acid', 'blueprint', 'brutalist', 'drafting', 'clay', 'atelier']

/** Cache of the last host-sent style, written by the theme-sync script in
 * index.html (flash-free boot). Its presence means the host has spoken. */
const STYLE_CACHE_KEY = 'livingui-style'

export function getStyle(): ThemeStyle {
  const attr = document.documentElement.getAttribute('data-style')
  return STYLES.includes(attr as ThemeStyle) ? (attr as ThemeStyle) : 'default'
}

/** Apply the app's intended style pack UNLESS the host/user has already
 * chosen one. Call once at the top of App.tsx. */
export function setDefaultStyle(style: ThemeStyle): void {
  if (!STYLES.includes(style)) return
  try {
    if (localStorage.getItem(STYLE_CACHE_KEY)) return
  } catch {
    /* ignore */
  }
  document.documentElement.setAttribute('data-style', style)
}
