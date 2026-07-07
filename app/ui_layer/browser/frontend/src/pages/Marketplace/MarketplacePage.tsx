import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  Boxes,
  CloudOff,
  FolderInput,
  Loader2,
  Package,
  PanelLeftClose,
  Search,
  Sparkles,
  Store,
  Tags,
  Wrench,
  X,
} from 'lucide-react'
import { useWebSocket } from '../../contexts/WebSocketContext'
import { ImportProfileModal } from '../../components/ui/ImportProfileModal'
import { fetchBanners, fetchCatalog } from './marketplaceApi'
import { useMarketplaceInstall } from './useMarketplaceInstall'
import { HeroBanner } from './components/HeroBanner'
import { ProductCard } from './components/ProductCard'
import { ConfigureInstallOverlay } from './components/ConfigureInstallOverlay'
import { LivingUICreatePanel } from './components/LivingUICreatePanel'
import { LivingUIImportPanel } from './components/LivingUIImportPanel'
import type { Banner, MarketplaceProduct, ProductType } from './types'
import styles from './Marketplace.module.css'

type Section = 'living-uis' | 'bundles' | 'skills'
type LivingUIMode = 'browse' | 'all' | 'create' | 'import'

const SECTIONS: Array<{ id: Section; label: string; icon: React.ReactNode; type: ProductType }> = [
  { id: 'living-uis', label: 'Living UIs', icon: <Boxes size={15} />, type: 'living_ui' },
  { id: 'bundles', label: 'Agent Bundles', icon: <Package size={15} />, type: 'agent_bundle' },
  { id: 'skills', label: 'Skills', icon: <Wrench size={15} />, type: 'skill' },
]

const SORT_OPTIONS = [
  { value: 'recent', label: 'Recent' },
  { value: 'downloads', label: 'Most downloaded' },
  { value: 'rating', label: 'Top rated' },
] as const

export function MarketplacePage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const section = (searchParams.get('section') as Section) || 'living-uis'
  const mode = (searchParams.get('mode') as LivingUIMode) || 'browse'
  const activeSection = SECTIONS.find(s => s.id === section) || SECTIONS[0]
  // Steam-style: the Featured home only exists for Living UIs with live
  // server data. Skills/bundles (small catalogs) and degraded mode go
  // straight to the full listing.
  const homeAvailable = section === 'living-uis'

  const [products, setProducts] = useState<MarketplaceProduct[]>([])
  const [banners, setBanners] = useState<Banner[]>([])
  const [degraded, setDegraded] = useState(false)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)

  const [searchQuery, setSearchQuery] = useState('')
  const [selectedTags, setSelectedTags] = useState<Set<string>>(new Set())
  const [sort, setSort] = useState<'recent' | 'downloads' | 'rating'>('recent')
  const [tagRailOpen, setTagRailOpen] = useState(
    () => localStorage.getItem('marketplace-tag-rail') !== 'closed',
  )

  const toggleTagRail = (open: boolean) => {
    setTagRailOpen(open)
    localStorage.setItem('marketplace-tag-rail', open ? 'open' : 'closed')
  }

  const {
    installingIds, installedIds, installError, setInstallError,
    configuring, setConfiguring, requestInstall, doInstall,
    stagedBundle, setStagedBundle, applyBundle, bundleApplying, bundleError,
  } = useMarketplaceInstall()
  const { livingUIProjects } = useWebSocket()

  // Installed marketplace versions by catalog slug (update-available badges).
  const installedVersionBySlug = useMemo(() => {
    const map = new Map<string, string>()
    livingUIProjects.forEach(p => {
      if (p.marketplaceSlug && p.marketplaceVersion) map.set(p.marketplaceSlug, p.marketplaceVersion)
    })
    return map
  }, [livingUIProjects])

  const setSection = (id: Section) => {
    setSearchParams(id === 'living-uis' ? {} : { section: id }, { replace: true })
  }
  const setMode = (m: LivingUIMode) => {
    const params: Record<string, string> = {}
    if (section !== 'living-uis') params.section = section
    if (m !== 'browse') params.mode = m
    setSearchParams(params, { replace: true })
  }

  const loadCatalog = useCallback(async (type: ProductType, sortBy: string, silent = false) => {
    if (!silent) setLoading(true)
    setLoadError(null)
    try {
      const data = await fetchCatalog({ type, sort: sortBy as 'recent' | 'downloads' | 'rating' })
      setProducts(data.products)
      setDegraded(data.degraded)
    } catch (err) {
      if (!silent) {
        setLoadError(err instanceof Error ? err.message : 'Failed to load marketplace')
        setProducts([])
      }
    } finally {
      if (!silent) setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadCatalog(activeSection.type, sort)
  }, [activeSection.type, sort, loadCatalog])

  // Refresh stats in place when an install completes (downloads counter
  // moves server-side) — silent so the grid doesn't flash a spinner. Small
  // delay: the backend reports the install event concurrently with the
  // completion broadcast, so an immediate refetch could beat the increment.
  useEffect(() => {
    if (installedIds.size === 0) return
    const t = setTimeout(() => loadCatalog(activeSection.type, sort, true), 1500)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [installedIds])

  useEffect(() => {
    fetchBanners()
      .then(data => setBanners(data.banners || []))
      .catch(() => setBanners([]))
  }, [])

  // Tag filter list derived from the catalogue: [tag, productCount], popular first
  const allTags = useMemo(() => {
    const counts = new Map<string, number>()
    products.forEach(p => p.tags.forEach(t => counts.set(t, (counts.get(t) || 0) + 1)))
    return Array.from(counts.entries())
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
  }, [products])

  const filteredProducts = useMemo(() => {
    const q = searchQuery.trim().toLowerCase()
    return products.filter(p => {
      if (q) {
        const hay = `${p.name} ${p.tagline || ''} ${p.tags.join(' ')}`.toLowerCase()
        if (!hay.includes(q)) return false
      }
      if (selectedTags.size > 0 && !p.tags.some(t => selectedTags.has(t))) return false
      return true
    })
  }, [products, searchQuery, selectedTags])

  const toggleTag = (tag: string) => {
    setSelectedTags(prev => {
      const next = new Set(prev)
      if (next.has(tag)) next.delete(tag)
      else next.add(tag)
      return next
    })
  }

  // Home shelves (server data only)
  const featuredShelf = useMemo(
    () => (degraded ? [] : products.filter(p => p.featured).slice(0, 12)),
    [products, degraded],
  )
  // Catalog arrives recent-first by default, so the newest slice is the shelf.
  // (Cards don't carry createdAt, so with another sort active we can't
  // reconstruct recency — the shelf just hides until sort is back to recent.)
  const newShelf = useMemo(
    () => (degraded || sort !== 'recent' ? [] : products.slice(0, 10)),
    [products, degraded, sort],
  )

  // The Featured home is only real with server data; degraded goes to All.
  const effectiveMode: LivingUIMode =
    !homeAvailable || (degraded && mode === 'browse') ? (mode === 'create' || mode === 'import' ? mode : 'all') : mode

  // Typing in the header search jumps from the home to the full listing.
  const onSearchChange = (value: string) => {
    setSearchQuery(value)
    if (homeAvailable && mode === 'browse' && value.trim()) setMode('all')
  }

  const renderCard = (product: MarketplaceProduct) => {
    const appId = product.repoPath || product.slug
    const installedVersion = installedVersionBySlug.get(product.slug)
    return (
      <ProductCard
        key={product.slug}
        product={product}
        installing={installingIds.has(appId)}
        installed={installedIds.has(appId)}
        degraded={degraded}
        updateAvailable={Boolean(
          installedVersion && product.latestVersion && installedVersion !== product.latestVersion,
        )}
        onInstall={requestInstall}
      />
    )
  }

  return (
    <div className={styles.page}>
      <div className={styles.pageInner}>
        <div className={styles.pageHeader}>
          <h1 className={styles.pageTitle}>
            <Store size={22} className={styles.pageTitleIcon} />
            Marketplace
          </h1>
          {degraded ? (
            <span className={styles.degradedNotice} title="Marketplace server unreachable — showing the offline catalogue from GitHub. Installs still work.">
              <CloudOff size={13} />
              Offline catalogue
            </span>
          ) : (
            (effectiveMode === 'browse' || effectiveMode === 'all') && (
              <div className={styles.searchWrapper}>
                <Search size={14} className={styles.searchIcon} />
                <input
                  className={styles.searchInput}
                  placeholder="search the store"
                  value={searchQuery}
                  onChange={e => onSearchChange(e.target.value)}
                />
              </div>
            )
          )}
        </div>

        <div className={styles.sectionTabs}>
          {SECTIONS.map(s => (
            <button
              key={s.id}
              className={`${styles.sectionTab} ${section === s.id ? styles.sectionTabActive : ''}`}
              onClick={() => setSection(s.id)}
            >
              {s.icon}
              {s.label}
            </button>
          ))}
        </div>

        <>
            {!degraded && <HeroBanner banners={banners} />}

            {section === 'living-uis' && (
              <div className={styles.modeTabs}>
                {!degraded && (
                  <button
                    className={`${styles.modeTab} ${effectiveMode === 'browse' ? styles.modeTabActive : ''}`}
                    onClick={() => setMode('browse')}
                  >
                    <Store size={13} /> Featured
                  </button>
                )}
                <button
                  className={`${styles.modeTab} ${effectiveMode === 'all' ? styles.modeTabActive : ''}`}
                  onClick={() => setMode('all')}
                >
                  <Boxes size={13} /> All Living UIs
                </button>
                <button
                  className={`${styles.modeTab} ${effectiveMode === 'create' ? styles.modeTabActive : ''}`}
                  onClick={() => setMode('create')}
                >
                  <Sparkles size={13} /> Create Custom
                </button>
                <button
                  className={`${styles.modeTab} ${effectiveMode === 'import' ? styles.modeTabActive : ''}`}
                  onClick={() => setMode('import')}
                >
                  <FolderInput size={13} /> Import
                </button>
              </div>
            )}

            {effectiveMode === 'create' && <LivingUICreatePanel />}
            {effectiveMode === 'import' && <LivingUIImportPanel />}

            {installError && effectiveMode !== 'all' && (
              <div className={styles.errorBar}>
                <span>{installError}</span>
                <button className={styles.errorBarClose} onClick={() => setInstallError(null)} aria-label="Dismiss">
                  <X size={14} />
                </button>
              </div>
            )}

            {/* Featured home: discovery shelves, no full listing (Steam-style) */}
            {effectiveMode === 'browse' && (
              loading ? (
                <div className={styles.stateCenter}>
                  <Loader2 size={24} className={styles.spinner} />
                </div>
              ) : loadError ? (
                <div className={styles.stateCenter}>
                  <p className={styles.stateText}>{loadError}</p>
                  <button className={styles.installBtn} onClick={() => loadCatalog(activeSection.type, sort)}>
                    Retry
                  </button>
                </div>
              ) : (
                <>
                  {featuredShelf.length > 0 && (
                    <section className={styles.shelf}>
                      <h2 className={styles.shelfHeader}>Featured &amp; Recommended</h2>
                      <div className={styles.shelfRow}>
                        {featuredShelf.map(renderCard)}
                      </div>
                    </section>
                  )}

                  {newShelf.length > 0 && (
                    <section className={styles.shelf}>
                      <h2 className={styles.shelfHeader}>New &amp; Noteworthy</h2>
                      <div className={styles.shelfRow}>
                        {newShelf.map(renderCard)}
                      </div>
                    </section>
                  )}

                  <div className={styles.browseAllRow}>
                    <button className={styles.browseAllBtn} onClick={() => setMode('all')}>
                      Browse all {products.length} Living UIs →
                    </button>
                  </div>
                </>
              )
            )}

            {effectiveMode === 'all' && (
              <div className={`${styles.browseLayout} ${tagRailOpen && allTags.length > 0 ? '' : styles.browseLayoutFull}`}>
                {tagRailOpen && allTags.length > 0 && (
                  <aside className={styles.tagRail}>
                    <div className={styles.tagRailHead}>
                      <h3 className={styles.tagRailTitle}>Tags</h3>
                      <button
                        className={styles.tagRailToggle}
                        onClick={() => toggleTagRail(false)}
                        title="Hide tag filters"
                        aria-label="Hide tag filters"
                      >
                        <PanelLeftClose size={13} />
                      </button>
                    </div>
                    <button
                      className={`${styles.tagRailItem} ${selectedTags.size === 0 ? styles.tagRailItemActive : ''}`}
                      onClick={() => setSelectedTags(new Set())}
                    >
                      <span>All</span>
                      <span className={styles.tagRailCount}>{products.length}</span>
                    </button>
                    {allTags.map(([tag, count]) => (
                      <button
                        key={tag}
                        className={`${styles.tagRailItem} ${selectedTags.has(tag) ? styles.tagRailItemActive : ''}`}
                        onClick={() => toggleTag(tag)}
                      >
                        <span>{tag}</span>
                        <span className={styles.tagRailCount}>{count}</span>
                      </button>
                    ))}
                  </aside>
                )}

                <div className={styles.browseMain}>
                {(degraded || (!tagRailOpen && allTags.length > 0)) && (
                  <div className={styles.toolbar}>
                    {!tagRailOpen && allTags.length > 0 && (
                      <button
                        className={styles.tagRailReopen}
                        onClick={() => toggleTagRail(true)}
                        title="Show tag filters"
                      >
                        <Tags size={13} />
                        Tags{selectedTags.size > 0 ? ` (${selectedTags.size})` : ''}
                      </button>
                    )}
                    {degraded && (
                      <div className={styles.searchWrapper}>
                        <Search size={14} className={styles.searchIcon} />
                        <input
                          className={styles.searchInput}
                          placeholder="search the store"
                          value={searchQuery}
                          onChange={e => setSearchQuery(e.target.value)}
                        />
                      </div>
                    )}
                  </div>
                )}

                {installError && (
                  <div className={styles.errorBar}>
                    <span>{installError}</span>
                    <button className={styles.errorBarClose} onClick={() => setInstallError(null)} aria-label="Dismiss">
                      <X size={14} />
                    </button>
                  </div>
                )}

                {loading ? (
                  <div className={styles.stateCenter}>
                    <Loader2 size={24} className={styles.spinner} />
                  </div>
                ) : loadError ? (
                  <div className={styles.stateCenter}>
                    <p className={styles.stateText}>{loadError}</p>
                    <button className={styles.installBtn} onClick={() => loadCatalog(activeSection.type, sort)}>
                      Retry
                    </button>
                  </div>
                ) : (
                  <>
                    <section className={styles.shelf}>
                      <div className={styles.toolbar}>
                        <h2 className={styles.shelfHeader} style={{ flex: 1 }}>
                          All {activeSection.label}
                        </h2>
                        {!degraded && (
                          <select
                            className={styles.sortSelect}
                            value={sort}
                            onChange={e => setSort(e.target.value as typeof sort)}
                            aria-label="Sort by"
                          >
                            {SORT_OPTIONS.map(o => (
                              <option key={o.value} value={o.value}>{o.label}</option>
                            ))}
                          </select>
                        )}
                      </div>

                      {filteredProducts.length === 0 ? (
                        <div className={styles.stateCenter}>
                          <Search size={32} className={styles.stateIcon} />
                          <p className={styles.stateText}>
                            {products.length === 0 ? 'No apps available yet.' : 'No apps match your filters.'}
                          </p>
                        </div>
                      ) : (
                        <div className={styles.grid}>
                          {filteredProducts.map(renderCard)}
                        </div>
                      )}
                    </section>
                  </>
                )}
                </div>
              </div>
            )}
          </>
      </div>

      {configuring && (
        <ConfigureInstallOverlay
          product={configuring}
          onCancel={() => setConfiguring(null)}
          onInstall={doInstall}
        />
      )}

      <ImportProfileModal
        isOpen={stagedBundle !== null}
        manifest={stagedBundle?.manifest ?? null}
        preview={stagedBundle?.preview ?? null}
        isApplying={bundleApplying}
        error={bundleError}
        onCancel={() => setStagedBundle(null)}
        onApply={applyBundle}
      />
    </div>
  )
}
