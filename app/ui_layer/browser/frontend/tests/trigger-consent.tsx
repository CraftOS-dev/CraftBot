import React, { useState } from 'react'
import { createRoot } from 'react-dom/client'
import { Provider } from 'react-redux'
import { getSocketClient } from '../src/store/socket/socketInstance'
import { dispatchInbound } from '../src/store/socket/messageRegistry'
import { setConnected } from '../src/store/slices/connectionSlice'
import { openTriggerReview, setProjects } from '../src/store/slices/agentAppSlice'
import { AgentAppTriggerConsentModal } from '../src/components/ui/AgentAppTriggerConsentModal'
import { Modal, ModalBody } from '../src/components/ui/Modal'
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
store.dispatch(setProjects([project]))
window.addEventListener('fixture-response', event => {
  dispatchInbound((event as CustomEvent).detail, store.dispatch, store.getState)
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
    <p>The app is running in the background.</p>
    <button onClick={() => store.dispatch(openTriggerReview(project.id))}>Review requests again</button>
    <AgentAppTriggerConsentModal />
  </Provider>,
)
