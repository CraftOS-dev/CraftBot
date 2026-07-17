/**
 * Tailwind configuration (SYSTEM-MANAGED — do not edit)
 *
 * Utilities-only integration: preflight (the CSS reset) is DISABLED so
 * Tailwind never fights the base styles in global.css — they own
 * structure; Tailwind styles component INTERNALS.
 *
 * The color names follow the shadcn/ui convention (background, foreground,
 * card, primary, muted, accent, destructive, border, input, ring, ...) and
 * every one maps to the design tokens in frontend/styles/global.css +
 * themes.css — so `bg-primary`, `text-muted-foreground`, `border-border`
 * etc. automatically follow the CraftBot theme AND the active style pack,
 * including live switches (the tokens are CSS variables).
 *
 * NOTE on opacity modifiers: the semantic colors resolve to CSS variables,
 * so `/50`-style alpha suffixes do NOT apply to them (use the provided
 * -hover/-subtle shades, or a palette color like `bg-indigo-500/20`).
 */

import animate from 'tailwindcss-animate'

/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './frontend/**/*.{ts,tsx}'],
  corePlugins: {
    preflight: false,
  },
  darkMode: ['selector', '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        // ── shadcn/ui semantic names → CraftBot theme tokens ──────────
        border: 'var(--border-primary)',
        input: 'var(--border-primary)',
        ring: 'var(--color-primary)',
        background: 'var(--bg-primary)',
        foreground: 'var(--text-primary)',
        primary: {
          DEFAULT: 'var(--color-primary)',
          foreground: 'var(--color-primary-foreground)',
          hover: 'var(--color-primary-hover)',
          light: 'var(--color-primary-light)',
          subtle: 'var(--color-primary-subtle)',
        },
        secondary: {
          DEFAULT: 'var(--bg-tertiary)',
          foreground: 'var(--text-primary)',
          hover: 'var(--bg-hover)',
        },
        destructive: {
          DEFAULT: 'var(--color-error)',
          foreground: 'var(--color-primary-foreground)',
          hover: 'var(--color-error-hover)',
        },
        muted: {
          DEFAULT: 'var(--bg-tertiary)',
          foreground: 'var(--text-muted)',
          subtle: 'var(--bg-hover)',
        },
        accent: {
          DEFAULT: 'var(--bg-hover)',
          foreground: 'var(--text-primary)',
        },
        popover: {
          DEFAULT: 'var(--bg-secondary)',
          foreground: 'var(--text-primary)',
        },
        card: {
          DEFAULT: 'var(--bg-secondary)',
          foreground: 'var(--text-primary)',
        },
        // ── semantic status colors (platform composites + app code) ───
        success: {
          DEFAULT: 'var(--color-success)',
          light: 'var(--color-success-light)',
        },
        warning: {
          DEFAULT: 'var(--color-warning)',
          light: 'var(--color-warning-light)',
        },
        info: {
          DEFAULT: 'var(--color-info)',
          light: 'var(--color-info-light)',
        },
        // ── legacy token classes (platform layout/composites) ─────────
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
        // Token-driven shape: style packs restyle every rounded-* corner.
        sm: 'var(--radius-sm)',
        md: 'var(--radius-md)',
        lg: 'var(--radius-lg)',
        xl: 'var(--radius-xl)',
        token: 'var(--radius-md)',
      },
      fontFamily: {
        app: 'var(--font-sans)',
      },
      keyframes: {
        'accordion-down': {
          from: { height: '0' },
          to: { height: 'var(--radix-accordion-content-height)' },
        },
        'accordion-up': {
          from: { height: 'var(--radix-accordion-content-height)' },
          to: { height: '0' },
        },
      },
      animation: {
        'accordion-down': 'accordion-down 0.2s ease-out',
        'accordion-up': 'accordion-up 0.2s ease-out',
      },
    },
  },
  plugins: [animate],
}
