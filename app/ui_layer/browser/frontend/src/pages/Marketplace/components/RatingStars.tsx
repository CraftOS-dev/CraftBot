import React, { useEffect, useState } from 'react'
import { Star } from 'lucide-react'
import { fetchRating, submitRating } from '../marketplaceApi'
import type { RatingResponse } from '../marketplaceApi'
import styles from '../Marketplace.module.css'

/** 5-star rating. Interactive only for signed-in CraftBot Live / CraftOS
 *  users (the server verifies the session with the dashboard); everyone
 *  else sees the community average read-only. */
export function RatingStars({ slug }: { slug: string }) {
  const [rating, setRating] = useState<RatingResponse | null>(null)
  const [hovered, setHovered] = useState(0)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(false)

  useEffect(() => {
    setRating(null)
    setError(false)
    fetchRating(slug).then(setRating).catch(() => setError(true))
  }, [slug])

  if (error) return null

  const canRate = rating?.authenticated === true

  const rate = async (stars: number) => {
    if (!canRate || submitting) return
    setSubmitting(true)
    try {
      setRating(await submitRating(slug, stars))
    } catch { /* keep previous state; transient server issue */ }
    setSubmitting(false)
  }

  // Filled state: hover preview > your rating > community average
  const filledTo = (canRate && hovered) || rating?.yourStars || Math.round(rating?.ratingAvg || 0)

  return (
    <div className={styles.ratingBlock}>
      <div
        className={styles.ratingStars}
        onMouseLeave={() => setHovered(0)}
      >
        {[1, 2, 3, 4, 5].map(i => (
          <button
            key={i}
            className={`${styles.ratingStarBtn} ${!canRate ? styles.ratingStarBtnStatic : ''}`}
            onMouseEnter={() => canRate && setHovered(i)}
            onClick={() => rate(i)}
            disabled={submitting || !canRate}
            aria-label={canRate ? `Rate ${i} star${i > 1 ? 's' : ''}` : 'Community rating'}
          >
            <Star
              size={18}
              className={
                i <= filledTo
                  ? (canRate && (hovered || rating?.yourStars) ? styles.starYours : styles.starFilled)
                  : styles.starEmpty
              }
            />
          </button>
        ))}
      </div>
      <span className={styles.ratingMeta}>
        {rating === null
          ? '…'
          : rating.ratingCount === 0
            ? (rating.yourStars
                ? 'Thanks for rating!'
                : canRate ? 'No ratings yet — be the first' : 'No ratings yet')
            : `${rating.ratingAvg.toFixed(1)} · ${rating.ratingCount} rating${rating.ratingCount > 1 ? 's' : ''}${rating.yourStars ? ` · yours: ${rating.yourStars}` : ''}`}
      </span>
      {rating !== null && !canRate && (
        <span className={styles.authNote}>
          Rating is available on CraftBot Live and CraftOS
        </span>
      )}
    </div>
  )
}
