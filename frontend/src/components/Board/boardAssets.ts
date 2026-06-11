// Side-effect module: point excalidraw at the self-hosted runtime assets
// BEFORE any excalidraw code evaluates. The bundle resolves its lazy
// `./fonts/...` URLs against `window.EXCALIDRAW_ASSET_PATH`; the default CDN
// fallback is unreliable on the prod VPS, so the fonts are vendored under
// `frontend/public/excalidraw-assets/` (see its README for the re-copy step on
// upgrade). BoardOverlay imports this module FIRST — keep it that way.

declare global {
  interface Window {
    EXCALIDRAW_ASSET_PATH?: string
  }
}

if (typeof window !== 'undefined') {
  window.EXCALIDRAW_ASSET_PATH = '/excalidraw-assets/'
}

export {}
