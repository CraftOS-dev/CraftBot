/**
 * The Connect tab of Add Agent App: use an Agent App that is already
 * running somewhere, by its URL. The host signs in to it (`connect`); the
 * app answers with a page where its owner approves access, which opens in
 * the system browser (o opens it again, c copies the link). The tab checks
 * every second (`connect_status`) and, once approved, the screen moves on to
 * the connected app. Leaving the tab while waiting cancels the sign-in.
 */
import { useEffect, useRef, useState } from 'react'
import { Box, Text, type Key } from 'ink'
import { receiveFrameworkAttachment } from '../../../../browser/frontend/src/store/slices/agentAppSlice'
import { useAppDispatch, useAppSelector } from '../../state/hooks'
import { TextField, fieldKey } from '../../ui/TextField'
import { useTicker } from '../../ui/useTicker'
import * as TB from '../../input/TextBuffer'
import { glyphs, ink, spinnerFrames } from '../../theme/theme'
import { truncate } from '../../text/width'
import { errorText, frameworkAppKey, frameworkRequest, requestAppList, type FrameworkAttachment } from '../../apps/framework'
import { openExternal } from '../settings/connectOpen'
import { copyToClipboard } from './hostUpload'
import { FormRow, type TabController, type TabProps, wrapProse } from './hostTab'

interface Attempt {
  id?: string
  status: 'pending' | 'connected' | 'error' | 'cancelled'
  approvalUrl?: string
  /** Approved and signed in; the host is adding the app. */
  finishing?: boolean
  attachment?: FrameworkAttachment
  error?: string
}

export function useConnectTab({ t, columns, active, onOpenApp }: TabProps): TabController {
  const dispatch = useAppDispatch()
  const connected = useAppSelector(s => s.connection.connected)
  const [url, setUrl] = useState<TB.Buffer>(TB.EMPTY)
  const [attempt, setAttempt] = useState<Attempt | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [copied, setCopied] = useState(false)
  const waiting = attempt?.status === 'pending'
  const tick = useTicker(120, busy || waiting)
  const pendingId = useRef<string | undefined>(undefined)
  const opened = useRef<string | undefined>(undefined)
  const g = glyphs()

  const receive = (value: Attempt) => {
    pendingId.current = value.status === 'pending' ? value.id : undefined
    setAttempt(value)
    if (value.status === 'pending' && value.approvalUrl && opened.current !== value.approvalUrl) {
      opened.current = value.approvalUrl
      void openExternal(value.approvalUrl)
    }
    if (value.status === 'connected' && value.attachment) {
      dispatch(receiveFrameworkAttachment(value.attachment))
      requestAppList()
      setBusy(false)
      onOpenApp(frameworkAppKey(value.attachment.path, value.attachment.appId))
    } else if (value.status !== 'pending') {
      setError(value.error || t('appsHost:connect.cancelled'))
      setBusy(false)
    }
  }

  // Waiting for the owner's approval: ask again every second.
  useEffect(() => {
    if (!attempt?.id || attempt.status !== 'pending') return
    const timer = setTimeout(() => {
      frameworkRequest<Attempt>({ operation: 'connect_status', id: attempt.id })
        .then(receive)
        .catch(err => {
          setError(errorText(err))
          setBusy(false)
        })
    }, 1000)
    return () => clearTimeout(timer)
  }, [attempt])

  const cancel = () => {
    const id = pendingId.current
    pendingId.current = undefined
    if (id) void frameworkRequest({ operation: 'connect_cancel', id }).catch(() => {})
  }
  // Leaving the screen cancels a sign-in still waiting.
  useEffect(() => cancel, [])

  const connect = () => {
    const target = url.text.trim()
    if (!target || busy || waiting || !connected) return
    setBusy(true)
    setError('')
    setAttempt(null)
    opened.current = undefined
    // No embedding page here: the approval page opens in the system browser.
    frameworkRequest<Attempt>({ operation: 'connect', url: target, embedder: '' })
      .then(receive)
      .catch(err => {
        setError(errorText(err))
        setBusy(false)
      })
  }

  const handleKey = (input: string, key: Key): boolean => {
    if (waiting) {
      if (key.escape) {
        cancel()
        setAttempt(null)
        setBusy(false)
        return true
      }
      if (input === 'o' && attempt?.approvalUrl) void openExternal(attempt.approvalUrl)
      else if (input === 'c' && attempt?.approvalUrl) {
        copyToClipboard(attempt.approvalUrl)
        setCopied(true)
      }
      return true
    }
    if (key.escape) return false
    if (key.return) {
      connect()
      return true
    }
    const next = fieldKey(url, input, key)
    if (next) {
      setUrl(next)
      setError('')
    }
    return true
  }

  const labelWidth = 10
  const spin = spinnerFrames()[tick % spinnerFrames().length]
  const hintLines = wrapProse(t('appsHost:connect.hint'), Math.max(10, columns - labelWidth - 3)).slice(0, 3)
  const body = (
    <Box flexDirection="column">
      <FormRow label={t('appsHost:connect.url')} labelWidth={labelWidth} focused={active && !waiting}>
        <TextField buffer={url} focused={active && !waiting && !busy} width={Math.max(10, columns - labelWidth - 2)} placeholder="https://app.example.com" />
      </FormRow>
      {hintLines.map((line, i) => (
        <Text key={i} color={ink.muted}>{' '.repeat(labelWidth + 3) + line}</Text>
      ))}
      <Text> </Text>
      {busy && !waiting ? <Text color={ink.brand}>{`  ${spin} ${t('appsHost:connect.connecting')}`}</Text> : null}
      {waiting ? (
        <Box flexDirection="column">
          <Text color={ink.brand}>{`  ${spin} ${truncate(attempt?.finishing ? t('appsHost:connect.finishing') : t('appsHost:connect.waiting'), columns - 4)}`}</Text>
          {attempt?.approvalUrl ? <Text>{'  ' + truncate(attempt.approvalUrl, columns - 2)}</Text> : null}
          {copied ? <Text color={ink.success}>{`  ${g.done} ${t('appsHost:connect.copied')}`}</Text> : null}
        </Box>
      ) : null}
      {!connected ? <Text color={ink.warn}>{'  ' + t('appsHost:connect.offline')}</Text> : null}
      {error ? <Text color={ink.error}>{`  ${g.failed} ${truncate(error, columns - 4)}`}</Text> : null}
    </Box>
  )

  const hints = waiting
    ? [
        ...(attempt?.approvalUrl ? [{ keys: 'o', label: t('appsHost:hint.openLink') }, { keys: 'c', label: t('appsHost:hint.copyLink') }] : []),
        { keys: 'Esc', label: t('appsHost:hint.cancel') },
      ]
    : [
        { keys: 'Enter', label: t('appsHost:hint.connect') },
        { keys: 'Esc', label: t('appsHost:hint.tabBar') },
      ]
  return { handleKey, textFocus: active && !waiting, hints, body, dirty: waiting || !!url.text.trim() }
}
