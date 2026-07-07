import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { BadgeCheck, Check, Download, Loader2, Package, Star } from 'lucide-react'
import { formatVersion, reportEvents } from '../marketplaceApi'
import type { MarketplaceProduct } from '../types'
import styles from '../Marketplace.module.css'

interface ProductCardProps {
  product: MarketplaceProduct
  installing: boolean
  installed: boolean
  degraded: boolean
  updateAvailable?: boolean
  onInstall: (product: MarketplaceProduct) => void
}

function formatCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`
  return String(n)
}

export function ProductCard({ product, installing, installed, degraded, updateAvailable, onInstall }: ProductCardProps) {
  const navigate = useNavigate()
  const [thumbFailed, setThumbFailed] = useState(false)
  const { stats } = product

  const openDetail = () => {
    if (!degraded) reportEvents([{ slug: product.slug, type: 'click' }])
    navigate(`/marketplace/${product.type}/${product.slug}`)
  }

  return (
    <div
      className={styles.card}
      onClick={openDetail}
      role="link"
      tabIndex={0}
      onKeyDown={e => { if (e.key === 'Enter') openDetail() }}
    >
      <div className={styles.cardThumbWrap}>
        {product.previewUrl && !thumbFailed ? (
          <img
            src={product.previewUrl}
            alt={product.name}
            referrerPolicy="no-referrer"
            className={styles.cardThumb}
            onError={() => setThumbFailed(true)}
          />
        ) : (
          <div className={styles.cardThumbPlaceholder}>
            <Package size={32} />
          </div>
        )}
        {updateAvailable && (
          <span className={styles.updateBadge}>Update available</span>
        )}
      </div>
      <div className={styles.cardBody}>
        <div className={styles.cardHeader}>
          <span className={styles.cardName}>
            {product.name}
            {product.approved && (
              <BadgeCheck size={14} className={styles.approvedBadge} aria-label="CraftOS approved" />
            )}
          </span>
          {product.latestVersion && <span className={styles.cardVersion}>v{formatVersion(product.latestVersion)}</span>}
        </div>
        {product.tags.length > 0 && (
          <div className={styles.cardTags}>
            {product.tags.slice(0, 3).map(tag => (
              <span key={tag} className={styles.cardTag}>{tag}</span>
            ))}
            {product.tags.length > 3 && (
              <span className={styles.cardTagMore}>+{product.tags.length - 3}</span>
            )}
          </div>
        )}
        <div className={styles.cardDesc}>{product.tagline || product.descriptionMd}</div>
      </div>
      <div className={styles.cardFooter} onClick={e => e.stopPropagation()}>
        {!degraded ? (
          <span className={styles.cardStats}>
            <span className={styles.cardStat} title="Downloads">
              <Download size={11} /> {formatCount(stats.downloads)}
            </span>
            {stats.ratingCount > 0 && (
              <span className={styles.cardStat} title={`${stats.ratingCount} ratings`}>
                <Star size={11} className={styles.starFilled} /> {stats.ratingAvg.toFixed(1)}
              </span>
            )}
            {installed && !installing && (
              <span className={styles.installedBadge}><Check size={11} /></span>
            )}
          </span>
        ) : installed && !installing ? (
          <span className={styles.installedBadge}><Check size={10} /> Installed</span>
        ) : <span />}
        <button
          className={styles.installBtn}
          onClick={() => !installing && onInstall(product)}
          disabled={installing}
        >
          {installing
            ? <><Loader2 size={13} className={styles.spinner} /> Installing</>
            : <><Download size={13} /> Install</>}
        </button>
      </div>
    </div>
  )
}
