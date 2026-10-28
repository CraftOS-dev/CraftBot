/**
 * Settings > MCP servers: the configured servers with their enabled state.
 * Space enables or disables, e edits the server's environment variables
 * (secret values masked), a adds a server from JSON written in $EDITOR,
 * d removes one (confirm), r reloads. Same messages as the browser's tab.
 */
import { useRef, useState } from 'react'
import { Box, Text } from 'ink'
import { useTranslation } from 'react-i18next'
import { useAppDispatch, useAppSelector, send } from '../../../state/hooks'
import {
  removeServer,
  setEnabled,
  type MCPServerConfig,
} from '../../../../../browser/frontend/src/store/slices/mcpSettingsSlice'
import { selectMcpHasLoaded, selectMcpServers } from '../../../../../browser/frontend/src/store/selectors/mcpSettings'
import { RESOURCES, useResource } from '../../../../../browser/frontend/src/store/resources'
import { useTab } from '../tabContext'
import { clampList, listKey, LIST_START } from '../../../ui/list'
import { confirmKey, type PendingConfirm } from '../../../ui/Confirm'
import * as TB from '../../../input/TextBuffer'
import { glyphs, ink } from '../../../theme/theme'
import { truncate, wrap } from '../../../text/width'
import { editorName, editText } from '../connectEditor'
import {
  FilterLine,
  filterKey,
  FormView,
  formInit,
  formKey,
  formTyping,
  formValues,
  NoticeLine,
  Row,
  str,
  useConnectKeys,
  useHints,
  useInbound,
  useNotice,
  useSuspend,
  useTextFocus,
  type FormField,
  type FormState,
  ConfirmBlock,
} from '../connectKit'

const TEMPLATE = `{
  "name": "my-server",
  "description": "My custom MCP server",
  "transport": "stdio",
  "command": "npx @my-org/my-mcp-server",
  "action_set": "default",
  "env": {}
}
`

/** Values of these variables are shown as dots, as the browser does. */
export function isSecretEnvKey(key: string): boolean {
  return /key|token|secret|pass|auth|credential/i.test(key)
}

function needsConfig(server: MCPServerConfig): boolean {
  const values = Object.values(server.env ?? {})
  return values.length > 0 && values.some(v => !v || !v.trim())
}

interface EnvEdit {
  name: string
  keys: string[]
  base: Record<string, string>
  form: FormState
  saving: number
}

export function McpTab() {
  const { t } = useTranslation('settingsConnect')
  const dispatch = useAppDispatch()
  const { active, width, height } = useTab()
  const suspend = useSuspend()
  useResource(RESOURCES.mcpServers)
  const servers = useAppSelector(selectMcpServers)
  const hasLoaded = useAppSelector(selectMcpHasLoaded)

  const [list, setList] = useState(LIST_START)
  const [filter, setFilter] = useState<TB.Buffer>(TB.EMPTY)
  const [filtering, setFiltering] = useState(false)
  const [confirm, setConfirm] = useState<PendingConfirm | null>(null)
  const [env, setEnv] = useState<EnvEdit | null>(null)
  const [draft, setDraft] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const [notice, showNotice] = useNotice()
  const reloading = useRef(false)
  const pendingSaves = useRef(0)

  const query = filter.text.trim().toLowerCase()
  const items = servers
    .filter(s => !query || s.name.toLowerCase().includes(query) || (s.description ?? '').toLowerCase().includes(query))
    .slice()
    .sort((a, b) => a.name.localeCompare(b.name))
  const enabledCount = servers.filter(s => s.enabled).length
  const listHeight = Math.max(3, height - 6)
  const view = clampList(list, items.length, listHeight)
  const selected = items[view.index]

  const envFields: FormField[] = env
    ? env.keys.map(key => ({ kind: 'text', key, label: key, masked: isSecretEnvKey(key), placeholder: t('mcp.envPlaceholder') }))
    : []
  useTextFocus(active && (filtering || (env !== null && formTyping(env.form, envFields))))

  useInbound(['mcp_list', 'mcp_enable', 'mcp_disable', 'mcp_remove', 'mcp_add_json', 'mcp_get_env', 'mcp_update_env'], (type, d) => {
    const ok = d.success === true
    const error = str(d.error)
    if (type === 'mcp_list') {
      if (!reloading.current) return
      reloading.current = false
      showNotice(ok ? t('mcp.reloaded') : error || t('mcp.reloadFailed'), ok ? 'success' : 'error')
    } else if (type === 'mcp_enable' || type === 'mcp_disable') {
      if (!ok) showNotice(error || t(type === 'mcp_enable' ? 'mcp.enableFailed' : 'mcp.disableFailed'), 'error')
    } else if (type === 'mcp_remove') {
      showNotice(ok ? str(d.message) || t('mcp.removed') : error || t('mcp.removeFailed'), ok ? 'success' : 'error')
    } else if (type === 'mcp_add_json') {
      if (!adding) return
      setAdding(false)
      if (ok) {
        setDraft(null)
        showNotice(str(d.message) || t('mcp.added'), 'success')
      } else {
        showNotice(t('mcp.addFailedFix', { error: error || t('mcp.addFailed') }), 'error', null)
      }
    } else if (type === 'mcp_get_env') {
      const values = d.env as Record<string, string> | undefined
      if (!ok || !values || !env || str(d.name) !== env.name) return
      setEnv({ ...env, base: { ...env.base, ...values }, form: { ...formInit(envFields, values), index: env.form.index } })
    } else if (type === 'mcp_update_env') {
      // Several replies can arrive in one batch: count them in a ref.
      if (pendingSaves.current <= 0) return
      if (!ok) {
        pendingSaves.current = 0
        setEnv(current => (current ? { ...current, saving: 0 } : current))
        showNotice(error || t('mcp.envFailed'), 'error')
        return
      }
      pendingSaves.current -= 1
      if (pendingSaves.current === 0) {
        setEnv(null)
        showNotice(str(d.message) || t('mcp.envSaved'), 'success')
      }
    }
  })

  const openEnv = (server: MCPServerConfig) => {
    const keys = Object.keys(server.env ?? {})
    if (keys.length === 0) {
      showNotice(t('mcp.noEnv'))
      return
    }
    const base = { ...server.env }
    const fields: FormField[] = keys.map(key => ({ kind: 'text', key, label: key }))
    setEnv({ name: server.name, keys, base, form: formInit(fields, base), saving: 0 })
    send('mcp_get_env', { name: server.name })
  }

  const saveEnv = () => {
    if (!env || env.saving > 0) return
    const values = formValues(env.form)
    const changed = env.keys.filter(key => (values[key] as string) !== (env.base[key] ?? ''))
    if (changed.length === 0) {
      setEnv(null)
      showNotice(t('mcp.envUnchanged'))
      return
    }
    pendingSaves.current = changed.length
    for (const key of changed) send('mcp_update_env', { name: env.name, key, value: values[key] })
    setEnv({ ...env, saving: changed.length })
  }

  const addFromJson = async () => {
    const result = await editText(suspend, draft ?? TEMPLATE, 'mcp-server', 'json')
    if (result.text === null) {
      showNotice(t('common.editorFailed', { editor: editorName() }), 'error')
      return
    }
    const text = result.text.trim()
    if (!text || (draft === null && !result.changed)) {
      showNotice(t('mcp.addCancelled'))
      return
    }
    setDraft(result.text)
    let config: { name?: unknown }
    try {
      config = JSON.parse(text) as { name?: unknown }
    } catch {
      showNotice(t('mcp.invalidJson'), 'error', null)
      return
    }
    if (typeof config?.name !== 'string' || !config.name.trim()) {
      showNotice(t('mcp.nameRequired'), 'error', null)
      return
    }
    setAdding(true)
    showNotice(t('mcp.adding', { name: config.name }), 'info', null)
    send('mcp_add_json', { name: config.name, config: text })
  }

  useConnectKeys((input, key) => {
    if (confirmKey(confirm, input, key, () => setConfirm(null))) return true
    if (env) {
      if (key.escape) {
        setEnv(null)
        return true
      }
      const out = formKey(env.form, envFields, input, key)
      if (out?.submit) saveEnv()
      else if (out) setEnv({ ...env, form: out.state })
      return true
    }
    if (filtering && (key.upArrow || key.downArrow)) {
      const moved = listKey(view, '', key, items.length, listHeight)
      if (moved) setList(moved)
      return true
    }
    const filtered = filterKey(filtering, filter, input, key)
    if (filtered) {
      setFiltering(filtered.filtering)
      setFilter(filtered.buffer)
      if (filtered.changed) setList(LIST_START)
      return true
    }
    const moved = listKey(view, input, key, items.length, listHeight)
    if (moved) {
      setList(moved)
      return true
    }
    if (input === '/') {
      setFiltering(true)
      return true
    }
    if (input === 'r') {
      reloading.current = true
      showNotice(t('mcp.reloading'))
      send('mcp_list')
      return true
    }
    if (input === 'a') {
      if (!adding) void addFromJson()
      return true
    }
    if (!selected) return false
    if (input === ' ') {
      const enabled = !selected.enabled
      send(enabled ? 'mcp_enable' : 'mcp_disable', { name: selected.name })
      dispatch(setEnabled({ name: selected.name, enabled }))
      return true
    }
    if (input === 'e' || key.return) {
      openEnv(selected)
      return true
    }
    if (input === 'd') {
      const name = selected.name
      setConfirm({
        message: t('mcp.confirmRemove', { name }),
        onConfirm: () => {
          send('mcp_remove', { name })
          dispatch(removeServer(name))
        },
      })
      return true
    }
    return false
  })

  useHints(
    env
      ? [
          { keys: 'Tab', label: t('hint.nextField') },
          { keys: 'Enter', label: t('hint.save') },
          { keys: 'Esc', label: t('hint.cancel') },
        ]
      : [
          { keys: 'Space', label: t('hint.toggle') },
          { keys: 'e', label: t('mcp.hintEnv') },
          { keys: 'a', label: t('mcp.hintAdd') },
          { keys: 'd', label: t('hint.remove') },
          { keys: 'r', label: t('hint.reload') },
          { keys: '/', label: t('hint.filter') },
        ],
  )

  const g = glyphs()
  if (env) {
    return (
      <Box flexDirection="column">
        <Text bold color={ink.brand}>{truncate(t('mcp.envTitle', { name: env.name }), width - 1)}</Text>
        <Text color={ink.muted}>{truncate(t('mcp.envDesc'), width - 1)}</Text>
        <Text> </Text>
        <FormView fields={envFields} state={env.form} width={width} focused={active} />
        <Text> </Text>
        {env.saving > 0 ? <Text color={ink.muted}>{t('common.saving')}</Text> : null}
        <NoticeLine notice={notice} width={width} />
      </Box>
    )
  }

  const description = selected ? wrap(selected.description || t('mcp.noDescription'), width - 2).slice(0, 2) : []
  return (
    <Box flexDirection="column">
      <FilterLine
        buffer={filter}
        typing={filtering}
        width={width}
        placeholder={t('mcp.filterPlaceholder')}
        idle={hasLoaded ? t('mcp.summary', { enabled: enabledCount, total: servers.length }) : t('common.loading')}
      />
      {hasLoaded && items.length === 0 ? (
        <Text color={ink.muted}>{truncate(query ? t('mcp.noMatch') : t('mcp.none'), width - 1)}</Text>
      ) : null}
      {items.slice(view.top, view.top + listHeight).map((server, i) => {
        const index = view.top + i
        const setup = needsConfig(server)
        return (
          <Row
            key={server.name}
            selected={active && index === view.index}
            mark={server.enabled ? g.done : g.idle}
            markColor={server.enabled ? ink.success : ink.muted}
            label={server.name}
            dim={!server.enabled}
            aside={setup ? t('mcp.needsConfig') : server.enabled ? t('common.enabled') : t('common.disabled')}
            asideColor={setup ? ink.warn : undefined}
            width={width}
          />
        )
      })}
      {selected ? (
        <Box flexDirection="column" marginTop={1}>
          {description.map((line, i) => (
            <Text key={i} color={ink.muted}>{line}</Text>
          ))}
          <Text color={ink.muted}>
            {truncate(
              [selected.transport, selected.command, t('mcp.envCount', { count: Object.keys(selected.env ?? {}).length })]
                .filter(Boolean)
                .join(' · '),
              width - 1,
            )}
          </Text>
        </Box>
      ) : null}
      {confirm ? <ConfirmBlock pending={confirm} width={width} hint={t('common.confirmHint')} /> : <NoticeLine notice={notice} width={width} />}
    </Box>
  )
}
