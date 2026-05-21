// frontend/src/stores/evalSurface.ts
//
// Thin per-process store backing the EvalMatrix drilldown's inline composer.
//
// EvalMatrixBody writes here whenever the user opens / closes the
// CellDrilldown panel; ChatPanel (compact mode) reads via getState() at
// submit time and threads the active cell into the chat envelope as a
// `surface: 'eval_cell'` SurfaceContext.
//
// Lifecycle:
//   - open drilldown  → setActive(ts, cell)
//   - close drilldown → setActive(null, null)
//   - unmount         → setActive(null, null)
//
// The store is intentionally minimal — no derived fields, no persistence.
// One client (EvalMatrixBody) writes, one client (ChatPanel.compact) reads,
// and a drilldown can only ever be "open on exactly one cell" at a time.

import { create } from 'zustand'

import type { CellVerdict } from '../types/eval'


interface State {
  activeCell: CellVerdict | null
  activeTs: string | null
  setActive: (ts: string | null, cell: CellVerdict | null) => void
}

export const useEvalSurface = create<State>((set) => ({
  activeCell: null,
  activeTs: null,
  setActive: (activeTs, activeCell) => set({ activeTs, activeCell }),
}))
