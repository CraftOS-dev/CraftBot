/**
 * The Import tab of Add Agent App: a ZIP on this computer (uploaded first),
 * a folder, a GitHub URL or `github:owner/repo@ref/path`. The framework
 * inspects it: an Agent App package is installed as it is, anything else is
 * rebuilt by your AI agent. Installs run in hostJobs, so they finish (with a
 * toast) even if the screen closes; their progress lines show here.
 */
import { useState } from 'react'
import { Box, Text, type Key } from 'ink'
import { TextField, fieldKey } from '../../ui/TextField'
import { useTicker } from '../../ui/useTicker'
import * as TB from '../../input/TextBuffer'
import { glyphs, ink, spinnerFrames } from '../../theme/theme'
import { truncate } from '../../text/width'
import { startImport, useImport, useJobs } from './hostJobs'
import { FormRow, type TabController, type TabProps, wrapProse } from './hostTab'

export function useImportTab({ t, columns, height, active }: TabProps): TabController {
  const job = useImport()
  const { jobs } = useJobs()
  const [source, setSource] = useState<TB.Buffer>(TB.EMPTY)
  const running = jobs.some(j => j.status === 'running')
  const tick = useTicker(120, job.starting || running)
  const g = glyphs()

  const handleKey = (input: string, key: Key): boolean => {
    if (key.escape) return false
    if (key.return) {
      if (!job.starting && source.text.trim()) {
        void startImport(source.text)
        setSource(TB.EMPTY)
      }
      return true
    }
    const next = fieldKey(source, input, key)
    if (next) setSource(next)
    return true
  }

  const labelWidth = 10
  const spin = spinnerFrames()[tick % spinnerFrames().length]
  const hintLines = wrapProse(t('appsHost:import.hint'), Math.max(10, columns - labelWidth - 3)).slice(0, 3)
  const jobRows = Math.max(1, height - 5 - hintLines.length)
  const body = (
    <Box flexDirection="column">
      <FormRow label={t('appsHost:import.source')} labelWidth={labelWidth} focused={active}>
        <TextField buffer={source} focused={active && !job.starting} width={Math.max(10, columns - labelWidth - 2)} placeholder={t('appsHost:import.placeholder')} />
      </FormRow>
      {hintLines.map((line, i) => (
        <Text key={i} color={ink.muted}>{' '.repeat(labelWidth + 3) + line}</Text>
      ))}
      <Text> </Text>
      {job.starting ? <Text color={ink.brand}>{`  ${spin} ${truncate(t('appsHost:import.starting', { name: job.name }), columns - 4)}`}</Text> : null}
      {job.error ? <Text color={ink.error}>{`  ${g.failed} ${truncate(job.error, columns - 4)}`}</Text> : null}
      {jobs.slice(-jobRows).map(j => {
        const busy = j.status === 'running'
        const ok = j.status === 'success' && !j.error
        const line = busy
          ? `${spin} ${t('appsHost:import.installing', { name: j.name })}${j.step ? `  ${g.sep}  ${j.step}` : ''}`
          : ok
            ? `${g.done} ${t('appsHost:import.done', { name: j.name })}`
            : `${g.failed} ${j.name}: ${j.error ?? t('appsHost:import.failed')}`
        return (
          <Text key={j.id} color={busy ? ink.brand : ok ? ink.success : ink.error}>
            {'  ' + truncate(line, columns - 2)}
          </Text>
        )
      })}
    </Box>
  )

  const hints = [
    { keys: 'Enter', label: t('appsHost:hint.import') },
    { keys: 'Esc', label: t('appsHost:hint.tabBar') },
  ]
  return { handleKey, textFocus: active, hints, body, dirty: !!source.text.trim() }
}
