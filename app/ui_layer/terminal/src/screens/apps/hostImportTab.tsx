/**
 * The Import tab of Add Agent App: a GitHub URL, a local folder, or a ZIP
 * path (uploaded first). Progress lines come from agent_app_import_progress;
 * the import itself runs in hostJobs, so it finishes (with a toast) even if
 * the screen closes. On success an open screen moves on to the new app.
 */
import { useEffect, useRef, useState } from 'react'
import { Box, Text, type Key } from 'ink'
import { TextField, fieldKey } from '../../ui/TextField'
import { useTicker } from '../../ui/useTicker'
import * as TB from '../../input/TextBuffer'
import { glyphs, ink, spinnerFrames } from '../../theme/theme'
import { truncate } from '../../text/width'
import { startImport, useImport } from './hostJobs'
import { FormRow, type TabController, type TabProps, wrapProse } from './hostTab'

export function useImportTab({ t, columns, height, active, onOpenProject }: TabProps): TabController {
  const job = useImport()
  const [source, setSource] = useState<TB.Buffer>(TB.EMPTY)
  const tick = useTicker(120, job.running)
  const g = glyphs()

  // Move on to the app, but only for an import finished after this screen opened.
  const seen = useRef(job.result?.seq ?? 0)
  const [shownSeq, setShownSeq] = useState(seen.current)
  useEffect(() => {
    if (!job.result || job.result.seq <= seen.current) return
    seen.current = job.result.seq
    setShownSeq(job.result.seq)
    if (job.result.success && job.result.projectId) onOpenProject(job.result.projectId)
  }, [job.result, onOpenProject])

  const handleKey = (input: string, key: Key): boolean => {
    if (key.escape) return false
    if (key.return) {
      if (!job.running && source.text.trim()) {
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
  const result = job.result && job.result.seq === shownSeq ? job.result : null
  const hintLines = wrapProse(t('appsHost:import.hint'), Math.max(10, columns - labelWidth - 3)).slice(0, 3)
  const lineRows = Math.max(1, height - 4 - hintLines.length)
  const body = (
    <Box flexDirection="column">
      <FormRow label={t('appsHost:import.source')} labelWidth={labelWidth} focused={active}>
        <TextField buffer={source} focused={active && !job.running} width={Math.max(10, columns - labelWidth - 2)} placeholder={t('appsHost:import.placeholder')} />
      </FormRow>
      {hintLines.map((line, i) => (
        <Text key={i} color={ink.muted}>{' '.repeat(labelWidth + 3) + line}</Text>
      ))}
      <Text> </Text>
      {job.running || job.lines.length > 0 || result ? (
        <Text bold>{truncate(t('appsHost:import.title', { name: job.name }), columns)}</Text>
      ) : null}
      {job.lines.slice(-lineRows).map((line, i, all) => {
        const last = i === all.length - 1
        const mark = last && job.running ? spin : g.done
        return (
          <Box key={`${line.phase}-${i}`}>
            <Text color={last && job.running ? ink.brand : ink.muted}>{`  ${mark} `}</Text>
            <Text color={last && job.running ? undefined : ink.muted}>{truncate(line.text, columns - 4)}</Text>
          </Box>
        )
      })}
      {job.running && job.lines.length === 0 ? <Text color={ink.brand}>{`  ${spin} ${t('appsHost:import.starting')}`}</Text> : null}
      {result ? (
        <Text color={result.success ? ink.success : ink.error}>
          {'  ' + truncate(result.success ? `${g.done} ${t('appsHost:import.done', { name: job.name })}` : `${g.failed} ${result.error ?? t('appsHost:import.failed')}`, columns - 2)}
        </Text>
      ) : null}
    </Box>
  )

  const hints = [
    { keys: 'Enter', label: t('appsHost:hint.import') },
    { keys: 'Esc', label: t('appsHost:hint.tabBar') },
  ]
  return { handleKey, textFocus: active, hints, body, dirty: !!source.text.trim() }
}
