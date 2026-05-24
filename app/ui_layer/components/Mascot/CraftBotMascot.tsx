import { useEffect, useRef, useState } from 'react'
import { LEFT_EYE_D, RIGHT_EYE_D, BODY_D, FOREHEAD_D, ANTENNA_D } from './mascotPaths'
import { getPose } from './poses'
import type { MascotState } from './types'
import type { ReactionKind } from './mascotEngine'
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
  /** When non-null, renders one of the reaction visuals (body still stays
   *  pinned by the FSM). 'happy' = > < eyes + yellow ray burst; 'frustrated'
   *  = flat eye dashes + sweat drop. null = normal eye paths. */
  reaction?: ReactionKind | null
}

// Single mirror pivot used for the entire SVG content. The body path's
// world X-range is 9–157 (chest spans -43→+105 in local coords plus the
// translate(52,…)), midpoint x=83. The chest portion of the silhouette is
// symmetric around that axis, so mirroring the full body path here leaves
// the "white square" visually unchanged while the head bump + forehead
// flip to the right side. Eyes and antenna ride along on the same pivot.
const MIRROR = 'translate(166 0) scale(-1 1)'

// Happy-reaction "> <" bracket eyes. Drawn as 3-point polylines that
// form an angle pointing inward — left eye looks like ">" (pointing
// right toward the face center), right eye like "<" (pointing left).
// Sized roughly to match the visual weight of the regular eye paths,
// and positioned slightly below the default eye Y so the brackets sit
// at "smiling-cheek" height rather than "eyebrow" height.
const HAPPY_EYE_Y = 115
const HAPPY_EYE_HALF_SIZE = 8
const HAPPY_EYE_LEFT_X = 82
const HAPPY_EYE_RIGHT_X = 123.25

// Frustrated-reaction "— —" flat eye dashes. Anime "resigned/exhausted"
// shape: just a short horizontal line where each eye would normally be.
// Positioned at the regular eye Y rather than the lower happy-eye Y so
// the expression reads as flat-stare-into-the-void rather than smiling.
const FLAT_EYE_Y = 100
const FLAT_EYE_HALF_WIDTH = 7

// Number of light-ray dashes radiating from the body during a happy
// reaction. 12 gives an evenly-distributed starburst at 30° intervals.
const HAPPY_RAY_COUNT = 12

export function CraftBotMascot({
  state,
  size = 140,
  progress = 0,
  completedCount = 0,
  facing = 'right',
  reaction = null,
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
  // When reacting, the normal eye paths are replaced with bracket polylines
  // or flat dashes below — so eyeClass only matters for the non-reacting path.
  const eyeClass = pose.sleeping ? styles.eyeClosed : styles.eye

  const isHappy = reaction === 'happy'
  const isFrustrated = reaction === 'frustrated'

  // Precompute the happy bracket polylines. Left eye is ">", right eye is
  // "<" — both point inward toward the face center.
  const happyLeftBracket =
    `${HAPPY_EYE_LEFT_X - HAPPY_EYE_HALF_SIZE},${HAPPY_EYE_Y - HAPPY_EYE_HALF_SIZE} ` +
    `${HAPPY_EYE_LEFT_X + HAPPY_EYE_HALF_SIZE},${HAPPY_EYE_Y} ` +
    `${HAPPY_EYE_LEFT_X - HAPPY_EYE_HALF_SIZE},${HAPPY_EYE_Y + HAPPY_EYE_HALF_SIZE}`
  const happyRightBracket =
    `${HAPPY_EYE_RIGHT_X + HAPPY_EYE_HALF_SIZE},${HAPPY_EYE_Y - HAPPY_EYE_HALF_SIZE} ` +
    `${HAPPY_EYE_RIGHT_X - HAPPY_EYE_HALF_SIZE},${HAPPY_EYE_Y} ` +
    `${HAPPY_EYE_RIGHT_X + HAPPY_EYE_HALF_SIZE},${HAPPY_EYE_Y + HAPPY_EYE_HALF_SIZE}`

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

            {isHappy ? (
              // Happy "> <" eyes — polylines (the original eye paths are
              // solid filled shapes and don't deform into a bracket
              // cleanly). Both use the left-eye color for visual unity.
              <g className={styles.happyEyes}>
                <polyline
                  points={happyLeftBracket}
                  fill="none"
                  stroke="#FF4D17"
                  strokeWidth="12"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
                <polyline
                  points={happyRightBracket}
                  fill="none"
                  stroke="#FF4D17"
                  strokeWidth="12"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </g>
            ) : isFrustrated ? (
              // Frustrated "— —" flat eye dashes. Same fade-in animation
              // as happy eyes for visual consistency on swap.
              <g className={styles.happyEyes}>
                <line
                  x1={HAPPY_EYE_LEFT_X - FLAT_EYE_HALF_WIDTH}
                  y1={FLAT_EYE_Y}
                  x2={HAPPY_EYE_LEFT_X + FLAT_EYE_HALF_WIDTH}
                  y2={FLAT_EYE_Y}
                  stroke="#FF4D17"
                  strokeWidth="10"
                  strokeLinecap="round"
                />
                <line
                  x1={HAPPY_EYE_RIGHT_X - FLAT_EYE_HALF_WIDTH}
                  y1={FLAT_EYE_Y}
                  x2={HAPPY_EYE_RIGHT_X + FLAT_EYE_HALF_WIDTH}
                  y2={FLAT_EYE_Y}
                  stroke="#FF4D17"
                  strokeWidth="10"
                  strokeLinecap="round"
                />
              </g>
            ) : (
              <>
                <g className={`${eyeClass} ${styles.eyeLeft}`}>
                  <path d={LEFT_EYE_D} fill="#FF4D17" transform="translate(82,93)" />
                </g>

                <g className={`${eyeClass} ${styles.eyeRight}`}>
                  <path d={RIGHT_EYE_D} fill="#FF4F1A" transform="translate(123.25,92.75)" />
                </g>
              </>
            )}

            <path d={ANTENNA_D} fill="#FF4F18" transform="translate(52,2)" />

            {showBlush && (
              <g className={styles.blushPulse}>
                <ellipse cx="60" cy="129" rx="6" ry="3.5" fill="#FF9BB0" opacity="0.7" />
                <ellipse cx="148" cy="129" rx="6" ry="3.5" fill="#FF9BB0" opacity="0.7" />
              </g>
            )}
          </g>

          {/* Happy-reaction starburst — small radial dashes around the
             body, animated via CSS. Lives outside the mirror group so it
             radiates symmetrically regardless of facing direction. The
             SVG has overflow:visible (.breathe class) so rays that fall
             outside the 160×200 viewBox still render. Each ray is a line
             from (0,-82) to (0,-98) — i.e., a 16-unit vertical dash
             above the local origin. The outer translate moves the origin
             to the body center (80, 109); the inner rotate then spins
             that dash around the center so the rays radiate outward. */}
          {isHappy && (
            <g className={styles.happyRays}>
              {Array.from({ length: HAPPY_RAY_COUNT }).map((_, i) => {
                const angle = (i * 360) / HAPPY_RAY_COUNT
                return (
                  <line
                    key={i}
                    x1="0"
                    y1="-82"
                    x2="0"
                    y2="-98"
                    stroke="#FFE600"
                    strokeWidth="3"
                    strokeLinecap="round"
                    transform={`translate(80 109) rotate(${angle})`}
                  />
                )
              })}
            </g>
          )}

          {/* Frustrated sweat drop — small blue teardrop anchored next to
             the head. Lives OUTSIDE the mirror group so it always renders
             on the same side of the panel regardless of facing direction
             (otherwise it would appear to "swap sides" as the mascot
             turns, which reads as a glitch). The drip animation drops it
             a few pixels then fades out, looping while frustrated. */}
          {isFrustrated && (
            <g className={styles.sweatDrop}>
              <path
                d="M 0 0 Q -6 7 -6 12 A 6 6 0 1 0 6 12 Q 6 7 0 0 Z"
                fill="#6BB7F0"
                transform="translate(135 55)"
              />
              <path
                d="M 0 0 Q -3 3 -3 6 A 3 3 0 1 0 3 6 Q 3 3 0 0 Z"
                fill="#FFFFFF"
                opacity="0.55"
                transform="translate(133 58)"
              />
            </g>
          )}

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
