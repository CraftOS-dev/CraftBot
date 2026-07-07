import React, { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  ArrowLeft,
  BadgeCheck,
  Download,
  Eye,
  Loader2,
  Package,
} from 'lucide-react'
import { ImportProfileModal } from '../../components/ui/ImportProfileModal'
import { MarkdownContent } from '../../components/ui/MarkdownContent'
import { useWebSocket } from '../../contexts/WebSocketContext'
import { fetchProduct, formatVersion, reportProductView } from './marketplaceApi'
import { useMarketplaceInstall } from './useMarketplaceInstall'
import { ConfigureInstallOverlay } from './components/ConfigureInstallOverlay'
import { RatingStars } from './components/RatingStars'
import { CommentsSection } from './components/CommentsSection'
import type { MarketplaceProduct } from './types'
import styles from './Marketplace.module.css'

export function ProductDetailPage() {
  const { slug } = useParams<{ type: string; slug: string }>()
  const [product, setProduct] = useState<MarketplaceProduct | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [galleryIndex, setGalleryIndex] = useState(0)
  const [brokenImages, setBrokenImages] = useState<Set<string>>(new Set())

  const {
    installingIds, installedIds, installError,
    configuring, setConfiguring, requestInstall, doInstall,
    stagedBundle, setStagedBundle, applyBundle, bundleApplying, bundleError,
  } = useMarketplaceInstall()
  const { livingUIProjects } = useWebSocket()

  useEffect(() => {
    if (!slug) return
    setLoading(true)
    setError(null)
    setGalleryIndex(0)
    fetchProduct(slug)
      .then(p => {
        setProduct(p)
        if (!p.degraded) reportProductView(p.slug)
      })
      .catch(err => setError(err instanceof Error ? err.message : 'Failed to load product'))
      .finally(() => setLoading(false))
  }, [slug])

  const gallery = useMemo(() => {
    if (!product) return []
    const images = [
      ...(product.screenshots || []),
      ...(product.previewUrl ? [product.previewUrl] : []),
    ]
    return [...new Set(images)].filter(src => !brokenImages.has(src))
  }, [product, brokenImages])

  if (loading) {
    return (
      <div className={styles.page}>
        <div className={styles.stateCenter}><Loader2 size={24} className={styles.spinner} /></div>
      </div>
    )
  }

  if (error || !product) {
    return (
      <div className={styles.page}>
        <div className={styles.pageInner}>
          <div className={styles.breadcrumb}>
            <Link to="/marketplace"><ArrowLeft size={13} /> Back to Marketplace</Link>
          </div>
          <div className={styles.stateCenter}>
            <Package size={32} className={styles.stateIcon} />
            <p className={styles.stateText}>{error || 'Product not found'}</p>
          </div>
        </div>
      </div>
    )
  }

  const appId = product.repoPath || product.slug
  const installing = installingIds.has(appId)
  const installed = installedIds.has(appId)
  const latest = product.versions?.find(v => v.isLatest)
  const degraded = !!product.degraded

  // Update detection: a locally installed project from this catalog entry
  // whose pinned commit (or version) differs from the catalog's latest.
  const installedProject = livingUIProjects.find(p => p.marketplaceSlug === product.slug)
  const updateAvailable = Boolean(
    installedProject && latest && (
      latest.gitCommitSha && installedProject.marketplaceCommitSha
        ? latest.gitCommitSha !== installedProject.marketplaceCommitSha
        : installedProject.marketplaceVersion && latest.version !== installedProject.marketplaceVersion
    ),
  )
  const mainImage = gallery[Math.min(galleryIndex, Math.max(gallery.length - 1, 0))]

  const sectionLabel = product.type === 'living_ui'
    ? 'Living UIs'
    : product.type === 'skill' ? 'Skills' : 'Agent Bundles'

  return (
    <div className={styles.page}>
      <div className={styles.pageInner}>
        <div className={styles.breadcrumb}>
          <Link to="/marketplace"><ArrowLeft size={13} /> All {sectionLabel}</Link>
          <span className={styles.breadcrumbSep}>/</span>
          <span>{product.name}</span>
        </div>

        <h1 className={styles.detailName}>
          {product.name}
          {product.approved && (
            <BadgeCheck size={20} className={styles.approvedBadge} aria-label="CraftOS approved" />
          )}
        </h1>

        <div className={styles.detailLayout}>
          <div className={styles.detailMain}>
            {mainImage ? (
              <img
                src={mainImage}
                alt={product.name}
                referrerPolicy="no-referrer"
                className={styles.galleryMain}
                onError={() => setBrokenImages(prev => new Set(prev).add(mainImage))}
              />
            ) : (
              <div className={styles.galleryPlaceholder}><Package size={48} /></div>
            )}

            {gallery.length > 1 && (
              <div className={styles.galleryThumbs}>
                {gallery.map((src, i) => (
                  <img
                    key={src}
                    src={src}
                    alt={`${product.name} media ${i + 1}`}
                    referrerPolicy="no-referrer"
                    className={`${styles.galleryThumb} ${i === galleryIndex ? styles.galleryThumbActive : ''}`}
                    onClick={() => setGalleryIndex(i)}
                    onError={() => setBrokenImages(prev => new Set(prev).add(src))}
                  />
                ))}
              </div>
            )}

            <div className={styles.installBand}>
              <div>
                <p className={styles.installBandTitle}>
                  {updateAvailable ? `Update ${product.name}` : `Install ${product.name}`}
                </p>
                <p className={styles.installBandMeta}>
                  {product.type === 'skill'
                    ? 'Installs into your skills library and is available to the agent immediately'
                    : product.type === 'agent_bundle'
                      ? "Agent bundle — you'll review its contents before it's applied"
                      : updateAvailable
                        ? `Installed ${installedProject?.marketplaceVersion ? `v${formatVersion(installedProject.marketplaceVersion)}` : 'an older build'} · v${formatVersion(latest?.version || product.latestVersion)} available (installs as a new tab)`
                        : `${latest?.version || product.latestVersion
                            ? `Version ${formatVersion(latest?.version || product.latestVersion)} · `
                            : ''}Runs locally as a Living UI tab`}
                </p>
                {installed && !installing && (
                  <p className={styles.installedNote}>
                    {product.type === 'living_ui'
                      ? 'Installed — check the sidebar for the new tab.'
                      : 'Installed.'}
                  </p>
                )}
                {installError && <p className={styles.errorText}>{installError}</p>}
              </div>
              <button
                className={styles.installBandBtn}
                onClick={() => !installing && requestInstall(product)}
                disabled={installing}
              >
                {installing
                  ? <><Loader2 size={16} className={styles.spinner} /> Installing...</>
                  : <><Download size={16} /> {updateAvailable ? 'Update' : installed && product.type === 'living_ui' ? 'Install again' : 'Install'}</>}
              </button>
            </div>

            {product.descriptionMd && (
              <div className={styles.aboutSection}>
                <h2 className={styles.aboutHeader}>About this {product.type === 'living_ui' ? 'Living UI' : 'product'}</h2>
                <div className={styles.aboutBody}>
                  <MarkdownContent content={product.descriptionMd} />
                </div>
              </div>
            )}

            {!degraded && <CommentsSection slug={product.slug} />}
          </div>

          <aside className={styles.detailSidebar}>
            {product.previewUrl && !brokenImages.has(`capsule:${product.previewUrl}`) && (
              <img
                src={product.previewUrl}
                alt={product.name}
                referrerPolicy="no-referrer"
                className={styles.sidebarCapsule}
                onError={() => setBrokenImages(prev => new Set(prev).add(`capsule:${product.previewUrl}`))}
              />
            )}
            {product.tagline && <p className={styles.detailTagline}>{product.tagline}</p>}

            {product.approved && (
              <span className={styles.approvedRow}>
                <BadgeCheck size={14} /> CraftOS approved
              </span>
            )}

            {!degraded && <RatingStars slug={product.slug} />}

            <div className={styles.sidebarStats}>
              {!degraded && (
                <>
                  <div className={styles.sidebarStatRow}>
                    <span className={styles.sidebarStatLabel}>Downloads</span>
                    <span className={styles.sidebarStatValue}>
                      <Download size={12} /> {product.stats.downloads.toLocaleString()}
                    </span>
                  </div>
                  <div className={styles.sidebarStatRow}>
                    <span className={styles.sidebarStatLabel}>Views</span>
                    <span className={styles.sidebarStatValue}>
                      <Eye size={12} /> {product.stats.views.toLocaleString()}
                    </span>
                  </div>
                </>
              )}
              {(latest?.version || product.latestVersion) && (
                <div className={styles.sidebarStatRow}>
                  <span className={styles.sidebarStatLabel}>Version</span>
                  <span className={styles.sidebarStatValue}>
                    v{formatVersion(latest?.version || product.latestVersion)}
                  </span>
                </div>
              )}
              {product.creator?.name && (
                <div className={styles.sidebarStatRow}>
                  <span className={styles.sidebarStatLabel}>Created by</span>
                  <span className={styles.sidebarStatValue}>
                    {product.creator.url ? (
                      <a href={product.creator.url} target="_blank" rel="noopener noreferrer">{product.creator.name}</a>
                    ) : product.creator.name}
                  </span>
                </div>
              )}
            </div>

            {product.tags.length > 0 && (
              <div className={styles.cardTags}>
                {product.tags.map(tag => <span key={tag} className={styles.tag}>{tag}</span>)}
              </div>
            )}

            {product.versions && product.versions.length > 1 && (
              <div className={styles.versionList}>
                <h3 className={styles.versionListTitle}>Versions</h3>
                {product.versions.map(v => (
                  <div key={v.version} className={styles.versionRow}>
                    <span className={styles.cardVersion}>v{formatVersion(v.version)}</span>
                    {v.isLatest && <span className={styles.latestBadge}>latest</span>}
                  </div>
                ))}
              </div>
            )}
          </aside>
        </div>
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
