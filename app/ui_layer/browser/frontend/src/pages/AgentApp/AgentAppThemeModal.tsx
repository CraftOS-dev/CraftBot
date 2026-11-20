import { useEffect, useState } from 'react'
import { Check } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Modal, ModalBody } from '../../components/ui/Modal'
import {
  PRESET_THEMES, ThemeMiniPreview,
} from './themeCatalog'
import type { AgentAppThemeId, AgentAppCustomColors } from './themeCatalog'
import styles from './AgentAppPage.module.css'

interface Props {
  isOpen: boolean
  activeTheme: AgentAppThemeId
  customColors: AgentAppCustomColors
  onSelect: (themeId: AgentAppThemeId, customColors?: AgentAppCustomColors) => void
  onClose: () => void
  disabled?: boolean
  error?: string
}

export function AgentAppThemeModal({ isOpen, activeTheme, customColors, onSelect, onClose, disabled, error }: Props) {
  const { t } = useTranslation(['agentapp', 'common'])
  const [localColors, setLocalColors] = useState<AgentAppCustomColors>(customColors)
  useEffect(() => { setLocalColors(customColors) }, [customColors])

  const handleColorChange = (key: keyof AgentAppCustomColors, value: string) => {
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
    <Modal isOpen={isOpen} onClose={onClose} title={t('agentapp:themeModal.title')} size="md">
      <ModalBody>
        <div className={styles.themeGrid}>
          {PRESET_THEMES.map(({ id, labelKey, descriptionKey, swatches }) => (
            <button
              key={id}
              type="button"
              disabled={disabled}
              aria-pressed={activeTheme === id}
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
            disabled={disabled}
            aria-pressed={activeTheme === 'custom'}
            className={`${styles.themeTile} ${activeTheme === 'custom' ? styles.themeTileActive : ''}`}
            onClick={() => onSelect('custom', localColors)}
          >
            <ThemeMiniPreview style="craftbot" swatches={customSwatches} />
            <span className={styles.themeLabel}>{t('agentapp:themeModal.custom')}</span>
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
                { key: 'bg',      label: t('agentapp:themeModal.colorBackground') },
                { key: 'surface', label: t('agentapp:themeModal.colorSurface')    },
                { key: 'text',    label: t('agentapp:themeModal.colorText')       },
                { key: 'accent',  label: t('agentapp:themeModal.colorAccent')     },
              ] as { key: keyof AgentAppCustomColors; label: string }[]
            ).map(({ key, label }) => (
              <label key={key} className={styles.colorRow}>
                <input
                  type="color"
                  disabled={disabled}
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
          {t('agentapp:themeModal.caption')}
        </p>
        {error && <p role="alert">{error}</p>}
      </ModalBody>
    </Modal>
  )
}
