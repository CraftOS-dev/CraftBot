import { useEffect, useRef, useState } from 'react'
import { LEFT_EYE_D, RIGHT_EYE_D, BODY_D, FOREHEAD_D, ANTENNA_D } from './mascotPaths'
import { getPose } from './poses'
import type { MascotState } from './types'
import styles from './Mascot.module.css'

interface Props {
  state: MascotState
  size?: number
  /** Used by LivingUI creation: blush appears past 60% progress. */
  progress?: number
  /** Incremented externally to trigger a celebratory wiggle. */
  completedCount?: number
  /** Visual orientation. 'right' is the default (matches the original art);
   *  'left' mirrors the head bump (with its antenna) over to the right side
   *  of the chest. The chest itself is symmetric around the mirror axis so
   *  the "white square" looks identical in both directions. */
  facing?: 'left' | 'right'
}

// Single mirror pivot used for the entire SVG content. The body path's
// world X-range is 9–157 (chest spans -43→+105 in local coords plus the
// translate(52,…)), midpoint x=83. The chest portion of the silhouette is
// symmetric around that axis, so mirroring the full body path here leaves
// the "white square" visually unchanged while the head bump + forehead
// flip to the right side. Eyes and antenna ride along on the same pivot.
const MIRROR = 'translate(166 0) scale(-1 1)'

export function CraftBotMascot({
  state,
  size = 140,
  progress = 0,
  completedCount = 0,
  facing = 'right',
}: Props) {
  const [wiggling, setWiggling] = useState(false)
  const prevCompleted = useRef(completedCount)

  useEffect(() => {
    if (completedCount > prevCompleted.current) {
      setWiggling(true)
      const t = setTimeout(() => setWiggling(false), 600)
      prevCompleted.current = completedCount
      return () => clearTimeout(t)
    }
    prevCompleted.current = completedCount
  }, [completedCount])

  const pose = getPose(state)
  // Blush is pose-driven everywhere except LivingUI creation, where it's a
  // late-stage progress signal (>60%). We OR them so either path lights it up.
  const showBlush = pose.showBlush || (state === 'creating' && progress > 60)
  const breatheClass = pose.sleeping ? styles.sleepBreathe : styles.breathe
  const eyeClass = pose.sleeping ? styles.eyeClosed : styles.eye

  return (
    <div
      className={styles.wrapper}
      style={{ width: size, height: size }}
      aria-hidden="true"
    >
      <div className={`${styles.float} ${wiggling ? styles.wiggle : ''}`}>
        <svg
          viewBox="0 0 160 200"
          width={size}
          height={size}
          xmlns="http://www.w3.org/2000/svg"
          className={breatheClass}
        >
          {/* Mirror group: wraps the body silhouette + the face features so
             they flip as one. The chest is symmetric around x=83 so the
             "white square" reads identically in both directions; only the
             head bump + forehead + antenna + eyes flip sides. */}
          <g transform={facing === 'left' ? MIRROR : undefined}>
            <path
              className={styles.body}
              d={BODY_D}
              fill="#FFFEFE"
              transform="translate(52,31) scale(1,0.94)"
            />

            <path
              d={FOREHEAD_D}
              fill="#FF4F19"
              transform="translate(52,31) scale(1,0.94)"
            />

            <g className={`${eyeClass} ${styles.eyeLeft}`}>
              <path d={LEFT_EYE_D} fill="#FF4D17" transform="translate(82,93)" />
            </g>

            <g className={`${eyeClass} ${styles.eyeRight}`}>
              <path d={RIGHT_EYE_D} fill="#FF4F1A" transform="translate(123.25,92.75)" />
            </g>

            <path d={ANTENNA_D} fill="#FF4F18" transform="translate(52,2)" />

            {showBlush && (
              <g className={styles.blushPulse}>
                <ellipse cx="60" cy="129" rx="6" ry="3.5" fill="#FF9BB0" opacity="0.7" />
                <ellipse cx="148" cy="129" rx="6" ry="3.5" fill="#FF9BB0" opacity="0.7" />
              </g>
            )}
          </g>

          {/* Sleep Z's live OUTSIDE the mirror group so the 'z' letters
             don't render backwards when the mascot faces left. They float
             above the body in the same screen-space position regardless of
             facing direction — they're a stylistic cue, not anatomy. */}
          {pose.sleeping && state !== 'error' && (
            <g
              fill="#C8C8C8"
              fontFamily="system-ui, sans-serif"
              fontWeight="800"
              fontSize="32"
            >
              <text x="118" y="52" className={styles.sleepZ}>z</text>
              <text
                x="142"
                y="30"
                className={`${styles.sleepZ} ${styles.sleepZDelayed}`}
                fontSize="22"
              >
                z
              </text>
            </g>
          )}
        </svg>
      </div>
    </div>
  )
}
