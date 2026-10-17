// What a download notice may offer.
//
// A web page can start a download without any click, so neither the name the
// toast shows nor the buttons it offers may be the page's to choose:
//   - names are shown without bidirectional/invisible format controls, so
//     "invoice‮fdp.exe" can never pose as "invoiceexe.pdf";
//   - a type that can run code on this computer is "dangerous" when the
//     backend says so OR its extension is on the list below (defence in
//     depth): the toast warns and offers only "Show in folder";
//   - "Open" (the file's default program) is offered only for inert types:
//     documents, pictures, plain text and media. A list of what is safe
//     cannot miss a new executable format the way a list of what is
//     dangerous can.

/** Bidi and format controls that reorder or hide characters of a name. */
const FORMAT_CONTROLS = /[؜‎‏‪-‮⁦-⁩]/g

/** Types that run code (or install, mount or configure something) when opened. */
const DANGEROUS_EXTENSIONS = new Set([
  // Windows programs, installers, scripts, shortcuts and system files
  'exe', 'com', 'scr', 'pif', 'cpl', 'msi', 'msp', 'mst', 'msix', 'msixbundle', 'appx', 'appxbundle',
  'appinstaller', 'application', 'appref-ms', 'gadget', 'bat', 'cmd', 'ps1', 'ps1xml', 'ps2', 'ps2xml',
  'psc1', 'psc2', 'psd1', 'psm1', 'vb', 'vbs', 'vbe', 'js', 'jse', 'ws', 'wsf', 'wsh', 'wsc', 'sct',
  'hta', 'jar', 'jnlp', 'lnk', 'url', 'website', 'scf', 'reg', 'inf', 'ins', 'isp', 'msc', 'chm', 'hlp',
  'dll', 'ocx', 'sys', 'drv', 'cab', 'diagcab', 'xbap', 'settingcontent-ms', 'library-ms', 'search-ms',
  'searchconnector-ms', 'xll', 'iqy', 'slk', 'ahk', 'au3',
  // Python files run with the Python launcher when it is installed
  'py', 'pyw', 'pyz', 'pyzw', 'pyc', 'pyo',
  // Office documents that carry macros
  'docm', 'dotm', 'xlsm', 'xltm', 'xlam', 'xla', 'pptm', 'potm', 'ppam', 'ppsm', 'sldm',
  // Disk images (files inside them don't keep the download's origin mark)
  'iso', 'img', 'vhd', 'vhdx',
  // macOS and Linux programs and installers
  'app', 'command', 'tool', 'terminal', 'workflow', 'dmg', 'pkg', 'mpkg', 'sh', 'bash', 'csh', 'ksh',
  'zsh', 'run', 'desktop', 'appimage', 'deb', 'rpm', 'snap', 'flatpakref',
])

/** Inert types that are safe to hand to their default program. */
const OPENABLE_EXTENSIONS = new Set([
  'pdf',
  'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'avif', 'heic', 'heif', 'tif', 'tiff',
  'txt', 'csv', 'tsv', 'json', 'md', 'log',
  'mp3', 'm4a', 'wav', 'ogg', 'oga', 'opus', 'flac', 'aac',
  'mp4', 'm4v', 'webm', 'mov',
])

/** `text` without bidi/format controls (safe to display as a file name). */
export function stripFormatControls(text: string): string {
  return text.replace(FORMAT_CONTROLS, '')
}

/** The file name (last path segment) of a saved download, ready to show. */
export function downloadName(path: string): string {
  const parts = path.split(/[\\/]/)
  return stripFormatControls(parts[parts.length - 1] || path)
}

/** Lower-case extension of a file name the way Windows reads it (trailing
 *  dots and spaces are dropped), or '' when there is none. */
export function fileExtension(name: string): string {
  const base = downloadName(name).replace(/[. ]+$/, '')
  const dot = base.lastIndexOf('.')
  return dot < 0 ? '' : base.slice(dot + 1).toLowerCase()
}

/** Can opening this download run code? `flagged` is the backend's verdict. */
export function isDangerousDownload(name: string, flagged: boolean | undefined): boolean {
  return flagged === true || DANGEROUS_EXTENSIONS.has(fileExtension(name))
}

/** May the toast offer "Open" for this download? */
export function canOpenDownload(name: string, flagged: boolean | undefined): boolean {
  return !isDangerousDownload(name, flagged) && OPENABLE_EXTENSIONS.has(fileExtension(name))
}
