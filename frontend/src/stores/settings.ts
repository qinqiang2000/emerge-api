// frontend/src/stores/settings.ts — open/close state for the Settings modal.
import { create } from 'zustand'

export type SettingsSection = 'general' | 'account' | 'developer' | 'team' | 'admin'

interface State {
  open: boolean
  section: SettingsSection
  show: (section?: SettingsSection) => void
  hide: () => void
}

export const useSettings = create<State>((set) => ({
  open: false,
  section: 'general',
  show: (section = 'general') => set({ open: true, section }),
  hide: () => set({ open: false }),
}))
