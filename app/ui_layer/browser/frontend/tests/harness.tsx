// Development-only fixture: exercises the real chat message and preview, without
// a model/provider or a live CraftBot database. Vite does not bundle it for release.
import React, { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { configureStore } from '@reduxjs/toolkit'
import { Provider } from 'react-redux'
import ui, { setUiState } from '../src/store/slices/uiSlice'
import agent from '../src/store/slices/agentSlice'
import messages from '../src/store/slices/messagesSlice'
import { UI_STATE, createUiPersistenceMiddleware, loadPersistedUiState } from '../src/store/uiState'
import { OutputWorkspace, type BrowserPanelMode, type PanelLayout } from '../src/components/GenerativeUI/OutputWorkspace'
import { QuestionBox } from '../src/components/Chat/QuestionBox'
import { ChatMessageItem } from '../src/pages/Chat/ChatMessage'
import type { GenerativeUIArtifact, ChatMessage } from '../src/types'
import i18n from '../src/i18n/config'
import '../src/styles/global.css'
import cooking from './fixtures/cooking.html?raw'
import weather from './fixtures/weather.html?raw'
import design from './fixtures/design.html?raw'

export const store = configureStore({ reducer: { ui, agent, messages }, preloadedState: { ui: loadPersistedUiState(), agent: { ...agent(undefined, { type: '@@init' }), profilePictureUrl: 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"%3E%3Ccircle cx="16" cy="16" r="14" fill="%23FF4F18"/%3E%3C/svg%3E' } }, middleware: getDefault => getDefault().concat(createUiPersistenceMiddleware()) })
const examples: Record<string, GenerativeUIArtifact> = {
  Cooking: { id: 'cooking', title: 'Cooking guide', html: cooking, revision: 1, connect_origins: [] },
  Weather: { id: 'weather', title: 'Weather explorer', html: weather, revision: 1, connect_origins: ['https://api.open-meteo.com', 'https://geocoding-api.open-meteo.com'] },
  Design: { id: 'design', title: 'Design playground', html: design, revision: 1, connect_origins: [] },
}
function Harness() {
  const [artifact, setArtifact] = useState<GenerativeUIArtifact | null>(() => new URLSearchParams(location.search).has('empty') ? null : examples.Cooking)
  const [visible, setVisible] = useState(true)
  const [messageVisible, setMessageVisible] = useState(true)
  const [history, setHistory] = useState<GenerativeUIArtifact[]>([])
  const [sessionId, setSessionId] = useState('demo')
  // A stand-in for the chat's own browser (the real one needs the backend).
  const [withBrowser, setWithBrowser] = useState(false)
  const browser: BrowserPanelMode | undefined = withBrowser ? {
    running: true,
    browsing: false,
    render: () => <div style={{ display: 'flex', flexDirection: 'column', height: '100%', padding: 10 }}>
      <strong>Fake browser</strong>
      <input aria-label="Fake page" />
    </div>,
  } : undefined
  // An Agent App's chat panel stacks the panel above the chat.
  const [layout, setLayout] = useState<PanelLayout>('side')
  // Revisions the user closed (the backend keeps only a marker for them).
  const [closedKeys, setClosedKeys] = useState<Set<string>>(new Set())
  useEffect(() => {
    const receive = (event: Event) => setArtifact((event as CustomEvent<GenerativeUIArtifact>).detail)
    const receiveHistory = (event: Event) => setHistory((event as CustomEvent<GenerativeUIArtifact[]>).detail)
    window.addEventListener('fixture-history', receiveHistory)
    const changeLanguage = (event: Event) => { void i18n.changeLanguage((event as CustomEvent<string>).detail) }
    window.addEventListener('fixture-artifact', receive)
    window.addEventListener('fixture-language', changeLanguage)
    return () => {
      window.removeEventListener('fixture-artifact', receive)
      window.removeEventListener('fixture-history', receiveHistory)
      window.removeEventListener('fixture-language', changeLanguage)
    }
  }, [])
  const artifacts = artifact ? [...history, artifact] : history
  const messages: ChatMessage[] = artifacts.map((item, index) => ({
    sender: 'CraftBot', content: item.title, style: 'agent', timestamp: index + 1, messageId: item.id + item.revision, sessionId,
    uiArtifact: closedKeys.has(`${item.id}:${item.revision}`)
      ? { id: item.id, title: item.title, revision: item.revision, closed: true as const }
      : item,
  }))
  const closeOutput = (id: string) => setClosedKeys(keys => new Set([
    ...keys,
    ...artifacts.filter(item => item.id === id).map(item => `${item.id}:${item.revision}`),
  ]))
  return <main style={{ width: '100%', height: '100dvh', display: 'flex', flexDirection: 'column', minHeight: 0, fontFamily: 'system-ui', color: 'var(--text-primary)' }}>
    <p style={{ color: 'var(--text-secondary)', fontSize: 12, textTransform: 'uppercase', letterSpacing: '.1em' }}>CraftBot · development preview</p>
    <h1 style={{ fontSize: 20, margin: '10px 0' }}>An answer you can use.</h1>
    <p>Explore three frontend-only answers. Every control runs in the preview.</p>
    <nav style={{ padding: '0 16px', display: 'flex', flexWrap: 'wrap', gap: 8, margin: '12px 0' }}>
      {Object.entries(examples).map(([name, value]) => <button key={name} onClick={() => setArtifact(value)}>{name}</button>)}
      <button onClick={() => setVisible(value => !value)}>{visible ? 'Leave preview' : 'Return to preview'}</button>
      <button onClick={() => setMessageVisible(value => !value)}>{messageVisible ? 'Hide message' : 'Show message'}</button>
      <button onClick={() => setSessionId(value => value === 'demo' ? 'other' : 'demo')}>Switch session</button>
      <button disabled={!artifact} onClick={() => setArtifact(value => value && ({ ...value, revision: value.revision + 1 }))}>Revise interface</button>
      <button onClick={() => setWithBrowser(value => !value)}>{withBrowser ? 'Remove browser' : 'Add browser'}</button>
      <button onClick={() => store.dispatch(setUiState(UI_STATE.chat.panelMode(sessionId), 'browser'))}>Agent starts browsing</button>
      <button onClick={() => setLayout(value => value === 'side' ? 'stacked' : 'side')}>{layout === 'side' ? 'Stack panel' : 'Panel beside chat'}</button>
    </nav>
    <div style={{ flex: 1, minHeight: 0 }}>
      {visible && <OutputWorkspace messages={messages} sessionId={sessionId} browser={browser} layout={layout} onCloseOutput={closeOutput}><div style={{ padding: 18 }}>{messageVisible && messages.map(message => <ChatMessageItem key={message.messageId} message={message} onOpenFile={() => {}} onOpenFolder={() => {}} />)}</div></OutputWorkspace>}
    </div>
  </main>
}
// Match the real chat's keyed question replacement: a resolved question
// immediately reveals the next one at the same place.
function QuestionHarness() {
  const [resolved, setResolved] = useState<{ id: string; value: string }[]>([])
  const index = resolved.length + 1
  const question: ChatMessage = {
    messageId: `question-${index}`, sessionId: 'demo', sender: 'CraftBot',
    content: `Question ${index}?`, timestamp: index, style: 'agent', isQuestion: true,
    options: [{ label: `Choice ${index}`, value: `choice-${index}` }],
  }
  const answer = (value: string) => setResolved(items => [...items, { id: question.messageId, value }])
  return <main style={{ width: 600, padding: 20 }}>
    {index <= 3 && <QuestionBox key={question.messageId} question={question} queueTotal={4 - index} onAnswer={answer} onDismiss={() => answer('__dismissed__')} />}
    <output aria-label="Resolved questions">{JSON.stringify(resolved)}</output>
  </main>
}
createRoot(document.getElementById('root')!).render(<Provider store={store}>{new URLSearchParams(location.search).has('questions') ? <QuestionHarness /> : <Harness />}</Provider>)
