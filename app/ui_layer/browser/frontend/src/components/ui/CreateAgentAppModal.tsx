import { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import { Sparkles, Download, Loader2, Package, Store, FolderInput, Upload, Search } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button } from './Button'
import { Modal } from './Modal'
import { AgentAppIcon } from './AgentAppIcon'
import { CreateCustomWizard } from './CreateCustomWizard'
import { useSettingsWebSocket } from '../../pages/Settings/useSettingsWebSocket'
import { tourAnchorProps, useTourEnvAction, type TourAnchorId } from '../../tour'
import styles from './CreateAgentAppModal.module.css'
import { frameworkRequest } from '../../features/agentApps/frameworkApi'
import { useFrameworkCreation } from '../../features/agentApps/useFrameworkCreation'
import { useAppSelector } from '../../store/hooks'

// The modal's tabs, in the order the guided tour walks them.
const TAB_TOUR_ANCHORS: Record<'marketplace' | 'custom' | 'import', TourAnchorId> = {
  marketplace: 'agentapp-tab-marketplace',
  custom: 'agentapp-tab-custom',
  import: 'agentapp-tab-import',
}

export interface CreateAgentAppModalProps {
  isOpen: boolean
  onClose: () => void
  onInstalled?: (projectId: string) => void
}

interface MarketplaceApp {
  id: string
  name: string
  description: string
  preview?: string
  // "lucide:<Name>" like a project's icon; none yet → the default cube.
  icon?: string
  tags?: string[]
  version?: string
}

export function CreateAgentAppModal({ isOpen, onClose, onInstalled }: CreateAgentAppModalProps) {
  const { t } = useTranslation(['components', 'common'])
  const [activeTab, setActiveTab] = useState<'marketplace' | 'custom' | 'import'>('marketplace')
  const native = useFrameworkCreation(onClose)

  // Import tab state
  const [importSource, setImportSource] = useState('')
  const [importing, setImporting] = useState(false)
  const [importError, setImportError] = useState<string | null>(null)
  const [dropActive, setDropActive] = useState(false)

  // The chat-triggered wizard keeps its existing interview messages.
  const { send, onMessage } = useSettingsWebSocket()
  const isConnected = useAppSelector(state => state.connection.connected)

  // Marketplace state
  const [apps, setApps] = useState<MarketplaceApp[]>([])
  const [marketplaceLoading, setMarketplaceLoading] = useState(false)
  const [marketplaceError, setMarketplaceError] = useState<string | null>(null)
  const [installingIds, setInstallingIds] = useState<Set<string>>(new Set())

  // Marketplace filter state
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedTags, setSelectedTags] = useState<Set<string>>(new Set())
  const [thumbFailures, setThumbFailures] = useState<Set<string>>(new Set())

  // Let the guided tour switch the modal's tab so each creation method is shown.
  useTourEnvAction('openAgentAppTab', (arg) => {
    if (arg === 'marketplace' || arg === 'custom' || arg === 'import') {
      setActiveTab(arg)
    }
  })

  // Chat-path requirements phase: agent_app_scaffold generated setup
  // questions (creating nothing yet) and the backend summons the SAME
  // Create Custom wizard, pre-seeded and opened at the interview step
  // (agent_app_wizard_open); its finalize creates the project as usual.
  const [chatWizard, setChatWizard] = useState<{
    wizardId: string
    config: Record<string, any>
    questions: any[]
    originSessionId?: string
  } | null>(null)
  useEffect(
    () =>
      onMessage('agent_app_wizard_open', (data: any) => {
        if (data?.wizardId && Array.isArray(data.questions) && data.questions.length > 0) {
          setChatWizard(data)
        }
      }),
    [onMessage]
  )

  // Upload ZIP, then install the staged package through Agent-App.
  const handleZipUpload = async (file: File) => {
    if (!isConnected || importing) return
    setImporting(true)
    setImportError(null)
    try {
      const formData = new FormData()
      formData.append('file', file)
      const zipName = file.name.replace('.zip', '').replace(/^agentapp_/, '').replace(/_[a-f0-9]+$/, '')
      formData.append('name', zipName)
      const resp = await fetch('/api/agent-app/import', { method: 'POST', body: formData })
      const result = await resp.json()
      if (result.success && result.path) {
        await native.install({ from: result.path })
        return
      }
      setImportError(result.error || t('components:createAgentApp.uploadFailed'))
    } catch (err) {
      setImportError(t('components:createAgentApp.uploadFailedDetail', { message: err instanceof Error ? err.message : String(err) }))
    } finally {
      setImporting(false)
    }
  }

  // The catalog is cached for the modal's lifetime, but a disconnect (e.g. a
  // backend update) makes the next marketplace view refetch it.
  const catalogStaleRef = useRef(false)
  useEffect(() => {
    if (!isConnected) catalogStaleRef.current = true
  }, [isConnected])
  const fetchCatalogIfNeeded = () => {
    if (apps.length > 0 && !catalogStaleRef.current) return
    catalogStaleRef.current = false
    fetchMarketplace()
  }

  // Reset filters on open; preserve pending installs when the modal is reopened.
  useEffect(() => {
    if (isOpen) {
      setSearchQuery('')
      setSelectedTags(new Set())
      // isConnected matters: opening straight onto the marketplace tab before
      // the websocket is up would send the request into a closed socket. The
      // effect below re-fires once the connection comes up.
      if (activeTab === 'marketplace' && isConnected) {
        fetchCatalogIfNeeded()
      }
    }
  }, [isOpen])

  // Fetch marketplace when tab changes
  useEffect(() => {
    if (isOpen && activeTab === 'marketplace' && isConnected) {
      fetchCatalogIfNeeded()
    }
  }, [activeTab, isConnected])

  const fetchMarketplace = useCallback(() => {
    setMarketplaceLoading(true)
    setMarketplaceError(null)
    void frameworkRequest<{ status: string; data?: { apps: MarketplaceApp[] }; stderr?: string }>({ operation: 'catalogue' })
      .then(result => {
        if (result.status !== 'success' || !result.data) throw new Error(result.stderr || 'The marketplace could not be loaded.')
        setApps(result.data.apps)
      }).catch(error => setMarketplaceError(String(error))).finally(() => setMarketplaceLoading(false))
  }, [])

  // Derive [tag, app count] list from catalogue, sorted by frequency (popular first)
  const allTags = useMemo(() => {
    const counts = new Map<string, number>()
    apps.forEach(a => a.tags?.forEach(t => counts.set(t, (counts.get(t) || 0) + 1)))
    return Array.from(counts.entries())
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
  }, [apps])

  const filteredApps = useMemo(() => {
    const q = searchQuery.trim().toLowerCase()
    return apps.filter(app => {
      if (q) {
        const hay = `${app.name} ${app.description} ${(app.tags || []).join(' ')}`.toLowerCase()
        if (!hay.includes(q)) return false
      }
      if (selectedTags.size > 0) {
        const tags = app.tags || []
        if (!tags.some(t => selectedTags.has(t))) return false
      }
      return true
    })
  }, [apps, searchQuery, selectedTags])

  const toggleTag = (tag: string) => {
    setSelectedTags(prev => {
      const next = new Set(prev)
      if (next.has(tag)) next.delete(tag)
      else next.add(tag)
      return next
    })
  }

  const installApp = (app: MarketplaceApp) => {
    setInstallingIds(prev => new Set([...prev, app.id]))
    setMarketplaceError(null)
    void native.install({ id: app.id }).catch(error => setMarketplaceError(String(error)))
      .finally(() => setInstallingIds(previous => { const next = new Set(previous); next.delete(app.id); return next }))
  }

  // Escape key intentionally does NOT close this modal — user must use the X button

  // The backend can open the chat wizard while the Add Agent App modal is
  // closed. Cancelling before finalize creates no project.
  if (chatWizard && !isOpen) {
    return (
      <Modal
        isOpen={true}
        onClose={() => setChatWizard(null)}
        size="full"
        closeOnOverlayClick={false}
        closeOnEsc={false}
        title={
          <>
            <Sparkles size={20} className={styles.headerIcon} />
            {t('components:createAgentApp.setupQuestions', { name: String(chatWizard.config?.name || 'Agent App') })}
          </>
        }
      >
        <CreateCustomWizard
          send={send}
          onMessage={onMessage}
          initial={chatWizard}
          onClose={() => setChatWizard(null)}
          onCreated={(projectId: string) => {
            setChatWizard(null)
            onInstalled?.(projectId)
          }}
        />
      </Modal>
    )
  }

  // Hide the UI while keeping chat wizard listeners and install tracking mounted.
  if (!isOpen) return null

  const tabsConfig = [
    { id: 'marketplace' as const, label: t('components:createAgentApp.tabMarketplace'), icon: <Store size={14} /> },
    { id: 'custom' as const, label: t('components:createAgentApp.tabCustom'), icon: <Sparkles size={14} /> },
    { id: 'import' as const, label: t('components:createAgentApp.tabImport'), icon: <FolderInput size={14} /> },
  ]

  return (
    <Modal
      isOpen={true}
      onClose={onClose}
      size="full"
      closeOnOverlayClick={false}
      closeOnEsc={false}
      title={
        <>
          <Sparkles size={20} className={styles.headerIcon} />
          {t('components:createAgentApp.addTitle')}
        </>
      }
    >
        <div className={styles.tabs}>
          {tabsConfig.map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`${styles.tab} ${activeTab === tab.id ? styles.tabActive : ''}`}
              {...tourAnchorProps(TAB_TOUR_ANCHORS[tab.id])}
            >
              {tab.icon}
              {tab.label}
            </button>
          ))}
        </div>

        {/* Marketplace Tab */}
        {activeTab === 'marketplace' && (
          <div className={styles.marketplaceBody}>
            <div className={styles.toolbar}>
              <div className={styles.searchWrapper}>
                <Search size={14} className={styles.searchIcon} />
                <input
                  className={styles.searchInput}
                  placeholder={t('components:createAgentApp.searchPlaceholder')}
                  value={searchQuery}
                  onChange={e => setSearchQuery(e.target.value)}
                />
              </div>
            </div>

            <div className={styles.marketplaceMain}>
              {allTags.length > 0 && (
                <nav className={styles.tagSidebar}>
                  <button
                    className={`${styles.tagItem} ${selectedTags.size === 0 ? styles.tagItemActive : ''}`}
                    onClick={() => setSelectedTags(new Set())}
                  >
                    <span className={styles.tagLabel}>{t('components:createAgentApp.filterAll')}</span>
                    <span className={styles.tagCount}>{apps.length}</span>
                  </button>
                  {allTags.map(([tag, count]) => (
                    <button
                      key={tag}
                      className={`${styles.tagItem} ${selectedTags.has(tag) ? styles.tagItemActive : ''}`}
                      onClick={() => toggleTag(tag)}
                    >
                      <span className={styles.tagLabel}>{tag}</span>
                      <span className={styles.tagCount}>{count}</span>
                    </button>
                  ))}
                </nav>
              )}

              <div className={styles.marketplaceContent}>
                {marketplaceError && apps.length > 0 && <p role="alert" className={styles.stateText}>{marketplaceError}</p>}
                {marketplaceLoading ? (
                  <div className={styles.stateCenter}>
                    <Loader2 size={24} className={styles.spinner} />
                  </div>
                ) : marketplaceError && apps.length === 0 ? (
                  <div className={styles.stateCenter}>
                    <p className={styles.stateText}>{marketplaceError}</p>
                    <Button size="sm" variant="secondary" onClick={fetchMarketplace}>{t('common:actions.retry')}</Button>
                  </div>
                ) : apps.length === 0 ? (
                  <div className={styles.stateCenter}>
                    <Package size={32} className={styles.stateIcon} />
                    <p className={styles.stateText}>{t('components:createAgentApp.emptyNone')}</p>
                  </div>
                ) : filteredApps.length === 0 ? (
                  <div className={styles.stateCenter}>
                    <Search size={32} className={styles.stateIcon} />
                    <p className={styles.stateText}>{t('components:createAgentApp.emptyFiltered')}</p>
                  </div>
                ) : (
                  <div className={styles.appsGrid}>
                    {filteredApps.map(app => {
                      const appKey = app.id
                      const installing = installingIds.has(appKey)
                      const addLabel = installing
                        ? t('common:status.installing')
                        : t('common:actions.add')
                      return (
                        <div key={app.id} className={styles.appCard}>
                          {app.preview && !thumbFailures.has(appKey) ? (
                            <img
                              src={app.preview}
                              alt={app.name}
                              referrerPolicy="no-referrer"
                              className={styles.appCardThumb}
                              onError={() => setThumbFailures(prev => new Set(prev).add(appKey))}
                            />
                          ) : (
                            <div className={styles.appCardPlaceholder}>
                              <Package size={32} className={styles.appCardPlaceholderIcon} />
                            </div>
                          )}
                          <div className={styles.appCardFooter}>
                            <span className={styles.appCardTitle}>
                              <AgentAppIcon
                                // file: icons belong to installed projects; a catalogue entry has none
                                icon={app.icon?.startsWith('lucide:') ? app.icon : undefined}
                                size={14}
                                className={styles.appCardIcon}
                              />
                              <span className={styles.appCardName} title={app.name}>{app.name}</span>
                            </span>
                            <button
                              type="button"
                              className={styles.appCardAdd}
                              onClick={() => !installing && installApp(app)}
                              disabled={installing || !isConnected}
                              aria-label={addLabel}
                              title={addLabel}
                            >
                              {installing
                                ? <Loader2 size={14} className={styles.spinner} />
                                : <Download size={14} />}
                            </button>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Custom Tab — collect requirements for Agent-App creation. */}
        {activeTab === 'custom' && (
          <CreateCustomWizard
            send={send}
            onMessage={onMessage}
            onClose={onClose}
            onConfigure={native.create}
            disabled={!isConnected}
          />
        )}

        {/* Import Tab — URL/path + ZIP upload */}
        {activeTab === 'import' && (
          <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
            <div className={styles.modalBody}>
              <div className={styles.centeredForm}>
                <div className={styles.formGroup}>
                  <label className={styles.label} htmlFor="agent-app-import-source">
                    {t('components:createAgentApp.importUrlLabel')}
                  </label>
                  <input
                    id="agent-app-import-source"
                    type="text"
                    className={styles.input}
                    placeholder={t('components:createAgentApp.importUrlPlaceholder')}
                    value={importSource}
                    onChange={e => setImportSource(e.target.value)}
                  />
                  <span className={styles.hint}>
                    {t('components:createAgentApp.importHint')}
                  </span>
                  {importError && (
                    <span role="alert" className={styles.hint} style={{ color: 'var(--color-error, #e5484d)' }}>
                      {importError}
                    </span>
                  )}
                </div>

                <div className={styles.orDivider}>
                  <span>{t('components:createAgentApp.or')}</span>
                </div>

                <div
                  className={`${styles.dropZone} ${dropActive ? styles.dropZoneDragOver : ''}`}
                  onClick={() => {
                    const input = document.createElement('input')
                    input.type = 'file'
                    input.accept = '.zip'
                    input.onchange = (e) => {
                      const file = (e.target as HTMLInputElement).files?.[0]
                      if (file) handleZipUpload(file)
                    }
                    input.click()
                  }}
                  onDragOver={(e) => { e.preventDefault(); setDropActive(true) }}
                  onDragLeave={() => setDropActive(false)}
                  onDrop={(e) => {
                    e.preventDefault()
                    setDropActive(false)
                    const file = e.dataTransfer.files[0]
                    if (file && file.name.endsWith('.zip')) handleZipUpload(file)
                  }}
                >
                  {importing ? (
                    <>
                      <Loader2 size={24} className={styles.spinner} />
                      <p className={styles.dropZoneSub}>{t('common:status.importing')}</p>
                    </>
                  ) : (
                    <>
                      <Upload size={24} className={styles.dropZoneIcon} />
                      <p className={styles.dropZoneLabel}>
                        {t('components:createAgentApp.dropZipLabel')}
                      </p>
                      <p className={styles.dropZoneSub}>
                        {t('components:createAgentApp.dropZipSub')}
                      </p>
                    </>
                  )}
                </div>
              </div>
            </div>

            <div className={styles.modalFooter}>
              <Button variant="secondary" type="button" onClick={onClose}>
                {t('common:actions.cancel')}
              </Button>
              <Button
                variant="primary"
                icon={importing ? <Loader2 size={16} className={styles.spinner} /> : <FolderInput size={16} />}
                disabled={!importSource.trim() || importing || !isConnected}
                onClick={() => {
                  setImporting(true)
                  setImportError(null)
                  void native.install({ from: importSource.trim() }).catch(error => setImportError(String(error))).finally(() => setImporting(false))
                }}
              >
                {importing ? t('common:status.importing') : t('components:createAgentApp.importButton')}
              </Button>
            </div>
          </div>
        )}
    </Modal>
  )
}
