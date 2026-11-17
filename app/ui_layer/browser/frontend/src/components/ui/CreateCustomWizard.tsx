import { useNavigate } from 'react-router-dom'
import React, { useEffect, useMemo, useRef, useState } from 'react'
import {
  Box, ChevronDown, Loader2, Paperclip,
  Sparkles, Upload, X,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button } from './Button'
import { AGENT_APP_ICONS } from './AgentAppIcon'
import { PRESET_THEMES, ThemeMiniPreview } from '../../pages/AgentApp/themeCatalog'
import { formatNumber } from '../../i18n/format'
import { BuildCheckpoints } from '../../features/agentApps/BuildCheckpoints'
import styles from './CreateCustomWizard.module.css'

/**
 * The Build tab of the Add Agent App modal:
 *
 *   1. CONFIGURE  name/description, layout silhouette, theme, icon,
 *                 access mode, reference attachments
 *   2. BUILD      the builder agent starts, and the build's stops for the
 *                 person show here: its questions, then the requirements it
 *                 wrote, to edit and approve. On approval the caller's view
 *                 moves to the build.
 *
 * The builder does the thinking (the framework's creator skill and its
 * checkpoints); this component owns only the configure form.
 */

interface CreateCustomWizardProps {
  onClose: () => void
  /** Start the build; resolves with its session. */
  onConfigure: (config: Record<string, unknown>, files: File[], icon: File | null) => Promise<string>
  disabled?: boolean
}

const MAX_WORDS = 5000

function countWords(text: string): number {
  const trimmed = text.trim()
  if (!trimmed) return 0
  return trimmed.split(/\s+/).length
}

// ── configure-step vocabulary ───────────────────────────────────────────────

// Labels live in the `components:createCustomWizard.layout.*` catalog, keyed here.
const LAYOUTS: { id: string; labelKey: string }[] = [
  { id: 'free', labelKey: 'free' },
  { id: 'sidebar-body', labelKey: 'sidebarBody' },
  { id: 'topnav-body', labelKey: 'topnavBody' },
  { id: 'hero-cards', labelKey: 'heroCards' },
  { id: 'split-view', labelKey: 'splitView' },
  { id: 'dashboard', labelKey: 'dashboard' },
  { id: 'columns-board', labelKey: 'columnsBoard' },
  { id: 'one-page', labelKey: 'onePage' },
]

// Miniature layout silhouettes, drawn as SVG rect compositions.
function LayoutSilhouette({ id }: { id: string }) {
  const f = 'currentColor'
  const parts: Record<string, React.ReactNode> = {
    'sidebar-body': (
      <>
        <rect x="2" y="2" width="14" height="40" rx="2" fill={f} opacity="0.55" />
        <rect x="19" y="2" width="43" height="40" rx="2" fill={f} opacity="0.25" />
      </>
    ),
    'topnav-body': (
      <>
        <rect x="2" y="2" width="60" height="9" rx="2" fill={f} opacity="0.55" />
        <rect x="2" y="14" width="60" height="28" rx="2" fill={f} opacity="0.25" />
      </>
    ),
    'hero-cards': (
      <>
        <rect x="2" y="2" width="60" height="17" rx="2" fill={f} opacity="0.55" />
        <rect x="2" y="23" width="18" height="19" rx="2" fill={f} opacity="0.3" />
        <rect x="23" y="23" width="18" height="19" rx="2" fill={f} opacity="0.3" />
        <rect x="44" y="23" width="18" height="19" rx="2" fill={f} opacity="0.3" />
      </>
    ),
    'split-view': (
      <>
        <rect x="2" y="2" width="24" height="40" rx="2" fill={f} opacity="0.45" />
        <rect x="29" y="2" width="33" height="40" rx="2" fill={f} opacity="0.25" />
        <rect x="5" y="6" width="18" height="4" rx="1" fill={f} opacity="0.7" />
        <rect x="5" y="13" width="18" height="4" rx="1" fill={f} opacity="0.5" />
        <rect x="5" y="20" width="18" height="4" rx="1" fill={f} opacity="0.5" />
      </>
    ),
    dashboard: (
      <>
        <rect x="2" y="2" width="18" height="11" rx="2" fill={f} opacity="0.55" />
        <rect x="23" y="2" width="18" height="11" rx="2" fill={f} opacity="0.55" />
        <rect x="44" y="2" width="18" height="11" rx="2" fill={f} opacity="0.55" />
        <rect x="2" y="16" width="29" height="26" rx="2" fill={f} opacity="0.25" />
        <rect x="34" y="16" width="28" height="26" rx="2" fill={f} opacity="0.25" />
      </>
    ),
    'columns-board': (
      <>
        <rect x="2" y="2" width="18" height="40" rx="2" fill={f} opacity="0.35" />
        <rect x="23" y="2" width="18" height="40" rx="2" fill={f} opacity="0.35" />
        <rect x="44" y="2" width="18" height="40" rx="2" fill={f} opacity="0.35" />
        <rect x="5" y="6" width="12" height="7" rx="1" fill={f} opacity="0.75" />
        <rect x="26" y="6" width="12" height="7" rx="1" fill={f} opacity="0.75" />
        <rect x="26" y="16" width="12" height="7" rx="1" fill={f} opacity="0.6" />
      </>
    ),
    'one-page': (
      <rect x="12" y="2" width="40" height="40" rx="2" fill={f} opacity="0.4" />
    ),
    free: (
      <rect
        x="3" y="3" width="58" height="38" rx="3" fill="none" stroke={f}
        strokeOpacity="0.55" strokeWidth="2" strokeDasharray="5 4"
      />
    ),
  }
  return (
    <svg viewBox="0 0 64 44" className={styles.silhouetteSvg} aria-hidden="true">
      {parts[id] || parts.free}
    </svg>
  )
}

const ACCESS_CHOICES: { value: 'none' | 'multi-user'; labelKey: 'none' | 'multiUser' }[] = [
  { value: 'none', labelKey: 'none' },
  { value: 'multi-user', labelKey: 'multiUser' },
]

// ── component ───────────────────────────────────────────────────────────────

export function CreateCustomWizard({ onClose, onConfigure, disabled }: CreateCustomWizardProps) {
  const { t } = useTranslation(['components', 'common', 'agentapp'])

  // Explicit (type-checked) key literals for the configure-step vocabulary.
  const layoutLabels: Record<string, string> = {
    free: t('components:createCustomWizard.layout.free'),
    sidebarBody: t('components:createCustomWizard.layout.sidebarBody'),
    topnavBody: t('components:createCustomWizard.layout.topnavBody'),
    heroCards: t('components:createCustomWizard.layout.heroCards'),
    splitView: t('components:createCustomWizard.layout.splitView'),
    dashboard: t('components:createCustomWizard.layout.dashboard'),
    columnsBoard: t('components:createCustomWizard.layout.columnsBoard'),
    onePage: t('components:createCustomWizard.layout.onePage'),
  }
  const accessLabels: Record<'none' | 'multiUser', string> = {
    none: t('components:createCustomWizard.access.none'),
    multiUser: t('components:createCustomWizard.access.multiUser'),
  }

  const navigate = useNavigate()
  const [sessionId, setSessionId] = useState<string>()

  // — configure state —
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [errors, setErrors] = useState<{ name?: string; description?: string }>({})
  const [layout, setLayout] = useState('free')
  const [uiTheme, setUiTheme] = useState('craftbot')
  const [authMode, setAuthMode] = useState<'none' | 'multi-user'>('none')
  const [iconChoice, setIconChoice] = useState<string | null>(null)
  const [iconFile, setIconFile] = useState<File | null>(null)
  const [iconPreview, setIconPreview] = useState<string | null>(null)
  const [files, setFiles] = useState<File[]>([])
  const [iconOpen, setIconOpen] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const nameInputRef = useRef<HTMLInputElement>(null)
  const wordCount = useMemo(() => countWords(description), [description])

  useEffect(() => {
    setTimeout(() => nameInputRef.current?.focus(), 100)
  }, [])

  // ── configure helpers ──────────────────────────────────────────────────

  const pickIconFile = () => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = '.png,.svg,.ico,.jpg,.jpeg,.webp'
    input.onchange = e => {
      const file = (e.target as HTMLInputElement).files?.[0]
      if (!file) return
      setIconFile(file)
      setIconChoice(null)
      setIconPreview(prev => {
        if (prev) URL.revokeObjectURL(prev)
        return URL.createObjectURL(file)
      })
    }
    input.click()
  }

  const addReferenceFiles = (list: FileList | File[]) => {
    const accepted = Array.from(list).filter(f => f.size > 0)
    if (accepted.length === 0) return
    setFiles(prev => {
      const names = new Set(prev.map(f => f.name))
      return [...prev, ...accepted.filter(f => !names.has(f.name))]
    })
  }

  const validate = (): boolean => {
    const next: { name?: string; description?: string } = {}
    if (!name.trim()) next.name = t('components:createCustomWizard.nameRequired')
    else if (name.length > 50) next.name = t('components:createCustomWizard.nameTooLong')
    if (!description.trim()) next.description = t('components:createCustomWizard.descRequired')
    else if (description.trim().length < 10) next.description = t('components:createCustomWizard.descTooShort')
    else if (wordCount > MAX_WORDS) next.description = t('components:createCustomWizard.descTooLong', { max: formatNumber(MAX_WORDS) })
    setErrors(next)
    return Object.keys(next).length === 0
  }

  const buildConfig = () => ({
    name: name.trim(),
    description: description.trim(),
    layout,
    uiTheme,
    // Every preset is a kit style pack; the backend stamps it at scaffold.
    stylePack: uiTheme,
    authMode,
    icon: iconFile ? null : iconChoice, // an uploaded icon wins server-side
    attachments: files.map(f => ({ name: f.name, kind: 'reference' })),
  })

  const handleNext = async () => {
    if (disabled || uploading) return
    if (!validate()) return
    setUploading(true); setUploadError(null)
    try { setSessionId(await onConfigure(buildConfig(), files, iconFile)) }
    catch (error) { setUploadError(error instanceof Error ? error.message : String(error)) }
    finally { setUploading(false) }
  }

  // ── render ──────────────────────────────────────────────────────────────

  if (sessionId) {
    const openBuild = () => { navigate(`/session/${sessionId}`); onClose() }
    return <BuildCheckpoints sessionId={sessionId} onApproved={openBuild} onOpenBuild={openBuild} />
  }

  // step === 'configure'
  return (
    <div className={styles.wizardScroll}>
      <div className={styles.configForm}>
        <div className={styles.configInner}>
        <div className={styles.formGroup}>
          <label htmlFor="cw-name" className={styles.label}>
            {t('components:createCustomWizard.projectName')} <span className={styles.required}>*</span>
          </label>
          <div className={styles.nameRow}>
            <div className={styles.iconDropdownWrap}>
              <button
                type="button"
                className={styles.iconSquare}
                onClick={() => setIconOpen(v => !v)}
                title={t('components:createCustomWizard.iconTitle')}
              >
                {iconPreview ? (
                  <img src={iconPreview} alt={t('components:createCustomWizard.iconAlt')} className={styles.iconPreview} />
                ) : iconChoice ? (
                  (() => {
                    const Cmp = AGENT_APP_ICONS[iconChoice.slice(7)]
                    return Cmp ? <Cmp size={16} /> : <Box size={16} />
                  })()
                ) : (
                  <Box size={16} />
                )}
                <ChevronDown size={11} className={styles.iconSquareChevron} />
              </button>
              {iconOpen && (
                <div className={styles.iconPanel}>
                  <button
                    type="button"
                    className={styles.iconUploadRow}
                    onClick={() => { pickIconFile(); setIconOpen(false) }}
                  >
                    <Upload size={13} /> {t('components:createCustomWizard.uploadFavicon')}
                  </button>
                  <div className={styles.iconGrid}>
                    {Object.entries(AGENT_APP_ICONS).map(([iconName, Cmp]) => {
                      const value = `lucide:${iconName}`
                      return (
                        <button
                          key={iconName}
                          type="button"
                          className={`${styles.iconCell} ${iconChoice === value ? styles.iconCellActive : ''}`}
                          onClick={() => {
                            setIconChoice(prev => (prev === value ? null : value))
                            setIconFile(null)
                            setIconPreview(prev => {
                              if (prev) URL.revokeObjectURL(prev)
                              return null
                            })
                            setIconOpen(false)
                          }}
                        >
                          <Cmp size={15} />
                        </button>
                      )
                    })}
                  </div>
                </div>
              )}
            </div>
            <input
              ref={nameInputRef}
              id="cw-name"
              type="text"
              className={`${styles.input} ${errors.name ? styles.inputError : ''}`}
              placeholder={t('components:createCustomWizard.namePlaceholder')}
              value={name}
              onChange={e => setName(e.target.value)}
              maxLength={50}
            />
          </div>
          {errors.name && <span className={styles.errorText}>{errors.name}</span>}
        </div>

        <div className={styles.formGroup}>
          <label htmlFor="cw-desc" className={styles.label}>
            {t('components:createCustomWizard.descLabel')} <span className={styles.required}>*</span>
          </label>
          <textarea
            id="cw-desc"
            className={`${styles.textarea} ${errors.description ? styles.inputError : ''}`}
            placeholder={t('components:createCustomWizard.descPlaceholder')}
            value={description}
            onChange={e => setDescription(e.target.value)}
            rows={6}
          />
          <div className={styles.fieldFooter}>
            <span className={`${styles.wordCount} ${wordCount > MAX_WORDS ? styles.wordCountError : ''}`}>
              {t('components:createCustomWizard.wordCount', {
                words: formatNumber(wordCount),
                max: formatNumber(MAX_WORDS),
              })}
            </span>
          </div>
          {errors.description && <span className={styles.errorText}>{errors.description}</span>}
        </div>

        <div className={styles.formGroup}>
          <label className={styles.label}>{t('components:createCustomWizard.referenceFiles')}</label>
          <div
            className={styles.dropZone}
            onClick={() => {
              const input = document.createElement('input')
              input.type = 'file'
              input.multiple = true
              input.accept = '.png,.jpg,.jpeg,.webp,.gif,.pdf,.md,.txt,.docx'
              input.onchange = e => {
                const list = (e.target as HTMLInputElement).files
                if (list) addReferenceFiles(list)
              }
              input.click()
            }}
            onDragOver={e => e.preventDefault()}
            onDrop={e => {
              e.preventDefault()
              addReferenceFiles(e.dataTransfer.files)
            }}
          >
            <Paperclip size={16} className={styles.dropIcon} />
            <span>{t('components:createCustomWizard.dropReference')}</span>
          </div>
          {files.length > 0 && (
            <div className={styles.fileList}>
              {files.map(f => (
                <span key={f.name} className={styles.fileChip}>
                  {f.name}
                  <button
                    type="button"
                    className={styles.fileRemove}
                    onClick={() => setFiles(prev => prev.filter(x => x.name !== f.name))}
                  >
                    <X size={11} />
                  </button>
                </span>
              ))}
            </div>
          )}
          {uploadError && <span role="alert" className={styles.errorText}>{uploadError}</span>}
        </div>

        <div className={styles.formGroup}>
          <label className={styles.label}>{t('components:createCustomWizard.layoutLabel')}</label>
          <div className={styles.layoutGrid}>
            {LAYOUTS.map(l => (
              <button
                key={l.id}
                type="button"
                className={`${styles.layoutCard} ${layout === l.id ? styles.layoutCardActive : ''}`}
                onClick={() => setLayout(l.id)}
              >
                <LayoutSilhouette id={l.id} />
                <span className={styles.layoutLabel}>{layoutLabels[l.labelKey]}</span>
              </button>
            ))}
          </div>
        </div>

        <div className={styles.formGroup}>
          <label className={styles.label}>{t('components:createCustomWizard.themeLabel')}</label>
          <div className={styles.themeGrid}>
            {PRESET_THEMES.map(theme => (
              <button
                key={theme.id}
                type="button"
                className={`${styles.themeCard} ${uiTheme === theme.id ? styles.themeCardActive : ''}`}
                onClick={() => setUiTheme(theme.id)}
                title={t(theme.descriptionKey)}
              >
                <ThemeMiniPreview style={theme.id} swatches={theme.swatches} />
                <span className={styles.layoutLabel}>{t(theme.labelKey)}</span>
              </button>
            ))}
          </div>
        </div>

        <div className={styles.formGroup}>
          <label className={styles.label}>{t('components:createCustomWizard.accessLabel')}</label>
          <div className={styles.accessRow}>
            {ACCESS_CHOICES.map(choice => (
              <button
                key={choice.value}
                type="button"
                className={`${styles.chip} ${authMode === choice.value ? styles.chipActive : ''}`}
                onClick={() => setAuthMode(choice.value)}
              >
                {accessLabels[choice.labelKey]}
              </button>
            ))}
          </div>
        </div>
        </div>
      </div>

      <div className={styles.footer}>
        <Button variant="secondary" type="button" onClick={onClose}>{t('common:actions.cancel')}</Button>
        <Button
          variant="primary"
          type="button"
          icon={uploading ? <Loader2 size={16} className={styles.spinner} /> : <Sparkles size={16} />}
          onClick={() => void handleNext()}
          disabled={uploading || disabled}
        >
          {uploading ? t('common:status.uploading') : t('common:actions.next')}
        </Button>
      </div>
    </div>
  )
}
