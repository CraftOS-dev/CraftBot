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
  // Style-bearing themes — CraftBot palette, follow light/dark mode.
  { id: 'craftbot', label: 'CraftBot', hint: 'The baseline',     style: 'default', swatches: ['#191919', '#202020', '#E6E6E4', '#FF4F18'], pinned: false },
  { id: 'modern',   label: 'Modern',   hint: 'Soft & roomy',     style: 'modern',  swatches: ['#191919', '#202020', '#E6E6E4', '#FF4F18'], pinned: false },
  { id: 'glass',    label: 'Glass',    hint: 'Translucent blur', style: 'glass',   swatches: ['#101018', '#2B2B33', '#F2F2F5', '#FF4F18'], pinned: false },
  { id: 'classic',  label: 'Classic',  hint: 'Flat & dense',     style: 'classic', swatches: ['#0A0A0A', '#1C1C1C', '#EDEDED', '#FF4F18'], pinned: false },
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
          {PRESET_THEMES.map(({ id, label, hint, swatches }) => (
            <button
              key={id}
              type="button"
              className={`${styles.themeTile} ${activeTheme === id ? styles.themeTileActive : ''}`}
              onClick={() => onSelect(id)}
            >
              <SwatchRow swatches={swatches} />
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
            <SwatchRow swatches={customSwatches} />
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

function SwatchRow({ swatches }: { swatches: [string, string, string, string] }) {
  return (
    <div className={styles.swatchRow}>
      {swatches.map((color, i) => (
        <span key={i} className={styles.swatch} style={{ background: color }} />
      ))}
    </div>
  )
}
