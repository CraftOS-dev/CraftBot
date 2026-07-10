import React, { useState } from 'react'
import { Check } from 'lucide-react'
import { Modal, ModalBody } from '../../components/ui/Modal'
import styles from './LivingUIPage.module.css'

export type LivingUIThemeId =
  | 'craftbot'
  | 'modern'
  | 'glass'
  | 'classic'
  | 'normal'
  | 'ocean'
  | 'forest'
  | 'pastel'
  | 'custom'

/** Style packs shipped in every Living UI (token overrides in the
 * template's themes.css). Each THEME below bundles one of these with a
 * palette — the user never picks them separately. */
export type LivingUIStyleId = 'default' | 'modern' | 'glass' | 'classic'

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
  { id: 'craftbot', label: 'CraftBot', hint: 'The baseline',    style: 'default', swatches: ['#191919', '#202020', '#E6E6E4', '#FF4F18'], pinned: false },
  { id: 'modern',   label: 'Modern',   hint: 'Airy indigo',     style: 'modern',  swatches: ['#12141D', '#1A1D2A', '#ECEEF8', '#7C8AFF'], pinned: false },
  { id: 'glass',    label: 'Glass',    hint: 'Aurora glass',    style: 'glass',   swatches: ['#0B0E1C', '#1C2340', '#F5F7FE', '#22D3EE'], pinned: false },
  { id: 'classic',  label: 'Classic',  hint: 'Flat & dense',    style: 'classic', swatches: ['#131311', '#1C1B17', '#F1EDE2', '#E8A317'], pinned: false },
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
export function ThemeMiniPreview({
  style,
  swatches,
}: {
  style: LivingUIStyleId
  swatches: [string, string, string, string]
}) {
  const [bg, surface, text, accent] = swatches
  const r = style === 'modern' ? 7 : style === 'glass' ? 8 : style === 'classic' ? 1 : 4
  const glass = style === 'glass'
  const classic = style === 'classic'
  const cardBg = glass ? 'rgba(255, 255, 255, 0.14)' : surface
  const cardBorder = classic ? '1px solid rgba(255, 255, 255, 0.18)' : undefined
  const cardShadow = style === 'modern' ? '0 2px 5px rgba(0, 0, 0, 0.45)' : undefined
  const block: React.CSSProperties = { position: 'absolute', display: 'block' }
  return (
    <span
      aria-hidden
      style={{
        position: 'relative',
        display: 'block',
        width: 68,
        height: 42,
        borderRadius: r + 2,
        background: glass
          ? `radial-gradient(40px 26px at 15% 0%, rgba(124, 58, 237, 0.45), transparent 70%),
             radial-gradient(40px 26px at 100% 45%, rgba(34, 211, 238, 0.4), transparent 70%),
             radial-gradient(36px 24px at 45% 110%, rgba(236, 72, 153, 0.32), transparent 70%),
             ${bg}`
          : bg,
        border: '1px solid rgba(255, 255, 255, 0.08)',
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
          backdropFilter: glass ? 'blur(2px)' : undefined,
        }}
      />
      {/* text lines — denser for classic, roomier for modern */}
      <span style={{ ...block, top: classic ? 13 : 14, left: 5, width: '42%', height: 3, borderRadius: 2, background: text, opacity: 0.9 }} />
      <span style={{ ...block, top: classic ? 18 : 20, left: 5, width: '60%', height: 3, borderRadius: 2, background: text, opacity: 0.35 }} />
      {classic && (
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
          backdropFilter: glass ? 'blur(2px)' : undefined,
        }}
      />
      <span
        style={{
          ...block,
          bottom: 4,
          right: 4,
          width: 16,
          height: 9,
          borderRadius: classic ? 1 : r,
          background: accent,
        }}
      />
    </span>
  )
}
