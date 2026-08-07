/**
 * Theme bridge (spec K3) — host-owned theming with a standalone fallback.
 *
 * Inside CraftBot: listens for `livingui-theme` postMessage
 *   { type: 'livingui-theme', themeId, mode: 'light'|'dark', customColors? }
 * and announces readiness with `craftbot-theme-request` so the host replays.
 *
 * Standalone (no embedding host): follows the system color scheme.
 *
 * All theming lands as attributes/custom properties on <html>; components only
 * ever read design tokens (no hardcoded colors anywhere in the kit).
 */

export type ThemeMode = 'light' | 'dark';

interface HostThemeMessage {
  type: 'livingui-theme';
  themeId?: string;
  mode?: ThemeMode;
  customColors?: Partial<Record<'bg' | 'surface' | 'text' | 'accent', string>>;
}

const CUSTOM_PROP_MAP: Record<string, string> = {
  bg: '--lui-bg',
  surface: '--lui-surface',
  text: '--lui-text',
  accent: '--lui-accent',
};

export class ThemeBridge {
  private detach: Array<() => void> = [];
  private hostControlled = false;

  start(): void {
    const onMessage = (event: MessageEvent<unknown>): void => {
      const data = event.data as HostThemeMessage | null;
      if (data === null || typeof data !== 'object' || data.type !== 'livingui-theme') return;
      this.hostControlled = true;
      this.apply(data);
    };
    window.addEventListener('message', onMessage);
    this.detach.push(() => window.removeEventListener('message', onMessage));

    // Standalone fallback: system preference, live-updating — until a host speaks.
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    const onSystem = (): void => {
      if (!this.hostControlled) this.setMode(media.matches ? 'dark' : 'light');
    };
    onSystem();
    media.addEventListener('change', onSystem);
    this.detach.push(() => media.removeEventListener('change', onSystem));

    // Ask the host (if any) to replay its theme.
    if (window.parent !== window) {
      window.parent.postMessage({ type: 'craftbot-theme-request' }, '*');
    }
  }

  stop(): void {
    for (const fn of this.detach) fn();
    this.detach = [];
  }

  private apply(msg: HostThemeMessage): void {
    if (msg.mode !== undefined) this.setMode(msg.mode);
    if (msg.themeId !== undefined) {
      document.documentElement.setAttribute('data-style', msg.themeId);
    }
    const root = document.documentElement;
    for (const [key, prop] of Object.entries(CUSTOM_PROP_MAP)) {
      const value = msg.customColors?.[key as keyof NonNullable<HostThemeMessage['customColors']>];
      if (typeof value === 'string') root.style.setProperty(prop, value);
      else root.style.removeProperty(prop);
    }
  }

  private setMode(mode: ThemeMode): void {
    document.documentElement.setAttribute('data-theme', mode);
  }
}
