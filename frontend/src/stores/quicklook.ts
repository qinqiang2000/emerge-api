import { create } from 'zustand'

export type QuickLookTarget =
  | { kind: 'schema'; pid: string }
  | { kind: 'version'; pid: string; versionId: string }

interface RawJsonSlot {
  value: string | null
  loading: boolean
  error: string | null
}

interface QuickLookState {
  target: QuickLookTarget | null
  rawJson: RawJsonSlot

  openSchema: (pid: string) => void
  openVersion: (pid: string, versionId: string) => void
  close: () => void
  loadRaw: () => Promise<void>
}

const EMPTY_RAW: RawJsonSlot = { value: null, loading: false, error: null }

export const useQuickLook = create<QuickLookState>((set, get) => ({
  target: null,
  rawJson: EMPTY_RAW,

  openSchema: pid => set({ target: { kind: 'schema', pid }, rawJson: EMPTY_RAW }),
  openVersion: (pid, versionId) =>
    set({ target: { kind: 'version', pid, versionId }, rawJson: EMPTY_RAW }),
  close: () => set({ target: null, rawJson: EMPTY_RAW }),

  loadRaw: async () => {
    const t = get().target
    if (!t) return
    set({ rawJson: { value: null, loading: true, error: null } })
    const url =
      t.kind === 'schema'
        ? `/lab/projects/${t.pid}/schema/raw`
        : `/lab/projects/${t.pid}/versions/${t.versionId}/raw`
    try {
      const resp = await fetch(url)
      if (!resp.ok) {
        let code = `http_${resp.status}`
        try {
          const j = await resp.json()
          code = j?.detail?.error_code ?? code
        } catch { /* not json */ }
        set({ rawJson: { value: null, loading: false, error: code } })
        return
      }
      const text = await resp.text()
      // Guard against a stale response if the user changed targets while the fetch was in flight.
      if (get().target !== t) return
      set({ rawJson: { value: text, loading: false, error: null } })
    } catch (e) {
      set({ rawJson: { value: null, loading: false, error: (e as Error).message ?? 'fetch_failed' } })
    }
  },
}))
