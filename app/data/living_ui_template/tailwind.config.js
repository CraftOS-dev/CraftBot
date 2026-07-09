/**
 * Tailwind configuration (SYSTEM-MANAGED — do not edit)
 *
 * Utilities-only integration: preflight (the CSS reset) is DISABLED so
 * Tailwind never fights the preset component library or the Layout Kit —
 * they own structure; Tailwind styles component INTERNALS.
 *
 * Every color maps to the design tokens in frontend/styles/global.css, so
 * `bg-primary`, `text-secondary`, `border-primary`, `bg-surface` etc.
 * automatically follow the CraftBot theme (including live theme switches,
 * since the tokens are CSS variables).
 */

/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './frontend/**/*.{ts,tsx}'],
  corePlugins: {
    preflight: false,
  },
  theme: {
    extend: {
      colors: {
        primary: {
          DEFAULT: 'var(--color-primary)',
          hover: 'var(--color-primary-hover)',
          light: 'var(--color-primary-light)',
          subtle: 'var(--color-primary-subtle)',
        },
        success: {
          DEFAULT: 'var(--color-success)',
          light: 'var(--color-success-light)',
        },
        warning: {
          DEFAULT: 'var(--color-warning)',
          light: 'var(--color-warning-light)',
        },
        error: {
          DEFAULT: 'var(--color-error)',
          light: 'var(--color-error-light)',
        },
        info: {
          DEFAULT: 'var(--color-info)',
          light: 'var(--color-info-light)',
        },
        // Surfaces + text + borders follow the active theme's tokens
        page: 'var(--bg-primary)',
        surface: 'var(--bg-secondary)',
        raised: 'var(--bg-tertiary)',
        ink: {
          DEFAULT: 'var(--text-primary)',
          secondary: 'var(--text-secondary)',
          muted: 'var(--text-muted)',
        },
        line: 'var(--border-primary)',
      },
      borderRadius: {
        token: 'var(--radius-md)',
      },
      fontFamily: {
        app: 'var(--font-sans)',
      },
    },
  },
  plugins: [],
}
