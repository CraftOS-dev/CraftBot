import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSettingsWebSocket } from '../pages/Settings/useSettingsWebSocket'
import type { SkillCreatorSubmit, SkillCreatorSuccessInfo } from '../components/ui/SkillCreatorModal'

export type SkillCreatorStatus = 'idle' | 'submitting' | 'success' | 'error'

interface SkillCreatorResponse {
  success: boolean
  sessionId?: string
  skillName?: string
  mode?: 'create' | 'improve'
  error?: string
}

const ERROR_MESSAGES: Record<string, string> = {
  invalid_mode: 'Invalid request mode.',
  missing_session_id: 'No source session selected.',
  missing_skill_name: 'Enter a skill name.',
  invalid_skill_name: 'Skill name format is invalid.',
  reserved_skill_name: 'That name is reserved.',
  session_not_found: 'Source session no longer exists.',
  skill_already_exists: 'A skill with this name already exists.',
  skill_not_found: 'The target skill no longer exists.',
  workflow_busy: 'Another skill workflow is in progress. Try again in a moment.',
  workflow_lock_unavailable: 'Agent is not ready.',
}

function humanize(error: string | undefined): string {
  if (!error) return 'Unknown error.'
  return ERROR_MESSAGES[error] ?? error
}

// Creates (or improves) a skill from a chat session's transcript. Opened
// from the sidebar's per-session context menu; the modal UI is the shared
// SkillCreatorModal.
export function useSkillCreator() {
  const { send, onMessage } = useSettingsWebSocket()
  const [isOpen, setIsOpen] = useState(false)
  const [sourceSessionId, setSourceSessionId] = useState<string | null>(null)
  const [status, setStatus] = useState<SkillCreatorStatus>('idle')
  const [serverError, setServerError] = useState<string | null>(null)
  const [lastResult, setLastResult] = useState<SkillCreatorResponse | null>(null)

  // Subscribe to backend responses. The modal stays OPEN on success so the
  // user sees the "submitted, agent is working" confirmation inside the
  // dialog they were just interacting with — they dismiss it manually.
  useEffect(() => {
    const unsubscribe = onMessage('create_skill_from_session', (data: unknown) => {
      const resp = data as SkillCreatorResponse
      setLastResult(resp)
      if (resp.success) {
        setStatus('success')
        setServerError(null)
      } else {
        setStatus('error')
        setServerError(humanize(resp.error))
      }
    })
    return unsubscribe
  }, [onMessage])

  const open = useCallback((sessionId: string) => {
    setSourceSessionId(sessionId)
    setIsOpen(true)
    setServerError(null)
    setStatus('idle')
  }, [])

  const close = useCallback(() => {
    if (status === 'submitting') return // don't allow closing mid-flight
    setIsOpen(false)
    setSourceSessionId(null)
    setServerError(null)
    // Reset status so the next open shows a fresh form (otherwise a prior
    // success/error would persist and the modal would skip the form view).
    setStatus('idle')
    setLastResult(null)
  }, [status])

  const submit = useCallback((payload: SkillCreatorSubmit) => {
    if (!sourceSessionId) return
    setStatus('submitting')
    setServerError(null)
    send('create_skill_from_session', {
      sessionId: sourceSessionId,
      mode: payload.mode,
      skillName: payload.skillName,
    })
  }, [send, sourceSessionId])

  // Compact view of the last successful submit, for the modal's success
  // state. Returns null unless we have a valid skill name + mode pair.
  const successInfo = useMemo<SkillCreatorSuccessInfo | null>(() => {
    if (status !== 'success') return null
    if (!lastResult?.skillName || !lastResult?.mode) return null
    return { skillName: lastResult.skillName, mode: lastResult.mode }
  }, [status, lastResult])

  return {
    isOpen,
    sourceSessionId,
    status,
    serverError,
    lastResult,
    successInfo,
    open,
    close,
    submit,
  }
}
