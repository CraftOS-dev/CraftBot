import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  testMatch: '**/*.test.ts',
  fullyParallel: true,
  use: { baseURL: 'http://127.0.0.1:7935', headless: true, trace: 'retain-on-failure' },
  webServer: { command: 'npm run dev -- --host 127.0.0.1 --port 7935', url: 'http://127.0.0.1:7935/tests/generative-ui.html', reuseExistingServer: !process.env.CI },
})
