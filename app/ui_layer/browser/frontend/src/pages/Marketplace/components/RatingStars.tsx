import React, { useEffect, useState } from 'react'
import { Star } from 'lucide-react'
import { fetchRating, submitRating } from '../marketplaceApi'
import type { RatingResponse } from '../marketplaceApi'
import styles from '../Marketplace.module.css'

/** Interactive 5-star rating: shows the community average and lets this
 *  instance rate (one rating per install, upserted server-side). */
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

  const rate = async (stars: number) => {
    if (submitting) return
    setSubmitting(true)
    try {
      setRating(await submitRating(slug, stars))
    } catch { /* keep previous state; transient server issue */ }
    setSubmitting(false)
  }

  // Filled state: hover preview > your rating > community average
  const filledTo = hovered || rating?.yourStars || Math.round(rating?.ratingAvg || 0)

  return (
    <div className={styles.ratingBlock}>
      <div className={styles.ratingStars} onMouseLeave={() => setHovered(0)}>
        {[1, 2, 3, 4, 5].map(i => (
          <button
            key={i}
            className={styles.ratingStarBtn}
            onMouseEnter={() => setHovered(i)}
            onClick={() => rate(i)}
            disabled={submitting}
            aria-label={`Rate ${i} star${i > 1 ? 's' : ''}`}
          >
            <Star
              size={18}
              className={
                i <= filledTo
                  ? (hovered || rating?.yourStars ? styles.starYours : styles.starFilled)
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
            ? (rating.yourStars ? 'Thanks for rating!' : 'No ratings yet — be the first')
            : `${rating.ratingAvg.toFixed(1)} · ${rating.ratingCount} rating${rating.ratingCount > 1 ? 's' : ''}${rating.yourStars ? ` · yours: ${rating.yourStars}` : ''}`}
      </span>
    </div>
  )
}
