import { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import { Sparkles, Download, Loader2, Package, Store, FolderInput, Upload, Check, Search } from 'lucide-react'
import { Button } from './Button'
import { Modal } from './Modal'
import { CreateCustomWizard } from './CreateCustomWizard'
import { useSettingsWebSocket } from '../../pages/Settings/useSettingsWebSocket'
import styles from './CreateLivingUIModal.module.css'

export interface CreateLivingUIModalProps {
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

export function CreateLivingUIModal({ isOpen, onClose, onInstalled }: CreateLivingUIModalProps) {
  const [activeTab, setActiveTab] = useState<'marketplace' | 'custom' | 'import'>('marketplace')

  // Import tab state
  const [importSource, setImportSource] = useState('')
  const [importing, setImporting] = useState(false)
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
  // Accumulate projectIds from completed installs — navigate only when all installs finish
  const pendingNavigationsRef = useRef<string[]>([])

  // Upload ZIP → stage on server → send to agent via WebSocket
  const handleZipUpload = async (file: File) => {
    setImporting(true)
    try {
      const formData = new FormData()
      formData.append('file', file)
      const zipName = file.name.replace('.zip', '').replace(/^livingui_/, '').replace(/_[a-f0-9]+$/, '')
      formData.append('name', zipName)
      const resp = await fetch('/api/living-ui/import', { method: 'POST', body: formData })
      const result = await resp.json()
      if (result.success && result.path) {
        send('living_ui_import', { source: result.path, name: result.name || zipName })
        onClose()
      } else {
        alert(result.error || 'Upload failed')
      }
    } catch (err) {
      alert('Upload failed: ' + (err instanceof Error ? err.message : err))
    } finally {
      setImporting(false)
    }
  }

  // Reset form fields on open — intentionally NOT resetting installingIds/completedIds
  // so ongoing installs remain visible when user closes and reopens the modal
  useEffect(() => {
    if (isOpen) {
      setConfiguringApp(null)
      setCustomValues({})
      setSearchQuery('')
      setSelectedTags(new Set())
      if (activeTab === 'marketplace' && apps.length === 0) {
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
      onMessage('living_ui_marketplace_list', (data: any) => {
        setMarketplaceLoading(false)
        if (data.success) {
          const appsWithThumbnails = (data.apps || []).map((app: any) => ({
            ...app,
            preview: app.preview || (app.folder ? `https://raw.githubusercontent.com/CraftOS-dev/living-ui-marketplace/main/${app.folder}/thumbnail.png` : undefined),
          }))
          setApps(appsWithThumbnails)
          setMarketplaceError(null)
        } else {
          setMarketplaceError(data.error || 'Failed to load marketplace')
        }
      }),
      onMessage('living_ui_marketplace_install', (data: any) => {
        console.log('[CreateLivingUIModal] received living_ui_marketplace_install:', data)
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
          setMarketplaceError(data.error || 'Installation failed')
        }
      }),
    ]
    return () => cleanups.forEach(c => c())
  }, [onMessage])

  const fetchMarketplace = useCallback(() => {
    setMarketplaceLoading(true)
    setMarketplaceError(null)
    send('living_ui_marketplace_list')
  }, [send])

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
      setMarketplaceError(`Installation of "${app.name}" timed out. Please try again.`)
      installTimeoutsRef.current.delete(appKey)
    }, 3 * 60 * 1000)
    installTimeoutsRef.current.set(appKey, timeout)

    send('living_ui_marketplace_install', {
      appId: appKey,
      appName: fields.APP_TITLE || app.name,
      appDescription: app.description,
      customFields: fields,
    })
  }

  // Escape key intentionally does NOT close this modal — user must use the X button

  // Fully unmount when closed and no installs pending; stay mounted (invisible) while installs run
  if (!isOpen && installingIds.size === 0) return null
  if (!isOpen) return <></> // mounted but invisible — keeps onMessage listeners alive

  const tabsConfig = [
    { id: 'marketplace' as const, label: 'Marketplace', icon: <Store size={14} /> },
    { id: 'custom' as const, label: 'Create Custom', icon: <Sparkles size={14} /> },
    { id: 'import' as const, label: 'Import', icon: <FolderInput size={14} /> },
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
          Add Living UI
        </>
      }
    >
        <div className={styles.tabs}>
          {tabsConfig.map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`${styles.tab} ${activeTab === tab.id ? styles.tabActive : ''}`}
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
                  placeholder="Search apps..."
                  value={searchQuery}
                  onChange={e => setSearchQuery(e.target.value)}
                />
              </div>
              {allTags.length > 0 && (
                <div className={styles.tagsRow}>
                  <span className={styles.tagsLabel}>Tags:</span>
                  <button
                    className={`${styles.tagChip} ${selectedTags.size === 0 ? styles.tagChipActive : ''}`}
                    onClick={() => setSelectedTags(new Set())}
                  >
                    All
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
                      {tagsExpanded ? 'Show less' : `+${hiddenTagCount} more`}
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
                  <Button size="sm" variant="secondary" onClick={fetchMarketplace}>Retry</Button>
                </div>
              ) : apps.length === 0 ? (
                <div className={styles.stateCenter}>
                  <Package size={32} className={styles.stateIcon} />
                  <p className={styles.stateText}>No apps available yet.</p>
                </div>
              ) : filteredApps.length === 0 ? (
                <div className={styles.stateCenter}>
                  <Search size={32} className={styles.stateIcon} />
                  <p className={styles.stateText}>No apps match your filters.</p>
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
                              {installedCount === 1 ? 'Installed' : `Installed ×${installedCount}`}
                            </span>
                          ) : <span />}
                          <Button
                            size="sm"
                            variant="primary"
                            icon={installing ? <Loader2 size={14} className={styles.spinner} /> : <Download size={14} />}
                            onClick={() => !installing && handleAddClick(app)}
                            disabled={installing}
                          >
                            {installing ? 'Installing...' : 'Add'}
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
                <h4>Configure: {configuringApp.name}</h4>
                <p>Customize before installing</p>
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
                <Button variant="secondary" onClick={() => setConfiguringApp(null)}>Back</Button>
                <Button variant="primary" icon={<Download size={14} />} onClick={() => doInstall(configuringApp, customValues)}>
                  Install
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
                    GitHub URL or Local Path
                  </label>
                  <input
                    type="text"
                    className={styles.input}
                    placeholder="https://github.com/user/repo or /path/to/local/app"
                    value={importSource}
                    onChange={e => setImportSource(e.target.value)}
                  />
                  <span className={styles.hint}>
                    Go · Node.js · Python · Rust · Docker · Static sites
                  </span>
                </div>

                <div className={styles.orDivider}>
                  <span>or</span>
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
                      <p className={styles.dropZoneSub}>Importing...</p>
                    </>
                  ) : (
                    <>
                      <Upload size={24} className={styles.dropZoneIcon} />
                      <p className={styles.dropZoneLabel}>
                        Drop a ZIP file here or click to browse
                      </p>
                      <p className={styles.dropZoneSub}>
                        Import a previously exported Living UI
                      </p>
                    </>
                  )}
                </div>
              </div>
            </div>

            <div className={styles.modalFooter}>
              <Button variant="secondary" type="button" onClick={onClose}>
                Cancel
              </Button>
              <Button
                variant="primary"
                icon={importing ? <Loader2 size={16} className={styles.spinner} /> : <FolderInput size={16} />}
                disabled={!importSource.trim() || importing}
                onClick={async () => {
                  setImporting(true)
                  send('living_ui_import', {
                    source: importSource.trim(),
                    name: importSource.trim().split('/').pop()?.replace('.git', '') || 'External App',
                  })
                  setImporting(false)
                  setImportSource('')
                  onClose()
                }}
              >
                {importing ? 'Importing...' : 'Import App'}
              </Button>
            </div>
          </div>
        )}
    </Modal>
  )
}
