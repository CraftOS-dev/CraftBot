import React, { useState } from 'react'
import { createRoot } from 'react-dom/client'
import { Provider } from 'react-redux'
import { ToastProvider } from '../src/contexts/ToastContext'
import { getSocketClient } from '../src/store/socket/socketInstance'
import { dispatchInbound } from '../src/store/socket/messageRegistry'
import { setConnected } from '../src/store/slices/connectionSlice'
import { openTriggerReview, setProjects } from '../src/store/slices/agentAppSlice'
import { AgentAppTriggerConsentModal } from '../src/components/ui/AgentAppTriggerConsentModal'
import { Modal, ModalBody } from '../src/components/ui/Modal'
import { AgentAppSettings } from '../src/pages/Settings/AgentAppSettings'
import { setSettings } from '../src/store/slices/agentAppSettingsSlice'
import type { AgentAppProject } from '../src/types'
import i18n from '../src/i18n/config'
import '../src/styles/global.css'

const requests: Array<{ type: string; data: Record<string, unknown> }> = []
const client = getSocketClient()
client.connect = () => {}
client.send = (type, data = {}) => { requests.push({ type, data }) }
Object.defineProperty(client, 'isConnected', { get: () => true })
Object.assign(window, { consentRequests: requests })
const { store } = await import('../src/store')
await i18n.changeLanguage('en')
store.dispatch(setConnected(true))
const project: AgentAppProject = {
  id: 'notes', name: 'Audio Notes', description: 'Fixture', path: '/fixture',
  status: 'running', createdAt: 0,
  triggerConsent: {
    revision: 'review-v1', required: true, needsReview: true,
    triggers: [{ name: 'summarize', description: 'Summarize a recording', instruction: 'Read the selected recording and prepare a summary.', change: 'new' }],
  },
}
if (new URLSearchParams(location.search).has('no-requests')) {
  project.triggerConsent = { revision: 'empty', required: false, needsReview: false, triggers: [] }
}
if (new URLSearchParams(location.search).has('many-requests')) {
  project.triggerConsent!.triggers = Array.from({ length: 30 }, (_, index) => ({
    name: `request_${index + 1}`, description: `QA request ${String(index + 1).padStart(2, '0')}`,
    instruction: `Instructions for request ${index + 1}. `.repeat(20), change: 'new',
  }))
}
const settingsPage = new URLSearchParams(location.search).has('settings')
if (settingsPage) {
  project.triggerConsent = { revision: 'review-v1', required: false, needsReview: false,
    triggers: [{ ...project.triggerConsent!.triggers[0], change: 'approved' }] }
  store.dispatch(setSettings({ backupOrphans: [], projects: [{
    id: 'notes', name: 'Audio Notes', status: 'stopped', port: null, backendPort: null, path: '/fixture',
    projectType: 'external', autoLaunch: false, logCleanup: false, backupsEnabled: false, backupInterval: 'daily', backupKeep: 7,
  }] }))
}
const otherProject: AgentAppProject = { ...project, id: 'calendar', name: 'Calendar',
  triggerConsent: { ...project.triggerConsent!, revision: 'calendar-v1', required: true,
    needsReview: new URLSearchParams(location.search).has('queued-apps') } }
store.dispatch(setProjects(new URLSearchParams(location.search).has('two-apps') ? [project, otherProject] : [project]))
window.addEventListener('fixture-response', event => {
  const message = (event as CustomEvent).detail
  // Settings tabs hear replies after the store applies them, as socket
  // frames do; deliver those through the socket client's inbound path.
  if (settingsPage) (client as unknown as { rawHandlers: Set<(msg: unknown) => void> }).rawHandlers.forEach(handler => handler(message))
  else dispatchInbound(message, store.dispatch, store.getState)
})
window.addEventListener('fixture-connected', event => {
  store.dispatch(setConnected((event as CustomEvent).detail))
})
function ModalFixture() {
  const [parent, setParent] = useState(false)
  const [child, setChild] = useState(false)
  const empty = new URLSearchParams(location.search).has('empty-modal')
  return <>
    <button onClick={() => setParent(true)}>Open parent</button>
    <Modal isOpen={parent} title="Parent dialog" onClose={() => setParent(false)} showCloseButton={!empty}>
      <ModalBody>
        <p>Parent content</p>
        {!empty && <button onClick={() => setChild(true)}>Open child</button>}
      </ModalBody>
    </Modal>
    <Modal isOpen={child} title="Child dialog" onClose={() => setChild(false)}>
      <ModalBody><button>Child action</button></ModalBody>
    </Modal>
  </>
}

createRoot(document.getElementById('root')!).render(new URLSearchParams(location.search).has('modal-test') ? <ModalFixture /> :
  <Provider store={store}>
    <ToastProvider>
    <p>The app is running in the background.</p>
    <button onClick={() => store.dispatch(openTriggerReview(project.id))}>Review requests again</button>
    <button onClick={() => store.dispatch(openTriggerReview(otherProject.id))}>Review other app</button>
    {settingsPage && <AgentAppSettings />}
    <AgentAppTriggerConsentModal />
    </ToastProvider>
  </Provider>,
)
