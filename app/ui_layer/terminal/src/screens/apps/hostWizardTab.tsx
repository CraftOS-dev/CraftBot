/**
 * The Build tab of Add Agent App: the browser's build form
 * (CreateCustomWizard) on the same request.
 *
 *   name, description, layout and theme (Left/Right pick), icon (a lucide
 *   name typed, or picked with Left/Right from the curated set), access, and
 *   reference files by path (staged with POST /api/agent-app/stage)
 *
 * Continue starts the build (the host's `workflow`, activity "create"), and
 * the screen moves to the new build: its progress, and its questions and
 * requirements review when the builder stops for you.
 */
import { useState } from 'react'
import { Box, Text, type Key } from 'ink'
import { PRESET_THEMES } from '../../../../browser/frontend/src/pages/AgentApp/themeCatalog'
import { TextField, fieldKey } from '../../ui/TextField'
import { useTicker } from '../../ui/useTicker'
import * as TB from '../../input/TextBuffer'
import { glyphs, ink, spinnerFrames } from '../../theme/theme'
import { truncate, width } from '../../text/width'
import { errorText as messageOf, frameworkRequest } from '../../apps/framework'
import { countWords, cycleIcon, cycleValue, humanBytes, MAX_WORDS, normalizeIconName, validateConfig, type ConfigError } from './hostModel'
import { checkLocalFile, stageReference } from './hostUpload'
import { themeName } from './hostThemes'
import { FormRow, MultiLineField, multiLineKey, type TabController, type TabProps } from './hostTab'

type Access = 'none' | 'multi-user'
const FIELDS = ['name', 'description', 'layout', 'theme', 'icon', 'access', 'files', 'continue'] as const
type FieldId = (typeof FIELDS)[number]

/** The browser's layout silhouettes, by id (labels in components:createCustomWizard.layout). */
const LAYOUTS: { id: string; labelKey: string }[] = [
  { id: 'free', labelKey: 'free' },
  { id: 'sidebar-body', labelKey: 'sidebarBody' },
  { id: 'topnav-body', labelKey: 'topnavBody' },
  { id: 'hero-cards', labelKey: 'heroCards' },
  { id: 'split-view', labelKey: 'splitView' },
  { id: 'dashboard', labelKey: 'dashboard' },
  { id: 'columns-board', labelKey: 'columnsBoard' },
  { id: 'one-page', labelKey: 'onePage' },
]
const THEMES = PRESET_THEMES.map(p => p.id)

interface PickedFile {
  path: string
  name: string
  size: number
}

export function useWizardTab({ t, columns, height, active, onOpenBuild }: TabProps): TabController {
  const g = glyphs()
  const [field, setField] = useState(0)
  const [name, setName] = useState<TB.Buffer>(TB.EMPTY)
  const [description, setDescription] = useState<TB.Buffer>(TB.EMPTY)
  const [layout, setLayout] = useState('free')
  const [theme, setTheme] = useState<string>('craftbot')
  const [icon, setIcon] = useState<TB.Buffer>(TB.EMPTY)
  const [access, setAccess] = useState<Access>('none')
  const [files, setFiles] = useState<PickedFile[]>([])
  const [filePath, setFilePath] = useState<TB.Buffer>(TB.EMPTY)
  const [errors, setErrors] = useState<{ name?: ConfigError; description?: ConfigError; icon?: boolean; file?: string }>({})
  const [starting, setStarting] = useState(false)
  const [startError, setStartError] = useState<string | null>(null)

  const tick = useTicker(120, starting)
  const spin = spinnerFrames()[tick % spinnerFrames().length]
  const iconName = normalizeIconName(icon.text)
  const fieldId: FieldId = FIELDS[field]
  const fieldLabels = ['name', 'description', 'layout', 'theme', 'icon', 'access', 'files'].map(id => t(`appsHost:wizard.${id}`))
  const labelWidth = Math.min(22, Math.max(...fieldLabels.map(l => width(l))) + 2)
  const inputWidth = Math.max(10, columns - labelWidth - 2)

  const addFile = () => {
    const raw = filePath.text.trim()
    if (!raw) return false
    const check = checkLocalFile(raw)
    if (!check.ok) {
      setErrors(e => ({ ...e, file: t(check.reason === 'missing' ? 'appsHost:files.missing' : 'appsHost:files.notFile', { path: raw }) }))
      return true
    }
    setFiles(prev => (prev.some(f => f.path === check.path) ? prev : [...prev, { path: check.path, name: check.name, size: check.size }]))
    setFilePath(TB.EMPTY)
    setErrors(e => ({ ...e, file: undefined }))
    return true
  }

  // Stage the files, then start the build: its session is where it goes on.
  const start = async () => {
    const found = validateConfig(name.text, description.text)
    const iconBad = !!icon.text.trim() && !iconName
    setErrors(e => ({ ...e, name: found.name, description: found.description, icon: iconBad }))
    if (found.name) return setField(0)
    if (found.description) return setField(1)
    if (iconBad) return setField(4)
    setStarting(true)
    setStartError(null)
    try {
      const references: { name: string; path: string; kind: string }[] = []
      for (const f of files) references.push({ ...(await stageReference(f.path)), kind: 'reference' })
      const config = {
        name: name.text.trim(),
        description: description.text.trim(),
        layout,
        uiTheme: theme,
        // Every preset is a kit style pack; the host stamps it at scaffold.
        stylePack: theme,
        authMode: access,
        icon: iconName ? `lucide:${iconName}` : null,
        attachments: references,
      }
      const result = await frameworkRequest<{ sessionId: string }>({
        operation: 'workflow',
        activity: 'create',
        request:
          "Create an app using these preferences. Use the framework's supported blueprint and styling options to match the requested design. Copy staged references into the app's reference directory.\n" +
          JSON.stringify(config, null, 2),
        creation: { name: config.name, authMode: config.authMode, uiTheme: config.uiTheme },
      })
      onOpenBuild(result.sessionId)
    } catch (err) {
      setStartError(t('appsHost:wizard.startFailed', { message: messageOf(err) }))
      setStarting(false)
    }
  }

  // Editing a field clears its error (and a failed start's).
  const clearError = (id: 'name' | 'description' | 'icon' | 'file') => {
    setErrors(e => (e[id] ? { ...e, [id]: undefined } : e))
    setStartError(null)
  }

  const handleKey = (input: string, key: Key): boolean => {
    if (starting) return true
    if (key.escape) return false
    const next = (delta: 1 | -1) => setField(f => Math.max(0, Math.min(FIELDS.length - 1, f + delta)))
    if (key.tab) {
      next(key.shift ? -1 : 1)
      return true
    }
    if (fieldId === 'description') {
      if (key.return && !key.shift && !key.meta) {
        next(1)
        return true
      }
      const edited = multiLineKey(description, input, key, inputWidth)
      if (edited) {
        setDescription(edited)
        clearError('description')
      } else if (key.upArrow) next(-1)
      else if (key.downArrow) next(1)
      return true
    }
    if (key.upArrow) {
      next(-1)
      return true
    }
    if (key.downArrow) {
      next(1)
      return true
    }
    const delta: 1 | -1 = key.leftArrow ? -1 : 1
    switch (fieldId) {
      case 'name': {
        if (key.return) next(1)
        else {
          const edited = fieldKey(name, input, key)
          if (edited) {
            setName(edited)
            clearError('name')
          }
        }
        return true
      }
      case 'layout':
      case 'theme':
      case 'access': {
        if (key.return) next(1)
        else if (key.leftArrow || key.rightArrow || input === ' ') {
          if (fieldId === 'layout') setLayout(l => cycleValue(LAYOUTS.map(x => x.id), l, delta))
          else if (fieldId === 'theme') setTheme(th => cycleValue(THEMES, th, delta))
          else setAccess(a => (a === 'none' ? 'multi-user' : 'none'))
        }
        return true
      }
      case 'icon': {
        if (key.return) next(1)
        else if (key.leftArrow || key.rightArrow) {
          setIcon(TB.fromText(cycleIcon(iconName, delta) ?? ''))
          clearError('icon')
        } else {
          const edited = fieldKey(icon, input, key)
          if (edited) {
            setIcon(edited)
            clearError('icon')
          }
        }
        return true
      }
      case 'files': {
        if (key.return) {
          if (!addFile()) next(1)
        } else if (key.backspace && !filePath.text && files.length > 0) setFiles(prev => prev.slice(0, -1))
        else {
          const edited = fieldKey(filePath, input, key)
          if (edited) {
            setFilePath(edited)
            clearError('file')
          }
        }
        return true
      }
      case 'continue': {
        if (key.return || input === ' ') void start()
        return true
      }
    }
    return true
  }

  const textFocus = active && ['name', 'description', 'icon', 'files'].includes(fieldId)
  const errorLine = (e: ConfigError | undefined) => (e ? t(`appsHost:wizard.errors.${e}`, { max: MAX_WORDS }) : '')
  const words = countWords(description.text)
  const descRows = Math.max(1, Math.min(6, height - 12 - Math.min(files.length, 3)))
  const fileRows = Math.max(0, Math.min(files.length, height - 12 - descRows))
  const error = startError || errorLine(errors.name) || errorLine(errors.description) || (errors.icon ? t('appsHost:wizard.errors.icon') : '') || errors.file || ''
  const focused = (id: FieldId) => active && fieldId === id
  const choice = (id: FieldId, label: string) => (focused(id) ? `< ${label} >` : label)
  const layoutLabel = t(`appsHost:wizard.layouts.${LAYOUTS.find(l => l.id === layout)?.labelKey ?? 'free'}`)

  const body = (
    <Box flexDirection="column">
      <FormRow label={t('appsHost:wizard.name')} labelWidth={labelWidth} focused={focused('name')} error={!!errors.name}>
        <TextField buffer={name} focused={focused('name')} width={inputWidth} placeholder={t('appsHost:wizard.namePlaceholder')} />
      </FormRow>
      <FormRow label={t('appsHost:wizard.description')} labelWidth={labelWidth} focused={focused('description')} error={!!errors.description}>
        <MultiLineField buffer={description} focused={focused('description')} width={inputWidth} maxRows={descRows} placeholder={t('appsHost:wizard.descPlaceholder')} />
      </FormRow>
      <Text color={words > MAX_WORDS ? ink.error : ink.muted}>
        {' '.repeat(labelWidth + 2) + truncate(t('appsHost:wizard.words', { words, max: MAX_WORDS }) + (focused('description') ? '  ' + t('appsHost:wizard.newlineHint') : ''), inputWidth)}
      </Text>
      <FormRow label={t('appsHost:wizard.layout')} labelWidth={labelWidth} focused={focused('layout')}>
        <Text>{choice('layout', layoutLabel)}</Text>
      </FormRow>
      <FormRow label={t('appsHost:wizard.theme')} labelWidth={labelWidth} focused={focused('theme')}>
        <Text>{choice('theme', themeName(t, theme))}</Text>
      </FormRow>
      <FormRow label={t('appsHost:wizard.icon')} labelWidth={labelWidth} focused={focused('icon')} error={errors.icon}>
        <TextField buffer={icon} focused={focused('icon')} width={Math.min(inputWidth, 24)} placeholder={t('appsHost:wizard.iconPlaceholder')} />
        <Text color={ink.muted}>{truncate('  ' + (iconName && iconName !== icon.text ? iconName + '  ' : '') + t('appsHost:wizard.iconHint'), Math.max(0, inputWidth - 24))}</Text>
      </FormRow>
      <FormRow label={t('appsHost:wizard.access')} labelWidth={labelWidth} focused={focused('access')}>
        <Text>{choice('access', t(`appsHost:wizard.accessOptions.${access}`))}</Text>
      </FormRow>
      <FormRow label={t('appsHost:wizard.files')} labelWidth={labelWidth} focused={focused('files')}>
        <TextField buffer={filePath} focused={focused('files')} width={inputWidth} placeholder={t('appsHost:wizard.filesPlaceholder')} />
      </FormRow>
      {files.slice(-fileRows).map(f => (
        <Text key={f.path} color={ink.muted}>
          {' '.repeat(labelWidth + 2) + truncate(`${g.bullet} ${f.name}  ${humanBytes(f.size)}`, inputWidth)}
        </Text>
      ))}
      {files.length > fileRows ? (
        <Text color={ink.muted}>{' '.repeat(labelWidth + 2) + t('appsHost:wizard.moreFiles', { count: files.length - fileRows })}</Text>
      ) : null}
      <Text> </Text>
      <Box>
        <Text color={focused('continue') ? ink.focus : undefined}>{focused('continue') ? `${g.pointer} ` : '  '}</Text>
        <Text inverse={focused('continue')} bold>{` ${starting ? `${spin} ${t('appsHost:wizard.starting')}` : t('appsHost:wizard.continue')} `}</Text>
      </Box>
      {error ? <Text color={ink.error}>{truncate(error, columns)}</Text> : null}
    </Box>
  )

  const hints: TabController['hints'] = [
    { keys: 'Tab', label: t('appsHost:hint.nextField') },
    ...(['layout', 'theme', 'access', 'icon'].includes(fieldId) ? [{ keys: 'Left/Right', label: t('appsHost:hint.change') }] : []),
    ...(fieldId === 'files' ? [{ keys: 'Enter', label: t('appsHost:hint.addFile') }] : []),
    ...(fieldId === 'continue' ? [{ keys: 'Enter', label: t('appsHost:hint.build') }] : []),
    { keys: 'Esc', label: t('appsHost:hint.tabBar') },
  ]
  const dirty = !!(name.text || description.text || files.length)
  return { handleKey, textFocus, hints, body, dirty }
}
