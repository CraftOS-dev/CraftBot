// Exercise the real settings/onboarding screens with an isolated saved login.
import React from 'react'
import { createRoot } from 'react-dom/client'
import { Provider } from 'react-redux'
import { MemoryRouter } from 'react-router-dom'
import { getSocketClient } from '../src/store/socket/socketInstance'
import { dispatchInbound } from '../src/store/socket/messageRegistry'
import { setConnected } from '../src/store/slices/connectionSlice'
import { setProviders, setSettings, setSlowModeEnabled, setSubscriptionStatus } from '../src/store/slices/modelSettingsSlice'
import { setStep } from '../src/store/slices/onboardingSlice'
import { ToastProvider } from '../src/contexts/ToastContext'
import { WebSocketProvider } from '../src/contexts/WebSocketContext'
import { ModelSettings } from '../src/pages/Settings/ModelSettings'
import { OnboardingPage } from '../src/pages/Onboarding/OnboardingPage'
import i18n from '../src/i18n/config'
import '../src/styles/global.css'

const requests: Array<{ type: string; data: Record<string, unknown> }> = []
const client = getSocketClient()
client.connect = () => {}
client.send = (type, data = {}) => { requests.push({ type, data }) }
Object.defineProperty(client, 'isConnected', { get: () => true })
Object.assign(window, { subscriptionRequests: requests })
// Bootstrap after substituting the transport so no real backend is contacted.
const { store } = await import('../src/store')
await i18n.changeLanguage('en')
store.dispatch(setConnected(true))
store.dispatch(setProviders([{
  id: 'anthropic', name: 'Anthropic', requires_api_key: true,
  llm_model: 'claude-sonnet-4-6', vlm_model: 'claude-sonnet-4-6', has_vlm: true,
  image_gen_model: null, video_gen_model: null, has_image_gen: false, has_video_gen: false,
  supports_subscription_oauth: true, subscription_label: 'Sign in with Claude',
}]))
store.dispatch(setSettings({
  provider: 'anthropic', imageGenProvider: 'openai', videoGenProvider: 'gemini',
  llmModel: 'claude-sonnet-4-6', vlmModel: 'claude-sonnet-4-6', imageGenModel: '', videoGenModel: '',
  apiKeys: { anthropic: { has_key: true, masked_key: 'fake...key' } }, baseUrls: {},
}))
store.dispatch(setSlowModeEnabled(false))
store.dispatch(setSubscriptionStatus({ provider: 'anthropic', status: {
  supported: true, configured: true, connected: false, error: 'Claude login needs recovery.',
} }))
store.dispatch(setStep({
  name: 'api_key', title: 'Connect Claude', description: 'Sign in or use an API key.',
  required: true, index: 2, total: 5, options: [], default: '', provider: 'anthropic',
  supports_subscription_oauth: true, subscription_label: 'Sign in with Claude',
}))
window.addEventListener('fixture-response', event => {
  dispatchInbound((event as CustomEvent).detail, store.dispatch, store.getState)
})
const onboarding = new URLSearchParams(location.search).get('screen') === 'onboarding'
createRoot(document.getElementById('root')!).render(
  <Provider store={store}><MemoryRouter><ToastProvider><WebSocketProvider>
    {onboarding ? <OnboardingPage /> : <ModelSettings />}
  </WebSocketProvider></ToastProvider></MemoryRouter></Provider>,
)
