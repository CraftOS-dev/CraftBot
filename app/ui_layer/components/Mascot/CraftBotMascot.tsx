import { useEffect, useRef, useState, type CSSProperties, type Ref } from 'react'
import {
  LEFT_EYE_D,
  RIGHT_EYE_D,
  BODY_D,
  // ANTENNA = stems[] + paths[]. Each variant in ANTENNA_VARIANTS fully
  // owns both halves — see mascotPaths.ts. The render block below
  // iterates both arrays from the same antennaSpec so a customize-swap
  // changes the whole antenna atomically.
  ANTENNA_VARIANTS,
  ACCESSORIES,
} from './mascotPaths'
import { getPose } from './poses'
import type { MascotState } from './types'
import { STAGE_BODY_SCALE, BODY_FEET_X, BODY_FEET_Y } from './mascotEngine'
import type { ReactionKind, IdleVariant } from './mascotEngine'
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
  /** Pet-system: stage (1-5) — drives body scale. Defaults to 5 (no shrink). */
  stage?: number
  /** Pet-system: body fill color (CSS color string). Default: bone white. */
  bodyColor?: string
  /** Pet-system: accent color, applied to eyes + antenna. */
  accentColor?: string
  /** Pet-system: antenna variant id (key into ANTENNA_VARIANTS). null = no antenna. */
  antennaVariant?: string | null
  /** Pet-system: accessory id (key into ACCESSORIES). null = no accessory. */
  accessory?: string | null
  /** Pet-system: idle-variant hint from useMascotBehavior. */
  idleVariant?: IdleVariant
  /** Pet-system: render the stage-up sparkle overlay. */
  stageUpOverlay?: boolean
  /** Pet-system: render the eating battery sprite. */
  eatingOverlay?: boolean
  /** Pet-system: render the petted blush burst. */
  pettedOverlay?: boolean
  /** Pet-system: render the hungry sigh/drop overlay. */
  hungryOverlay?: boolean
  /** Pet-system: render the dragged drop shadow / shake. */
  draggedOverlay?: boolean
}

// ─────────────────────────────────────────────────────────────────────
// Anchor constants used to compute per-stage positions for the eyes,
// antenna, etc. All in SVG viewBox coordinates (viewBox = "0 0 160 200").
// STAGE_BODY_SCALE + BODY_FEET_X/Y are imported from mascotEngine so the
// dangle code in useMascotBehavior can use the SAME numbers — keeping
// the rotation pivot on the visible body at every stage.
// ─────────────────────────────────────────────────────────────────────

// ── All stages — original silhouette (BODY_D + FOREHEAD_D + ANTENNA_D).
//    Eyes sit on the head bump area, slightly right of body center —
//    this is the iconic CraftBot look. Values lifted verbatim from the
//    pre-pet-system rendering. ────────────────────────────────────────
const NATIVE_LEFT_EYE_X  = 82
const NATIVE_LEFT_EYE_Y  = 93
const NATIVE_RIGHT_EYE_X = 123.25
const NATIVE_RIGHT_EYE_Y = 92.75

// Antenna anchor for Stage 2+ — the (52, 2) viewBox origin used by the
// antenna GROUP. Every variant's `paths[]` is authored in this local
// frame (bulb-equivalent center at local (-5, 10)); see ANTENNA_VARIANTS
// in mascotPaths.ts for the per-variant tip designs.
const NATIVE_ANTENNA_X = 52
const NATIVE_ANTENNA_Y = 2

/** Scale a viewBox-coordinate point around the feet pivot by `s`.
 *  This is the same math the body's scaling transform applies, so eyes /
 *  antenna / blush / accessory all stay LINED UP with the scaled body
 *  regardless of stage. */
function scaledFromFeet(x: number, y: number, s: number): { x: number; y: number } {
  return {
    x: BODY_FEET_X + (x - BODY_FEET_X) * s,
    y: BODY_FEET_Y + (y - BODY_FEET_Y) * s,
  }
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
// The X anchors come from the resting-eye anchors (NATIVE_LEFT/RIGHT_EYE_X)
// via FaceEyes' scaledFromFeet call — no separate happy-eye X needed.
const HAPPY_EYE_Y = 115
const HAPPY_EYE_HALF_SIZE = 8

// Frustrated-reaction "— —" flat eye dashes. At the regular eye Y so the
// expression reads as flat-stare-into-the-void rather than smiling.
const FLAT_EYE_Y = 100
const FLAT_EYE_HALF_WIDTH = 7

// 12 rays at 30° intervals — even starburst around the body center.
const HAPPY_RAY_COUNT = 12

// Default theme color used when no accent is provided.
const DEFAULT_ACCENT = '#FF4D17'

// ─────────────────────────────────────────────────────────────────────
// Sub-renderers — one per face variant + overlay
// ─────────────────────────────────────────────────────────────────────

/** The "normal" eye paths: two filled SVG shapes from mascotPaths, classed
 *  with .eye (blinking) or .eyeClosed (sleeping) based on pose.
 *
 *  Eyes scale by `eyeScale` (less aggressively than the body — see
 *  FaceEyes for the formula) so a young pet keeps its eyes proportionally
 *  bigger than a mature pet, without the eyes overflowing the small face. */
function RestingEyes({
  closed,
  color,
  leftX,
  leftY,
  rightX,
  rightY,
  eyeScale,
}: {
  closed: boolean
  color: string
  leftX: number
  leftY: number
  rightX: number
  rightY: number
  eyeScale: number
}) {
  const eyeClass = closed ? styles.eyeClosed : styles.eye
  return (
    <>
      <g transform={`translate(${leftX} ${leftY}) scale(${eyeScale})`}>
        <g className={`${eyeClass} ${styles.eyeLeft}`}>
          <path d={LEFT_EYE_D} fill={color} />
        </g>
      </g>
      <g transform={`translate(${rightX} ${rightY}) scale(${eyeScale})`}>
        <g className={`${eyeClass} ${styles.eyeRight}`}>
          <path d={RIGHT_EYE_D} fill={color} />
        </g>
      </g>
    </>
  )
}

/** Happy "> <" bracket eyes. Each bracket is drawn at local (0,0) inside
 *  its own translate+scale group so the bracket SIZE shrinks with
 *  `eyeScale` and the POSITION lands on the scaled face. */
function HappyEyes({
  color,
  leftX,
  rightX,
  y,
  eyeScale,
}: {
  color: string
  leftX: number
  rightX: number
  y: number
  eyeScale: number
}) {
  const half = HAPPY_EYE_HALF_SIZE
  const leftPoints  = `${-half},${-half} ${half},0 ${-half},${half}`
  const rightPoints = `${half},${-half} ${-half},0 ${half},${half}`
  return (
    <g className={styles.happyEyes}>
      <g transform={`translate(${leftX} ${y}) scale(${eyeScale})`}>
        <polyline
          points={leftPoints}
          fill="none"
          stroke={color}
          strokeWidth="12"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </g>
      <g transform={`translate(${rightX} ${y}) scale(${eyeScale})`}>
        <polyline
          points={rightPoints}
          fill="none"
          stroke={color}
          strokeWidth="12"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </g>
    </g>
  )
}

/** Frustrated "— —" flat eye dashes. Same fade-in animation as happy
 *  eyes so the swap from regular eyes doesn't read as a hard cut. */
function FrustratedEyes({
  color,
  leftX,
  rightX,
  y,
  eyeScale,
}: {
  color: string
  leftX: number
  rightX: number
  y: number
  eyeScale: number
}) {
  const half = FLAT_EYE_HALF_WIDTH
  return (
    <g className={styles.happyEyes}>
      <g transform={`translate(${leftX} ${y}) scale(${eyeScale})`}>
        <line
          x1={-half}
          y1={0}
          x2={half}
          y2={0}
          stroke={color}
          strokeWidth="10"
          strokeLinecap="round"
        />
      </g>
      <g transform={`translate(${rightX} ${y}) scale(${eyeScale})`}>
        <line
          x1={-half}
          y1={0}
          x2={half}
          y2={0}
          stroke={color}
          strokeWidth="10"
          strokeLinecap="round"
        />
      </g>
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
  color,
  bodyScale,
}: {
  reaction: ReactionKind | null
  sleeping: boolean
  eyeGroupRef?: Ref<SVGGElement>
  color: string
  bodyScale: number
}) {
  // All stages use the same native eye anchors. EYE SIZE is decoupled
  // from BODY SIZE so younger pets have proportionally bigger eyes:
  //   eyeScale = bodyScale + (1 - bodyScale) * 0.25
  // The 0.25 blend factor controls how much the eyes "resist" shrinking
  // — bigger factor → bigger ratio difference at low stages.
  //
  //   Stage | bodyScale | eyeScale | eye:body ratio
  //   ------+-----------+----------+----------------
  //     5   |   1.000   |  1.000   |  1.00  (native)
  //     4   |   0.875   |  0.906   |  1.04
  //     3   |   0.719   |  0.789   |  1.10
  //     2   |   0.594   |  0.696   |  1.17
  //     1   |   0.469   |  0.602   |  1.28  (biggest ratio)
  const eyeScale     = bodyScale + (1 - bodyScale) * 0.25
  const restingLeft  = scaledFromFeet(NATIVE_LEFT_EYE_X,  NATIVE_LEFT_EYE_Y,  bodyScale)
  const restingRight = scaledFromFeet(NATIVE_RIGHT_EYE_X, NATIVE_RIGHT_EYE_Y, bodyScale)
  const happy        = scaledFromFeet(0, HAPPY_EYE_Y, bodyScale)
  const flat         = scaledFromFeet(0, FLAT_EYE_Y,  bodyScale)

  let inner
  if (reaction === 'happy') {
    inner = (
      <HappyEyes
        color={color}
        leftX={restingLeft.x}
        rightX={restingRight.x}
        y={happy.y}
        eyeScale={eyeScale}
      />
    )
  } else if (reaction === 'frustrated') {
    inner = (
      <FrustratedEyes
        color={color}
        leftX={restingLeft.x}
        rightX={restingRight.x}
        y={flat.y}
        eyeScale={eyeScale}
      />
    )
  } else {
    inner = (
      <RestingEyes
        closed={sleeping}
        color={color}
        leftX={restingLeft.x}
        leftY={restingLeft.y}
        rightX={restingRight.x}
        rightY={restingRight.y}
        eyeScale={eyeScale}
      />
    )
  }
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
  stage = 5,
  bodyColor = '#FFFEFE',
  accentColor = DEFAULT_ACCENT,
  antennaVariant = 'antenna_1',
  accessory = null,
  idleVariant = 'normal',
  stageUpOverlay = false,
  eatingOverlay = false,
  pettedOverlay: _pettedOverlay = false,
  hungryOverlay = false,
  draggedOverlay = false,
}: Props) {
  const wiggling = useWiggleOnIncrease(completedCount)
  const pose = getPose(state)
  // Blush rendering removed (user feedback). `progress` is also no longer
  // consumed for blush; preserved on the prop to avoid breaking callers
  // (LivingUI creation page passes it but nothing reads it now).
  void progress
  const breatheClass = pose.sleeping ? styles.sleepBreathe : styles.breathe

  // Idle variant overrides for mood/hunger. Class composition only — the
  // original .breathe / .sleepBreathe still drive the animation, the
  // variant just retunes duration/filter.
  const variantClass =
    idleVariant === 'sad'
      ? styles.restingSad
      : idleVariant === 'happy'
      ? styles.restingHappy
      : idleVariant === 'hungry'
      ? styles.restingHungry
      : ''

  // Stage-driven uniform scale of the body silhouette, anchored at the
  // FEET pivot so the pet keeps standing on the same ground line.
  // The body's native compound transform (translate(52,31) scale(1,0.94))
  // stays intact INSIDE this group; the outer scale around feet only
  // shrinks the whole silhouette without distorting it.
  const bodyScale = STAGE_BODY_SCALE[stage] ?? 1
  const bodyScaleTransform =
    bodyScale === 1
      ? undefined
      : `translate(${BODY_FEET_X} ${BODY_FEET_Y}) ` +
        `scale(${bodyScale}) ` +
        `translate(${-BODY_FEET_X} ${-BODY_FEET_Y})`

  // Antenna only renders from Stage 2+ — hatchlings haven't grown one yet.
  const antennaSpec = stage >= 2 && antennaVariant
    ? ANTENNA_VARIANTS[antennaVariant] ?? ANTENNA_VARIANTS.antenna_1
    : null
  const antennaAnchor = scaledFromFeet(NATIVE_ANTENNA_X, NATIVE_ANTENNA_Y, bodyScale)
  const antennaTransform =
    `translate(${antennaAnchor.x} ${antennaAnchor.y}) scale(${bodyScale})`

  const accessoryDef = accessory ? ACCESSORIES[accessory] : null

  const wrapperStyle: CSSProperties = { width: size, height: size }

  return (
    <div
      className={styles.wrapper}
      style={wrapperStyle}
      aria-hidden="true"
    >
      <div
        className={`${styles.float} ${wiggling ? styles.wiggle : ''} ${draggedOverlay ? styles.dragged : ''}`}
      >
        <svg
          viewBox="0 0 160 200"
          width={size}
          height={size}
          xmlns="http://www.w3.org/2000/svg"
          className={`${styles.mascotSvg} ${breatheClass} ${variantClass} ${draggedOverlay ? styles.draggedBreathe : ''} ${eatingOverlay ? styles.eating : ''}`}
        >
          {/* Mirror group: body silhouette + face features flip as one.
             Chest is symmetric around x=83 so the "white square" reads
             identically in both directions; only head bump + forehead +
             antenna + eyes flip sides. */}
          <g transform={facing === 'left' ? MIRROR : undefined}>

            {/* BODY GROUP — clean silhouette + the variant's body-frame
               stem(s) + accessory. Every variant ships at least one stem
               (all using the same ANTENNA_STEM_D shape so thickness is
               consistent across the catalog); the twin variant ships two.

               ╔═══════════════════════════════════════════════════════╗
               ║ ANTENNA = stems[] (here) + paths[] (tip, below).      ║
               ║ Both arrays come from the SAME antennaSpec, so a      ║
               ║ customize-swap changes the whole antenna atomically.  ║
               ╚═══════════════════════════════════════════════════════╝ */}
            <g transform={bodyScaleTransform}>
              <path
                className={styles.body}
                d={BODY_D}
                fill={bodyColor}
                transform="translate(52,31) scale(1,0.94)"
              />
              {/* VARIANT STEMS (body-frame) — every variant ships at least
                  one stem and they all share the same ANTENNA_STEM_D
                  silhouette. Multi-stem variants (twin) supply a per-stem
                  transform that runs in body-local space before the outer
                  body transform. The body transform wraps the per-stem
                  transform in a <g> so SVG composes them left-to-right. */}
              {antennaSpec?.stems?.map((s, i) => (
                <g key={i} transform="translate(52,31) scale(1,0.94)">
                  <path d={s.d} fill={accentColor} transform={s.transform} />
                </g>
              ))}
            </g>

            {/* EYES — size scales with body (Stage 5 = native size,
               matches the iconic mascot). Positions branch on stage:
               Stage 1 uses symmetric cube anchors, Stage 2+ uses the
               original head-bump anchors. */}
            <FaceEyes
              reaction={reaction}
              sleeping={pose.sleeping}
              eyeGroupRef={eyeGroupRef}
              color={accentColor}
              bodyScale={bodyScale}
            />

            {/* ANTENNA TIPS — bulbs / star / leaves / X / etc. Paired
                with the variant's stems[] in the body group above. Each
                tip path can carry its own local transform (rotation for
                the X variant, horizontal offset for the twin variant). */}
            {antennaSpec && (
              <g transform={antennaTransform} aria-hidden="true">
                {antennaSpec.paths.map((p, i) => (
                  <path key={i} d={p.d} fill={accentColor} transform={p.transform} />
                ))}
              </g>
            )}

            {/* ACCESSORY (hat) — rendered LAST inside the mirror group so
                it draws on top of the antenna stems AND tips. Wrapped in
                bodyScaleTransform so it shrinks with the body at lower
                stages. Inner transform: scale 1.5× around (80, 66), then
                anchor to (95, 58) — +15 forward in body-local x (mirror
                flips the sign for facing='left'), and -8 up so the brim
                sits at the body top rather than sinking in. */}
            {accessoryDef && (
              <g transform={bodyScaleTransform}>
                <g
                  aria-hidden="true"
                  transform="translate(95 58) scale(1.5) translate(-80 -66)"
                >
                  {accessoryDef.paths.map((p, i) => (
                    <path key={i} d={p.d} fill={p.fill} />
                  ))}
                </g>
              </g>
            )}
          </g>

          {/* Overlays outside the mirror group — see each sub-component
             for why their position must stay screen-stable. Each is
             wrapped in bodyScaleTransform so it scales around the body's
             feet pivot just like the body silhouette — without this,
             at low stages (small body) the overlays float in mid-air
             above where the body used to be at full size. */}
          <g transform={bodyScaleTransform}>
            {reaction === 'happy' && <HappyRays />}
            {reaction === 'frustrated' && <SweatDrop />}
            {pose.sleeping && state !== 'error' && <SleepZs />}
            {hungryOverlay && (
              <g className={styles.hungrySigh}>
                <path
                  d="M 0 0 Q -6 7 -6 12 A 6 6 0 1 0 6 12 Q 6 7 0 0 Z"
                  fill="#6BB7F0"
                  transform="translate(135 55)"
                />
              </g>
            )}
            {stageUpOverlay && (
              <g className={styles.stageUpSparkle}>
                {Array.from({ length: 16 }).map((_, i) => (
                  <line
                    key={i}
                    x1="0"
                    y1="-92"
                    x2="0"
                    y2="-112"
                    stroke="#FFD54F"
                    strokeWidth="3.5"
                    strokeLinecap="round"
                    transform={`translate(80 109) rotate(${(i * 360) / 16})`}
                  />
                ))}
              </g>
            )}
          </g>
        </svg>
        {eatingOverlay && (
          // Battery is rendered at half the mascot height — substantial
          // enough to read as a "real" object the mascot bites into.
          // --eating-side: +1 when facing right, -1 when facing left,
          // consumed by .eatingBattery's `left` calc so the drop lands
          // IN FRONT of the mascot (toward the facing direction)
          // rather than dead-center over the body.
          <div
            className={styles.eatingBattery}
            style={{ '--eating-side': facing === 'left' ? -1 : 1 } as CSSProperties}
            aria-hidden="true"
          >
            <BatterySprite size={size * 0.5} />
          </div>
        )}
      </div>
    </div>
  )
}

/** Battery SVG drawn in front of the mascot during eating AND reused in
 *  the Shop's purchase row and the HUD's Food button. Designed to match
 *  the flat / thick-outline cartoon art style of the pet scene: tilted
 *  body, dark cartoon outline, yellow wrap-band on the upper third,
 *  white terminal cap, and a yellow lightning bolt on the dark lower
 *  section. Colors are fixed (not driven by accentColor) so a battery
 *  always reads as a battery regardless of which accent the user picked.
 *
 *  `size` is the rendered HEIGHT in px; width follows the natural
 *  viewBox ratio (70:90 ≈ 0.78) so the silhouette stays proportional. */
export function BatterySprite({ size = 58 }: { size?: number } = {}) {
  return (
    <svg
      width={size * (70 / 90)}
      height={size}
      viewBox="-5 -5 70 90"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <g transform="rotate(12 30 40)">
        {/* Body — dark base with thick cartoon outline */}
        <rect
          x="10" y="14" width="40" height="58" rx="7"
          fill="#2D2D2D"
          stroke="#1A1A1A"
          strokeWidth="3"
          strokeLinejoin="round"
        />
        {/* Yellow band wrapping the upper third — rounded top corners
            (matched to the body's rx) and a flat bottom edge. */}
        <path
          d="M 17 14 L 43 14 A 7 7 0 0 1 50 21 L 50 36 L 10 36 L 10 21 A 7 7 0 0 1 17 14 Z"
          fill="#FFC633"
        />
        {/* Terminal cap — drawn AFTER the body so its bottom edge sits in
            front of the body's top outline, like a real battery's nub. */}
        <rect
          x="23" y="5" width="14" height="11" rx="2.5"
          fill="#E8E8E8"
          stroke="#1A1A1A"
          strokeWidth="2.5"
          strokeLinejoin="round"
        />
        {/* Lightning bolt — classic zigzag on the dark lower section */}
        <path
          d="M 35 41 L 24 56 L 32 56 L 25 69 L 38 53 L 30 53 Z"
          fill="#FFE066"
          stroke="#1A1A1A"
          strokeWidth="1.6"
          strokeLinejoin="round"
        />
      </g>
    </svg>
  )
}
