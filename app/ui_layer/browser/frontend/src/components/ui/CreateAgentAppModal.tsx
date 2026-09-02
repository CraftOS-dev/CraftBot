import { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import { Sparkles, Download, Loader2, Package, Store, FolderInput, Upload, Check, Search } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button } from './Button'
import { Modal } from './Modal'
import { CreateCustomWizard } from './CreateCustomWizard'
import { useSettingsWebSocket } from '../../pages/Settings/useSettingsWebSocket'
import { tourAnchorProps, useTourEnvAction, type TourAnchorId } from '../../tour'
import styles from './CreateAgentAppModal.module.css'

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

interface CustomField {
  key: string
  label: string
  type: string
  default: string
  placeholder?: string
}

interface MarketplaceApp {
  id: string
  name: string
  description: string
  preview?: string
  folder: string
  tags?: string[]
  version?: string
  customizable?: CustomField[]
}

export function CreateAgentAppModal({ isOpen, onClose, onInstalled }: CreateAgentAppModalProps) {
  const { t } = useTranslation(['components', 'common'])
  const [activeTab, setActiveTab] = useState<'marketplace' | 'custom' | 'import'>('marketplace')

  // Import tab state
  const [importSource, setImportSource] = useState('')
  const [importing, setImporting] = useState(false)
  const [importError, setImportError] = useState<string | null>(null)
  const [dropActive, setDropActive] = useState(false)

  // Marketplace state
  const { send, onMessage, isConnected } = useSettingsWebSocket()
  const [apps, setApps] = useState<MarketplaceApp[]>([])
  const [marketplaceLoading, setMarketplaceLoading] = useState(false)
  const [marketplaceError, setMarketplaceError] = useState<string | null>(null)
  const [installingIds, setInstallingIds] = useState<Set<string>>(new Set())
  const [installCounts, setInstallCounts] = useState<Map<string, number>>(new Map())
  const [configuringApp, setConfiguringApp] = useState<MarketplaceApp | null>(null)
  const installTimeoutsRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map())
  const marketplaceTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [customValues, setCustomValues] = useState<Record<string, string>>({})

  // Marketplace filter state
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedTags, setSelectedTags] = useState<Set<string>>(new Set())
  const [thumbFailures, setThumbFailures] = useState<Set<string>>(new Set())
  const [tagsExpanded, setTagsExpanded] = useState(false)

  const onCloseRef = useRef(onClose)
  const onInstalledRef = useRef(onInstalled)
  useEffect(() => { onCloseRef.current = onClose }, [onClose])
  useEffect(() => { onInstalledRef.current = onInstalled }, [onInstalled])
  useEffect(() => () => { installTimeoutsRef.current.forEach(t => clearTimeout(t)) }, [])

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
  // Accumulate projectIds from completed installs — navigate only when all installs finish
  const pendingNavigationsRef = useRef<string[]>([])

  // Upload ZIP → stage on server → send to agent via WebSocket
  const handleZipUpload = async (file: File) => {
    setImporting(true)
    try {
      const formData = new FormData()
      formData.append('file', file)
      const zipName = file.name.replace('.zip', '').replace(/^agentapp_/, '').replace(/_[a-f0-9]+$/, '')
      formData.append('name', zipName)
      const resp = await fetch('/api/agent-app/import', { method: 'POST', body: formData })
      const result = await resp.json()
      if (result.success && result.path) {
        // Handed off to AgentAppImportToast (see the URL import button).
        setImportError(null)
        send('agent_app_import', { source: result.path, name: result.name || zipName })
        setImporting(false)
        onCloseRef.current()
        return
      }
      setImportError(result.error || t('components:createAgentApp.uploadFailed'))
    } catch (err) {
      setImportError(t('components:createAgentApp.uploadFailedDetail', { message: err instanceof Error ? err.message : String(err) }))
    }
    setImporting(false)
  }

  // Reset form fields on open — intentionally NOT resetting installingIds/completedIds
  // so ongoing installs remain visible when user closes and reopens the modal
  useEffect(() => {
    if (isOpen) {
      setConfiguringApp(null)
      setCustomValues({})
      setSearchQuery('')
      setSelectedTags(new Set())
      // isConnected matters: opening straight onto the marketplace tab before
      // the websocket is up would send the request into a closed socket. The
      // effect below re-fires once the connection comes up.
      if (activeTab === 'marketplace' && apps.length === 0 && isConnected) {
        fetchMarketplace()
      }
    }
  }, [isOpen])

  // Fetch marketplace when tab changes
  useEffect(() => {
    if (isOpen && activeTab === 'marketplace' && apps.length === 0 && isConnected) {
      fetchMarketplace()
    }
  }, [activeTab, isConnected])

  // Listen for marketplace responses
  useEffect(() => {
    const cleanups = [
      onMessage('agent_app_marketplace_list', (data: any) => {
        if (marketplaceTimeoutRef.current) {
          clearTimeout(marketplaceTimeoutRef.current)
          marketplaceTimeoutRef.current = null
        }
        setMarketplaceLoading(false)
        if (data.success) {
          const appsWithThumbnails = (data.apps || []).map((app: any) => ({
            ...app,
            preview: app.preview || (app.folder ? `https://raw.githubusercontent.com/CraftOS-dev/living-ui-marketplace/main/${app.folder}/thumbnail.png` : undefined),
          }))
          setApps(appsWithThumbnails)
          setMarketplaceError(null)
        } else {
          setMarketplaceError(data.error || t('components:createAgentApp.marketplaceFailed'))
        }
      }),
      onMessage('agent_app_import_result', (data: any) => {
        // The modal has usually closed by now — AgentAppImportToast owns
        // telling the user how it went. All that is left here is the
        // navigation on success, and restoring the inline error for the
        // case where the modal is somehow still open.
        setImporting(false)
        if (data.success) {
          setImportSource('')
          setImportError(null)
          if (data.projectId && onInstalledRef.current) {
            onInstalledRef.current(data.projectId)
          }
          onCloseRef.current()
        } else {
          setImportError(data.error || t('components:createAgentApp.importFailed'))
        }
      }),
      onMessage('agent_app_marketplace_install', (data: any) => {
        console.log('[CreateAgentAppModal] received agent_app_marketplace_install:', data)
        const finishedId = data.appId as string | undefined
        if (data.status === 'success') {
          const projectId = data.project?.id
          if (projectId) pendingNavigationsRef.current.push(projectId)

          if (finishedId) {
            const t = installTimeoutsRef.current.get(finishedId)
            if (t) { clearTimeout(t); installTimeoutsRef.current.delete(finishedId) }
            setInstallCounts(prev => {
              const next = new Map(prev)
              next.set(finishedId, (next.get(finishedId) || 0) + 1)
              return next
            })
          }

          setInstallingIds(prev => {
            const next = new Set(prev)
            if (finishedId) next.delete(finishedId)
            else next.clear()
            if (next.size === 0) {
              const lastProjectId = pendingNavigationsRef.current[pendingNavigationsRef.current.length - 1]
              pendingNavigationsRef.current = []
              if (lastProjectId && onInstalledRef.current) {
                onInstalledRef.current(lastProjectId)
              }
              setTimeout(() => onCloseRef.current(), 800)
            }
            return next
          })
        } else {
          if (finishedId) {
            const t = installTimeoutsRef.current.get(finishedId)
            if (t) { clearTimeout(t); installTimeoutsRef.current.delete(finishedId) }
            setInstallingIds(prev => { const n = new Set(prev); n.delete(finishedId); return n })
          } else {
            installTimeoutsRef.current.forEach(t => clearTimeout(t))
            installTimeoutsRef.current.clear()
            setInstallingIds(new Set())
          }
          setMarketplaceError(data.error || t('components:createAgentApp.installFailed'))
        }
      }),
    ]
    return () => cleanups.forEach(c => c())
  }, [onMessage])

  const fetchMarketplace = useCallback(() => {
    setMarketplaceLoading(true)
    setMarketplaceError(null)
    // The backend always answers — but only if the socket actually delivered
    // the request. Without this, a request sent into a closing or not-yet-open
    // connection leaves the spinner up for ever with nothing to explain it,
    // which is exactly how this looked when the marketplace "kept loading".
    if (marketplaceTimeoutRef.current) clearTimeout(marketplaceTimeoutRef.current)
    marketplaceTimeoutRef.current = setTimeout(() => {
      marketplaceTimeoutRef.current = null
      setMarketplaceLoading(false)
      setMarketplaceError(t('components:createAgentApp.marketplaceFailed'))
    }, 45000)
    send('agent_app_marketplace_list')
  }, [send, t])

  // Derive tag list from catalogue, sorted by frequency (popular first)
  const allTags = useMemo(() => {
    const counts = new Map<string, number>()
    apps.forEach(a => a.tags?.forEach(t => counts.set(t, (counts.get(t) || 0) + 1)))
    return Array.from(counts.entries())
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
      .map(([t]) => t)
  }, [apps])

  const TAG_COLLAPSE_LIMIT = 6
  const visibleTags = tagsExpanded ? allTags : allTags.slice(0, TAG_COLLAPSE_LIMIT)
  const hiddenTagCount = Math.max(0, allTags.length - TAG_COLLAPSE_LIMIT)

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

  const handleAddClick = (app: MarketplaceApp) => {
    if (app.customizable && app.customizable.length > 0) {
      setConfiguringApp(app)
      const defaults: Record<string, string> = {}
      app.customizable.forEach(f => { defaults[f.key] = f.default })
      setCustomValues(defaults)
    } else {
      doInstall(app, {})
    }
  }

  const doInstall = (app: MarketplaceApp, fields: Record<string, string>) => {
    const appKey = app.folder || app.id
    setConfiguringApp(null)
    setInstallingIds(prev => new Set([...prev, appKey]))
    setMarketplaceError(null)

    // Stuck-install timeout: clear installing state after 3 minutes
    const timeout = setTimeout(() => {
      setInstallingIds(prev => { const n = new Set(prev); n.delete(appKey); return n })
      setMarketplaceError(t('components:createAgentApp.installTimeout', { name: app.name }))
      installTimeoutsRef.current.delete(appKey)
    }, 3 * 60 * 1000)
    installTimeoutsRef.current.set(appKey, timeout)

    send('agent_app_marketplace_install', {
      appId: appKey,
      appName: fields.APP_TITLE || app.name,
      appDescription: app.description,
      customFields: fields,
    })
  }

  // Escape key intentionally does NOT close this modal — user must use the X button

  // Chat-summoned wizard: same component, entered at the interview step.
  // Renders regardless of isOpen — the summons comes from the backend, not
  // the "+" button. Closing it mid-interview leaves nothing behind (no
  // project exists until finalize), same as cancelling the modal wizard.
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
            onInstalledRef.current?.(projectId)
          }}
        />
      </Modal>
    )
  }

  // Fully unmount when closed and no installs pending; stay mounted (invisible) while installs run
  if (!isOpen && installingIds.size === 0 && !chatWizard) return null
  if (!isOpen) return <></> // mounted but invisible — keeps onMessage listeners alive

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
        {activeTab === 'marketplace' && !configuringApp && (
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
              {allTags.length > 0 && (
                <div className={styles.tagsRow}>
                  <span className={styles.tagsLabel}>{t('components:createAgentApp.tagsLabel')}</span>
                  <button
                    className={`${styles.tagChip} ${selectedTags.size === 0 ? styles.tagChipActive : ''}`}
                    onClick={() => setSelectedTags(new Set())}
                  >
                    {t('components:createAgentApp.filterAll')}
                  </button>
                  {visibleTags.map(tag => (
                    <button
                      key={tag}
                      className={`${styles.tagChip} ${selectedTags.has(tag) ? styles.tagChipActive : ''}`}
                      onClick={() => toggleTag(tag)}
                    >
                      {tag}
                    </button>
                  ))}
                  {hiddenTagCount > 0 && (
                    <button
                      className={styles.tagChip}
                      onClick={() => setTagsExpanded(v => !v)}
                    >
                      {tagsExpanded ? t('common:actions.showLess') : t('components:createAgentApp.moreCount', { count: hiddenTagCount })}
                    </button>
                  )}
                </div>
              )}
            </div>

            <div className={styles.marketplaceContent}>
              {marketplaceLoading ? (
                <div className={styles.stateCenter}>
                  <Loader2 size={24} className={styles.spinner} />
                </div>
              ) : marketplaceError ? (
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
                    const appKey = app.folder || app.id
                    const installing = installingIds.has(appKey)
                    const installedCount = installCounts.get(appKey) || 0
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
                        <div className={styles.appCardBody}>
                          <div className={styles.appCardHeader}>
                            <span className={styles.appCardName}>{app.name}</span>
                            {app.version && <span className={styles.appCardVersion}>v{app.version}</span>}
                          </div>
                          {app.tags && app.tags.length > 0 && (
                            <div className={styles.appCardTags}>
                              {app.tags.map(tag => (
                                <span key={tag} className={styles.tag}>{tag}</span>
                              ))}
                            </div>
                          )}
                          <div className={styles.appCardDesc}>{app.description}</div>
                        </div>
                        <div className={styles.appCardFooter}>
                          {installedCount > 0 && !installing ? (
                            <span className={styles.installedBadge}>
                              <Check size={10} />
                              {t('components:createAgentApp.installedBadge', { count: installedCount })}
                            </span>
                          ) : <span />}
                          <Button
                            size="sm"
                            variant="primary"
                            icon={installing ? <Loader2 size={14} className={styles.spinner} /> : <Download size={14} />}
                            onClick={() => !installing && handleAddClick(app)}
                            disabled={installing}
                          >
                            {installing ? t('common:status.installing') : t('common:actions.add')}
                          </Button>
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          </div>
        )}

        {/* Marketplace Config Form (shown when app has customizable fields) */}
        {configuringApp && (
          <div className={styles.configBody}>
            <div className={styles.configCard}>
              <div className={styles.configHeader}>
                <h4>{t('components:createAgentApp.configureApp', { name: configuringApp.name })}</h4>
                <p>{t('components:createAgentApp.configureSubtitle')}</p>
              </div>
              {configuringApp.customizable?.map(field => (
                <div key={field.key} className={styles.formGroup} style={{ marginBottom: 'var(--space-3)' }}>
                  <label className={styles.label}>{field.label}</label>
                  <input
                    type={field.type || 'text'}
                    className={styles.input}
                    value={customValues[field.key] || ''}
                    onChange={(e) => setCustomValues(prev => ({ ...prev, [field.key]: e.target.value }))}
                    placeholder={field.placeholder || field.default}
                  />
                </div>
              ))}
              <div className={styles.configActions}>
                <Button variant="secondary" onClick={() => setConfiguringApp(null)}>{t('common:actions.back')}</Button>
                <Button variant="primary" icon={<Download size={14} />} onClick={() => doInstall(configuringApp, customValues)}>
                  {t('common:actions.install')}
                </Button>
              </div>
            </div>
          </div>
        )}

        {/* Custom Tab — three-step wizard (configure → interview → creating) */}
        {activeTab === 'custom' && (
          <CreateCustomWizard
            send={send}
            onMessage={onMessage}
            onClose={onClose}
            onCreated={onInstalled}
          />
        )}

        {/* Import Tab — URL/path + ZIP upload */}
        {activeTab === 'import' && (
          <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
            <div className={styles.modalBody}>
              <div className={styles.centeredForm}>
                <div className={styles.formGroup}>
                  <label className={styles.label}>
                    {t('components:createAgentApp.importUrlLabel')}
                  </label>
                  <input
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
                    <span className={styles.hint} style={{ color: 'var(--color-error, #e5484d)' }}>
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
                disabled={!importSource.trim() || importing}
                onClick={() => {
                  // Close NOW and let AgentAppImportToast carry it. Holding
                  // this modal open until agent_app_import_result was the old
                  // way of not hiding failures, but an import can run for
                  // minutes (odoo/odoo: ~300MB, ~58k files) and a modal
                  // parked over the whole app for that long is its own bug.
                  // The root-level toast reports progress AND the failure,
                  // so nothing is hidden by closing.
                  setImportError(null)
                  send('agent_app_import', {
                    source: importSource.trim(),
                    name: importSource.trim().split('/').pop()?.replace('.git', '') || t('components:createAgentApp.externalAppName'),
                  })
                  setImportSource('')
                  onCloseRef.current()
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
