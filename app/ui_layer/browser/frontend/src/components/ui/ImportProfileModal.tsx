import { useState } from 'react'
import { Loader2, AlertTriangle, Package, Wrench, Server, Layout, FileText } from 'lucide-react'
import { Button } from './Button'
import { Modal, ModalBody, ModalFooter } from './Modal'
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
    living_ui_apps?: string[]
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
    const d = new Date(iso)
    return d.toLocaleDateString(undefined, {
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
            title={conflictSet.has(name) ? 'Already installed locally' : undefined}
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
  const [mode, setMode] = useState<ImportMode>('replace')

  const contents = manifest?.contents ?? {}
  const skills = contents.skills ?? []
  const mcps = contents.mcp_servers ?? []
  const apps = contents.living_ui_apps ?? []
  const mds = contents.md_files ?? []

  const title = manifest ? `Import "${manifest.name}"` : 'Import agent profile'

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
            <span>Reading bundle…</span>
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
                <span>Made with CraftBot {manifest.source_app_version}</span>
              )}
              {manifest.created_at && <span>· {formatDate(manifest.created_at)}</span>}
              {contents.agent_name && (
                <span>· from agent "{contents.agent_name}"</span>
              )}
            </div>

            {manifest.description && (
              <p className={styles.description}>{manifest.description}</p>
            )}

            <SectionRow
              icon={<FileText size={14} />}
              label="Personality files"
              items={mds}
            />
            <SectionRow
              icon={<Wrench size={14} />}
              label="Skills"
              items={skills}
              conflicts={preview?.skills_already_installed}
            />
            <SectionRow
              icon={<Server size={14} />}
              label="MCP servers"
              items={mcps}
              conflicts={preview?.mcp_already_installed}
            />
            <SectionRow
              icon={<Layout size={14} />}
              label="Living UI apps"
              items={apps}
            />

            {preview && preview.mcp_needs_env.length > 0 && (
              <div className={styles.notice}>
                <AlertTriangle size={14} />
                <div>
                  After import, fill in API keys for:{' '}
                  <strong>
                    {preview.mcp_needs_env.map(m => m.name).join(', ')}
                  </strong>
                </div>
              </div>
            )}

            <div className={styles.modeBlock}>
              <div className={styles.modeTitle}>How should I apply this?</div>
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
                  <div className={styles.modeName}>Merge and Replace (recommended)</div>
                  <div className={styles.modeHint}>
                    Adds new skills, MCPs, and apps. Overwrites personality files
                    and MCP/skill config on name conflict. Living UI apps with
                    matching names are imported alongside (never destroyed).
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
                  <div className={styles.modeName}>Overwrite</div>
                  <div className={styles.modeHint}>
                    <strong>Destructive.</strong> Wipes <em>all</em> existing
                    skills, MCP servers, and Living UI apps, then installs only
                    what's in this bundle. Your agent becomes a copy of the
                    bundle. Cannot be undone.
                  </div>
                </div>
              </label>
            </div>
          </>
        )}
      </ModalBody>
      <ModalFooter>
        <Button variant="secondary" onClick={onCancel} disabled={isApplying}>
          Cancel
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
            ? 'Applying…'
            : mode === 'overwrite'
              ? 'Overwrite Agent'
              : 'Apply Profile'}
        </Button>
      </ModalFooter>
    </Modal>
  )
}
