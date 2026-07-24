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
    },
  },
);
