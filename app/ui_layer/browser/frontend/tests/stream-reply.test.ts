import { test, expect, type Page } from '@playwright/test'

// A decision reply streamed by the backend (agent_stream) shows as it is
// written, inside the run's work block (collapsed unless the user opened
// it), and the real rows and message take its place without a duplicate,
// without remounting, and without the bubble ever changing width.

const S = 'dest'
const R = 'dest:reasoning:r1'
const A1 = 'run-search'
const M1 = 'run-reply'
const START = Date.now()
const LONG = 'The forecast for Tokyo today is sunny with light winds from the south and a high of twenty one degrees, '
  + 'with clear skies continuing into the evening and a low of fourteen degrees overnight.'

async function open(page: Page) {
  await page.goto('/tests/stream-reply.html')
  await page.waitForFunction(() => typeof (window as unknown as { fixtureReceive?: unknown }).fixtureReceive === 'function')
}

async function send(page: Page, type: string, data: Record<string, unknown>) {
  await page.evaluate(([type, data]) => {
    (window as unknown as { fixtureReceive: (e: unknown) => void }).fixtureReceive({ type, data })
  }, [type, data] as const)
}

function update(body: Record<string, unknown>, attempt = 1) {
  return {
    sessionId: S, streamId: 'stream-1', attempt, sender: 'Agent', startedAt: START,
    phase: 'update', reasoning: null, actions: [], messages: [], ...body,
  }
}

async function start(page: Page) {
  await open(page)
  await send(page, 'session_busy', { sessionId: S, busy: true, state: 'running' })
  await send(page, 'chat_message', {
    sender: 'You', content: 'What is the weather in Tokyo?', style: 'user',
    timestamp: START / 1000 - 1, messageId: 'u1', sessionId: S,
  })
}

// Timeline rows only (a bubble still being measured is laid out invisibly
// outside them).
const row = (page: Page, text: string) => page.locator('[data-index]').filter({ hasText: text })
const working = (page: Page) => page.getByRole('status', { name: 'Agent is working' })
const chunkHeader = (page: Page) => page.getByRole('button', { name: /Working|action executed|actions executed/ })
const settle = (page: Page) => page.waitForTimeout(150)

test('the first step after a bubble stays collapsed: only "Working" shows', async ({ page }) => {
  await start(page)
  await send(page, 'agent_stream', update({
    reasoning: { id: R, text: 'Checking the forecast first.', done: true },
    actions: [{ id: A1, name: 'web_search', input: '{"query": "Tokyo weather"}', done: false }],
  }))
  await settle(page)
  await expect(working(page)).toBeVisible()
  await expect(page.getByText('Checking the forecast first.')).toHaveCount(0)
  await expect(page.getByText('Web search')).toHaveCount(0)

  // It starts: the collapsed block's header carries the state; nothing of
  // the step appears and then vanishes.
  await send(page, 'action_add', { id: R, name: 'Reasoning', status: 'completed', itemType: 'reasoning', sessionId: S, createdAt: START + 100, output: 'Checking the forecast first.' })
  await send(page, 'action_add', { id: A1, name: 'Web search', status: 'running', itemType: 'action', sessionId: S, createdAt: START + 200, input: '{"query": "Tokyo weather"}' })
  await settle(page)
  await expect(chunkHeader(page)).toHaveAttribute('aria-expanded', 'false')
  await expect(page.getByText('Checking the forecast first.')).toHaveCount(0)
  await expect(page.getByText('Web search')).toHaveCount(0)
})

test('a quick reply never shows its reasoning and then takes it away', async ({ page }) => {
  await start(page)
  for (const text of ['Simple question,', 'Simple question, answer directly.']) {
    await send(page, 'agent_stream', update({ reasoning: { id: R, text, done: false } }))
    await settle(page)
    await expect(page.getByText('Simple question')).toHaveCount(0)
  }
  await send(page, 'agent_stream', update({
    reasoning: { id: R, text: 'Simple question, answer directly.', done: true },
    messages: [{ id: M1, text: 'Hi! How can I help?', continueWork: false, done: true }],
  }))
  await expect(page.getByText('Hi! How can I help?')).toHaveCount(1)
  await expect(page.getByText('Simple question')).toHaveCount(0)
})

test('an open work block shows the step being written below its rows', async ({ page }) => {
  await start(page)
  // An earlier step of this run made the work block; the user opens it.
  await send(page, 'action_add', { id: 'run-0', name: 'Read file', status: 'completed', itemType: 'action', sessionId: S, createdAt: START - 500, input: '{"file_path": "notes.md"}' })
  await chunkHeader(page).click()
  await expect(chunkHeader(page)).toHaveAttribute('aria-expanded', 'true')

  await send(page, 'agent_stream', update({ reasoning: { id: R, text: 'Now the forecast', done: false } }))
  await expect(page.getByText('Now the forecast')).toBeVisible()
  await send(page, 'agent_stream', update({
    reasoning: { id: R, text: 'Now the forecast.', done: true },
    actions: [{ id: A1, name: 'web_search', input: '{"query": "Tokyo weather"}', done: false }],
  }))
  await expect(page.getByText('Tokyo weather')).toBeVisible()

  // The real rows take over in place: each shows once, nothing vanishes.
  await send(page, 'action_add', { id: R, name: 'Reasoning', status: 'completed', itemType: 'reasoning', sessionId: S, createdAt: START + 100, output: 'Now the forecast.' })
  await send(page, 'action_add', { id: A1, name: 'Web search', status: 'running', itemType: 'action', sessionId: S, createdAt: START + 200, input: '{"query": "Tokyo weather"}' })
  await settle(page)
  await expect(page.getByText('Now the forecast.')).toHaveCount(1)
  await expect(page.getByText('Tokyo weather')).toHaveCount(1)
})

test('the reply bubble appears at its final width and only grows downward', async ({ page }) => {
  await start(page)
  // A first line shorter than the widest bubble: not shown yet.
  await send(page, 'agent_stream', update({ messages: [{ id: M1, text: 'The forecast for', continueWork: false, done: false }] }))
  await settle(page)
  await expect(row(page, 'The forecast for')).toHaveCount(0)
  await expect(working(page)).toBeVisible()

  // Wide enough: it shows, at the width it keeps.
  const widths: number[] = []
  const bubble = page.locator('[data-index]').filter({ hasText: 'The forecast for Tokyo' })
  for (const end of [LONG.length * 0.6, LONG.length * 0.8, LONG.length].map(Math.round)) {
    await send(page, 'agent_stream', update({ messages: [{ id: M1, text: LONG.slice(0, end), continueWork: false, done: end === LONG.length }] }))
    await expect(bubble).toHaveCount(1)
    widths.push((await bubble.locator('[class*="messageWrapper"]').boundingBox())!.width)
  }
  await bubble.evaluate(el => el.setAttribute('data-probe', 'draft'))
  await send(page, 'agent_stream', { ...update({}), phase: 'end', keep: [M1] })
  await send(page, 'chat_message', {
    sender: 'Agent', content: LONG, style: 'agent',
    timestamp: START / 1000 + 3, messageId: 'agent:real', sessionId: S, clientId: M1,
  })
  await send(page, 'session_busy', { sessionId: S, busy: false, state: 'idle' })
  await settle(page)
  await expect(page.getByText(LONG)).toHaveCount(1)
  await expect(page.locator('[data-probe="draft"]')).toContainText(LONG)
  widths.push((await page.locator('[data-probe="draft"] [class*="messageWrapper"]').boundingBox())!.width)
  expect(new Set(widths).size).toBe(1)
  // The bubble's own width (the widest a bubble gets), not the whole row's.
  const rowWidth = (await page.locator('[data-probe="draft"]').boundingBox())!.width
  expect(widths[0]).toBeLessThan(rowWidth * 0.85)
})

test('a reply still being written fades at the bottom until it is complete', async ({ page }) => {
  await start(page)
  await send(page, 'agent_stream', update({ messages: [{ id: M1, text: LONG.slice(0, 140), continueWork: false, done: false }] }))
  // The whole bubble (text, background and border) fades at the bottom.
  const bubble = row(page, 'The forecast for Tokyo').locator('[class*="messageContent"]').locator('..')
  const fade = () => bubble.evaluate(el => getComputedStyle(el).getPropertyValue('--stream-fade').trim())
  await expect.poll(fade).toBe('36px')
  await send(page, 'agent_stream', update({ messages: [{ id: M1, text: LONG, continueWork: false, done: true }] }))
  await expect.poll(fade).toBe('0px')
})

test('scrolling up while a reply streams stays where the user scrolled', async ({ page }) => {
  await page.setViewportSize({ width: 900, height: 480 })
  await start(page)
  const words = (LONG + ' ').repeat(24).split(' ')
  let n = 40
  const stream = async (steps: number) => {
    for (let i = 0; i < steps; i++, n += 6) {
      await send(page, 'agent_stream', update({ messages: [{ id: M1, text: words.slice(0, n).join(' '), continueWork: false, done: false }] }))
      await page.waitForTimeout(60)
    }
  }
  await stream(40) // the reply overflows the view; the chat follows the bottom
  const container = page.locator('[class*="messagesContainer"]')
  const distFromBottom = () => container.evaluate(el => el.scrollHeight - el.scrollTop - el.clientHeight)
  expect(await distFromBottom()).toBeLessThan(2)
  expect(await container.evaluate(el => el.scrollHeight - el.clientHeight)).toBeGreaterThan(200)

  // A small wheel-up while it keeps streaming: the view must stay up.
  await container.hover()
  await page.mouse.wheel(0, -60)
  await page.waitForTimeout(250)
  const scrolledTo = await container.evaluate(el => el.scrollTop)
  await stream(12)
  expect(await container.evaluate(el => el.scrollTop)).toBeLessThanOrEqual(scrolledTo + 1)
  expect(await distFromBottom()).toBeGreaterThan(40)

  // Back to the bottom: it follows again.
  await page.mouse.wheel(0, 4000)
  await page.waitForTimeout(250)
  await stream(6)
  expect(await distFromBottom()).toBeLessThan(2)
})

test('a short reply appears whole once complete', async ({ page }) => {
  await start(page)
  await send(page, 'agent_stream', update({ messages: [{ id: M1, text: 'Sure', continueWork: false, done: false }] }))
  await settle(page)
  await expect(row(page, 'Sure')).toHaveCount(0)
  await send(page, 'agent_stream', update({ messages: [{ id: M1, text: 'Sure, done.', continueWork: false, done: true }] }))
  await expect(page.getByText('Sure, done.')).toHaveCount(1)
})

test('a retried reply replaces what the failed one showed', async ({ page }) => {
  await start(page)
  await send(page, 'agent_stream', update({
    messages: [{ id: 'm-first', text: 'Draft that failed to parse', continueWork: false, done: true }],
  }))
  await expect(page.getByText('Draft that failed to parse')).toHaveCount(1)
  await send(page, 'agent_stream', update({ reasoning: { id: 'dest:reasoning:r2', text: 'Second try', done: false } }, 2))
  await expect(page.getByText('Draft that failed to parse')).toHaveCount(0)
})

test('a message that is not sent leaves no bubble behind', async ({ page }) => {
  await start(page)
  await send(page, 'agent_stream', update({
    messages: [{ id: 'm-drop', text: 'Will be dropped', continueWork: false, done: true }],
  }))
  await expect(page.getByText('Will be dropped')).toHaveCount(1)
  await send(page, 'agent_stream', { ...update({}), phase: 'end', keep: [] })
  await expect(page.getByText('Will be dropped')).toHaveCount(0)
})
