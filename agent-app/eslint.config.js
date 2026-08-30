import tseslint from 'typescript-eslint';

export default tseslint.config(
  { ignores: ['**/node_modules/**', '**/dist/**', '**/pb_public/**', '**/pb_data/**'] },
  ...tseslint.configs.recommended,
  {
    rules: {
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
      '@typescript-eslint/consistent-type-imports': 'error',
    },
  },
  {
    // PocketBase JSVM files: plain JS run by goja — triple-slash typing is the
    // official PB convention there (no module system available).
    files: ['**/pb_hooks/**/*.js', '**/pb_migrations/**/*.js'],
    rules: {
      '@typescript-eslint/triple-slash-reference': 'off',
      // require() is not a style choice here. Hook callbacks run in isolated
      // VMs that cannot see their own file's scope, so shared code is only
      // reachable via require() INSIDE each callback. ESM is unavailable.
      '@typescript-eslint/no-require-imports': 'off',
    },
  },
);
