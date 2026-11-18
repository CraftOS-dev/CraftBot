/**
 * Settings > Skills: every discovered skill with its enabled state (system
 * skills are always on). Space enables or disables, Enter shows a skill's
 * details, e opens its SKILL.md in $EDITOR (then reloads), n creates one
 * from the backend's template, a installs from a path or git URL, d removes
 * (confirm), r reloads from disk. Same messages as the browser's tab.
 */
import { useEffect, useRef, useState } from 'react'
import { existsSync } from 'node:fs'
import { isAbsolute, resolve } from 'node:path'
import { Box, Text } from 'ink'
import { useTranslation } from 'react-i18next'
import { useAppDispatch, useAppSelector, send } from '../../../state/hooks'
import {
  removeSkill,
  setEnabled,
  type SkillConfig,
} from '../../../../../browser/frontend/src/store/slices/skillsSettingsSlice'
import {
  selectEnabledSkills,
  selectSkills,
  selectSkillsHasLoaded,
  selectTotalSkills,
} from '../../../../../browser/frontend/src/store/selectors/skillsSettings'
import { RESOURCES, useResource } from '../../../../../browser/frontend/src/store/resources'
import { useTab } from '../tabContext'
import { clampList, listKey, LIST_START } from '../../../ui/list'
import { confirmKey, type PendingConfirm } from '../../../ui/Confirm'
import * as TB from '../../../input/TextBuffer'
import { glyphs, ink } from '../../../theme/theme'
import { truncate, wrap } from '../../../text/width'
import { editFile, editorName, editText } from '../connectEditor'
import {
  FilterLine,
  filterKey,
  FormView,
  formInit,
  formKey,
  formTyping,
  formValues,
  NoticeLine,
  Pager,
  pagerKey,
  Row,
  str,
  useConnectKeys,
  useHints,
  useInbound,
  useNotice,
  useSpinner,
  useSuspend,
  useTextFocus,
  wrapStyled,
  type FormField,
  type FormState,
  type PagerLine,
  ConfirmBlock,
} from '../connectKit'

/**
 * The SKILL.md path on this machine. The backend reports it relative to its
 * own folder (skills\x\SKILL.md); the skill folders it searches are absolute,
 * so the file is looked up next to them before falling back to this cwd.
 */
function skillFilePath(source: string, dirs: string[]): string {
  if (isAbsolute(source)) return source
  for (const dir of dirs) {
    for (const candidate of [resolve(dir, '..', source), resolve(dir, source)]) {
      if (existsSync(candidate)) return candidate
    }
  }
  return resolve(source)
}

interface SkillInfo extends SkillConfig {
  argument_hint?: string
  allowed_tools?: string[]
  instructions?: string
}

type Mode =
  | { kind: 'list' }
  | { kind: 'info'; name: string; skill: SkillInfo | null; top: number }
  | { kind: 'install'; form: FormState; busy: boolean; error: string }
  | { kind: 'create'; form: FormState; busy: 'template' | 'create' | null; error: string }

export function SkillsTab() {
  const { t } = useTranslation('settingsConnect')
  const dispatch = useAppDispatch()
  const { active, width, height } = useTab()
  const suspend = useSuspend()
  useResource(RESOURCES.skills)
  const skills = useAppSelector(selectSkills)
  const total = useAppSelector(selectTotalSkills)
  const enabled = useAppSelector(selectEnabledSkills)
  const hasLoaded = useAppSelector(selectSkillsHasLoaded)

  const [mode, setMode] = useState<Mode>({ kind: 'list' })
  const [list, setList] = useState(LIST_START)
  const [filter, setFilter] = useState<TB.Buffer>(TB.EMPTY)
  const [filtering, setFiltering] = useState(false)
  const [confirm, setConfirm] = useState<PendingConfirm | null>(null)
  const [dirs, setDirs] = useState<string[]>([])
  const [notice, showNotice] = useNotice()
  const reloading = useRef(false)
  // The create form's name and description while its template is on its way.
  const templateFor = useRef<{ name: string; description: string } | null>(null)

  useEffect(() => {
    send('skill_dirs')
  }, [])

  const installFields: FormField[] = [
    { kind: 'text', key: 'source', label: t('skills.source'), placeholder: t('skills.sourcePlaceholder') },
  ]
  const createFields: FormField[] = [
    { kind: 'text', key: 'name', label: t('skills.name'), placeholder: t('skills.namePlaceholder'), hint: t('skills.nameHint') },
    { kind: 'text', key: 'description', label: t('skills.description'), placeholder: t('skills.descriptionPlaceholder') },
  ]

  const query = filter.text.trim().toLowerCase()
  const items = skills
    .filter(s => !query || s.name.toLowerCase().includes(query) || s.description.toLowerCase().includes(query))
    .slice()
    .sort((a, b) => a.name.localeCompare(b.name))
  const listHeight = Math.max(3, height - 6)
  const view = clampList(list, items.length, listHeight)
  const selected = items[view.index]

  const typing =
    filtering ||
    (mode.kind === 'install' && formTyping(mode.form, installFields)) ||
    (mode.kind === 'create' && formTyping(mode.form, createFields))
  useTextFocus(active && typing)
  const spinner = useSpinner((mode.kind === 'install' && mode.busy) || (mode.kind === 'create' && mode.busy !== null))

  const createWithTemplate = async (name: string, description: string, template: string) => {
    const result = await editText(suspend, template, `skill-${name.replace(/[^A-Za-z0-9_-]+/g, '_')}`)
    if (result.text === null) {
      setMode(m => (m.kind === 'create' ? { ...m, busy: null, error: t('common.editorFailed', { editor: editorName() }) } : m))
      return
    }
    if (!result.text.trim()) {
      setMode(m => (m.kind === 'create' ? { ...m, busy: null, error: t('skills.createCancelled') } : m))
      return
    }
    setMode(m => (m.kind === 'create' ? { ...m, busy: 'create', error: '' } : m))
    send('skill_create', { name, description, content: result.text })
  }

  useInbound(
    ['skill_list', 'skill_enable', 'skill_disable', 'skill_install', 'skill_create', 'skill_template', 'skill_remove', 'skill_reload', 'skill_info', 'skill_dirs'],
    (type, d) => {
      const ok = d.success === true
      const error = str(d.error)
      const message = str(d.message)
      switch (type) {
        case 'skill_list':
          if (!ok && error) showNotice(error, 'error')
          break
        case 'skill_enable':
        case 'skill_disable':
          if (!ok) showNotice(error || message || t(type === 'skill_enable' ? 'skills.enableFailed' : 'skills.disableFailed'), 'error')
          break
        case 'skill_install':
          if (mode.kind !== 'install' || !mode.busy) break
          if (ok) {
            setMode({ kind: 'list' })
            showNotice(message || t('skills.installed'), 'success')
          } else {
            setMode({ ...mode, busy: false, error: error || message || t('skills.installFailed') })
          }
          break
        case 'skill_template': {
          const pending = templateFor.current
          if (!pending) break
          templateFor.current = null
          if (ok && typeof d.template === 'string') void createWithTemplate(pending.name, pending.description, d.template)
          else setMode(m => (m.kind === 'create' ? { ...m, busy: null, error: error || t('skills.templateFailed') } : m))
          break
        }
        case 'skill_create':
          if (mode.kind !== 'create' || mode.busy !== 'create') break
          if (ok) {
            setMode({ kind: 'list' })
            showNotice(message || t('skills.created'), 'success')
          } else {
            setMode({ ...mode, busy: null, error: error || message || t('skills.createFailed') })
          }
          break
        case 'skill_remove':
          showNotice(ok ? message || t('skills.removed') : error || message || t('skills.removeFailed'), ok ? 'success' : 'error')
          break
        case 'skill_reload':
          if (!reloading.current) break
          reloading.current = false
          showNotice(ok ? message || t('skills.reloaded') : error || message || t('skills.reloadFailed'), ok ? 'success' : 'error')
          break
        case 'skill_info':
          if (mode.kind !== 'info' || str(d.name) !== mode.name) break
          if (ok && d.skill) setMode({ ...mode, skill: d.skill as SkillInfo })
          else {
            setMode({ kind: 'list' })
            showNotice(error || t('skills.infoFailed'), 'error')
          }
          break
        case 'skill_dirs':
          if (ok && Array.isArray(d.directories)) setDirs((d.directories as unknown[]).map(String))
          break
      }
    },
  )

  const toggle = (skill: SkillConfig) => {
    if (skill.is_system) {
      showNotice(t('skills.systemLocked'))
      return
    }
    const next = !skill.enabled
    send(next ? 'skill_enable' : 'skill_disable', { name: skill.name })
    dispatch(setEnabled({ name: skill.name, enabled: next }))
  }

  const editSkillFile = async (skill: SkillConfig) => {
    const path = skillFilePath(skill.source, dirs)
    const result = await editFile(suspend, path, `skill-${skill.name.replace(/[^A-Za-z0-9_-]+/g, '_')}`)
    if (!result.ok) {
      showNotice(t('skills.editFailed', { path, editor: editorName() }), 'error')
      return
    }
    if (result.changed) {
      reloading.current = true
      send('skill_reload')
      showNotice(t('skills.savedReloading'))
    } else {
      showNotice(t('skills.unchanged'))
    }
  }

  const reload = () => {
    reloading.current = true
    showNotice(t('skills.reloading'))
    send('skill_reload')
  }

  const remove = (skill: SkillConfig) => {
    if (skill.is_system) {
      showNotice(t('skills.systemNoRemove'))
      return
    }
    setConfirm({
      message: t('skills.confirmRemove', { name: skill.name }),
      onConfirm: () => {
        send('skill_remove', { name: skill.name })
        dispatch(removeSkill(skill.name))
      },
    })
  }

  // Info view: the skill as shown in the list, then the full details once they arrive.
  const infoSkill: SkillInfo | null =
    mode.kind === 'info' ? mode.skill ?? (skills.find(s => s.name === mode.name) as SkillInfo | undefined) ?? null : null
  const infoLines: PagerLine[] = infoSkill
    ? wrapStyled(
        [
          { text: infoSkill.description || t('skills.noDescription') },
          { text: '' },
          { text: `${t('skills.status')}  ${infoSkill.enabled ? t('common.enabled') : t('common.disabled')}${infoSkill.is_system ? ` · ${t('skills.system')}` : ''}`, color: ink.muted },
          {
            text: `${t('skills.invocable')}  ${infoSkill.user_invocable ? `/${infoSkill.name}${infoSkill.argument_hint ? ` ${infoSkill.argument_hint}` : ''}` : t('skills.notInvocable')}`,
            color: ink.muted,
          },
          ...(infoSkill.action_sets?.length ? [{ text: `${t('skills.actionSets')}  ${infoSkill.action_sets.join(', ')}`, color: ink.muted }] : []),
          ...(infoSkill.allowed_tools?.length ? [{ text: `${t('skills.allowedTools')}  ${infoSkill.allowed_tools.join(', ')}`, color: ink.muted }] : []),
          { text: `${t('skills.file')}  ${infoSkill.source}`, color: ink.muted },
          ...(mode.kind === 'info' && mode.skill?.instructions
            ? [{ text: '' }, { text: t('skills.instructions'), bold: true }, ...mode.skill.instructions.split('\n').map(text => ({ text }))]
            : mode.kind === 'info' && !mode.skill
              ? [{ text: '' }, { text: t('common.loading'), color: ink.muted }]
              : []),
        ],
        width - 2,
      )
    : []
  const pagerHeight = Math.max(3, height - 3)

  useConnectKeys((input, key) => {
    if (confirmKey(confirm, input, key, () => setConfirm(null))) return true
    if (mode.kind === 'info') {
      if (key.escape || key.leftArrow) {
        setMode({ kind: 'list' })
        return true
      }
      if (input === ' ' && infoSkill) {
        toggle(infoSkill)
        if (mode.skill && !infoSkill.is_system) setMode({ ...mode, skill: { ...mode.skill, enabled: !infoSkill.enabled } })
        return true
      }
      if (input === 'e' && infoSkill) {
        void editSkillFile(infoSkill)
        return true
      }
      const top = pagerKey(mode.top, input, key, infoLines.length, pagerHeight)
      if (top === null) return false
      setMode({ ...mode, top })
      return true
    }
    if (mode.kind === 'install') {
      if (key.escape) {
        setMode({ kind: 'list' })
        return true
      }
      if (mode.busy) return true
      const out = formKey(mode.form, installFields, input, key)
      if (out?.submit) {
        const source = String(formValues(out.state).source ?? '').trim()
        if (!source) setMode({ ...mode, form: out.state, error: t('skills.sourceRequired') })
        else {
          setMode({ ...mode, form: out.state, busy: true, error: '' })
          send('skill_install', { source })
        }
      } else if (out) setMode({ ...mode, form: out.state })
      return true
    }
    if (mode.kind === 'create') {
      if (key.escape) {
        templateFor.current = null
        setMode({ kind: 'list' })
        return true
      }
      if (mode.busy) return true
      const out = formKey(mode.form, createFields, input, key)
      if (out?.submit) {
        const values = formValues(out.state)
        const name = String(values.name ?? '').trim()
        const description = String(values.description ?? '').trim()
        if (!name) setMode({ ...mode, form: out.state, error: t('skills.nameRequired') })
        else {
          templateFor.current = { name, description }
          setMode({ ...mode, form: out.state, busy: 'template', error: '' })
          send('skill_template', { name, description })
        }
      } else if (out) setMode({ ...mode, form: out.state })
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
      reload()
      return true
    }
    if (input === 'a') {
      setMode({ kind: 'install', form: formInit(installFields), busy: false, error: '' })
      return true
    }
    if (input === 'n') {
      setMode({ kind: 'create', form: formInit(createFields), busy: null, error: '' })
      return true
    }
    if (!selected) return false
    if (input === ' ') {
      toggle(selected)
      return true
    }
    if (key.return || input === 'l' || key.rightArrow) {
      setMode({ kind: 'info', name: selected.name, skill: null, top: 0 })
      send('skill_info', { name: selected.name })
      return true
    }
    if (input === 'e') {
      void editSkillFile(selected)
      return true
    }
    if (input === 'd') {
      remove(selected)
      return true
    }
    return false
  })

  useHints(
    mode.kind === 'info'
      ? [
          { keys: 'j/k', label: t('hint.scroll') },
          { keys: 'Space', label: t('hint.toggle') },
          { keys: 'e', label: t('skills.hintEdit') },
          { keys: 'Esc', label: t('hint.back') },
        ]
      : mode.kind === 'install' || mode.kind === 'create'
        ? [
            ...(mode.kind === 'create' ? [{ keys: 'Tab', label: t('hint.nextField') }] : []),
            { keys: 'Enter', label: mode.kind === 'install' ? t('skills.hintInstall') : t('skills.hintWrite') },
            { keys: 'Esc', label: t('hint.cancel') },
          ]
        : [
            { keys: 'Space', label: t('hint.toggle') },
            { keys: 'Enter', label: t('hint.details') },
            { keys: 'e', label: t('skills.hintEdit') },
            { keys: 'n', label: t('skills.hintCreate') },
            { keys: 'a', label: t('skills.hintInstallKey') },
            { keys: 'd', label: t('hint.remove') },
            { keys: 'r', label: t('hint.reload') },
            { keys: '/', label: t('hint.filter') },
          ],
  )

  const g = glyphs()
  if (mode.kind === 'info' && infoSkill) {
    return (
      <Box flexDirection="column">
        <Text bold color={ink.brand}>{truncate(infoSkill.name, width - 1)}</Text>
        <Pager lines={infoLines} top={mode.top} height={pagerHeight} width={width} />
        {confirm ? <ConfirmBlock pending={confirm} width={width} hint={t('common.confirmHint')} /> : <NoticeLine notice={notice} width={width} />}
      </Box>
    )
  }
  if (mode.kind === 'install') {
    return (
      <Box flexDirection="column">
        <Text bold color={ink.brand}>{truncate(t('skills.installTitle'), width - 1)}</Text>
        {wrap(t('skills.installDesc'), width - 1).map((line, i) => (
          <Text key={i} color={ink.muted}>{line}</Text>
        ))}
        <Text> </Text>
        <FormView fields={installFields} state={mode.form} width={width} focused={active && !mode.busy} />
        <Text> </Text>
        {mode.busy ? <Text color={ink.muted}>{`${spinner} ${t('skills.installing')}`}</Text> : null}
        {mode.error ? <Text color={ink.error}>{truncate(mode.error, width - 1)}</Text> : null}
        {dirs.length > 0 ? (
          <Box flexDirection="column" marginTop={1}>
            <Text color={ink.muted}>{t('skills.dirsTitle')}</Text>
            {dirs.slice(0, 4).map(dir => (
              <Text key={dir} color={ink.muted}>{truncate(`  ${dir}`, width - 1, 'middle')}</Text>
            ))}
          </Box>
        ) : null}
      </Box>
    )
  }
  if (mode.kind === 'create') {
    return (
      <Box flexDirection="column">
        <Text bold color={ink.brand}>{truncate(t('skills.createTitle'), width - 1)}</Text>
        {wrap(t('skills.createDesc'), width - 1).map((line, i) => (
          <Text key={i} color={ink.muted}>{line}</Text>
        ))}
        <Text> </Text>
        <FormView fields={createFields} state={mode.form} width={width} focused={active && mode.busy === null} />
        <Text> </Text>
        {mode.busy ? <Text color={ink.muted}>{`${spinner} ${mode.busy === 'template' ? t('skills.openingEditor') : t('skills.creating')}`}</Text> : null}
        {mode.error ? <Text color={ink.error}>{truncate(mode.error, width - 1)}</Text> : null}
      </Box>
    )
  }

  const description = selected ? wrap(selected.description || t('skills.noDescription'), width - 2).slice(0, 2) : []
  return (
    <Box flexDirection="column">
      <FilterLine
        buffer={filter}
        typing={filtering}
        width={width}
        placeholder={t('skills.filterPlaceholder')}
        idle={hasLoaded ? t('skills.summary', { enabled, total }) : t('common.loading')}
      />
      {hasLoaded && items.length === 0 ? (
        <Text color={ink.muted}>{truncate(query ? t('skills.noMatch') : t('skills.none'), width - 1)}</Text>
      ) : null}
      {items.slice(view.top, view.top + listHeight).map((skill, i) => {
        const index = view.top + i
        const tags = [skill.is_system ? t('skills.system') : '', skill.user_invocable ? `/${skill.name}` : ''].filter(Boolean)
        return (
          <Row
            key={skill.name}
            selected={active && index === view.index}
            mark={skill.enabled ? g.checked : g.unchecked}
            markColor={skill.enabled ? ink.success : ink.muted}
            label={skill.name}
            dim={!skill.enabled}
            aside={tags.join(' · ')}
            width={width}
          />
        )
      })}
      {selected ? (
        <Box flexDirection="column" marginTop={1}>
          {description.map((line, i) => (
            <Text key={i} color={ink.muted}>{line}</Text>
          ))}
          {selected.action_sets?.length ? (
            <Text color={ink.muted}>
              {truncate(
                `${t('skills.actionSets')}  ${selected.action_sets.slice(0, 3).join(', ')}${selected.action_sets.length > 3 ? ` +${selected.action_sets.length - 3}` : ''}`,
                width - 1,
              )}
            </Text>
          ) : null}
        </Box>
      ) : null}
      {confirm ? <ConfirmBlock pending={confirm} width={width} hint={t('common.confirmHint')} /> : <NoticeLine notice={notice} width={width} />}
    </Box>
  )
}
