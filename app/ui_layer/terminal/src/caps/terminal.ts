/**
 * What the terminal in front of us can do, decided once at startup from the
 * environment. Conservative: a feature is used only where the terminal is
 * known to support it, never guessed from a partial match.
 */
import { platform } from 'node:os'

export interface TerminalCaps {
  /** Terminal name for diagnostics. */
  name: string
  /** OSC 8 clickable links. */
  hyperlinks: boolean
  /** Shift+Enter arrives distinctly (kitty keyboard / modifyOtherKeys). */
  shiftEnter: boolean
  /** OSC 9 desktop notifications. */
  notifications: boolean
  /** OSC 9;4 progress in the tab and taskbar (Windows Terminal). */
  progress: boolean
  /** The legacy Windows console host: no synchronized output, no paste brackets. */
  legacyConsole: boolean
  /**
   * The terminal draws characters its font lacks from another font. Without
   * it (the classic Windows console, and any Windows terminal not known to
   * have it) a missing character is a box with a question mark.
   */
  fontFallback: boolean
  /** Running inside tmux or screen. */
  multiplexer: boolean
}

function detect(env: NodeJS.ProcessEnv): TerminalCaps {
  const program = env.TERM_PROGRAM ?? ''
  const windowsTerminal = !!env.WT_SESSION
  const vscode = program === 'vscode'
  const iterm = program === 'iTerm.app'
  const wezterm = program === 'WezTerm'
  const ghostty = program === 'ghostty' || !!env.GHOSTTY_RESOURCES_DIR
  const kitty = !!env.KITTY_WINDOW_ID || env.TERM === 'xterm-kitty'
  const vte = Number(env.VTE_VERSION ?? 0) >= 5000
  const multiplexer = !!env.TMUX || (env.TERM ?? '').startsWith('screen')
  const isWindows = platform() === 'win32'
  const legacyConsole = isWindows && !windowsTerminal && !vscode && !wezterm && !env.ConEmuANSI
  const mintty = program === 'mintty'
  const fontFallback = !isWindows || windowsTerminal || vscode || wezterm || mintty

  const name = windowsTerminal
    ? 'Windows Terminal'
    : vscode
      ? 'VS Code'
      : iterm
        ? 'iTerm2'
        : wezterm
          ? 'WezTerm'
          : ghostty
            ? 'Ghostty'
            : kitty
              ? 'kitty'
              : legacyConsole
                ? 'Windows Console'
                : program || env.TERM || 'terminal'

  return {
    name,
    hyperlinks: !multiplexer && (windowsTerminal || vscode || iterm || wezterm || ghostty || kitty || vte),
    shiftEnter: windowsTerminal || vscode || kitty || ghostty || wezterm,
    notifications: windowsTerminal || iterm || wezterm || ghostty || kitty,
    progress: windowsTerminal,
    legacyConsole,
    fontFallback,
    multiplexer,
  }
}

let caps: TerminalCaps | null = null

export function terminalCaps(): TerminalCaps {
  if (!caps) caps = detect(process.env)
  return caps
}

/** An OSC 8 hyperlink where supported, else the plain label. */
export function hyperlink(label: string, url: string): string {
  if (!terminalCaps().hyperlinks) return label
  return `\u001B]8;;${url}\u0007${label}\u001B]8;;\u0007`
}

/** Ring the bell / raise a desktop notification for something that needs the user. */
export function notify(title: string, body: string): void {
  if (!process.stdout.isTTY) return
  if (terminalCaps().notifications) {
    process.stdout.write(`\u001B]9;${title}: ${body}\u0007`)
  } else {
    process.stdout.write('\u0007')
  }
}

/** Windows Terminal tab/taskbar progress: indeterminate while busy, cleared when idle. */
export function setBusyProgress(busy: boolean): void {
  if (!process.stdout.isTTY || !terminalCaps().progress) return
  process.stdout.write(busy ? '\u001B]9;4;3;0\u0007' : '\u001B]9;4;0;0\u0007')
}

export function setTitle(title: string): void {
  if (!process.stdout.isTTY) return
  process.stdout.write(`\u001B]0;${title.replace(/[\u0000-\u001F]/g, '')}\u0007`)
}
