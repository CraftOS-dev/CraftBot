/**
 * ESLint configuration (SYSTEM-MANAGED — do not edit)
 *
 * Deliberately minimal: the react-hooks rules catch the bug class the
 * TypeScript compiler cannot see (conditional hooks, stale-closure
 * dependency arrays -> runtime blank screens). Style is not linted —
 * tsc + these two rules are the deterministic safety net.
 */
module.exports = {
  root: true,
  parser: '@typescript-eslint/parser',
  parserOptions: { ecmaVersion: 2022, sourceType: 'module', ecmaFeatures: { jsx: true } },
  plugins: ['react-hooks'],
  rules: {
    'react-hooks/rules-of-hooks': 'error',
    'react-hooks/exhaustive-deps': 'warn',
  },
  ignorePatterns: ['dist', 'node_modules', '*.gen.ts'],
}
