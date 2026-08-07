/** Minimal logger — no dependencies, ANSI only when stdout is a TTY. */

const tty = process.stdout.isTTY === true;
const paint = (code: string, s: string): string => (tty ? `\x1b[${code}m${s}\x1b[0m` : s);

export const log = {
  raw(msg: string): void {
    console.log(msg);
  },
  info(msg: string): void {
    console.log(`${paint('36', 'ℹ')} ${msg}`);
  },
  step(msg: string): void {
    console.log(`${paint('35', '▸')} ${msg}`);
  },
  ok(msg: string): void {
    console.log(`${paint('32', '✓')} ${msg}`);
  },
  warn(msg: string): void {
    console.warn(`${paint('33', '⚠')} ${msg}`);
  },
  error(msg: string): void {
    console.error(`${paint('31', '✗')} ${msg}`);
  },
};
