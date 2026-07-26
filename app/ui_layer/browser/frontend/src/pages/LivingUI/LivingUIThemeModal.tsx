import { useState } from 'react'
import { Check } from 'lucide-react'
import { Modal, ModalBody } from '../../components/ui/Modal'
import {
  PRESET_THEMES, ThemeMiniPreview, DEFAULT_CUSTOM_COLORS,
} from './themeCatalog'
import type { LivingUIThemeId, LivingUICustomColors } from './themeCatalog'
import styles from './LivingUIPage.module.css'

// Re-exported so existing imports keep working; the catalog is the source
// of truth shared with the create wizard.
export { DEFAULT_CUSTOM_COLORS }
export type { LivingUIThemeId, LivingUICustomColors }

interface Props {
  isOpen: boolean
  activeTheme: LivingUIThemeId
  customColors: LivingUICustomColors
  onSelect: (themeId: LivingUIThemeId, customColors?: LivingUICustomColors) => void
  onClose: () => void
}

export function LivingUIThemeModal({ isOpen, activeTheme, customColors, onSelect, onClose }: Props) {
  const [localColors, setLocalColors] = useState<LivingUICustomColors>(customColors)

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
    <Modal isOpen={isOpen} onClose={onClose} title="Choose Theme" size="md">
      <ModalBody>
        <div className={styles.themeGrid}>
          {PRESET_THEMES.map(({ id, label, hint, swatches }) => (
            <button
              key={id}
              type="button"
              className={`${styles.themeTile} ${activeTheme === id ? styles.themeTileActive : ''}`}
              onClick={() => onSelect(id)}
              title={hint || label}
            >
              <ThemeMiniPreview style={id} swatches={swatches} />
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
            onClick={() => onSelect('custom', localColors)}
          >
            <ThemeMiniPreview style="craftbot" swatches={customSwatches} />
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
