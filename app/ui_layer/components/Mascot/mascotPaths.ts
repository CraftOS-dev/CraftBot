// SVG path data for the CraftBot mascot. Lifted verbatim from the original
// logo (paths 2 and 3 for the eyes). Kept in their own module so the React
// component stays focused on animation orchestration.

export const LEFT_EYE_D =
  'M0 0 C2.92937654 1.81310142 5.43647949 3.87295899 7 7 C7.12311126 9.56761586 7.18836415 12.10706019 7.203125 14.67578125 C7.20882507 15.43795456 7.21452515 16.20012787 7.22039795 16.98539734 C7.22985081 18.60019542 7.23638307 20.21501282 7.24023438 21.82983398 C7.24992133 24.29250092 7.28093303 26.75432656 7.3125 29.21679688 C7.3190321 30.78645338 7.32428176 32.35611586 7.328125 33.92578125 C7.3404718 34.65928299 7.3528186 35.39278473 7.36553955 36.14851379 C7.34154924 41.69538739 6.08230904 44.91769096 2.1875 48.8125 C-0.8527265 50.46290867 -2.57949832 50.54728027 -6 50 C-8.9228334 48.16899068 -11.43323854 46.13352292 -13 43 C-13.28424778 37.93535225 -13.31377183 32.86972252 -13.35009766 27.79785156 C-13.36663059 26.1063051 -13.39388581 24.41482773 -13.43212891 22.72363281 C-13.48710365 20.27893001 -13.50880304 17.835864 -13.5234375 15.390625 C-13.54610687 14.64041077 -13.56877625 13.89019653 -13.59213257 13.11724854 C-13.57625216 9.13973933 -13.06467198 6.59267156 -10.59228516 3.53808594 C-6.97219204 -0.00631866 -5.04757551 -0.58241256 0 0 Z'

export const RIGHT_EYE_D =
  'M0 0 C4.33669495 0.36139125 5.72030822 1.28280822 8.75 4.3125 C11.19715759 7.98323639 11.07300278 10.80084797 11.0859375 15.05078125 C11.0925943 15.80916794 11.0992511 16.56755463 11.10610962 17.34892273 C11.11623038 18.95353778 11.12092682 20.55819486 11.12060547 22.1628418 C11.12496613 24.60602159 11.16125324 27.04737571 11.19921875 29.49023438 C11.20508977 31.05207718 11.20905726 32.61392854 11.2109375 34.17578125 C11.22530853 34.90098465 11.23967957 35.62618805 11.25448608 36.37336731 C11.20886626 41.49335244 9.99115623 44.38403683 6.75 48.3125 C3.0126144 50.8040904 1.17668417 50.77043285 -3.25 50.3125 C-6.00329021 48.51687595 -7.77627461 47.25995078 -9.25 44.3125 C-9.53474008 38.94460889 -9.56375869 33.57565738 -9.60009766 28.20092773 C-9.61665091 26.40554842 -9.6439329 24.61023484 -9.68212891 22.81518555 C-9.73696923 20.22409959 -9.75878148 17.63455732 -9.7734375 15.04296875 C-9.79610687 14.24384567 -9.81877625 13.4447226 -9.84213257 12.62138367 C-9.82575533 8.28890941 -9.65327311 6.79951266 -6.77978516 3.3293457 C-5.94495605 2.66378662 -5.11012695 1.99822754 -4.25 1.3125 C-3.25 0.3125 -3.25 0.3125 0 0 Z'

// BODY_D — clean rounded-rect body silhouette, NO head bump baked in.
// (The head bump used to be part of this path, which made it impossible
// to hide the bump without also hiding the body. Now the head bump is
// HEAD_BUMP_D, a separate piece that gates with the antenna assembly.)
//
// Coordinates are in the same local space as the original BODY_D so the
// existing `translate(52,31) scale(1,0.94)` transform still positions it
// correctly. Path-coord box: x = -43..105, y = 37..167 (chest + feet,
// no head). After transform → viewBox x = 9..157, y = 66..188.
export const BODY_D =
  'M -31 37 L 93 37 A 12 12 0 0 1 105 49 L 105 155 A 12 12 0 0 1 93 167 L -31 167 A 12 12 0 0 1 -43 155 L -43 49 A 12 12 0 0 1 -31 37 Z'

// ═════════════════════════════════════════════════════════════════════
// THE ANTENNA — STEM + BULB TOGETHER FORM ONE ANTENNA
// ─────────────────────────────────────────────────────────────────────
// IMPORTANT — DO NOT TREAT THESE AS SEPARATE FEATURES.
//
// The "antenna" the user sees on the mascot is built from TWO parts:
//
//   STEM(S)  (lower) — `stems[]` in the ANTENNA_VARIANTS entry. Drawn
//                      inside the body group with the body's transform.
//                      Every variant uses ANTENNA_STEM_D so thickness is
//                      consistent across the catalog; the twin variant
//                      ships two copies with horizontal offsets.
//
//   TIP(S)   (upper) — `paths[]` in the ANTENNA_VARIANTS entry. Drawn
//                      inside the antenna group at (52, 2). The default
//                      is ANTENNA_BULB_D; alternative tips include the
//                      rounded star, leaves, X, and double bulb.
//
// OWNERSHIP RULE — both arrays belong to the SAME ANTENNA_VARIANTS entry,
// so selecting a different antenna swaps STEM AND TIP atomically. Never
// render a stem outside of antennaSpec; if you do, picking a different
// variant will only swap the tip and the user gets an orphaned stem.
//
// HISTORICAL NOTE: There used to be a third piece HEAD_BUMP_D — a
// body-colored stub that sat under the stem. It was removed because
// its rounded-rect shape didn't perfectly align with the stem's
// natural path, causing a faint white sliver to peek around the stem.
// The stem now attaches directly to the body's flat top edge instead.
// ═════════════════════════════════════════════════════════════════════

export const ANTENNA_STEM_D =
  'M0 0 C4.08091529 2.39531984 5.58538732 4.56420399 7 9 C7.24291992 12.10620117 7.24291992 12.10620117 7.23046875 15.54296875 C7.22853516 16.78111328 7.22660156 18.01925781 7.22460938 19.29492188 C7.20624023 21.22174805 7.20624023 21.22174805 7.1875 23.1875 C7.18685547 24.48365234 7.18621094 25.77980469 7.18554688 27.11523438 C7.14041085 36.71917831 7.14041085 36.71917831 6 39 C-0.6 39 -7.2 39 -14 39 C-14.09202984 34.39083893 -14.1715972 29.78488631 -14.21972656 25.17553711 C-14.23979558 23.60902077 -14.26705751 22.04257891 -14.30175781 20.47631836 C-14.35048754 18.21970206 -14.3730147 15.96407917 -14.390625 13.70703125 C-14.41127014 13.01100296 -14.43191528 12.31497467 -14.45318604 11.59785461 C-14.45483032 8.00418065 -14.08015358 6.12318719 -12.10058594 3.08081055 C-8.48911679 -0.49665942 -4.91351779 -0.67902741 0 0 Z'

export const ANTENNA_BULB_D =
  'M0 0 C2.80703896 1.34040619 3.86054551 2.54745461 6 5 C7.20266683 8.96172602 7.47141915 10.96287786 5.75 14.75 C4.88375 15.86375 4.88375 15.86375 4 17 C3.566875 17.5775 3.13375 18.155 2.6875 18.75 C0.17427295 20.61164966 -1.90568597 20.81434116 -5 21 C-8.97317198 19.95940734 -11.6509186 18.39311757 -14 15 C-14.86292997 10.34540805 -14.65016836 7.04026938 -12.125 3 C-8.46623217 -0.44354619 -4.87578937 -0.78700125 0 0 Z'

// ─────────────────────────────────────────────────────────────────────
// Tip shapes — alternative "heads" for the antenna. Each tip is designed
// to occupy roughly the same screen space as ANTENNA_BULB_D (the default
// round bulb) so swapping variants in the Customize modal doesn't make
// the antenna jump around. All authored in the ANTENNA group's local
// frame (origin at viewBox (52, 2)); bulb-equivalent center is (-5, 10).
// ─────────────────────────────────────────────────────────────────────

// 5-point puffy star — bezier-curved between vertices for a soft, rounded
// look instead of sharp spikes. Same footprint as the default bulb.
export const ANTENNA_STAR_D =
  'M -5 -1 Q -4 5, -2 6 Q 2 7, 5 8 Q 3 11, 0 12 Q 1 17, 2 20 Q -3 17, -5 16 ' +
  'Q -7 17, -12 20 Q -11 17, -10 12 Q -13 11, -15 8 Q -12 7, -8 6 Q -6 5, -5 -1 Z'

// Plant — THIN tapered stem + two LARGE teardrop leaves. Matches the
// sprout-emoji reference where the leaves are the visual centerpiece
// and the stem is a barely-there line. Asymmetry is size-only: the
// right leaf is ~20% larger than the left, but both attach at the same
// point and tilt outward at mirrored 45° angles.
//
// Stem: thin slim line tapered from width 4 at the body top (y=64) to
// width 2 at the leaf base (y=30) — the visual weight should be in the
// leaves, NOT the stem.
export const ANTENNA_PLANT_STEM_D =
  'M -3 64 Q -3 47, -2 30 L 0 30 Q 1 47, 1 64 Z'
// Leaves are authored as horizontal teardrops with the SHARP end at the
// path origin (0,0); positioned and tilted via per-path transforms in
// ANTENNA_VARIANTS.antenna_3. Outer end is rounded (vertical tangents),
// inner end is pointed (~45° tangents). Sized large so the leaves
// dominate the antenna silhouette.
// Left leaf: 24 long × ~15 wide.
export const ANTENNA_LEAF_LEFT_D =
  'M 0 0 C -6 -10, -24 -10, -24 0 C -24 10, -6 10, 0 0 Z'
// Right leaf: 28 long × ~17 wide — ~17% bigger.
export const ANTENNA_LEAF_RIGHT_D =
  'M 0 0 C 7 -11, 28 -11, 28 0 C 28 11, 7 11, 0 0 Z'

// X — a single rounded-pill blade. Used twice with ±45° rotations about
// the bulb center (-5, 10) to form an X. Length 16, thickness 5.
export const ANTENNA_X_BLADE_D =
  'M -8 -2.5 H 8 A 2.5 2.5 0 0 1 8 2.5 H -8 A 2.5 2.5 0 0 1 -8 -2.5 Z'

// ─────────────────────────────────────────────────────────────────────
// Antenna variants — Stage 2+ unlocks. Each variant is built from:
//
//   stems  — body-frame paths (drawn inside the body group with the
//            body's own transform `translate(52,31) scale(1,0.94)`).
//            ALL variants use the same ANTENNA_STEM_D silhouette so the
//            stem thickness reads identically across the catalog; the
//            optional per-stem `transform` offsets stems horizontally
//            for multi-stem variants (e.g. the twin-antenna).
//
//   paths  — tip/bulb/decoration paths in the antenna group's local
//            frame (anchor at viewBox (52, 2)). Each can carry its own
//            local `transform` for offsetting, rotating, etc.
//
// Local coordinate notes (antenna group):
//   y = 64 → BODY TOP. Anything below this is inside the body.
//   y =  0 → just above the head.
//   y < 0 → tips and decorations live here.
//   x =  0 → horizontal center of the antenna assembly.
// ─────────────────────────────────────────────────────────────────────

interface AntennaPart {
  d: string
  /** Local transform applied to this path, AFTER its host group's
   *  transform. Used by multi-stem variants to offset copies, and by
   *  the X variant to rotate the two crossed blades. */
  transform?: string
}

interface AntennaVariant {
  stems?: AntennaPart[]
  paths: AntennaPart[]
}

// Half-distance between the two side-by-side stems in antenna_4. Picked so
// the two stem silhouettes have a small visible gap rather than overlapping.
const TWIN_OFFSET = 13

export const ANTENNA_VARIANTS: Record<string, AntennaVariant> = {
  // V1 — Classic: wide trapezoid stem + small round bulb. The baseline
  // every other variant aligns to.
  antenna_1: {
    stems: [{ d: ANTENNA_STEM_D }],
    paths: [{ d: ANTENNA_BULB_D }],
  },
  // V2 — Rounded star: same stem, puffy 5-point star instead of the bulb.
  // Star is scaled 1.7× around its natural center (-5, 10) so it reads as
  // a deliberate large decoration rather than a tiny accent on the stem.
  antenna_2: {
    stems: [{ d: ANTENNA_STEM_D }],
    paths: [
      { d: ANTENNA_STAR_D, transform: 'translate(-5 10) scale(1.7) translate(5 -10)' },
    ],
  },
  // V3 — Sprout: the WHOLE antenna is a plant (thick tapered organic
  // stem + two teardrop leaves). No `stems` entry — the plant stem lives
  // inside `paths` alongside the leaves so all three pieces share the
  // antenna group's local frame. Both leaves attach at the stem-top
  // center (-2, 10) and tilt outward at ±45°; the right leaf is slightly
  // larger so the asymmetry is size-only.
  antenna_3: {
    paths: [
      { d: ANTENNA_PLANT_STEM_D },
      { d: ANTENNA_LEAF_LEFT_D, transform: 'translate(-1 30) rotate(45)' },
      { d: ANTENNA_LEAF_RIGHT_D, transform: 'translate(-1 30) rotate(-45)' },
    ],
  },
  // V4 — Twin: two default antennas side by side. Both stems and bulbs are
  // duplicated and offset by ±TWIN_OFFSET so the silhouette stays centered
  // on the body's natural antenna anchor.
  antenna_4: {
    stems: [
      { d: ANTENNA_STEM_D, transform: `translate(${-TWIN_OFFSET},0)` },
      { d: ANTENNA_STEM_D, transform: `translate(${TWIN_OFFSET},0)` },
    ],
    paths: [
      { d: ANTENNA_BULB_D, transform: `translate(${-TWIN_OFFSET},0)` },
      { d: ANTENNA_BULB_D, transform: `translate(${TWIN_OFFSET},0)` },
    ],
  },
  // V5 — X: same stem, two crossed pill blades forming an X where the
  // bulb would sit. Both blades share ANTENNA_X_BLADE_D, rotated ±45°
  // about the bulb-equivalent center (-5, 10). Blades are scaled 1.7×
  // (after rotation) so the X is a bold mark rather than a thin cross.
  antenna_5: {
    stems: [{ d: ANTENNA_STEM_D }],
    paths: [
      { d: ANTENNA_X_BLADE_D, transform: 'translate(-5,10) rotate(45) scale(1.7)' },
      { d: ANTENNA_X_BLADE_D, transform: 'translate(-5,10) rotate(-45) scale(1.7)' },
    ],
  },
}

// ─────────────────────────────────────────────────────────────────────
// Accessories — head overlays. Drawn ABOVE the body+forehead layer so they
// always sit on top of the head silhouette. Coordinates are in the SVG's
// 160×200 viewBox (same space as the body group), no translate parent.
// ─────────────────────────────────────────────────────────────────────

interface AccessoryDef {
  paths: { d: string; fill: string }[]
}

export const ACCESSORIES: Record<string, AccessoryDef> = {
  // Cap — curved baseball-cap silhouette built from a domed crown, a
  // curved brim with a darker underside, a soft highlight on the
  // front-left, and a small button on top. Layers go shadow → main →
  // highlight → button so each successive piece reads as on top.
  hat_cap: {
    paths: [
      // Brim — gentle downward curve at the front edge.
      { d: 'M 38 66 Q 80 80 122 66 L 122 73 Q 80 84 38 73 Z', fill: '#2E6BFF' },
      // Brim underside (darker arc tucked below the brim).
      { d: 'M 40 71 Q 80 82 120 71 L 118 75 Q 80 84 42 75 Z', fill: '#1A4FBF' },
      // Crown / dome — bottom edge curves DOWN at the center
      // (Q 80 80) so it dips into the brim's downward-curving top
      // edge. This closes the visible gap where a flat dome bottom
      // (y=70) would expose body color between the dome and the
      // brim's center dip (y≈73).
      { d: 'M 52 70 Q 52 34 80 34 Q 108 34 108 70 Q 80 80 52 70 Z', fill: '#2E6BFF' },
      // Crown highlight — soft lighter wedge on the front-left.
      { d: 'M 58 64 Q 58 40 78 40 Q 66 48 62 64 Z', fill: '#5589FF' },
      // Button on top.
      { d: 'M 80 33 m -3 0 a 3 3 0 1 0 6 0 a 3 3 0 1 0 -6 0', fill: '#1A4FBF' },
    ],
  },
  // Beanie — full rounded crown that flares slightly into a folded
  // brim band, with a chunky pom and a small bright spot on the pom
  // for a "knit fluff" feel.
  hat_beanie: {
    paths: [
      // Main crown — rounded top, vertical sides to band height.
      { d: 'M 50 76 L 50 48 Q 50 28 80 28 Q 110 28 110 48 L 110 76 Z', fill: '#7A3FBF' },
      // Crown highlight — front-left lighter wedge.
      { d: 'M 56 60 Q 56 32 80 32 Q 66 38 62 60 Z', fill: '#9558D8' },
      // Folded brim — wider at the bottom with a gentle hammock curve.
      { d: 'M 46 74 L 46 84 Q 80 90 114 84 L 114 74 Z', fill: '#5C2C95' },
      // Brim highlight stripe.
      { d: 'M 50 75 Q 80 80 110 75 L 110 77 Q 80 82 50 77 Z', fill: '#6D34B0' },
      // Pom — off-white so the highlight reads.
      { d: 'M 80 22 m -7 0 a 7 7 0 1 0 14 0 a 7 7 0 1 0 -14 0', fill: '#EAEAEA' },
      // Pom highlight.
      { d: 'M 77 19 m -2 0 a 2 2 0 1 0 4 0 a 2 2 0 1 0 -4 0', fill: '#FFFFFF' },
    ],
  },
  // Headband — slim band with subtle top/bottom curves so it hugs
  // the cube head, a lighter highlight stripe, and a small tied bow
  // on the left side instead of the old angular notches.
  hat_headband: {
    paths: [
      // Main band — slight curves so it wraps the head.
      { d: 'M 44 72 Q 80 67 116 72 L 116 82 Q 80 87 44 82 Z', fill: '#FF3B5C' },
      // Highlight stripe.
      { d: 'M 48 73 Q 80 69 112 73 L 112 76 Q 80 72 48 76 Z', fill: '#FF7088' },
      // Bow — left outer loop.
      { d: 'M 38 70 Q 24 72 26 78 Q 30 84 38 84 L 42 78 Z', fill: '#FF3B5C' },
      // Bow — left inner loop (slightly darker for depth).
      { d: 'M 40 73 Q 30 74 32 78 Q 34 82 40 82 L 44 78 Z', fill: '#D8273D' },
      // Bow center knot.
      { d: 'M 40 71 L 50 71 L 50 83 L 40 83 Z', fill: '#D8273D' },
    ],
  },
  hat_halo: {
    paths: [
      // Halo ellipse — golden ring above the head.
      { d: 'M 80 36 m -22 0 a 22 6 0 1 0 44 0 a 22 6 0 1 0 -44 0', fill: 'none' },
      // Outline ring (use a fat stroke via two fills approximation).
      { d: 'M 80 36 m -22 0 a 22 6 0 1 0 44 0 a 22 6 0 1 0 -44 0 M 80 36 m -18 0 a 18 4 0 1 1 36 0 a 18 4 0 1 1 -36 0', fill: '#FFD700' },
    ],
  },
  hat_crown: {
    paths: [
      // Crown band.
      { d: 'M 50 70 L 110 70 L 110 80 L 50 80 Z', fill: '#FFC107' },
      // Crown points.
      { d: 'M 50 70 L 56 50 L 64 68 L 72 46 L 80 68 L 88 46 L 96 68 L 104 50 L 110 70 Z', fill: '#FFD54F' },
      // Gem.
      { d: 'M 80 76 m -4 0 a 4 4 0 1 0 8 0 a 4 4 0 1 0 -8 0', fill: '#E91E63' },
    ],
  },
}
