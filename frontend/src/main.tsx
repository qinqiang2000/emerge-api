// frontend/src/main.tsx
import React from 'react'
import ReactDOM from 'react-dom/client'

import App from './App'
import './index.css'
import { readBoardOpenFromSearch, readSlugFromPathname } from './lib/slugUrl'
import { useBoard } from './stores/board'
import { useDocs } from './stores/docs'
import './theme/fonts'

// Eager board prefetch (perf, 2026-06-18): on a cold load of `/p/<slug>?board=1`
// the board's data chain (audit/latest → locate POSTs → board-notes) used to
// fire only after React mounted, the lazy excalidraw chunk loaded AND the whole
// `/lab/*` project-metadata fan-out resolved — measured on prod as a strictly
// serial waterfall that didn't reach `audit/latest` until ~4.3s and the first
// page raster until ~6.6s. `useBoard.load` is cache-first + in-flight-deduped
// and keys only on slug, so kicking it off here (before createRoot) runs that
// chain CONCURRENTLY with app bootstrap instead of behind it. The component's
// own effect later no-ops on the warm cache. Pure URL parse, no React needed.
if (readBoardOpenFromSearch(window.location.search)) {
  const slug = readSlugFromPathname(window.location.pathname)
  if (slug) {
    const board = useBoard.getState()
    void board.load(slug)
    void board.loadNotes(slug)
    // The scene build also gates on the docs sidecar (page counts) — warm it
    // here too so page-raster layout isn't waiting on the metadata fan-out.
    void useDocs.getState().refresh(slug)
    // Kick the lazy board chunk (excalidraw, ~418KB) at t=0 so it downloads
    // alongside the data + app bootstrap instead of only after AppShell paints
    // — same module specifier AppShell's `lazy()` uses, so Vite dedupes it.
    void import('./components/Board/BoardOverlay')
  }
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)
