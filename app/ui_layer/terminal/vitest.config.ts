import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    include: ['test/unit/**/*.test.ts'],
    environment: 'node',
    // Glyphs follow the terminal; tests pin the modern set (and switch per test).
    env: { CRAFTBOT_GLYPHS: 'modern' },
  },
})
