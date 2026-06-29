import { useId } from 'react'
import { ANTENNA_VARIANTS, ACCESSORIES } from '@mascot'

export type FillState = 'full' | 'half' | 'empty'

const HEART_PATH =
  'M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z'

const BOLT_PATH = 'M13 2L3 14h7l-2 8 10-12h-7l2-8z'

function gradStops(state: FillState): { fillPct: number } {
  if (state === 'full')  return { fillPct: 100 }
  if (state === 'half')  return { fillPct: 50 }
  return { fillPct: 0 }
}

export function MoodIcon({ state, size = 28 }: { state: FillState; size?: number }) {
  const id = useId()
  const { fillPct } = gradStops(state)
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} aria-hidden="true">
      <defs>
        <linearGradient id={`mood-${id}`} x1="0" x2="1" y1="0" y2="0">
          <stop offset={`${fillPct}%`} stopColor="#FF4F6D" />
          <stop offset={`${fillPct}%`} stopColor="rgba(255,79,109,0.16)" />
        </linearGradient>
      </defs>
      <path
        d={HEART_PATH}
        fill={`url(#mood-${id})`}
        stroke="#FF4F6D"
        strokeWidth="1.2"
        strokeLinejoin="round"
      />
    </svg>
  )
}

export function EnergyIcon({ state, size = 28 }: { state: FillState; size?: number }) {
  const id = useId()
  const { fillPct } = gradStops(state)
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} aria-hidden="true">
      <defs>
        <linearGradient id={`energy-${id}`} x1="0" x2="1" y1="0" y2="0">
          <stop offset={`${fillPct}%`} stopColor="#FFC633" />
          <stop offset={`${fillPct}%`} stopColor="rgba(255,198,51,0.16)" />
        </linearGradient>
      </defs>
      <path
        d={BOLT_PATH}
        fill={`url(#energy-${id})`}
        stroke="#FFC633"
        strokeWidth="1.2"
        strokeLinejoin="round"
      />
    </svg>
  )
}

export function ShopIcon({ size = 22 }: { size?: number }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 8h18l-1.5 11a2 2 0 0 1-2 1.7H6.5A2 2 0 0 1 4.5 19L3 8z" />
      <path d="M8 8V6a4 4 0 0 1 8 0v2" />
    </svg>
  )
}

export function InventoryIcon({ size = 22 }: { size?: number }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M4 7h16v13H4z" />
      <path d="M9 7V5a3 3 0 0 1 6 0v2" />
      <path d="M4 12h16" />
    </svg>
  )
}

/** Food / feed action — shows as a battery on the HUD button. */
export function FoodIcon({ size = 22 }: { size?: number }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} aria-hidden="true">
      <rect x="3" y="8" width="16" height="9" rx="2" fill="none" stroke="currentColor" strokeWidth="1.8" />
      <rect x="19" y="11" width="2.2" height="3" rx="0.5" fill="currentColor" />
      <rect x="5" y="10" width="12" height="5" rx="0.8" fill="currentColor" />
    </svg>
  )
}

/** Location selector — flat mountain silhouette. */
export function LocationIcon({ size = 22 }: { size?: number }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 19l5-9 4 6 3-4 6 7H3z" fill="currentColor" stroke="none" />
      <circle cx="17" cy="6" r="2" fill="currentColor" stroke="none" />
    </svg>
  )
}

export function WardrobeIcon({ size = 22 }: { size?: number }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 4l-7 4 2 12h10l2-12-7-4z" />
      <circle cx="12" cy="9" r="1.5" fill="currentColor" stroke="none" />
    </svg>
  )
}

/** Gold coin — flat 2-tone token shown in the shop wallet bar. */
export function GoldCoinIcon({ size = 20 }: { size?: number }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} aria-hidden="true">
      <circle cx="12" cy="12" r="10" fill="#E8B100" stroke="#7A5A00" strokeWidth="1.4" />
      <circle cx="12" cy="12" r="6.5" fill="none" stroke="#FFE066" strokeWidth="1.2" />
      <text
        x="12"
        y="15.5"
        fontSize="9"
        fontWeight="800"
        fill="#7A5A00"
        textAnchor="middle"
        fontFamily="system-ui, sans-serif"
      >
        T
      </text>
    </svg>
  )
}

/** Info "i" used as a hover affordance on the wallet bar. */
export function InfoIcon({ size = 16 }: { size?: number }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="9.2" stroke="currentColor" strokeWidth="1.6" />
      <circle cx="12" cy="8" r="1.2" fill="currentColor" />
      <path d="M12 11 V17" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  )
}

export function CloseIcon({ size = 18 }: { size?: number }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true">
      <line x1="6" y1="6" x2="18" y2="18" />
      <line x1="18" y1="6" x2="6" y2="18" />
    </svg>
  )
}

export function LockIcon({ size = 18 }: { size?: number }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="5" y="11" width="14" height="9" rx="2" />
      <path d="M8 11V8a4 4 0 0 1 8 0v3" />
    </svg>
  )
}

export function BatteryIcon({ size = 22, charge = 1 }: { size?: number; charge?: number }) {
  const w = Math.max(0, Math.min(1, charge)) * 14
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} aria-hidden="true">
      <rect x="2" y="7" width="18" height="10" rx="2" fill="none" stroke="#9ed957" strokeWidth="1.6" />
      <rect x="20" y="10" width="2.5" height="4" rx="0.6" fill="#9ed957" />
      <rect x="4" y="9" width={w} height="6" rx="1" fill="#9ed957" />
    </svg>
  )
}

/** Renders one antenna variant into a small preview SVG so the picker
 *  shows the actual shape rather than a name. Renders stem + tip in the
 *  same coordinate frame the mascot uses: stems via the body's transform
 *  `translate(52,31) scale(1,0.94)`, tips via the antenna group's
 *  `translate(52,2)`. The viewBox crops to the union of those bounds with
 *  enough horizontal room for the twin-antenna variant.
 *
 *  Aspect ratio is non-square — antennas are tall — so width is rendered
 *  smaller than height to keep the preview from squishing. */
export function AntennaPreview({ variantId, size = 44, color = '#FF4F19' }: { variantId: string; size?: number; color?: string }) {
  const spec = ANTENNA_VARIANTS[variantId]
  if (!spec) return null
  return (
    <svg viewBox="20 -10 56 80" width={size * 0.7} height={size} aria-hidden="true">
      {/* Stems — body frame (matches CraftBotMascot body transform). */}
      {spec.stems?.map((s, i) => (
        <g key={`stem-${i}`} transform="translate(52,31) scale(1,0.94)">
          <path d={s.d} fill={color} transform={s.transform} />
        </g>
      ))}
      {/* Tips — antenna group frame. */}
      <g transform="translate(52,2)">
        {spec.paths.map((p, i) => (
          <path key={i} d={p.d} fill={color} transform={p.transform} />
        ))}
      </g>
    </svg>
  )
}

/** Renders one accessory into a small preview SVG cropped to its head area. */
export function AccessoryPreview({ accessoryId, size = 44 }: { accessoryId: string; size?: number }) {
  const def = ACCESSORIES[accessoryId]
  if (!def) return null
  return (
    <svg viewBox="30 25 100 65" width={size} height={size * 0.65} aria-hidden="true">
      {def.paths.map((p, i) => (
        <path key={i} d={p.d} fill={p.fill} />
      ))}
    </svg>
  )
}

/** Small "no accessory" indicator (a slashed circle). */
export function NoAccessoryIcon({ size = 36 }: { size?: number }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
      <circle cx="12" cy="12" r="9" opacity="0.4" />
      <line x1="6" y1="18" x2="18" y2="6" opacity="0.4" />
    </svg>
  )
}
