/**
 * Settings > General, as the browser's General tab: the agent's name, the UI
 * language (applied live and saved), the avatar, the agent's own files
 * (USER.md, SOUL.md, AGENT.md, edited in $EDITOR), version and updates,
 * profile export and import, and reset. The theme is a browser preference
 * and has no row here.
 */
import { useEffect, useRef, useState } from 'react'
import { readFileSync, statSync } from 'node:fs'
import { basename, extname, sep } from 'node:path'
import { useTranslation } from 'react-i18next'
import { useAppDispatch, useAppSelector, send } from '../../../state/hooks'
import { RESOURCES, useResource } from '../../../../../browser/frontend/src/store/resources'
import { resetUpdateCheck } from '../../../../../browser/frontend/src/store/slices/generalSettingsSlice'
import {
  selectAgentMd,
  selectGeneralSettingsValues,
  selectHasLoadedAgentMd,
  selectHasLoadedSoulMd,
  selectHasLoadedUserMd,
  selectLatestVersion,
  selectSoulMd,
  selectUpdateAvailable,
  selectUpdateBranch,
  selectUpdateChecked,
  selectUserMd,
} from '../../../../../browser/frontend/src/store/selectors/generalSettings'
import { selectAgentName, selectAgentProfilePictureHasCustom } from '../../../../../browser/frontend/src/store/selectors/agent'
import { selectVersion } from '../../../../../browser/frontend/src/store/selectors/connection'
import { SUPPORTED_LANGUAGES, resolveSupportedLanguage } from '../../../../../browser/frontend/src/i18n/languages'
import { setUiLanguage } from '../../../platform/i18n'
import { useTab, useTabKeys } from '../tabContext'
import { FormView, useForm, type FormRow } from '../coreForm'
import { useExternalEditor, useFlash, useInbound } from '../coreHooks'
import { cleanPath } from '../coreLogic'
import {
  defaultExportFolder,
  exportProfile,
  importProfile,
  inspectProfile,
  type ImportMode,
  type Inspected,
} from '../coreProfile'

type AgentFile = 'USER.md' | 'SOUL.md' | 'AGENT.md'
const AGENT_FILES: { name: AgentFile; badge: string }[] = [
  { name: 'USER.md', badge: 'general.files.user' },
  { name: 'SOUL.md', badge: 'general.files.soul' },
  { name: 'AGENT.md', badge: 'general.files.agent' },
]

/** Components the backend's reset knows (AgentBase.RESET_COMPONENTS); destructive ones start unchecked. */
const RESET_ITEMS: { id: string; destructive?: boolean }[] = [
  { id: 'sessions' },
  { id: 'memory' },
  { id: 'triggers' },
  { id: 'workspace', destructive: true },
  { id: 'agentapp', destructive: true },
]

const AVATAR_TYPES: Record<string, string> = {
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.webp': 'image/webp',
  '.gif': 'image/gif',
}

type ImportState =
  | { phase: 'path' }
  | { phase: 'reading'; path: string }
  | { phase: 'preview'; path: string; bundle: Inspected; mode: ImportMode }
  | { phase: 'applying'; path: string; bundle: Inspected; mode: ImportMode }

export function GeneralTab() {
  const { t } = useTranslation('settingsCore')
  const dispatch = useAppDispatch()
  const { active, width, height } = useTab()
  const form = useForm()
  const [flash, say] = useFlash()
  const { edit, editing: inEditor } = useExternalEditor()

  useResource(RESOURCES.generalSettings)
  useResource(RESOURCES.agentFiles)
  const connected = useAppSelector(s => s.connection.connected)
  const saved = useAppSelector(selectGeneralSettingsValues)
  const agentName = useAppSelector(selectAgentName)
  const hasCustomAvatar = useAppSelector(selectAgentProfilePictureHasCustom)
  const version = useAppSelector(selectVersion)
  const updateChecked = useAppSelector(selectUpdateChecked)
  const updateAvailable = useAppSelector(selectUpdateAvailable)
  const latestVersion = useAppSelector(selectLatestVersion)
  const updateBranch = useAppSelector(selectUpdateBranch)
  const files: Record<AgentFile, { content: string; loaded: boolean }> = {
    'USER.md': { content: useAppSelector(selectUserMd), loaded: useAppSelector(selectHasLoadedUserMd) },
    'SOUL.md': { content: useAppSelector(selectSoulMd), loaded: useAppSelector(selectHasLoadedSoulMd) },
    'AGENT.md': { content: useAppSelector(selectAgentMd), loaded: useAppSelector(selectHasLoadedAgentMd) },
  }
  const filesRef = useRef(files)
  filesRef.current = files

  const savedLanguage = saved?.language ? resolveSupportedLanguage(saved.language) ?? 'en' : null
  const name = saved?.agentName || agentName || ''

  const [updating, setUpdating] = useState(false)
  const [updateLines, setUpdateLines] = useState<string[]>([])
  const [exportOpen, setExportOpen] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [importState, setImportState] = useState<ImportState | null>(null)
  const [resetOpen, setResetOpen] = useState(false)
  const [resetChoice, setResetChoice] = useState<string[]>(RESET_ITEMS.filter(i => !i.destructive).map(i => i.id))
  const [resetting, setResetting] = useState(false)
  const [avatarOpen, setAvatarOpen] = useState(false)
  const [uploadingAvatar, setUploadingAvatar] = useState(false)
  const [busyFile, setBusyFile] = useState<AgentFile | null>(null)
  // This tab's own requests in flight; replies to other clients' requests
  // only update data.
  const savingSettings = useRef<'name' | 'language' | null>(null)
  const savingFile = useRef<{ name: AgentFile; content: string } | null>(null)
  const restoringFile = useRef<AgentFile | null>(null)

  // The saved language drives the UI language, as in the browser.
  useEffect(() => {
    if (savedLanguage) setUiLanguage(savedLanguage)
  }, [savedLanguage])

  // Check for updates once per launch, as the browser does on first open.
  useEffect(() => {
    if (connected && !updateChecked) send('check_update')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connected])

  useInbound('settings_update', data => {
    const which = savingSettings.current
    if (!which) return
    savingSettings.current = null
    const d = data as { success: boolean; error?: string }
    if (d.success) say(which === 'name' ? t('general.nameSaved') : t('general.languageSaved'), 'success')
    else say(t('general.saveFailed', { error: d.error ?? '' }), 'error')
  })
  useInbound('update_progress', data => {
    const d = data as { message?: string }
    if (d.message) setUpdateLines(lines => [...lines, d.message as string].slice(-40))
  })
  useInbound('reset', data => {
    if (!resetting) return
    setResetting(false)
    const d = data as { success: boolean }
    say(d.success ? t('general.reset.done') : t('general.reset.failed'), d.success ? 'success' : 'error')
  })
  useInbound(['agent_profile_picture_upload', 'agent_profile_picture_remove'], (data, type) => {
    const d = data as { success: boolean; error?: string }
    if (type === 'agent_profile_picture_upload') {
      if (!uploadingAvatar) return
      setUploadingAvatar(false)
    }
    if (d.success) say(type === 'agent_profile_picture_upload' ? t('general.avatar.uploaded') : t('general.avatar.removed'), 'success')
    else say(t('general.avatar.failed', { error: d.error ?? '' }), 'error')
  })
  useInbound('agent_file_write', data => {
    const d = data as { filename: string; success: boolean; error?: string }
    const pending = savingFile.current
    if (!pending || d.filename !== pending.name) return
    savingFile.current = null
    setBusyFile(null)
    say(d.success ? t('general.files.saved', { file: d.filename }) : t('general.files.saveFailed', { file: d.filename, error: d.error ?? '' }), d.success ? 'success' : 'error')
  })
  useInbound('agent_file_restore', data => {
    const d = data as { filename: string; success: boolean; error?: string }
    if (restoringFile.current !== d.filename) return
    restoringFile.current = null
    setBusyFile(null)
    say(d.success ? t('general.files.restored', { file: d.filename }) : t('general.files.restoreFailed', { file: d.filename, error: d.error ?? '' }), d.success ? 'success' : 'error')
  })

  // ── Actions ──

  const saveName = (value: string) => {
    const next = value.trim()
    if (!next || next === name) return
    savingSettings.current = 'name'
    send('settings_update', { settings: { agentName: next } })
  }

  const chooseLanguage = (code: string) => {
    setUiLanguage(code)
    savingSettings.current = 'language'
    send('settings_update', { settings: { language: code } })
  }

  const uploadAvatar = (input: string) => {
    setAvatarOpen(false)
    const path = cleanPath(input)
    if (!path) return
    const type = AVATAR_TYPES[extname(path).toLowerCase()]
    if (!type) {
      say(t('general.avatar.badType'), 'error')
      return
    }
    try {
      if (statSync(path).size > 5 * 1024 * 1024) {
        say(t('general.avatar.tooBig'), 'error')
        return
      }
      const content = readFileSync(path).toString('base64')
      setUploadingAvatar(true)
      send('agent_profile_picture_upload', { name: basename(path), mimeType: type, content })
      say(t('general.avatar.uploading'), 'muted', null)
    } catch (err) {
      say(t('general.avatar.unreadable', { error: err instanceof Error ? err.message : String(err) }), 'error')
    }
  }

  const write = (file: AgentFile, content: string) => {
    savingFile.current = { name: file, content }
    setBusyFile(file)
    send('agent_file_write', { filename: file, content })
    say(t('general.files.saving', { file }), 'muted', null)
  }

  const openFile = async (file: AgentFile) => {
    const current = filesRef.current[file]
    if (!current.loaded) {
      say(t('general.files.loading', { file }), 'muted')
      return
    }
    const before = current.content
    const result = await edit(before, file)
    if (result.error === 'busy') {
      say(t('general.files.editorBusy'), 'warn')
      return
    }
    if (result.text === null) {
      say(t('general.files.editorFailed', { editor: result.editor, error: result.error ?? '' }), 'error', 8000)
      return
    }
    if (result.text === before) {
      say(t('general.files.unchanged', { file }), 'muted')
      return
    }
    const text = result.text
    // Someone else saved the file while the editor was open.
    if (filesRef.current[file].content !== before) {
      form.confirm(t('general.files.changedElsewhere', { file }), () => write(file, text))
      return
    }
    write(file, text)
  }

  const restoreFile = (file: AgentFile) => {
    form.confirm(t('general.files.restoreConfirm', { file }), () => {
      restoringFile.current = file
      setBusyFile(file)
      send('agent_file_restore', { filename: file })
    })
  }

  const checkUpdate = () => {
    dispatch(resetUpdateCheck())
    setUpdateLines([])
    send('check_update')
  }

  const runUpdate = () => {
    const message = latestVersion === version ? t('general.update.confirmMain') : t('general.update.confirm', { version: latestVersion })
    form.confirm(message, () => {
      setUpdating(true)
      setUpdateLines([])
      send('do_update')
    })
  }

  const runExport = async (input: string) => {
    setExportOpen(false)
    setExporting(true)
    say(t('general.profile.exporting'), 'muted', null)
    try {
      const path = await exportProfile(input || defaultExportFolder())
      say(t('general.profile.exported', { path }), 'success', 10000)
    } catch (err) {
      say(t('general.profile.exportFailed', { error: err instanceof Error ? err.message : String(err) }), 'error', 10000)
    } finally {
      setExporting(false)
    }
  }

  const runInspect = async (input: string) => {
    const path = cleanPath(input)
    if (!path) {
      setImportState(null)
      return
    }
    setImportState({ phase: 'reading', path })
    try {
      const bundle = await inspectProfile(path)
      setImportState({ phase: 'preview', path, bundle, mode: 'replace' })
      form.select('import.mode')
    } catch (err) {
      setImportState(null)
      say(t('general.profile.readFailed', { error: err instanceof Error ? err.message : String(err) }), 'error', 10000)
    }
  }

  const applyImport = () => {
    if (importState?.phase !== 'preview') return
    const { bundle, mode, path } = importState
    const message = mode === 'overwrite' ? t('general.profile.confirmOverwrite') : t('general.profile.confirmMerge', { name: bundle.manifest.name })
    form.confirm(message, async () => {
      setImportState({ phase: 'applying', path, bundle, mode })
      try {
        const summary = await importProfile(bundle.token, mode)
        const parts: string[] = []
        if (summary.skills_added?.length) parts.push(t('general.profile.skills', { count: summary.skills_added.length }))
        if (summary.mcp_added?.length) parts.push(t('general.profile.mcps', { count: summary.mcp_added.length }))
        const apps = (summary.agent_app_added?.length ?? 0) + (summary.agent_app_renamed?.length ?? 0)
        if (apps) parts.push(t('general.profile.apps', { count: apps }))
        const what = parts.length ? parts.join(', ') : t('general.profile.profileWord')
        say(mode === 'overwrite' ? t('general.profile.importedOverwrite', { what }) : t('general.profile.importedMerge', { what }), 'success', 10000)
        setImportState(null)
      } catch (err) {
        setImportState({ phase: 'preview', path, bundle, mode })
        say(t('general.profile.importFailed', { error: err instanceof Error ? err.message : String(err) }), 'error', 10000)
      }
    })
  }

  const runReset = () => {
    if (!resetChoice.length) {
      say(t('general.reset.pickOne'), 'warn')
      return
    }
    const labels = RESET_ITEMS.filter(i => resetChoice.includes(i.id)).map(i => t(`general.reset.items.${i.id}`)).join(', ')
    form.confirmTyped(t('general.reset.confirm', { what: labels }), t('general.reset.word'), () => {
      setResetting(true)
      setResetOpen(false)
      send('reset', { components: resetChoice })
      say(t('general.reset.running'), 'muted', null)
    })
  }

  // ── Rows ──

  const languageOptions = SUPPORTED_LANGUAGES.map(l => ({ value: l.code, label: l.label }))
  const rows: FormRow[] = [
    { kind: 'text', id: 'name', label: t('general.name'), value: name, placeholder: t('general.namePlaceholder'), onSubmit: saveName },
    {
      kind: 'choice',
      id: 'language',
      label: t('general.language'),
      value: savedLanguage ?? 'en',
      options: languageOptions,
      picker: true,
      pickerTitle: t('general.languagePicker'),
      onChange: chooseLanguage,
    },
    avatarOpen
      ? {
          kind: 'text',
          id: 'avatar',
          label: t('general.avatar.label'),
          value: '',
          placeholder: t('general.avatar.pathPlaceholder'),
          onSubmit: uploadAvatar,
          onCancel: () => setAvatarOpen(false),
        }
      : {
          kind: 'action',
          id: 'avatar',
          label: t('general.avatar.action'),
          detail: uploadingAvatar ? t('general.avatar.uploading') : hasCustomAvatar ? t('general.avatar.custom') : t('general.avatar.default'),
          disabled: uploadingAvatar,
          onRun: () => {
            setAvatarOpen(true)
            form.startEdit('avatar', '')
          },
          onKey: (input: string) => {
            if (input !== 'x' || !hasCustomAvatar) return false
            form.confirm(t('general.avatar.removeConfirm'), () => send('agent_profile_picture_remove'))
            return true
          },
          hints: hasCustomAvatar ? [{ keys: 'x', label: t('hint.remove') }] : [],
        },

    { kind: 'heading', text: t('general.files.title'), aside: t('general.files.aside') },
    ...AGENT_FILES.map(({ name: file, badge }): FormRow => {
      const state = files[file]
      const lines = state.content ? state.content.split(/\r?\n/).length : 0
      const status =
        busyFile === file
          ? t('general.files.working')
          : inEditor
            ? t('general.files.inEditor')
            : state.loaded
              ? t('general.files.lines', { count: lines })
              : t('general.files.loadingShort')
      return {
        kind: 'action',
        id: `file.${file}`,
        label: file,
        detail: `${t(badge)} · ${status}`,
        disabled: busyFile === file,
        onRun: () => void openFile(file),
        onKey: (input: string) => {
          if (input !== 'r') return false
          restoreFile(file)
          return true
        },
        hints: [{ keys: 'r', label: t('hint.restoreDefault') }],
      }
    }),

    { kind: 'heading', text: t('general.update.title') },
    { kind: 'info', label: t('general.update.current'), value: version ? `v${version}` : t('general.update.unknown') },
    {
      kind: 'info',
      label: t('general.update.status'),
      ...(!updateChecked
        ? { value: t('general.update.checking'), tone: 'muted' as const }
        : updateAvailable
          ? { value: latestVersion === version ? t('general.update.availableMain') : t('general.update.available', { version: latestVersion }), tone: 'info' as const }
          : updateBranch
            ? { value: t('general.update.onBranch', { branch: updateBranch }), tone: 'warn' as const }
            : { value: t('general.update.upToDate'), tone: 'success' as const }),
    },
    updateChecked && updateAvailable
      ? {
          kind: 'action',
          id: 'update',
          label: updating ? t('general.update.updating') : latestVersion === version ? t('general.update.updateLatest') : t('general.update.updateTo', { version: latestVersion }),
          tone: 'brand',
          disabled: updating,
          onRun: runUpdate,
        }
      : {
          kind: 'action',
          id: 'update',
          label: updateChecked ? t('general.update.check') : t('general.update.checkingButton'),
          disabled: !updateChecked,
          onRun: checkUpdate,
        },
    ...updateLines.slice(-6).map((line): FormRow => ({ kind: 'note', text: line, indent: 4, maxLines: 1 })),

    { kind: 'heading', text: t('general.profile.title') },
    { kind: 'note', text: t('general.profile.description') },
    exportOpen
      ? {
          kind: 'text',
          id: 'export',
          label: t('general.profile.saveTo'),
          value: defaultExportFolder() + sep,
          onSubmit: value => void runExport(value),
          onCancel: () => setExportOpen(false),
        }
      : {
          kind: 'action',
          id: 'export',
          label: exporting ? t('general.profile.exporting') : t('general.profile.export'),
          detail: t('general.profile.exportDetail'),
          disabled: exporting,
          onRun: () => {
            setExportOpen(true)
            form.startEdit('export', defaultExportFolder() + sep)
          },
        },
    ...importRows(),

    { kind: 'heading', text: t('general.reset.title') },
    ...resetRows(),
  ]

  function importRows(): FormRow[] {
    if (!importState) {
      return [
        {
          kind: 'action',
          id: 'import',
          label: t('general.profile.import'),
          detail: t('general.profile.importDetail'),
          onRun: () => {
            setImportState({ phase: 'path' })
            form.startEdit('import', '')
          },
        },
      ]
    }
    if (importState.phase === 'path') {
      return [
        {
          kind: 'text',
          id: 'import',
          label: t('general.profile.bundle'),
          value: '',
          placeholder: t('general.profile.bundlePlaceholder'),
          onSubmit: value => void runInspect(value),
          onCancel: () => setImportState(null),
        },
      ]
    }
    if (importState.phase === 'reading') {
      return [{ kind: 'info', label: t('general.profile.bundle'), value: t('general.profile.reading'), detail: importState.path }]
    }
    const { manifest, preview } = importState.bundle
    const c = manifest.contents
    const installedSkills = new Set(preview.skills_already_installed)
    const installedMcp = new Set(preview.mcp_already_installed)
    const listOf = (items: string[] | undefined, installed?: Set<string>) =>
      (items ?? []).map(item => (installed?.has(item) ? t('general.profile.installed', { name: item }) : item)).join(', ')
    const out: FormRow[] = [
      { kind: 'info', label: t('general.profile.bundle'), value: manifest.name || importState.path, tone: 'brand', detail: manifest.source_app_version ? t('general.profile.madeWith', { version: manifest.source_app_version }) : undefined },
    ]
    if (manifest.description) out.push({ kind: 'note', text: manifest.description, maxLines: 2 })
    if (c.agent_name) out.push({ kind: 'info', label: t('general.profile.fromAgent'), value: c.agent_name })
    if (c.md_files?.length) out.push({ kind: 'info', label: t('general.profile.files'), value: c.md_files.join(', ') })
    if (c.skills?.length) out.push({ kind: 'info', label: t('general.profile.skillsLabel', { count: c.skills.length }), value: listOf(c.skills, installedSkills) })
    if (c.mcp_servers?.length) out.push({ kind: 'info', label: t('general.profile.mcpLabel', { count: c.mcp_servers.length }), value: listOf(c.mcp_servers, installedMcp) })
    if (c.agent_app_apps?.length) out.push({ kind: 'info', label: t('general.profile.appsLabel', { count: c.agent_app_apps.length }), value: listOf(c.agent_app_apps) })
    if (preview.mcp_needs_env.length) {
      out.push({ kind: 'note', tone: 'warn', text: t('general.profile.needsEnv', { names: preview.mcp_needs_env.map(n => n.name).join(', ') }) })
    }
    const applying = importState.phase === 'applying'
    out.push(
      {
        kind: 'choice',
        id: 'import.mode',
        label: t('general.profile.mode'),
        value: importState.mode,
        disabled: applying,
        options: [
          { value: 'replace', label: t('general.profile.modeMerge') },
          { value: 'overwrite', label: t('general.profile.modeOverwrite') },
        ],
        detail: importState.mode === 'overwrite' ? t('general.profile.overwriteWarn') : t('general.profile.mergeHint'),
        detailTone: importState.mode === 'overwrite' ? 'error' : 'muted',
        onChange: value => importState.phase === 'preview' && setImportState({ ...importState, mode: value as ImportMode }),
      },
      {
        kind: 'action',
        id: 'import.apply',
        label: applying ? t('general.profile.applying') : importState.mode === 'overwrite' ? t('general.profile.applyOverwrite') : t('general.profile.apply'),
        tone: importState.mode === 'overwrite' ? 'error' : 'brand',
        disabled: applying,
        onRun: applyImport,
      },
      { kind: 'action', id: 'import.cancel', label: t('general.profile.cancel'), disabled: applying, onRun: () => setImportState(null) },
    )
    return out
  }

  function resetRows(): FormRow[] {
    if (!resetOpen) {
      return [
        { kind: 'note', text: t('general.reset.description') },
        {
          kind: 'action',
          id: 'reset',
          label: resetting ? t('general.reset.resetting') : t('general.reset.open'),
          tone: 'error',
          disabled: resetting,
          onRun: () => {
            setResetChoice(RESET_ITEMS.filter(i => !i.destructive).map(i => i.id))
            setResetOpen(true)
            form.select(`reset.${RESET_ITEMS[0].id}`)
          },
        },
      ]
    }
    return [
      { kind: 'note', text: t('general.reset.intro') },
      ...RESET_ITEMS.map(
        (item): FormRow => ({
          kind: 'toggle',
          id: `reset.${item.id}`,
          label: t(`general.reset.items.${item.id}`),
          value: resetChoice.includes(item.id),
          detail: item.destructive ? t('general.reset.cantUndo') : t(`general.reset.details.${item.id}`),
          detailTone: item.destructive ? 'error' : 'muted',
          onChange: on => setResetChoice(list => (on ? [...list, item.id] : list.filter(x => x !== item.id))),
        }),
      ),
      { kind: 'action', id: 'reset.run', label: t('general.reset.run'), tone: 'error', disabled: !resetChoice.length, onRun: runReset },
      { kind: 'action', id: 'reset.cancel', label: t('general.reset.cancel'), onRun: () => setResetOpen(false) },
    ]
  }

  useTabKeys((input, key) => form.handleKey(rows, input, key))

  return <FormView form={form} rows={rows} width={width} height={height} active={active} flash={flash} />
}
