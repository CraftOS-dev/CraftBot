import { useEffect, useRef, useState, type Ref } from 'react'
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
  /** External handle to the <g> that wraps the eyes. useCursorEyeTracking
   *  writes its `transform` attribute directly for the idle eye-following
   *  animation; the component must NOT bind that attribute in JSX or React
   *  will clobber the hook's writes on every render. */
  eyeGroupRef?: Ref<SVGGElement>
}

// ─────────────────────────────────────────────────────────────────────
// Geometry & visual constants
// ─────────────────────────────────────────────────────────────────────

// Single mirror pivot used for the entire SVG content. The body path's
// world X-range is 9–157 (chest spans -43→+105 in local coords plus the
// translate(52,…)), midpoint x=83. The chest portion of the silhouette is
// symmetric around that axis, so mirroring the full body path here leaves
// the "white square" visually unchanged while the head bump + forehead
// flip to the right side. Eyes and antenna ride along on the same pivot.
const MIRROR = 'translate(166 0) scale(-1 1)'

// Happy-reaction "> <" bracket eyes. Positioned slightly below the default
// eye Y so the brackets sit at "smiling-cheek" height, not "eyebrow" height.
const HAPPY_EYE_Y = 115
const HAPPY_EYE_HALF_SIZE = 8
const HAPPY_EYE_LEFT_X = 82
const HAPPY_EYE_RIGHT_X = 123.25

// Frustrated-reaction "— —" flat eye dashes. At the regular eye Y so the
// expression reads as flat-stare-into-the-void rather than smiling.
const FLAT_EYE_Y = 100
const FLAT_EYE_HALF_WIDTH = 7

// 12 rays at 30° intervals — even starburst around the body center.
const HAPPY_RAY_COUNT = 12

// Theme color used for all eye variants (regular paths + brackets + flat
// dashes). One source of truth so the reactions read as the same character.
const EYE_COLOR = '#FF4D17'

// ─────────────────────────────────────────────────────────────────────
// Sub-renderers — one per face variant + overlay
// ─────────────────────────────────────────────────────────────────────

/** The "normal" eye paths: two filled SVG shapes from mascotPaths, classed
 *  with .eye (blinking) or .eyeClosed (sleeping) based on pose. */
function RestingEyes({ closed }: { closed: boolean }) {
  const eyeClass = closed ? styles.eyeClosed : styles.eye
  return (
    <>
      <g className={`${eyeClass} ${styles.eyeLeft}`}>
        <path d={LEFT_EYE_D} fill={EYE_COLOR} transform="translate(82,93)" />
      </g>
      <g className={`${eyeClass} ${styles.eyeRight}`}>
        <path d={RIGHT_EYE_D} fill="#FF4F1A" transform="translate(123.25,92.75)" />
      </g>
    </>
  )
}

/** Happy "> <" bracket eyes. Polylines because the original eye paths are
 *  solid fills and don't deform into brackets cleanly. Both eyes use the
 *  same color for visual unity during the reaction. */
function HappyEyes() {
  const leftPoints =
    `${HAPPY_EYE_LEFT_X - HAPPY_EYE_HALF_SIZE},${HAPPY_EYE_Y - HAPPY_EYE_HALF_SIZE} ` +
    `${HAPPY_EYE_LEFT_X + HAPPY_EYE_HALF_SIZE},${HAPPY_EYE_Y} ` +
    `${HAPPY_EYE_LEFT_X - HAPPY_EYE_HALF_SIZE},${HAPPY_EYE_Y + HAPPY_EYE_HALF_SIZE}`
  const rightPoints =
    `${HAPPY_EYE_RIGHT_X + HAPPY_EYE_HALF_SIZE},${HAPPY_EYE_Y - HAPPY_EYE_HALF_SIZE} ` +
    `${HAPPY_EYE_RIGHT_X - HAPPY_EYE_HALF_SIZE},${HAPPY_EYE_Y} ` +
    `${HAPPY_EYE_RIGHT_X + HAPPY_EYE_HALF_SIZE},${HAPPY_EYE_Y + HAPPY_EYE_HALF_SIZE}`
  return (
    <g className={styles.happyEyes}>
      <polyline
        points={leftPoints}
        fill="none"
        stroke={EYE_COLOR}
        strokeWidth="12"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <polyline
        points={rightPoints}
        fill="none"
        stroke={EYE_COLOR}
        strokeWidth="12"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </g>
  )
}

/** Frustrated "— —" flat eye dashes. Same fade-in animation as happy
 *  eyes so the swap from regular eyes doesn't read as a hard cut. */
function FrustratedEyes() {
  return (
    <g className={styles.happyEyes}>
      <line
        x1={HAPPY_EYE_LEFT_X - FLAT_EYE_HALF_WIDTH}
        y1={FLAT_EYE_Y}
        x2={HAPPY_EYE_LEFT_X + FLAT_EYE_HALF_WIDTH}
        y2={FLAT_EYE_Y}
        stroke={EYE_COLOR}
        strokeWidth="10"
        strokeLinecap="round"
      />
      <line
        x1={HAPPY_EYE_RIGHT_X - FLAT_EYE_HALF_WIDTH}
        y1={FLAT_EYE_Y}
        x2={HAPPY_EYE_RIGHT_X + FLAT_EYE_HALF_WIDTH}
        y2={FLAT_EYE_Y}
        stroke={EYE_COLOR}
        strokeWidth="10"
        strokeLinecap="round"
      />
    </g>
  )
}

/** Pick the face variant for the current reaction state. The wrapping
 *  <g> exists in every branch so the eye-tracking hook always has a
 *  stable element to write its transform onto, even across reaction
 *  swaps. We intentionally do NOT set a `transform` attribute here —
 *  the hook owns it; binding from React would clobber its writes.
 *
 *  The `.eyeTrackingGroup` class adds a CSS `transition: transform` so
 *  the hook's setAttribute writes interpolate rather than snap. Same
 *  duration both for per-mousemove updates (light smoothing, feels like
 *  natural eye easing) and for the reset to center when tracking turns
 *  off — that reset is what would otherwise read as a jump. */
function FaceEyes({
  reaction,
  sleeping,
  eyeGroupRef,
}: {
  reaction: ReactionKind | null
  sleeping: boolean
  eyeGroupRef?: Ref<SVGGElement>
}) {
  let inner
  if (reaction === 'happy') inner = <HappyEyes />
  else if (reaction === 'frustrated') inner = <FrustratedEyes />
  else inner = <RestingEyes closed={sleeping} />
  return <g ref={eyeGroupRef} className={styles.eyeTrackingGroup}>{inner}</g>
}

/** Happy-reaction starburst. Lives outside the mirror group so it radiates
 *  symmetrically regardless of facing direction. The .breathe class sets
 *  overflow:visible so rays that fall outside the 160×200 viewBox still
 *  render. Each ray is a 16-unit dash positioned 82–98 units above local
 *  origin; the outer translate moves the origin to body center (80, 109),
 *  the inner rotate spins the dash around that center. */
function HappyRays() {
  return (
    <g className={styles.happyRays}>
      {Array.from({ length: HAPPY_RAY_COUNT }).map((_, i) => (
        <line
          key={i}
          x1="0"
          y1="-82"
          x2="0"
          y2="-98"
          stroke="#FFE600"
          strokeWidth="3"
          strokeLinecap="round"
          transform={`translate(80 109) rotate(${(i * 360) / HAPPY_RAY_COUNT})`}
        />
      ))}
    </g>
  )
}

/** Frustrated-reaction sweat drop — blue teardrop anchored next to the
 *  head. Lives OUTSIDE the mirror group so it stays on the same side of
 *  the panel regardless of facing direction (a side-swap would read as a
 *  glitch). The CSS animation handles the drip + fade. */
function SweatDrop() {
  return (
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
  )
}

/** Sleep Z's. Live OUTSIDE the mirror group so the 'z' letters don't
 *  render backwards when the mascot faces left — they're a stylistic
 *  cue, not anatomy. */
function SleepZs() {
  return (
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
  )
}

// ─────────────────────────────────────────────────────────────────────
// Wiggle trigger — fires the celebrate wiggle when the completed-count
// counter rises. Local-state hook factored out so the component body
// stays focused on render logic.
// ─────────────────────────────────────────────────────────────────────
function useWiggleOnIncrease(counter: number): boolean {
  const [wiggling, setWiggling] = useState(false)
  const prev = useRef(counter)

  useEffect(() => {
    if (counter > prev.current) {
      setWiggling(true)
      const t = setTimeout(() => setWiggling(false), 600)
      prev.current = counter
      return () => clearTimeout(t)
    }
    prev.current = counter
  }, [counter])

  return wiggling
}

// ─────────────────────────────────────────────────────────────────────
// Top-level component
// ─────────────────────────────────────────────────────────────────────

export function CraftBotMascot({
  state,
  size = 140,
  progress = 0,
  completedCount = 0,
  facing = 'right',
  reaction = null,
  eyeGroupRef,
}: Props) {
  const wiggling = useWiggleOnIncrease(completedCount)
  const pose = getPose(state)
  // Blush is pose-driven everywhere except LivingUI creation, where it's a
  // late-stage progress signal (>60%). OR them so either path lights it up.
  const showBlush = pose.showBlush || (state === 'creating' && progress > 60)
  const breatheClass = pose.sleeping ? styles.sleepBreathe : styles.breathe

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
          {/* Mirror group: body silhouette + face features flip as one.
             Chest is symmetric around x=83 so the "white square" reads
             identically in both directions; only head bump + forehead +
             antenna + eyes flip sides. */}
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
            <FaceEyes reaction={reaction} sleeping={pose.sleeping} eyeGroupRef={eyeGroupRef} />
            <path d={ANTENNA_D} fill="#FF4F18" transform="translate(52,2)" />
            {showBlush && (
              <g className={styles.blushPulse}>
                <ellipse cx="60" cy="129" rx="6" ry="3.5" fill="#FF9BB0" opacity="0.7" />
                <ellipse cx="148" cy="129" rx="6" ry="3.5" fill="#FF9BB0" opacity="0.7" />
              </g>
            )}
          </g>

          {/* Overlays outside the mirror group — see each sub-component
             for why their position must stay screen-stable. */}
          {reaction === 'happy' && <HappyRays />}
          {reaction === 'frustrated' && <SweatDrop />}
          {pose.sleeping && state !== 'error' && <SleepZs />}
        </svg>
      </div>
    </div>
  )
}
