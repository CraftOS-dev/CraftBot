import React from 'react'

/**
 * The single source of truth for Agent App themes — used by BOTH the create
 * wizard's theme picker and the running app's theme modal (so the two can
 * never drift apart).
 *
 * V2 model: every preset is a kit style pack (`data-style` in the kit's
 * tokens.css) that carries light AND dark palettes and follows the host's
 * mode. 'custom' pins the four core colors via the bridge's customColors.
 * Applied over postMessage: { type: 'agentapp-theme', themeId, mode,
 * customColors? } (see agent-app/kit/src/theme/bridge.ts).
 */

export type AgentAppStyleId =
  | 'craftbot' | 'modern' | 'normal' | 'ocean' | 'forest' | 'pastel'
  | 'glass' | 'classic' | 'velvet' | 'ink' | 'acid' | 'blueprint'
  | 'brutalist' | 'drafting' | 'clay' | 'atelier'

export type AgentAppThemeId = AgentAppStyleId | 'custom'

export interface AgentAppCustomColors {
  bg: string
  surface: string
  text: string
  accent: string
}

export const DEFAULT_CUSTOM_COLORS: AgentAppCustomColors = {
  bg: '#191919',
  surface: '#202020',
  text: '#E6E6E4',
  accent: '#FF4F18',
}

export interface ThemeDef {
  id: AgentAppStyleId
  /** English fallback label; user-facing rendering uses `labelKey` via i18n. */
  label: string
  /** English fallback descriptor; user-facing rendering uses `descriptionKey`. */
  hint?: string
  /** i18n key for the label (rendered with t() at the consumer). */
  labelKey: `agentapp:themes.${AgentAppStyleId}.label`
  /** i18n key for the short descriptor shown under the label. */
  descriptionKey: `agentapp:themes.${AgentAppStyleId}.description`
  /** Tile preview colors [bg, surface, text, accent] (dark-mode leaning). */
  swatches: [string, string, string, string]
}

export const PRESET_THEMES: ThemeDef[] = [
  { id: 'craftbot',  label: 'CraftBot',  hint: 'The baseline',    labelKey: 'agentapp:themes.craftbot.label',  descriptionKey: 'agentapp:themes.craftbot.description',  swatches: ['#191919', '#202020', '#E6E6E4', '#FF4F18'] },
  { id: 'modern',    label: 'Modern',    hint: 'Airy indigo',     labelKey: 'agentapp:themes.modern.label',    descriptionKey: 'agentapp:themes.modern.description',    swatches: ['#12141D', '#1A1D2A', '#ECEEF8', '#7C8AFF'] },
  { id: 'normal',    label: 'Normal',    hint: 'Clean blue',      labelKey: 'agentapp:themes.normal.label',    descriptionKey: 'agentapp:themes.normal.description',    swatches: ['#131316', '#1D1D22', '#F2F2F5', '#3B82F6'] },
  { id: 'ocean',     label: 'Ocean',     hint: 'Deep sea',        labelKey: 'agentapp:themes.ocean.label',     descriptionKey: 'agentapp:themes.ocean.description',     swatches: ['#0B1B26', '#102635', '#F8FAFC', '#38BDF8'] },
  { id: 'forest',    label: 'Forest',    hint: 'Mossy green',     labelKey: 'agentapp:themes.forest.label',    descriptionKey: 'agentapp:themes.forest.description',    swatches: ['#0E1A12', '#14261A', '#F3F6F4', '#4ADE80'] },
  { id: 'pastel',    label: 'Pastel',    hint: 'Soft lilac',      labelKey: 'agentapp:themes.pastel.label',    descriptionKey: 'agentapp:themes.pastel.description',    swatches: ['#1A1420', '#251C2E', '#F3E8FF', '#C084FC'] },
  { id: 'glass',     label: 'Glass',     hint: 'Aurora glass',    labelKey: 'agentapp:themes.glass.label',     descriptionKey: 'agentapp:themes.glass.description',     swatches: ['#10131C', '#1E2436', '#F5F7FE', '#818CF8'] },
  { id: 'classic',   label: 'Classic',   hint: 'Flat & dense',    labelKey: 'agentapp:themes.classic.label',   descriptionKey: 'agentapp:themes.classic.description',   swatches: ['#1C1A14', '#26231B', '#F1EDE2', '#D4A017'] },
  { id: 'velvet',    label: 'Velvet',    hint: 'Plush pink',      labelKey: 'agentapp:themes.velvet.label',    descriptionKey: 'agentapp:themes.velvet.description',    swatches: ['#1C1018', '#281826', '#F8F2F6', '#EC4899'] },
  { id: 'ink',       label: 'Ink',       hint: 'Mono playful',    labelKey: 'agentapp:themes.ink.label',       descriptionKey: 'agentapp:themes.ink.description',       swatches: ['#F3F3F1', '#FFFFFF', '#111111', '#111111'] },
  { id: 'acid',      label: 'Acid',      hint: 'Greige & lime',   labelKey: 'agentapp:themes.acid.label',      descriptionKey: 'agentapp:themes.acid.description',      swatches: ['#131A0C', '#1B2513', '#FAFFF2', '#A3E635'] },
  { id: 'blueprint', label: 'Blueprint', hint: 'Grid datasheet',  labelKey: 'agentapp:themes.blueprint.label', descriptionKey: 'agentapp:themes.blueprint.description', swatches: ['#0B1526', '#102039', '#EEF4FB', '#60A5FA'] },
  { id: 'brutalist', label: 'Brutalist', hint: 'Hard blocks',     labelKey: 'agentapp:themes.brutalist.label', descriptionKey: 'agentapp:themes.brutalist.description', swatches: ['#FFFFFF', '#FFFFFF', '#0A0A0A', '#7C3AED'] },
  { id: 'drafting',  label: 'Drafting',  hint: 'Monoline sketch', labelKey: 'agentapp:themes.drafting.label',  descriptionKey: 'agentapp:themes.drafting.description',  swatches: ['#E9EDE4', '#E9EDE4', '#2E3528', '#3A4232'] },
  { id: 'clay',      label: 'Clay',      hint: 'Soft extruded',   labelKey: 'agentapp:themes.clay.label',      descriptionKey: 'agentapp:themes.clay.description',      swatches: ['#E4E6EC', '#E4E6EC', '#3A3F4C', '#5B7CFA'] },
  { id: 'atelier',   label: 'Atelier',   hint: 'Studio minimal',  labelKey: 'agentapp:themes.atelier.label',   descriptionKey: 'agentapp:themes.atelier.description',   swatches: ['#EDEFF2', '#F8F9FB', '#1C1E22', '#17181B'] },
]

/**
 * Translate a theme selection into the `agentapp-theme` postMessage payload
 * the kit's ThemeBridge understands. Presets are pure style packs (the kit
 * owns their palettes, both modes); 'custom' rides the base style with the
 * four core colors pinned.
 */
export function buildThemeMessage(
  themeId: AgentAppThemeId,
  mode: 'dark' | 'light',
  customColors: AgentAppCustomColors,
): { type: 'agentapp-theme'; themeId: string; mode: 'dark' | 'light'; customColors?: AgentAppCustomColors } {
  if (themeId === 'custom') {
    return { type: 'agentapp-theme', themeId: 'craftbot', mode, customColors }
  }
  // No customColors key → the bridge clears any previous pinned colors.
  return { type: 'agentapp-theme', themeId, mode }
}

// ── mini previews ───────────────────────────────────────────────────────────

interface MiniStyleSpec {
  /** Corner radius of the preview blocks. */
  r: number
  /** Canvas background. */
  canvas: (bg: string) => string
  /** Card fill (surfaces). */
  card: (surface: string, bg: string) => string
  /** Card border. */
  cardBorder: (text: string) => string | undefined
  /** Card shadow. */
  cardShadow: (text: string, bg: string) => string | undefined
  /** Extra text line (dense styles). */
  denseLines?: boolean
  /** Blur hint on surfaces (glass styles). */
  blur?: boolean
}

const FLAT: MiniStyleSpec = {
  r: 4,
  canvas: bg => bg,
  card: s => s,
  cardBorder: () => undefined,
  cardShadow: () => undefined,
}

const MINI_SPECS: Record<AgentAppStyleId, MiniStyleSpec> = {
  craftbot: FLAT,
  normal: FLAT,
  ocean: FLAT,
  forest: FLAT,
  pastel: FLAT,
  modern: {
    r: 7,
    canvas: bg => bg,
    card: s => s,
    cardBorder: () => undefined,
    cardShadow: () => '0 2px 5px rgba(0, 0, 0, 0.45)',
  },
  glass: {
    r: 8,
    canvas: bg =>
      `radial-gradient(40px 26px at 15% 0%, rgba(124, 58, 237, 0.45), transparent 70%),
       radial-gradient(40px 26px at 100% 45%, rgba(34, 211, 238, 0.4), transparent 70%),
       radial-gradient(36px 24px at 45% 110%, rgba(236, 72, 153, 0.32), transparent 70%),
       ${bg}`,
    card: () => 'rgba(255, 255, 255, 0.14)',
    cardBorder: () => undefined,
    cardShadow: () => undefined,
    blur: true,
  },
  classic: {
    r: 1,
    canvas: bg => bg,
    card: s => s,
    cardBorder: () => '1px solid rgba(255, 255, 255, 0.18)',
    cardShadow: () => undefined,
    denseLines: true,
  },
  velvet: {
    r: 9,
    canvas: bg =>
      `radial-gradient(44px 30px at 72% 30%, rgba(236, 72, 153, 0.4), transparent 70%),
       radial-gradient(40px 28px at 8% 95%, rgba(157, 23, 77, 0.35), transparent 70%),
       ${bg}`,
    card: () => 'rgba(255, 255, 255, 0.14)',
    cardBorder: () => undefined,
    cardShadow: () => undefined,
    blur: true,
  },
  ink: {
    r: 8,
    canvas: bg => bg,
    card: s => s,
    cardBorder: () => undefined,
    cardShadow: () => '0 1px 3px rgba(17, 17, 17, 0.14)',
  },
  acid: {
    r: 11,
    canvas: bg => bg,
    card: s => s,
    cardBorder: () => undefined,
    cardShadow: () => undefined,
  },
  blueprint: {
    r: 0,
    canvas: bg =>
      `repeating-linear-gradient(0deg, rgba(96, 165, 250, 0.14) 0 1px, transparent 1px 7px),
       repeating-linear-gradient(90deg, rgba(96, 165, 250, 0.14) 0 1px, transparent 1px 7px),
       ${bg}`,
    card: s => s,
    cardBorder: text => `1px solid ${text}44`,
    cardShadow: () => undefined,
    denseLines: true,
  },
  brutalist: {
    r: 0,
    canvas: bg => bg,
    card: s => s,
    cardBorder: text => `1.5px solid ${text}`,
    cardShadow: text => `2px 2px 0 ${text}`,
  },
  drafting: {
    r: 4,
    canvas: bg => bg,
    card: (_s, bg) => bg,
    cardBorder: text => `1px solid ${text}`,
    cardShadow: () => undefined,
  },
  clay: {
    r: 10,
    canvas: bg => bg,
    card: s => s,
    cardBorder: () => undefined,
    cardShadow: () =>
      '2px 2px 4px rgba(163, 169, 184, 0.7), -2px -2px 4px rgba(255, 255, 255, 0.95)',
  },
  atelier: {
    r: 5,
    canvas: bg => `linear-gradient(180deg, rgba(255, 255, 255, 0.55) 0%, rgba(150, 158, 172, 0.35) 100%), ${bg}`,
    card: s => s,
    cardBorder: text => `1px solid ${text}22`,
    cardShadow: () => '0 1px 2px rgba(20, 22, 26, 0.12)',
  },
}

export function ThemeMiniPreview({
  style,
  swatches,
}: {
  style: AgentAppStyleId
  swatches: [string, string, string, string]
}) {
  const [bg, surface, text, accent] = swatches
  const spec = MINI_SPECS[style] ?? FLAT
  const r = spec.r
  const cardBg = spec.card(surface, bg)
  const cardBorder = spec.cardBorder(text)
  const cardShadow = spec.cardShadow(text, bg)
  const block: React.CSSProperties = { position: 'absolute', display: 'block' }
  return (
    <span
      aria-hidden
      style={{
        position: 'relative',
        display: 'block',
        width: 68,
        height: 42,
        borderRadius: Math.max(r + 2, 2),
        background: spec.canvas(bg),
        border: '1px solid rgba(127, 127, 127, 0.25)',
        overflow: 'hidden',
        flexShrink: 0,
      }}
    >
      {/* header bar */}
      <span
        style={{
          ...block,
          top: 4,
          left: 4,
          right: 4,
          height: 6,
          borderRadius: r,
          background: cardBg,
          border: cardBorder,
          backdropFilter: spec.blur ? 'blur(2px)' : undefined,
        }}
      />
      {/* text lines — an extra one for dense styles */}
      <span style={{ ...block, top: spec.denseLines ? 13 : 14, left: 5, width: '42%', height: 3, borderRadius: 2, background: text, opacity: 0.9 }} />
      <span style={{ ...block, top: spec.denseLines ? 18 : 20, left: 5, width: '60%', height: 3, borderRadius: 2, background: text, opacity: 0.35 }} />
      {spec.denseLines && (
        <span style={{ ...block, top: 23, left: 5, width: '50%', height: 3, borderRadius: 2, background: text, opacity: 0.35 }} />
      )}
      {/* surface card + accent button */}
      <span
        style={{
          ...block,
          bottom: 4,
          left: 4,
          right: 24,
          height: 9,
          borderRadius: r,
          background: cardBg,
          border: cardBorder,
          boxShadow: cardShadow,
          backdropFilter: spec.blur ? 'blur(2px)' : undefined,
        }}
      />
      <span
        style={{
          ...block,
          bottom: 4,
          right: 4,
          width: 16,
          height: 9,
          borderRadius: r,
          background: accent,
          border: style === 'drafting' ? `1px solid ${text}` : undefined,
          boxShadow: style === 'brutalist' ? `2px 2px 0 ${text}` : undefined,
        }}
      />
    </span>
  )
}
