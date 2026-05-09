import { create } from 'zustand'

export type ThemeMode = 'system' | 'light' | 'dark'

const STORAGE_KEY = 'emerge.theme'

function isMode(s: string | null): s is ThemeMode {
  return s === 'system' || s === 'light' || s === 'dark'
}

function writeAttribute(mode: ThemeMode): void {
  if (mode === 'system') {
    document.documentElement.removeAttribute('data-theme')
  } else {
    document.documentElement.setAttribute('data-theme', mode)
  }
}

interface State {
  mode: ThemeMode
  setMode: (mode: ThemeMode) => void
  apply: () => void
  hydrate: () => void
}

export const useTheme = create<State>((set, get) => ({
  mode: 'system',
  setMode: (mode) => {
    set({ mode })
    writeAttribute(mode)
    try {
      localStorage.setItem(STORAGE_KEY, mode)
    } catch {
      // Ignore storage failures in private mode or constrained test envs.
    }
  },
  apply: () => writeAttribute(get().mode),
  hydrate: () => {
    let stored: string | null = null
    try {
      stored = localStorage.getItem(STORAGE_KEY)
    } catch {
      stored = null
    }
    const mode: ThemeMode = isMode(stored) ? stored : 'system'
    set({ mode })
    writeAttribute(mode)
  },
}))
