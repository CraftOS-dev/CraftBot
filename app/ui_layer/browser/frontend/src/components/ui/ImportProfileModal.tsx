import { useState, useEffect } from 'react'
import { Loader2, AlertTriangle, Package, Wrench, Server, Layout, FileText } from 'lucide-react'
import { useTranslation, Trans } from 'react-i18next'
import { Button } from './Button'
import { Modal, ModalBody, ModalFooter } from './Modal'
import { formatDate as formatDateI18n, formatList } from '../../i18n/format'
import styles from './ImportProfileModal.module.css'

export type ImportMode = 'replace' | 'overwrite'

export interface ProfileBundleManifest {
  name: string
  description?: string
  source_app_version?: string
  created_at?: string
  contents: {
    agent_name?: string
    md_files?: string[]
    skills?: string[]
    mcp_servers?: string[]
    agent_app_apps?: string[]
  }
}

export interface ProfileBundlePreview {
  skills_already_installed: string[]
  mcp_already_installed: string[]
  mcp_needs_env: Array<{ name: string; env_keys: string[] }>
}

export interface ImportProfileModalProps {
  isOpen: boolean
  manifest: ProfileBundleManifest | null
  preview: ProfileBundlePreview | null
  isApplying: boolean
  error?: string | null
  onCancel: () => void
  onApply: (mode: ImportMode) => void
}

function formatDate(iso?: string): string {
  if (!iso) return ''
  try {
    return formatDateI18n(new Date(iso), {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    })
  } catch {
    return iso
  }
}

function SectionRow({
  icon,
  label,
  items,
  conflicts,
}: {
  icon: React.ReactNode
  label: string
  items: string[]
  conflicts?: string[]
}) {
  const { t } = useTranslation(['components', 'common'])
  if (items.length === 0) return null
  const conflictSet = new Set(conflicts ?? [])
  return (
    <div className={styles.section}>
      <div className={styles.sectionLabel}>
        {icon}
        <span>{label}</span>
        <span className={styles.sectionCount}>({items.length})</span>
      </div>
      <div className={styles.chips}>
        {items.map(name => (
          <span
            key={name}
            className={`${styles.chip} ${conflictSet.has(name) ? styles.chipConflict : ''}`}
            title={conflictSet.has(name) ? t('components:importProfileModal.alreadyInstalledLocally') : undefined}
          >
            {name}
          </span>
        ))}
      </div>
    </div>
  )
}

export function ImportProfileModal({
  isOpen,
  manifest,
  preview,
  isApplying,
  error,
  onCancel,
  onApply,
}: ImportProfileModalProps) {
  const { t } = useTranslation(['components', 'common'])
  const [mode, setMode] = useState<ImportMode>('replace')

  useEffect(() => {
    if (isOpen) setMode('replace')
  }, [isOpen])

  const contents = manifest?.contents ?? {}
  const skills = contents.skills ?? []
  const mcps = contents.mcp_servers ?? []
  const apps = contents.agent_app_apps ?? []
  const mds = contents.md_files ?? []

  const title = manifest
    ? t('components:importProfileModal.titleNamed', { name: manifest.name })
    : t('components:importProfileModal.titleDefault')

  return (
    <Modal
      isOpen={isOpen}
      onClose={isApplying ? () => undefined : onCancel}
      title={title}
      size="md"
      closeOnOverlayClick={!isApplying}
      closeDisabled={isApplying}
    >
      <ModalBody className={styles.body}>
        {!manifest && !error && (
          <div className={styles.centered}>
            <Loader2 size={20} className={styles.spinning} />
            <span>{t('components:importProfileModal.readingBundle')}</span>
          </div>
        )}

        {error && (
          <div className={styles.error}>
            <AlertTriangle size={16} />
            <span>{error}</span>
          </div>
        )}

        {manifest && (
          <>
            <div className={styles.meta}>
              {manifest.source_app_version && (
                <span>{t('components:importProfileModal.madeWith', { version: manifest.source_app_version })}</span>
              )}
              {manifest.created_at && <span>· {formatDate(manifest.created_at)}</span>}
              {contents.agent_name && (
                <span>· {t('components:importProfileModal.fromAgent', { name: contents.agent_name })}</span>
              )}
            </div>

            {manifest.description && (
              <p className={styles.description}>{manifest.description}</p>
            )}

            <SectionRow
              icon={<FileText size={14} />}
              label={t('components:importProfileModal.personalityFiles')}
              items={mds}
            />
            <SectionRow
              icon={<Wrench size={14} />}
              label={t('components:importProfileModal.skills')}
              items={skills}
              conflicts={preview?.skills_already_installed}
            />
            <SectionRow
              icon={<Server size={14} />}
              label={t('components:importProfileModal.mcpServers')}
              items={mcps}
              conflicts={preview?.mcp_already_installed}
            />
            <SectionRow
              icon={<Layout size={14} />}
              label={t('components:importProfileModal.agentAppApps')}
              items={apps}
            />

            {preview && preview.mcp_needs_env.length > 0 && (
              <div className={styles.notice}>
                <AlertTriangle size={14} />
                <div>
                  <Trans
                    ns="components"
                    i18nKey="importProfileModal.needsEnv"
                    values={{ names: formatList(preview.mcp_needs_env.map(m => m.name)) }}
                    components={{ 1: <strong /> }}
                  />
                </div>
              </div>
            )}

            <div className={styles.modeBlock}>
              <div className={styles.modeTitle}>{t('components:importProfileModal.modeTitle')}</div>
              <label className={styles.modeOption}>
                <input
                  type="radio"
                  name="import-mode"
                  value="replace"
                  checked={mode === 'replace'}
                  onChange={() => setMode('replace')}
                  disabled={isApplying}
                />
                <div>
                  <div className={styles.modeName}>{t('components:importProfileModal.mergeReplaceName')}</div>
                  <div className={styles.modeHint}>
                    {t('components:importProfileModal.mergeReplaceHint')}
                  </div>
                </div>
              </label>
              <label className={styles.modeOption}>
                <input
                  type="radio"
                  name="import-mode"
                  value="overwrite"
                  checked={mode === 'overwrite'}
                  onChange={() => setMode('overwrite')}
                  disabled={isApplying}
                />
                <div>
                  <div className={styles.modeName}>{t('components:importProfileModal.overwriteName')}</div>
                  <div className={styles.modeHint}>
                    <Trans
                      ns="components"
                      i18nKey="importProfileModal.overwriteHint"
                      components={{ 0: <strong />, 1: <em /> }}
                    />
                  </div>
                </div>
              </label>
            </div>
          </>
        )}
      </ModalBody>
      <ModalFooter>
        <Button variant="secondary" onClick={onCancel} disabled={isApplying}>
          {t('common:actions.cancel')}
        </Button>
        <Button
          variant={mode === 'overwrite' ? 'danger' : 'primary'}
          onClick={() => onApply(mode)}
          disabled={isApplying || !manifest || !!error}
          icon={
            isApplying ? (
              <Loader2 size={14} className={styles.spinning} />
            ) : (
              <Package size={14} />
            )
          }
        >
          {isApplying
            ? t('components:importProfileModal.applying')
            : mode === 'overwrite'
              ? t('components:importProfileModal.overwriteButton')
              : t('components:importProfileModal.applyButton')}
        </Button>
      </ModalFooter>
    </Modal>
  )
}
