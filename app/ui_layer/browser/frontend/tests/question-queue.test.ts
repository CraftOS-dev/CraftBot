import { test, expect, type Page } from '@playwright/test'

const question = (page: Page) => page.getByRole('region', { name: 'Question from agent' })
const resolved = (page: Page) => page.getByRole('status', { name: 'Resolved questions' })
const answer = (id: number, value = `choice-${id}`) => ({ id: `question-${id}`, value })

async function open(page: Page) {
  await page.goto('/tests/generative-ui.html?questions')
  await expect(question(page).getByText('Question 1?', { exact: true })).toBeVisible()
}

for (const count of [2, 3]) test(`${count} clicks cannot answer the next queued question`, async ({ page }) => {
  await open(page)
  await question(page).getByRole('button', { name: 'Choice 1 (recommended)', exact: true }).click({ clickCount: count })
  await expect(resolved(page)).toHaveText(JSON.stringify([answer(1)]))
  await expect(question(page).getByText('Question 2?', { exact: true })).toBeVisible()
  // A deliberate new click works immediately, without a cooldown timer.
  await question(page).getByRole('button', { name: 'Choice 2 (recommended)', exact: true }).click()
  await expect(resolved(page)).toHaveText(JSON.stringify([answer(1), answer(2)]))
  await expect(question(page).getByText('Question 3?', { exact: true })).toBeVisible()
})

test('double-clicking dismiss cannot dismiss the next question', async ({ page }) => {
  await open(page)
  await question(page).getByRole('button', { name: 'Dismiss question', exact: true }).dblclick()
  await expect(resolved(page)).toHaveText(JSON.stringify([answer(1, '__dismissed__')]))
  await expect(question(page).getByText('Question 2?', { exact: true })).toBeVisible()
  await question(page).getByRole('button', { name: 'Dismiss question', exact: true }).click()
  await expect(resolved(page)).toHaveText(JSON.stringify([answer(1, '__dismissed__'), answer(2, '__dismissed__')]))
})

test('double-clicking send cannot submit a saved draft for the next question', async ({ page }) => {
  await page.addInitScript(() => sessionStorage.setItem('craftbot.ui.chat.questionAnswerDraft.question-2', JSON.stringify('Unreviewed draft')))
  await open(page)
  await question(page).getByRole('textbox').fill('First answer')
  await question(page).getByRole('button', { name: 'Send answer', exact: true }).dblclick()
  await expect(resolved(page)).toHaveText(JSON.stringify([answer(1, 'First answer')]))
  await expect(question(page).getByRole('textbox')).toHaveValue('Unreviewed draft')
  await question(page).getByRole('button', { name: 'Send answer', exact: true }).click()
  await expect(resolved(page)).toHaveText(JSON.stringify([answer(1, 'First answer'), answer(2, 'Unreviewed draft')]))
})

test('keyboard Enter, Space and a typed answer each resolve only their own question', async ({ page }) => {
  await open(page)
  await question(page).getByRole('button', { name: 'Choice 1 (recommended)', exact: true }).press('Enter')
  await expect(resolved(page)).toHaveText(JSON.stringify([answer(1)]))
  await question(page).getByRole('button', { name: 'Choice 2 (recommended)', exact: true }).press('Space')
  await expect(resolved(page)).toHaveText(JSON.stringify([answer(1), answer(2)]))
  await question(page).getByRole('textbox').fill('Keyboard answer')
  await question(page).getByRole('textbox').press('Enter')
  await expect(resolved(page)).toHaveText(JSON.stringify([answer(1), answer(2), answer(3, 'Keyboard answer')]))
  await expect(question(page)).toHaveCount(0)
})
