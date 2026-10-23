/// <reference types="vite/client" />

// A Generative UI library, bundled by generativeUILibraries.ts.
declare module 'virtual:generative-ui-library/*' {
  const bundle: import('./components/GenerativeUI/assets').LibraryBundle
  export default bundle
}
