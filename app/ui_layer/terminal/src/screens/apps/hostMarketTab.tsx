/**
 * The Marketplace tab of Add Agent App: the framework's catalogue with
 * search, tag filters (most used first), "Installed" badges, and an app's
 * page to install it from. Installs run in hostJobs, so they finish (and
 * report) even after the screen closes.
 *
 * Keys on the list: j/k move, / search, f tag filters, Enter opens an app,
 * r reloads the catalogue. On an app's page: Enter installs, Esc goes back.
 */
import { useEffect, useMemo, useState } from 'react'
import { Box, Text, type Key } from 'ink'
import { TextField, fieldKey } from '../../ui/TextField'
import { useAppSelector } from '../../state/hooks'
import { clampList, listKey, LIST_START } from '../../ui/list'
import { useTicker } from '../../ui/useTicker'
import * as TB from '../../input/TextBuffer'
import { glyphs, ink, spinnerFrames } from '../../theme/theme'
import { padEnd, truncate, width } from '../../text/width'
import { filterMarketplace, installedFrom, tagsByFrequency, type MarketplaceApp } from './hostModel'
import { fetchMarketplace, installMarketplaceApp, useJobs, useMarketplace } from './hostJobs'
import { type TabController, type TabProps, wrapProse } from './hostTab'

type Focus = 'list' | 'search' | 'tags'

interface Detail {
  app: MarketplaceApp
}

export function useMarketTab({ t, columns, height, active }: TabProps): TabController {
  const market = useMarketplace()
  const { jobs } = useJobs()
  const registry = useAppSelector(s => s.agentApp.framework.apps)
  const installed = useMemo(() => installedFrom(registry, market.source), [registry, market.source])
  const installing = (app: MarketplaceApp) => market.starting.includes(app.id) || jobs.some(j => j.sourceId === app.id && j.status === 'running')
  const [focus, setFocus] = useState<Focus>('list')
  const [query, setQuery] = useState<TB.Buffer>(TB.EMPTY)
  const [selectedTags, setSelectedTags] = useState<Set<string>>(new Set())
  const [tagCursor, setTagCursor] = useState(0)
  const [list, setList] = useState(LIST_START)
  const [detail, setDetail] = useState<Detail | null>(null)
  const tick = useTicker(120, market.loading || market.starting.length > 0 || jobs.some(j => j.status === 'running'))
  const g = glyphs()

  useEffect(() => {
    if (active) fetchMarketplace()
  }, [active])

  const tags = useMemo(() => tagsByFrequency(market.apps), [market.apps])
  const apps = useMemo(() => filterMarketplace(market.apps, query.text, selectedTags), [market.apps, query.text, selectedTags])
  // Rows: search, tags, list, two description lines and a status line.
  const listHeight = Math.max(1, height - 5)
  const view = clampList(list, apps.length, listHeight)
  const selected = apps[view.index]

  const toggleTag = (tag: string | null) => {
    if (tag === null) setSelectedTags(new Set())
    else
      setSelectedTags(prev => {
        const next = new Set(prev)
        if (next.has(tag)) next.delete(tag)
        else next.add(tag)
        return next
      })
    setList(LIST_START)
  }

  const install = (d: Detail) => {
    if (!installing(d.app)) installMarketplaceApp(d.app)
    setDetail(null)
  }

  const handleKey = (input: string, key: Key): boolean => {
    if (detail) {
      if (key.escape) setDetail(null)
      else if (key.return) install(detail)
      return true
    }

    if (focus === 'search') {
      if (key.escape || key.return) {
        setFocus('list')
        if (key.escape) setQuery(TB.EMPTY)
        return true
      }
      if (key.upArrow || key.downArrow) {
        const moved = listKey(view, '', key, apps.length, listHeight)
        if (moved) setList(moved)
        return true
      }
      const next = fieldKey(query, input, key)
      if (next) {
        setQuery(next)
        setList(LIST_START)
      }
      return true
    }

    if (focus === 'tags') {
      const count = tags.length + 1 // "All" first
      if (key.escape || input === 'f' || key.downArrow) {
        setFocus('list')
        return true
      }
      if (key.leftArrow || input === 'h') setTagCursor(c => Math.max(0, c - 1))
      else if (key.rightArrow || input === 'l') setTagCursor(c => Math.min(count - 1, c + 1))
      else if (input === ' ' || key.return) toggleTag(tagCursor === 0 ? null : tags[tagCursor - 1])
      return true
    }

    const moved = listKey(view, input, key, apps.length, listHeight)
    if (moved) {
      setList(moved)
      return true
    }
    if (input === '/') {
      setFocus('search')
      return true
    }
    if (input === 'f' && tags.length > 0) {
      setFocus('tags')
      return true
    }
    if (input === 'r') {
      fetchMarketplace(true)
      return true
    }
    if (key.return && selected) {
      setDetail({ app: selected })
      return true
    }
    return false
  }

  const textFocus = focus === 'search'

  const hints = detail
    ? [
        ...(installing(detail.app) ? [] : [{ keys: 'Enter', label: t('appsHost:hint.install') }]),
        { keys: 'Esc', label: t('appsHost:hint.back') },
      ]
    : focus === 'search'
      ? [
          { keys: 'Enter', label: t('appsHost:hint.done') },
          { keys: 'Esc', label: t('appsHost:hint.clear') },
        ]
      : focus === 'tags'
        ? [
            { keys: 'Left/Right', label: t('appsHost:hint.move') },
            { keys: 'Space', label: t('appsHost:hint.toggle') },
            { keys: 'Esc', label: t('appsHost:hint.done') },
          ]
        : [
            ...(selected ? [{ keys: 'Enter', label: t('appsHost:hint.view') }] : []),
            { keys: '/', label: t('appsHost:hint.search') },
            ...(tags.length ? [{ keys: 'f', label: t('appsHost:hint.tags') }] : []),
            { keys: 'r', label: t('appsHost:hint.reload') },
            { keys: '[ ]', label: t('appsHost:hint.tabs') },
            { keys: 'Esc', label: t('appsHost:hint.tabBar') },
          ]

  const spin = spinnerFrames()[tick % spinnerFrames().length]

  // ── the app's page ──
  const renderDetail = (d: Detail) => {
    const metaParts = [d.app.version ? `v${d.app.version}` : '', (d.app.tags ?? []).join(', ')].filter(Boolean)
    const descRows = Math.max(1, height - 4)
    const desc = wrapProse(d.app.description || '', columns).slice(0, descRows)
    const busy = installing(d.app)
    return (
      <Box flexDirection="column">
        <Box>
          <Text bold color={ink.brand}>{truncate(d.app.name, Math.max(8, columns - 20))}</Text>
          {busy ? <Text color={ink.brand}>{`  ${spin} ${t('appsHost:market.installingBadge')}`}</Text> : installed.has(d.app.id) ? <Text color={ink.success}>{'  ' + t('appsHost:market.installedBadge')}</Text> : null}
        </Box>
        <Text color={ink.muted}>{truncate(metaParts.join(`  ${g.sep}  `), columns)}</Text>
        {desc.map((line, i) => (
          <Text key={i}>{line}</Text>
        ))}
        <Text> </Text>
        <Text color={ink.muted}>{truncate(busy ? t('appsHost:market.installingHint') : installed.has(d.app.id) ? t('appsHost:market.installAgain') : t('appsHost:market.installHint'), columns)}</Text>
      </Box>
    )
  }

  // ── the list ──
  const renderTags = () => {
    if (tags.length === 0) return <Text> </Text>
    const label = t('appsHost:market.tags') + ' '
    const chips = [t('appsHost:market.all'), ...tags]
    const parts: { text: string; on: boolean; cursor: boolean }[] = []
    let used = width(label)
    let shown = 0
    // Keep the cursor's chip visible: start the strip early enough.
    const start = focus === 'tags' ? Math.max(0, tagCursor - 6) : 0
    for (let i = start; i < chips.length; i++) {
      const on = i === 0 ? selectedTags.size === 0 : selectedTags.has(chips[i])
      const text = on ? `[${chips[i]}]` : ` ${chips[i]} `
      if (used + width(text) + 1 > columns - 10) break
      parts.push({ text, on, cursor: focus === 'tags' && i === tagCursor })
      used += width(text) + 1
      shown++
    }
    const hidden = chips.length - start - shown
    return (
      <Box>
        <Text color={focus === 'tags' ? ink.focus : ink.muted}>{label}</Text>
        {parts.map((p, i) => (
          <Text key={i} inverse={p.cursor} color={p.on ? ink.brand : undefined} bold={p.on}>
            {p.text}{' '}
          </Text>
        ))}
        {hidden > 0 ? <Text color={ink.muted}>{t('appsHost:market.more', { count: hidden })}</Text> : null}
      </Box>
    )
  }

  const renderList = () => {
    if (market.loading && market.apps.length === 0) {
      return <Text color={ink.muted}>{`${spin} ${t('appsHost:market.loading')}`}</Text>
    }
    if (market.error && market.apps.length === 0) {
      return (
        <Box flexDirection="column">
          <Text color={ink.error}>{truncate(market.error, columns)}</Text>
          <Text color={ink.muted}>{t('appsHost:market.retry')}</Text>
        </Box>
      )
    }
    if (market.apps.length === 0) return <Text color={ink.muted}>{t('appsHost:market.empty')}</Text>
    if (apps.length === 0) return <Text color={ink.muted}>{t('appsHost:market.emptyFiltered')}</Text>
    const versionWidth = 8
    const badgeWidth = 14
    const room = columns - 2 - versionWidth - badgeWidth
    // Names first (up to 30 cells); tags take what is left on wide terminals.
    const nameWidth = Math.max(8, columns >= 90 ? Math.min(30, room) : room)
    const tagWidth = columns >= 90 ? Math.max(0, room - nameWidth) : 0
    return (
      <Box flexDirection="column">
        {apps.slice(view.top, view.top + listHeight).map((app, i) => {
          const index = view.top + i
          const isSelected = index === view.index && active
          const busy = installing(app)
          const badge = busy ? `${spin} ${t('appsHost:market.installingBadge')}` : installed.has(app.id) ? `${g.done} ${t('appsHost:market.installedBadge')}` : ''
          return (
            <Box key={app.id}>
              <Text color={isSelected ? ink.focus : undefined}>{isSelected ? `${g.pointer} ` : '  '}</Text>
              <Text bold={isSelected}>{padEnd(app.name, nameWidth)}</Text>
              <Text color={ink.muted}>{padEnd(app.version ? `v${app.version}` : '', versionWidth)}</Text>
              <Text color={busy ? ink.brand : ink.success}>{padEnd(badge, badgeWidth)}</Text>
              {tagWidth ? <Text color={ink.muted}>{padEnd((app.tags ?? []).join(', '), tagWidth)}</Text> : null}
            </Box>
          )
        })}
      </Box>
    )
  }

  const descLines = selected && !detail ? wrapProse((selected.description || '').replace(/\s+/g, ' '), columns).slice(0, 2) : []
  const body = detail ? (
    renderDetail(detail)
  ) : (
    <Box flexDirection="column">
      {focus === 'search' || query.text ? (
        <TextField label="/" buffer={query} focused={focus === 'search'} width={columns} placeholder={t('appsHost:market.search')} />
      ) : (
        <Text color={ink.muted}>{truncate(`/ ${t('appsHost:market.search')}`, columns)}</Text>
      )}
      {renderTags()}
      <Box flexDirection="column" height={listHeight}>
        {renderList()}
      </Box>
      {descLines.map((line, i) => (
        <Text key={i} color={ink.muted}>{line}</Text>
      ))}
      {market.error && market.apps.length > 0 ? <Text color={ink.error}>{truncate(market.error, columns)}</Text> : null}
    </Box>
  )

  return { handleKey, textFocus, hints, body, dirty: false }
}
