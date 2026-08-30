import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSettingsWebSocket } from '../pages/Settings/useSettingsWebSocket'
import type { SkillCreatorSubmit, SkillCreatorSuccessInfo } from '../components/ui/SkillCreatorModal'
import i18n from '../i18n/config'

export type SkillCreatorStatus = 'idle' | 'submitting' | 'success' | 'error'

interface SkillCreatorResponse {
  success: boolean
  sessionId?: string
  skillName?: string
  mode?: 'create' | 'improve'
  error?: string
}

function humanize(error: string | undefined): string {
  switch (error) {
    case 'invalid_mode': return i18n.t('nav:skillCreator.errors.invalidMode')
    case 'missing_session_id': return i18n.t('nav:skillCreator.errors.missingSessionId')
    case 'missing_skill_name': return i18n.t('nav:skillCreator.errors.missingSkillName')
    case 'invalid_skill_name': return i18n.t('nav:skillCreator.errors.invalidSkillName')
    case 'reserved_skill_name': return i18n.t('nav:skillCreator.errors.reservedSkillName')
    case 'session_not_found': return i18n.t('nav:skillCreator.errors.sessionNotFound')
    case 'skill_already_exists': return i18n.t('nav:skillCreator.errors.skillAlreadyExists')
    case 'skill_not_found': return i18n.t('nav:skillCreator.errors.skillNotFound')
    case 'workflow_busy': return i18n.t('nav:skillCreator.errors.workflowBusy')
    case 'workflow_lock_unavailable': return i18n.t('nav:skillCreator.errors.workflowLockUnavailable')
    default: return error || i18n.t('nav:skillCreator.errors.unknown')
  }
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
