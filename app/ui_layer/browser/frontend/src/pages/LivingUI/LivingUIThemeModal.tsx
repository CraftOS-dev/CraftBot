import React, { useState } from 'react'
import { Check } from 'lucide-react'
import { Modal, ModalBody } from '../../components/ui/Modal'
import styles from './LivingUIPage.module.css'

export type LivingUIThemeId =
  | 'craftbot'
  | 'modern'
  | 'glass'
  | 'classic'
  | 'velvet'
  | 'ink'
  | 'acid'
  | 'blueprint'
  | 'brutalist'
  | 'drafting'
  | 'clay'
  | 'atelier'
  | 'normal'
  | 'ocean'
  | 'forest'
  | 'pastel'
  | 'custom'

/** Style packs shipped in every Living UI (token overrides in the
 * template's themes.css). Each THEME below bundles one of these with a
 * palette — the user never picks them separately. */
export type LivingUIStyleId =
  | 'default' | 'modern' | 'glass' | 'classic'
  | 'velvet' | 'ink' | 'acid' | 'blueprint'
  | 'brutalist' | 'drafting' | 'clay' | 'atelier'

export interface LivingUICustomColors {
  bg: string
  surface: string
  text: string
  accent: string
}

export const DEFAULT_CUSTOM_COLORS: LivingUICustomColors = {
  bg: '#191919',
  surface: '#202020',
  text: '#E6E6E4',
  accent: '#FF4F18',
}

interface ThemeDef {
  id: Exclude<LivingUIThemeId, 'custom'>
  label: string
  /** Short descriptor shown under the label (style-bearing themes). */
  hint?: string
  /** Which style pack the theme applies inside the app. */
  style: LivingUIStyleId
  /** Tile preview colors [bg, surface, text, accent]. */
  swatches: [string, string, string, string]
  /** Pinned palettes override the app's CSS vars; non-pinned themes keep
   * the CraftBot palette and follow the host's light/dark mode. */
  pinned: boolean
}

export const PRESET_THEMES: ThemeDef[] = [
  // Style-bearing themes — each pack carries its OWN palette (defined in
  // the template's themes.css) and follows the host's light/dark mode.
  { id: 'craftbot',  label: 'CraftBot',  hint: 'The baseline',    style: 'default',   swatches: ['#191919', '#202020', '#E6E6E4', '#FF4F18'], pinned: false },
  { id: 'modern',    label: 'Modern',    hint: 'Airy indigo',     style: 'modern',    swatches: ['#12141D', '#1A1D2A', '#ECEEF8', '#7C8AFF'], pinned: false },
  { id: 'glass',     label: 'Glass',     hint: 'Aurora glass',    style: 'glass',     swatches: ['#0B0E1C', '#1C2340', '#F5F7FE', '#22D3EE'], pinned: false },
  { id: 'classic',   label: 'Classic',   hint: 'Flat & dense',    style: 'classic',   swatches: ['#131311', '#1C1B17', '#F1EDE2', '#E8A317'], pinned: false },
  { id: 'velvet',    label: 'Velvet',    hint: 'Warm glass',      style: 'velvet',    swatches: ['#F4E9DF', '#FFFFFF', '#3A2E26', '#F06F2A'], pinned: false },
  { id: 'ink',       label: 'Ink',       hint: 'Mono playful',    style: 'ink',       swatches: ['#F3F3F1', '#FFFFFF', '#111111', '#111111'], pinned: false },
  { id: 'acid',      label: 'Acid',      hint: 'Greige & lime',   style: 'acid',      swatches: ['#DCD9CE', '#FFFFFF', '#17170F', '#D8F21D'], pinned: false },
  { id: 'blueprint', label: 'Blueprint', hint: 'Grid datasheet',  style: 'blueprint', swatches: ['#F4F3EF', '#FFFFFF', '#16161A', '#F25C1A'], pinned: false },
  { id: 'brutalist', label: 'Brutalist', hint: 'Hard blocks',     style: 'brutalist', swatches: ['#FFFFFF', '#FFFFFF', '#0A0A0A', '#7C3AED'], pinned: false },
  { id: 'drafting',  label: 'Drafting',  hint: 'Monoline sketch', style: 'drafting',  swatches: ['#E9EDE4', '#E9EDE4', '#2E3528', '#3A4232'], pinned: false },
  { id: 'clay',      label: 'Clay',      hint: 'Soft extruded',   style: 'clay',      swatches: ['#E4E6EC', '#E4E6EC', '#3A3F4C', '#5B7CFA'], pinned: false },
  { id: 'atelier',   label: 'Atelier',   hint: 'Studio minimal',  style: 'atelier',   swatches: ['#EDEFF2', '#F8F9FB', '#1C1E22', '#17181B'], pinned: false },
  // Color themes — default style, palette pinned via CSS variables.
  { id: 'normal',   label: 'Normal',   style: 'default', swatches: ['#0A0A0A', '#181818', '#FFFFFF', '#3B82F6'], pinned: true },
  { id: 'ocean',    label: 'Ocean',    style: 'default', swatches: ['#0F172A', '#1E293B', '#F8FAFC', '#38BDF8'], pinned: true },
  { id: 'forest',   label: 'Forest',   style: 'default', swatches: ['#0F1A14', '#1B2A21', '#F3F6F4', '#22C55E'], pinned: true },
  { id: 'pastel',   label: 'Pastel',   style: 'default', swatches: ['#1A1023', '#231530', '#F3E8FF', '#C084FC'], pinned: true },
]

function paletteVars(
  [bg, surface, text, accent]: [string, string, string, string],
): Record<string, string> {
  return {
    '--bg-primary': bg,
    '--bg-secondary': surface,
    '--bg-tertiary': surface,
    '--bg-elevated': surface,
    '--text-primary': text,
    '--color-primary': accent,
    '--color-primary-hover': accent,
  }
}

/**
 * Translate a Living UI theme selection into the `craftbot-theme`
 * postMessage payload embedded apps understand ({ theme, cssVars, style }
 * — see the theme-sync script in the template's index.html). Every theme
 * bundles a style pack with a palette: CraftBot/Modern/Glass/Classic keep
 * the app's own palette and follow the host's light/dark mode; the color
 * themes and Custom pin their palette via CSS variable overrides on the
 * default style.
 */
export function buildThemeMessage(
  themeId: LivingUIThemeId,
  mode: 'dark' | 'light',
  customColors: LivingUICustomColors,
): { type: 'craftbot-theme'; theme: string; cssVars: Record<string, string>; style: LivingUIStyleId } {
  if (themeId === 'custom') {
    return {
      type: 'craftbot-theme',
      theme: 'dark', // pinned palettes are self-contained; base on dark tokens
      cssVars: paletteVars([
        customColors.bg, customColors.surface, customColors.text, customColors.accent,
      ]),
      style: 'default',
    }
  }
  const def = PRESET_THEMES.find(t => t.id === themeId) ?? PRESET_THEMES[0]
  if (!def.pinned) {
    // Empty cssVars clears any previous palette override in the app.
    return { type: 'craftbot-theme', theme: mode, cssVars: {}, style: def.style }
  }
  return {
    type: 'craftbot-theme',
    theme: 'dark',
    cssVars: paletteVars(def.swatches),
    style: def.style,
  }
}

interface Props {
  isOpen: boolean
  activeTheme: LivingUIThemeId
  customColors: LivingUICustomColors
  onSelect: (themeId: LivingUIThemeId, customColors?: LivingUICustomColors) => void
  onClose: () => void
}

export function LivingUIThemeModal({ isOpen, activeTheme, customColors, onSelect, onClose }: Props) {
  const [localColors, setLocalColors] = useState<LivingUICustomColors>(customColors)

  const handleCustomClick = () => {
    onSelect('custom', localColors)
  }

  const handleColorChange = (key: keyof LivingUICustomColors, value: string) => {
    const updated = { ...localColors, [key]: value }
    setLocalColors(updated)
    // Live-preview: if custom is already active, apply immediately
    if (activeTheme === 'custom') {
      onSelect('custom', updated)
    }
  }

  const customSwatches: [string, string, string, string] = [
    localColors.bg, localColors.surface, localColors.text, localColors.accent,
  ]

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Choose Theme" size="sm">
      <ModalBody>
        <div className={styles.themeGrid}>
          {PRESET_THEMES.map(({ id, label, hint, swatches, style }) => (
            <button
              key={id}
              type="button"
              className={`${styles.themeTile} ${activeTheme === id ? styles.themeTileActive : ''}`}
              onClick={() => onSelect(id)}
            >
              <ThemeMiniPreview style={style} swatches={swatches} />
              <span className={styles.themeLabel}>{label}</span>
              {hint && <span className={styles.themeCaption}>{hint}</span>}
              {activeTheme === id && (
                <span className={styles.themeTileCheck}>
                  <Check size={10} />
                </span>
              )}
            </button>
          ))}

          {/* Custom tile — default style with user-chosen colors */}
          <button
            type="button"
            className={`${styles.themeTile} ${activeTheme === 'custom' ? styles.themeTileActive : ''}`}
            onClick={handleCustomClick}
          >
            <ThemeMiniPreview style="default" swatches={customSwatches} />
            <span className={styles.themeLabel}>Custom</span>
            <span className={styles.themeCaption}>Your colors</span>
            {activeTheme === 'custom' && (
              <span className={styles.themeTileCheck}>
                <Check size={10} />
              </span>
            )}
          </button>
        </div>

        {/* Custom color editor — shown when custom is active */}
        {activeTheme === 'custom' && (
          <div className={styles.customColors}>
            {(
              [
                { key: 'bg',      label: 'Background' },
                { key: 'surface', label: 'Surface'    },
                { key: 'text',    label: 'Text'       },
                { key: 'accent',  label: 'Accent'     },
              ] as { key: keyof LivingUICustomColors; label: string }[]
            ).map(({ key, label }) => (
              <label key={key} className={styles.colorRow}>
                <input
                  type="color"
                  value={localColors[key]}
                  onChange={e => handleColorChange(key, e.target.value)}
                  className={styles.colorInput}
                />
                <span className={styles.colorLabel}>{label}</span>
                <span className={styles.colorValue}>{localColors[key]}</span>
              </label>
            ))}
          </div>
        )}

        <p className={styles.themeCaption}>
          CraftBot, Modern, Glass &amp; Classic follow light/dark mode &middot;
          Color themes stay fixed
        </p>
      </ModalBody>
    </Modal>
  )
}

/**
 * Tiny abstract app preview: a header bar, text lines, a surface card and an
 * accent button, drawn with the theme's colors AND its style pack's shape
 * language (radii, shadows, density, glass blur) — so the tile conveys what
 * the theme actually feels like, not just its palette. Self-contained inline
 * styles so the wizard can reuse it without CSS-module coupling.
 */
interface MiniStyleSpec {
  /** Card corner radius. */
  r: number
  /** Tile background (may layer gradients over bg). */
  canvas: (bg: string) => string
  /** Card fill (surfaces). */
  card: (surface: string, bg: string) => string
  /** Card border. */
  cardBorder: (text: string) => string | undefined
  /** Card shadow. */
  cardShadow: (text: string, bg: string) => string | undefined
  /** Extra text line (dense styles). */
  denseLines?: boolean
  /** Blur hint on surfaces (glass styles). */
  blur?: boolean
}

const MINI_SPECS: Record<LivingUIStyleId, MiniStyleSpec> = {
  default: {
    r: 4,
    canvas: bg => bg,
    card: s => s,
    cardBorder: () => undefined,
    cardShadow: () => undefined,
  },
  modern: {
    r: 7,
    canvas: bg => bg,
    card: s => s,
    cardBorder: () => undefined,
    cardShadow: () => '0 2px 5px rgba(0, 0, 0, 0.45)',
  },
  glass: {
    r: 8,
    canvas: bg =>
      `radial-gradient(40px 26px at 15% 0%, rgba(124, 58, 237, 0.45), transparent 70%),
       radial-gradient(40px 26px at 100% 45%, rgba(34, 211, 238, 0.4), transparent 70%),
       radial-gradient(36px 24px at 45% 110%, rgba(236, 72, 153, 0.32), transparent 70%),
       ${bg}`,
    card: () => 'rgba(255, 255, 255, 0.14)',
    cardBorder: () => undefined,
    cardShadow: () => undefined,
    blur: true,
  },
  classic: {
    r: 1,
    canvas: bg => bg,
    card: s => s,
    cardBorder: () => '1px solid rgba(255, 255, 255, 0.18)',
    cardShadow: () => undefined,
    denseLines: true,
  },
  velvet: {
    r: 9,
    canvas: bg =>
      `radial-gradient(44px 30px at 72% 30%, rgba(240, 111, 42, 0.5), transparent 70%),
       radial-gradient(40px 28px at 8% 95%, rgba(230, 160, 130, 0.4), transparent 70%),
       ${bg}`,
    card: () => 'rgba(255, 255, 255, 0.55)',
    cardBorder: () => undefined,
    cardShadow: () => undefined,
    blur: true,
  },
  ink: {
    r: 8,
    canvas: bg => bg,
    card: s => s,
    cardBorder: () => undefined,
    cardShadow: () => '0 1px 3px rgba(17, 17, 17, 0.14)',
  },
  acid: {
    r: 11,
    canvas: bg => bg,
    card: s => s,
    cardBorder: () => undefined,
    cardShadow: () => undefined,
  },
  blueprint: {
    r: 0,
    canvas: bg =>
      `repeating-linear-gradient(0deg, rgba(60, 60, 90, 0.12) 0 1px, transparent 1px 7px),
       repeating-linear-gradient(90deg, rgba(60, 60, 90, 0.12) 0 1px, transparent 1px 7px),
       ${bg}`,
    card: s => s,
    cardBorder: text => `1px solid ${text}44`,
    cardShadow: () => undefined,
    denseLines: true,
  },
  brutalist: {
    r: 0,
    canvas: bg => bg,
    card: s => s,
    cardBorder: text => `1.5px solid ${text}`,
    cardShadow: text => `2px 2px 0 ${text}`,
  },
  drafting: {
    r: 4,
    canvas: bg => bg,
    card: (_s, bg) => bg,
    cardBorder: text => `1px solid ${text}`,
    cardShadow: () => undefined,
  },
  clay: {
    r: 10,
    canvas: bg => bg,
    card: s => s,
    cardBorder: () => undefined,
    cardShadow: (_t, bg) =>
      bg === '#23262E'
        ? '2px 2px 4px rgba(10, 12, 18, 0.7), -2px -2px 4px rgba(60, 66, 82, 0.55)'
        : '2px 2px 4px rgba(163, 169, 184, 0.7), -2px -2px 4px rgba(255, 255, 255, 0.95)',
  },
  atelier: {
    r: 5,
    canvas: bg => `linear-gradient(180deg, rgba(255, 255, 255, 0.55) 0%, rgba(150, 158, 172, 0.35) 100%), ${bg}`,
    card: s => s,
    cardBorder: text => `1px solid ${text}22`,
    cardShadow: () => '0 1px 2px rgba(20, 22, 26, 0.12)',
  },
}

export function ThemeMiniPreview({
  style,
  swatches,
}: {
  style: LivingUIStyleId
  swatches: [string, string, string, string]
}) {
  const [bg, surface, text, accent] = swatches
  const spec = MINI_SPECS[style] ?? MINI_SPECS.default
  const r = spec.r
  const cardBg = spec.card(surface, bg)
  const cardBorder = spec.cardBorder(text)
  const cardShadow = spec.cardShadow(text, bg)
  const block: React.CSSProperties = { position: 'absolute', display: 'block' }
  return (
    <span
      aria-hidden
      style={{
        position: 'relative',
        display: 'block',
        width: 68,
        height: 42,
        borderRadius: Math.max(r + 2, 2),
        background: spec.canvas(bg),
        border: '1px solid rgba(127, 127, 127, 0.25)',
        overflow: 'hidden',
        flexShrink: 0,
      }}
    >
      {/* header bar */}
      <span
        style={{
          ...block,
          top: 4,
          left: 4,
          right: 4,
          height: 6,
          borderRadius: r,
          background: cardBg,
          border: cardBorder,
          backdropFilter: spec.blur ? 'blur(2px)' : undefined,
        }}
      />
      {/* text lines — an extra one for dense styles */}
      <span style={{ ...block, top: spec.denseLines ? 13 : 14, left: 5, width: '42%', height: 3, borderRadius: 2, background: text, opacity: 0.9 }} />
      <span style={{ ...block, top: spec.denseLines ? 18 : 20, left: 5, width: '60%', height: 3, borderRadius: 2, background: text, opacity: 0.35 }} />
      {spec.denseLines && (
        <span style={{ ...block, top: 23, left: 5, width: '50%', height: 3, borderRadius: 2, background: text, opacity: 0.35 }} />
      )}
      {/* surface card + accent button */}
      <span
        style={{
          ...block,
          bottom: 4,
          left: 4,
          right: 24,
          height: 9,
          borderRadius: r,
          background: cardBg,
          border: cardBorder,
          boxShadow: cardShadow,
          backdropFilter: spec.blur ? 'blur(2px)' : undefined,
        }}
      />
      <span
        style={{
          ...block,
          bottom: 4,
          right: 4,
          width: 16,
          height: 9,
          borderRadius: r,
          background: accent,
          border: style === 'drafting' ? `1px solid ${text}` : undefined,
          boxShadow: style === 'brutalist' ? `2px 2px 0 ${text}` : undefined,
        }}
      />
    </span>
  )
}
