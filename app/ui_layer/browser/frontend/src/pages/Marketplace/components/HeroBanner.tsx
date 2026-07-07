import React, { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import type { Banner } from '../types'
import styles from '../Marketplace.module.css'

const ROTATE_INTERVAL_MS = 7000

/** Steam-style main capsule: full-bleed image with an info panel fading in
 *  from the right. Server-driven; hidden entirely in degraded mode. */
export function HeroBanner({ banners }: { banners: Banner[] }) {
  const navigate = useNavigate()
  const [index, setIndex] = useState(0)
  const heroes = banners.filter(b => b.slot === 'hero')

  useEffect(() => {
    if (heroes.length < 2) return
    const t = setInterval(() => setIndex(i => (i + 1) % heroes.length), ROTATE_INTERVAL_MS)
    return () => clearInterval(t)
  }, [heroes.length])

  if (heroes.length === 0) return null
  const banner = heroes[Math.min(index, heroes.length - 1)]

  const open = () => {
    if (banner.productSlug) navigate(`/marketplace/living_ui/${banner.productSlug}`)
    else if (banner.ctaUrl) window.open(banner.ctaUrl, '_blank', 'noopener')
  }

  return (
    <div className={styles.hero}>
      <div
        className={styles.heroSlide}
        style={banner.imageUrl ? { backgroundImage: `url(${banner.imageUrl})` } : undefined}
        onClick={open}
        role={banner.productSlug || banner.ctaUrl ? 'link' : undefined}
      >
        <div className={styles.heroOverlay}>
          <span className={styles.heroKicker}>Featured</span>
          <h2 className={styles.heroTitle}>{banner.title}</h2>
          {banner.subtitle && <p className={styles.heroSubtitle}>{banner.subtitle}</p>}
          {(banner.productSlug || banner.ctaUrl) && (
            <button className={styles.heroCta} onClick={e => { e.stopPropagation(); open() }}>
              View
            </button>
          )}
        </div>
      </div>
      {heroes.length > 1 && (
        <>
          <button
            className={`${styles.heroArrow} ${styles.heroArrowLeft}`}
            onClick={() => setIndex(i => (i - 1 + heroes.length) % heroes.length)}
            aria-label="Previous banner"
          >
            <ChevronLeft size={20} />
          </button>
          <button
            className={`${styles.heroArrow} ${styles.heroArrowRight}`}
            onClick={() => setIndex(i => (i + 1) % heroes.length)}
            aria-label="Next banner"
          >
            <ChevronRight size={20} />
          </button>
          <div className={styles.heroDots}>
            {heroes.map((_, i) => (
              <button
                key={i}
                className={`${styles.heroDot} ${i === index ? styles.heroDotActive : ''}`}
                onClick={() => setIndex(i)}
                aria-label={`Banner ${i + 1}`}
              />
            ))}
          </div>
        </>
      )}
    </div>
  )
}
