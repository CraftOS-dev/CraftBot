/** Locale catalogs bundled by build.mjs: language -> namespace -> strings. */
declare module 'virtual:locales' {
  const catalogs: Record<string, Record<string, Record<string, unknown>>>
  export default catalogs
}

/**
 * The shared browser store is written for Vite. The build defines
 * `import.meta.env` and swaps the one module that uses `import.meta.glob`;
 * these declarations let the type checker read those files as they are.
 */
interface ImportMeta {
  readonly env: Record<string, string | undefined>
  glob<T = unknown>(pattern: string, options?: { eager?: boolean; import?: string }): Record<string, T>
}
