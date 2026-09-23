---
name: skillui
description: |
  Reverse-engineer any website's, repo's, or local project's design system into a Claude-ready skill via the SkillUI CLI. Use this skill whenever the user wants to "match the look of <site>", "clone the design of", "extract the design system / brand / theme from", "make it look like Linear/Notion/Stripe", "pull the colors, fonts, and spacing from a website", or "build a UI in the style of" an existing product. It runs pure static analysis (no AI, no API keys) and outputs a folder of design tokens (colors, typography, spacing), bundled fonts, and a generated SKILL.md/DESIGN.md that a subsequent build step reads to reproduce the design. Pair it with agent-app-creator or frontend-design to then build the interface. Do NOT trigger for generic "make it pretty" requests with no reference source, backend work, or non-UI tasks.
allowed-tools:
  - Bash(npx skillui *)
  - Bash(npx -y skillui *)
  - Bash(skillui *)
  - Bash(npx playwright *)
---

# SkillUI — Design-System Extraction

Extract a complete design system (color tokens, typography, spacing, fonts, layout, components) from any live website, public Git repo, or local codebase, then use the generated tokens to build interfaces that match it. Pure static analysis: no AI calls, no API keys.

Run `npx -y skillui --help` for the full option list.

## When to use

Use this when the user wants new UI to look like an existing product or when they hand you a reference URL/repo. The typical flow is: **extract with SkillUI → hand the generated tokens to the builder** (`agent-app-creator` for Agent Apps, or `frontend-design` for standalone frontend). SkillUI produces the design language; the builder writes the code.

## Prerequisites

- Node.js 18+ (already required by this project's toolchain).
- No install step needed — invoke via `npx -y skillui ...`. For repeated use you may `npm install -g skillui`.
- **Ultra mode only** (screenshots, animation/interaction/component analysis) needs Playwright + Chromium:

```bash
npm install playwright
npx playwright install chromium
```

If Playwright is missing, stick to default mode — it still returns colors, fonts, spacing, and typography.

## Commands

```bash
npx -y skillui --url <url>      # Analyze a live website (default: HTML/CSS static analysis)
npx -y skillui --dir <path>     # Scan a local project (CSS/SCSS/TS/JS, Tailwind config, CSS vars)
npx -y skillui --repo <url>     # Clone a public Git repo, then analyze it as a directory
```

Common flags:

| Flag | Purpose |
| --- | --- |
| `--mode ultra` | Playwright-powered: scroll screenshots, interaction states, CSS animations, layout + component fingerprinting |
| `--screens <n>` | Pages to capture in ultra mode (max 20) |
| `--out <path>` | Output directory |
| `--name <string>` | Override the extracted project name |
| `--format design-md\|skill\|both` | Control output format (default `both`) |
| `--no-skill` | Emit only `DESIGN.md`, skip the packaged `.skill` |

Always quote URLs — the shell treats `?` and `&` as special characters.

### Examples

```bash
npx -y skillui --url "https://linear.app" --mode ultra --screens 10
npx -y skillui --url "https://stripe.com" --format design-md
npx -y skillui --dir ./my-nextjs-app --name "MyApp"
npx -y skillui --repo "https://github.com/vercel/next.js" --name "Next.js"
```

## Output

Extraction writes an organized folder (default `<name>-design/`):

- **`SKILL.md`** and **`CLAUDE.md`** — generated docs describing the design system for a subsequent build step.
- **`DESIGN.md`** — the full design-token reference (read this first).
- **`tokens/`** — JSON for `colors`, `spacing`, `typography`.
- **`fonts/`** — bundled Google Fonts as WOFF2.
- **`references/`** — `ANIMATIONS.md`, `LAYOUT.md`, `COMPONENTS.md`, `INTERACTIONS.md`, `VISUAL_GUIDE.md` (ultra mode).
- **`screens/`** — scroll-journey screenshots and section clips (ultra mode).
- **`.skill`** — a zipped bundle of the whole extraction.

## Workflow

1. Confirm the reference source (URL, repo, or local path). If the user only named a product, use its site URL.
2. Run the extraction. Prefer default mode for speed; use `--mode ultra` when the user cares about motion, interaction states, or pixel-accurate layout and Playwright is available.
3. Read `DESIGN.md` and `tokens/` to understand the palette, type scale, and spacing.
4. Build the requested UI with the appropriate builder skill (`agent-app-creator` / `frontend-design`), applying the extracted tokens (CSS variables, font families, spacing scale). Reference `references/` and `screens/` for component and layout fidelity.
5. Keep the generated `<name>-design/` folder out of the app's committed source unless the user wants it kept — treat it as an extraction artifact.
