import { useState } from 'react'
import { Check } from 'lucide-react'
import { useTranslation } from 'react-i18next'
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
  const { t } = useTranslation(['livingui', 'common'])
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
    <Modal isOpen={isOpen} onClose={onClose} title={t('livingui:themeModal.title')} size="md">
      <ModalBody>
        <div className={styles.themeGrid}>
          {PRESET_THEMES.map(({ id, labelKey, descriptionKey, swatches }) => (
            <button
              key={id}
              type="button"
              className={`${styles.themeTile} ${activeTheme === id ? styles.themeTileActive : ''}`}
              onClick={() => onSelect(id)}
              title={t(descriptionKey) || t(labelKey)}
            >
              <ThemeMiniPreview style={id} swatches={swatches} />
              <span className={styles.themeLabel}>{t(labelKey)}</span>
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
            <span className={styles.themeLabel}>{t('livingui:themeModal.custom')}</span>
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
                { key: 'bg',      label: t('livingui:themeModal.colorBackground') },
                { key: 'surface', label: t('livingui:themeModal.colorSurface')    },
                { key: 'text',    label: t('livingui:themeModal.colorText')       },
                { key: 'accent',  label: t('livingui:themeModal.colorAccent')     },
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
          {t('livingui:themeModal.caption')}
        </p>
      </ModalBody>
    </Modal>
  )
}
