/**
 * Agent App theme packs for the terminal: the browser's catalog (one source
 * of truth, themeCatalog.tsx, read-only) and a keyboard picker shared by the
 * Apps screen (`t`) and the settings panel. A pick is saved as the app's
 * preference on the host (the request channel's `preference`), the same
 * place the browser keeps it, so it follows the app into every client.
 */
import { Box, Text, type Key } from 'ink'
import { PRESET_THEMES, type AgentAppThemeId } from '../../../../browser/frontend/src/pages/AgentApp/themeCatalog'
import type { FrameworkRegistryApp } from '../../../../browser/frontend/src/types'
import { receiveFrameworkTheme } from '../../../../browser/frontend/src/store/slices/agentAppSlice'
import type { AppDispatch } from '../../state/store'
import { frameworkRequest, type FrameworkAttachment } from '../../apps/framework'
import { clampList, listKey } from '../../ui/list'
import { glyphs, ink } from '../../theme/theme'
import { padEnd, truncate, width } from '../../text/width'

/** A translate function (any namespace's `t`; keys carry their namespace). */
export type Tr = (key: string, options?: Record<string, unknown>) => string

export interface ThemePack {
  id: string
  labelKey: string
  descriptionKey: string
  /** [background, surface, text, accent] */
  swatches: [string, string, string, string]
}

export const THEME_PACKS: readonly ThemePack[] = PRESET_THEMES
export const DEFAULT_THEME = 'craftbot'

/** The theme an app shows: the saved pick, else the baseline. */
export function appThemeId(app: Pick<FrameworkRegistryApp, 'uiTheme'> | undefined): string {
  return app?.uiTheme?.themeId || DEFAULT_THEME
}

/** A pack's display name. The baseline pack reads "Default" (app copy never names the product). */
export function themeName(t: Tr, id: string): string {
  if (id === DEFAULT_THEME) return t('appsHost:theme.default')
  if (id === 'custom') return t('appsHost:theme.custom')
  const pack = THEME_PACKS.find(p => p.id === id)
  return pack ? t(pack.labelKey) : id
}

export function themeDescription(t: Tr, id: string): string {
  if (id === 'custom') return t('appsHost:theme.customHint')
  const pack = THEME_PACKS.find(p => p.id === id)
  return pack ? t(pack.descriptionKey) : ''
}

/** Save `themeId` as the app's theme; the row shows the host's answer. Throws on a refusal. */
export async function applyTheme(dispatch: AppDispatch, app: FrameworkRegistryApp, themeId: string): Promise<void> {
  const result = await frameworkRequest<FrameworkAttachment>({
    operation: 'preference',
    path: app.path,
    appId: app.id,
    uiTheme: { themeId: themeId as AgentAppThemeId },
  })
  dispatch(receiveFrameworkTheme({ path: app.path, id: app.id, uiTheme: result.uiTheme }))
}

// ── picker ──────────────────────────────────────────────────────────────────

export interface ThemePickerState {
  index: number
  top: number
}

export function openThemePicker(currentId: string): ThemePickerState {
  return { index: Math.max(0, THEME_PACKS.findIndex(p => p.id === currentId)), top: 0 }
}

export type ThemePickerResult =
  | { kind: 'move'; state: ThemePickerState }
  | { kind: 'apply'; themeId: string }
  | { kind: 'cancel' }

/** Keys of an open picker: j/k and arrows move, Enter applies, Esc cancels. Null = unused key. */
export function themePickerKey(state: ThemePickerState, input: string, key: Key, height: number): ThemePickerResult | null {
  if (key.escape) return { kind: 'cancel' }
  if (key.return || input === ' ') return { kind: 'apply', themeId: THEME_PACKS[state.index]?.id ?? DEFAULT_THEME }
  const moved = listKey(state, input, key, THEME_PACKS.length, height)
  return moved ? { kind: 'move', state: moved } : null
}

/** Rows the picker list gets inside `rows` (title and caption take two). */
export const pickerListHeight = (rows: number): number => Math.max(1, rows - 2)

export function ThemePicker({
  t,
  state,
  currentId,
  title,
  columns,
  rows,
}: {
  t: Tr
  state: ThemePickerState
  currentId: string
  title: string
  columns: number
  rows: number
}) {
  const g = glyphs()
  const height = pickerListHeight(rows)
  const view = clampList(state, THEME_PACKS.length, height)
  const nameWidth = Math.min(16, Math.max(8, Math.floor(columns / 5)))
  const currentMark = t('appsHost:theme.current')
  return (
    <Box flexDirection="column">
      <Text bold>{truncate(title, columns)}</Text>
      {THEME_PACKS.slice(view.top, view.top + height).map((pack, i) => {
        const index = view.top + i
        const selected = index === view.index
        const isCurrent = pack.id === currentId
        const mark = isCurrent ? `  ${g.done} ${currentMark}` : ''
        const descWidth = Math.max(0, columns - 4 - 2 - nameWidth - width(mark))
        return (
          <Box key={pack.id}>
            <Text color={selected ? ink.focus : undefined}>{selected ? `${g.pointer} ` : '  '}</Text>
            {/* The accent swatch is decoration only: the name carries the meaning. */}
            <Text color={ink.brand === undefined ? undefined : pack.swatches[3]}>{g.rule === '-' ? '# ' : '■ '}</Text>
            <Text bold={selected}>{padEnd(themeName(t, pack.id), nameWidth)}</Text>
            <Text color={ink.muted}>{padEnd(' ' + themeDescription(t, pack.id), descWidth)}</Text>
            {mark ? <Text color={ink.success}>{mark}</Text> : null}
          </Box>
        )
      })}
      <Text color={ink.muted}>{truncate(t('appsHost:theme.caption'), columns)}</Text>
    </Box>
  )
}
