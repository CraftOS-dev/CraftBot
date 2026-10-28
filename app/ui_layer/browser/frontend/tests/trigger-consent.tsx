import React from 'react'
import { createRoot } from 'react-dom/client'
import { Provider } from 'react-redux'
import { getSocketClient } from '../src/store/socket/socketInstance'
import { dispatchInbound } from '../src/store/socket/messageRegistry'
import { setConnected } from '../src/store/slices/connectionSlice'
import { openTriggerReview, setProjects } from '../src/store/slices/agentAppSlice'
import { AgentAppTriggerConsentModal } from '../src/components/ui/AgentAppTriggerConsentModal'
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
store.dispatch(setProjects([project]))
window.addEventListener('fixture-response', event => {
  dispatchInbound((event as CustomEvent).detail, store.dispatch, store.getState)
})
window.addEventListener('fixture-connected', event => {
  store.dispatch(setConnected((event as CustomEvent).detail))
})
createRoot(document.getElementById('root')!).render(
  <Provider store={store}>
    <p>The app is running in the background.</p>
    <button onClick={() => store.dispatch(openTriggerReview(project.id))}>Review requests again</button>
    <AgentAppTriggerConsentModal />
  </Provider>,
)
