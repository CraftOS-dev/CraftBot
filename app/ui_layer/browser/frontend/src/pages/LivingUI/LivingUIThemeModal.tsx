import { useState } from 'react'
import { Check } from 'lucide-react'
import { Modal, ModalBody } from '../../components/ui/Modal'
import styles from './LivingUIPage.module.css'

export type LivingUIThemeId = 'craftbot' | 'normal' | 'ocean' | 'forest' | 'pastel' | 'custom'

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

const PRESET_THEMES: { id: Exclude<LivingUIThemeId, 'custom'>; label: string; swatches: [string, string, string, string] }[] = [
  { id: 'craftbot', label: 'CraftBot', swatches: ['#191919', '#202020', '#E6E6E4', '#FF4F18'] },
  { id: 'normal',   label: 'Normal',   swatches: ['#0A0A0A', '#181818', '#FFFFFF', '#3B82F6'] },
  { id: 'ocean',    label: 'Ocean',    swatches: ['#0F172A', '#1E293B', '#F8FAFC', '#38BDF8'] },
  { id: 'forest',   label: 'Forest',   swatches: ['#0F1A14', '#1B2A21', '#F3F6F4', '#22C55E'] },
  { id: 'pastel',   label: 'Pastel',   swatches: ['#1A1023', '#231530', '#F3E8FF', '#C084FC'] },
]

interface Props {
  isOpen: boolean
  activeTheme: LivingUIThemeId
  customColors: LivingUICustomColors
  onSelect: (themeId: LivingUIThemeId, customColors?: LivingUICustomColors) => void
  onClose: () => void
}

export function LivingUIThemeModal({ isOpen, activeTheme, customColors, onSelect, onClose }: Props) {
  const [localColors, setLocalColors] = useState<LivingUICustomColors>(customColors)

  const handlePresetClick = (id: Exclude<LivingUIThemeId, 'custom'>) => {
    onSelect(id)
  }

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
          {PRESET_THEMES.map(({ id, label, swatches }) => (
            <button
              key={id}
              type="button"
              className={`${styles.themeTile} ${activeTheme === id ? styles.themeTileActive : ''}`}
              onClick={() => handlePresetClick(id)}
            >
              <SwatchRow swatches={swatches} />
              <span className={styles.themeLabel}>{label}</span>
              {activeTheme === id && (
                <span className={styles.themeTileCheck}>
                  <Check size={10} />
                </span>
              )}
            </button>
          ))}

          {/* Custom tile */}
          <button
            type="button"
            className={`${styles.themeTile} ${activeTheme === 'custom' ? styles.themeTileActive : ''}`}
            onClick={handleCustomClick}
          >
            <SwatchRow swatches={customSwatches} />
            <span className={styles.themeLabel}>Custom</span>
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
          Themes adapt to light/dark mode &middot; Custom stays fixed
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
