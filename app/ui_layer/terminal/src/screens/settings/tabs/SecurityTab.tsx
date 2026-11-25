/**
 * Settings > Security: Auto mode (and, when it is off, which actions ask
 * first), the security level (Standard / Enhanced / Strict, "Custom" when
 * settings were changed on top of it), the Advanced settings, the security
 * check with its fixes, the audit log and reset (confirmed).
 *
 * Every change is sent at once (`security_set_level`, `security_update`,
 * `security_reset`); the backend answers every window with the new state,
 * and a refused change keeps the saved state and sets the slice's error.
 * Lowering the level, dropping custom settings and reset ask first. The
 * path and domain lists are shown read-only: they are edited in the browser.
 */
import { useRef, useState } from 'react'
import type { Key } from 'ink'
import { useTranslation } from 'react-i18next'
import { useAppSelector, send } from '../../../state/hooks'
import { RESOURCES, resourceSync, useResource } from '../../../../../browser/frontend/src/store/resources'
import type {
  SecurityCheck,
  SecurityLevel,
  SecuritySettingKey,
} from '../../../../../browser/frontend/src/store/slices/securitySlice'
import { glyphs } from '../../../theme/theme'
import { width as cells } from '../../../text/width'
import { useTab, useTabKeys } from '../tabContext'
import { FormView, useForm, type FormRow, type Tone } from '../coreForm'
import { useFlash, useInbound } from '../coreHooks'
import {
  ADVANCED_TOGGLES,
  APPROVAL_EFFECTS,
  SECURITY_LEVELS,
  SECURITY_LISTS,
  isLowering,
  parseRetentionDays,
  withEffect,
} from '../securityLogic'

const AUDIT_SHOWN = 5
/** The check status column: a mark and a word. */
const STATUS_WIDTH = 10

const CHECK_TONE: Record<SecurityCheck['status'], Tone> = { ok: 'success', info: 'info', warn: 'warn', fail: 'error' }

const isSpaceOrEnter = (input: string, key: Key) => key.return || input === ' '

export function SecurityTab() {
  const { t, i18n } = useTranslation('settingsCore')
  const { active, width, height } = useTab()
  const form = useForm()
  const [flash, say] = useFlash()
  const g = glyphs()

  const policy = useAppSelector(s => s.security.policy)
  const overrides = useAppSelector(s => s.security.overrides)
  const loaded = useAppSelector(s => s.security.hasLoaded)
  const error = useAppSelector(s => s.security.error)
  const checks = useAppSelector(s => s.security.checks)
  const loadedChecks = useAppSelector(s => s.security.hasLoadedChecks)
  const audit = useAppSelector(s => s.security.audit)
  const [advanced, setAdvanced] = useState(false)
  const [checking, setChecking] = useState(false)

  useResource(RESOURCES.securityState)
  useResource(RESOURCES.securityChecks)
  useResource(policy?.audit_log ? RESOURCES.securityAudit : null)

  // This tab's own requests in flight: their replies flash a result line.
  const saving = useRef(0)
  const fixing = useRef<string | null>(null)

  useInbound('security_state', data => {
    if (saving.current <= 0) return
    saving.current--
    const d = data as { success: boolean; error?: string | null }
    if (d.success) say(t('security.saved'), 'success', 2500)
    else say(d.error || t('security.saveFailed'), 'error', 8000)
  })
  useInbound('security_check', data => {
    setChecking(false)
    const fix = fixing.current
    if (!fix) return
    fixing.current = null
    const d = data as { success: boolean; error?: string }
    if (d.success) say(t('security.fixed'), 'success')
    else say(d.error || t('security.fixFailed'), 'error', 8000)
  })

  const save = (type: string, fields: Record<string, unknown> = {}) => {
    saving.current++
    send(type, fields)
  }
  const update = (changes: Partial<Record<SecuritySettingKey, unknown>>) => save('security_update', { changes })
  const levelName = (level: SecurityLevel) => t(`security.levels.${level}.name`)

  const chooseLevel = (level: SecurityLevel) => {
    if (!policy) return
    const current = policy.level
    if (level === current && !policy.customized) return
    const run = () => save('security_set_level', { level })
    if (level === current) form.confirm(t('security.useDefaultsConfirm', { level: levelName(level) }), run)
    else if (isLowering(current, level)) form.confirm(t('security.lowerConfirm', { level: levelName(level) }), run)
    else if (policy.customized) form.confirm(t('security.switchConfirm', { level: levelName(level) }), run)
    else run()
  }

  const runCheck = () => {
    setChecking(true)
    resourceSync.refresh(RESOURCES.securityChecks)
  }

  const box = (on: boolean) => `${on ? g.checked : g.unchecked} `
  const boxWidth = Math.max(cells(g.checked), cells(g.unchecked)) + 1
  const radioWidth = Math.max(cells(g.radioOn), cells(g.radioOff)) + 1

  const rows: FormRow[] = []
  if (error) rows.push({ kind: 'note', id: 'error', text: t('security.error', { error }), tone: 'error', indent: 0 })

  if (!loaded || !policy) {
    rows.push({ kind: 'note', text: t('security.loading') })
  } else {
    // ── Approvals ──
    rows.push({ kind: 'heading', text: t('security.approvalsTitle') })
    rows.push({
      kind: 'toggle',
      id: 'auto_mode',
      label: t('security.autoMode'),
      value: policy.auto_mode,
      onChange: on => update({ auto_mode: on }),
    })
    if (!policy.auto_mode) {
      rows.push({ kind: 'note', text: t('security.askFirst') })
      const choices = [
        ...APPROVAL_EFFECTS.map(effect => {
          const on = policy.approval_effects.includes(effect)
          return {
            id: `effect:${effect}`,
            on,
            text: t(`security.effects.${effect}`),
            toggle: () => update({ approval_effects: withEffect(policy.approval_effects, effect, !on) }),
          }
        }),
        {
          id: 'ask_after_untrusted',
          on: policy.ask_after_untrusted,
          text: t('security.askAfterUntrusted'),
          toggle: () => update({ ask_after_untrusted: !policy.ask_after_untrusted }),
        },
      ]
      for (const choice of choices) {
        rows.push({
          kind: 'item',
          id: choice.id,
          cells: [
            { text: '  ', width: 2 },
            { text: box(choice.on), width: boxWidth, tone: choice.on ? 'success' : 'muted' },
            { text: choice.text },
          ],
          onKey: (input, key) => {
            if (!isSpaceOrEnter(input, key)) return false
            choice.toggle()
            return true
          },
          hints: [{ keys: 'Space', label: t('hint.toggle') }],
        })
      }
      rows.push({
        kind: 'info',
        label: t('security.timeout'),
        value: t('security.minutes', { count: Math.max(1, Math.round(policy.approval_timeout_s / 60)) }),
      })
    }

    // ── Level ──
    rows.push({
      kind: 'heading',
      text: t('security.levelTitle'),
      aside: policy.customized ? t('security.customAside', { level: levelName(policy.level) }) : levelName(policy.level),
    })
    const levelLabel = (level: SecurityLevel) =>
      level === policy.level && policy.customized ? `${levelName(level)} (${t('security.custom')})` : levelName(level)
    const levelWidth = Math.max(...SECURITY_LEVELS.map(level => cells(levelLabel(level)))) + 3
    for (const level of SECURITY_LEVELS) {
      const current = level === policy.level
      rows.push({
        kind: 'item',
        id: `level:${level}`,
        cells: [
          { text: `${current ? g.radioOn : g.radioOff} `, width: radioWidth, tone: current ? 'brand' : 'muted' },
          { text: levelLabel(level), bold: current, width: levelWidth },
          { text: t(`security.levels.${level}.description`), tone: 'muted' },
        ],
        onKey: (input, key) => {
          if (!isSpaceOrEnter(input, key)) return false
          chooseLevel(level)
          return true
        },
        hints: current && !policy.customized ? [] : [{ keys: 'Enter', label: t('security.hintChoose') }],
      })
    }
    if (policy.customized) {
      rows.push({
        kind: 'action',
        id: 'useDefaults',
        label: t('security.useDefaults', { level: levelName(policy.level) }),
        onRun: () => chooseLevel(policy.level),
      })
    }

    // ── Advanced ──
    rows.push({ kind: 'heading', text: t('security.advancedTitle') })
    rows.push({
      kind: 'action',
      id: 'advanced',
      label: `${advanced ? g.expanded : g.chunk} ${advanced ? t('security.hideAdvanced') : t('security.showAdvanced')}`,
      onRun: () => setAdvanced(v => !v),
    })
    if (advanced) {
      for (const name of ADVANCED_TOGGLES) {
        const changed = overrides.includes(name)
        rows.push({
          kind: 'toggle',
          id: name,
          label: t(`security.settings.${name}.label`),
          value: policy[name],
          detail: changed ? t('security.changed') : undefined,
          detailTone: 'warn',
          onChange: on => update({ [name]: on }),
        })
      }
      const days = policy.retention_days
      const changed = overrides.includes('retention_days')
      rows.push({
        kind: 'text',
        id: 'retention_days',
        label: t('security.settings.retention_days.label'),
        value: String(days),
        display: days === 0 ? t('security.keepForever') : t('security.days', { count: days }),
        detail: changed ? t('security.changed') : undefined,
        detailTone: 'warn',
        onSubmit: v => {
          const next = parseRetentionDays(v)
          if (next === null) say(t('security.badDays'), 'warn')
          else if (next !== days) update({ retention_days: next })
        },
      })
      for (const list of SECURITY_LISTS) {
        const values = policy[list]
        rows.push({
          kind: 'info',
          label: t(`security.lists.${list}`),
          value: values.length ? values.join(', ') : t('security.none'),
          tone: values.length ? 'normal' : 'muted',
        })
      }
      rows.push({ kind: 'note', text: t('security.listsNote') })
    }

    // ── Security check ──
    const toFix = checks.filter(c => c.status === 'warn' || c.status === 'fail').length
    rows.push({
      kind: 'heading',
      text: t('security.checkTitle'),
      aside: loadedChecks ? (toFix ? t('security.checkIssues', { count: toFix }) : t('security.checkAllGood')) : undefined,
    })
    if (!loadedChecks) rows.push({ kind: 'note', text: t('security.checking') })
    const fixLabel = `  ${t('security.canFix')}`
    for (const check of checks) {
      const fixId = check.fix_id
      const mark = check.status === 'ok' ? g.done : check.status === 'fail' ? g.failed : check.status === 'warn' ? g.warn : g.notice
      rows.push({
        kind: 'item',
        id: `check:${check.id}`,
        cells: [
          { text: `${mark} ${t(`security.status.${check.status}`)}`, width: STATUS_WIDTH, tone: CHECK_TONE[check.status] },
          // Room for the title before "fix available" (the form's scrollbar takes a cell).
          { text: check.title, bold: check.status === 'fail', width: fixId ? Math.max(8, width - 4 - STATUS_WIDTH - cells(fixLabel)) : undefined },
          ...(fixId ? [{ text: fixLabel, tone: 'brand' as Tone }] : []),
        ],
        onKey: fixId
          ? (input, key) => {
              if (!key.return && input !== 'f') return false
              form.confirm(t('security.fixConfirm', { title: check.title }), () => {
                fixing.current = fixId
                send('security_check_fix', { id: fixId })
              })
              return true
            }
          : undefined,
        hints: fixId ? [{ keys: 'Enter', label: t('security.hintFix') }] : [],
      })
      if (check.detail && (check.status === 'warn' || check.status === 'fail')) rows.push({ kind: 'note', text: check.detail, indent: 2 + STATUS_WIDTH, maxLines: 3 })
    }
    rows.push({
      kind: 'action',
      id: 'checkAgain',
      label: checking ? t('security.checking') : t('security.checkAgain'),
      disabled: checking,
      onRun: runCheck,
    })

    // ── Audit log ──
    rows.push({ kind: 'heading', text: t('security.auditTitle') })
    if (!policy.audit_log) {
      rows.push({ kind: 'note', text: t('security.auditOff') })
    } else if (!audit) {
      rows.push({ kind: 'note', text: t('security.auditLoading') })
    } else {
      rows.push({
        kind: 'info',
        label: t('security.auditRecords'),
        value: t('security.records', { count: audit.count }),
        detail: audit.intact ? t('security.auditIntact') : t('security.auditBroken', { line: audit.brokenAt ?? '?' }),
        tone: audit.intact ? 'normal' : 'error',
      })
      rows.push({ kind: 'info', label: t('security.auditFile'), value: audit.path, tone: 'muted' })
      for (const [i, entry] of audit.entries.slice(0, AUDIT_SHOWN).entries()) {
        const when = new Date(entry.ts * 1000).toLocaleString(i18n.language, { dateStyle: 'short', timeStyle: 'short' })
        const outcome = typeof entry.outcome === 'string' ? entry.outcome : typeof entry.action === 'string' ? entry.action : ''
        rows.push({
          kind: 'item',
          id: `audit:${i}`,
          dim: true,
          cells: [
            { text: when, width: Math.max(16, cells(when) + 2), tone: 'muted' },
            { text: entry.event, width: 26 },
            { text: outcome, tone: 'muted' },
          ],
        })
      }
      rows.push({ kind: 'action', id: 'auditRefresh', label: t('security.auditRefresh'), onRun: () => send('security_audit_list') })
    }

    // ── Reset ──
    rows.push({ kind: 'heading', text: t('security.resetTitle') })
    rows.push({
      kind: 'action',
      id: 'reset',
      label: t('security.reset'),
      tone: 'error',
      onRun: () => form.confirm(t('security.resetConfirm'), () => save('security_reset')),
    })
  }

  useTabKeys((input, key) => form.handleKey(rows, input, key))

  return <FormView form={form} rows={rows} width={width} height={height} active={active} flash={flash} />
}
