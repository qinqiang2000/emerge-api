import { Monitor, Moon, Sun } from 'lucide-react'

import { useTheme, type ThemeMode } from '../../stores/theme'

const NEXT: Record<ThemeMode, ThemeMode> = {
  system: 'light',
  light: 'dark',
  dark: 'system',
}

export default function ThemeToggle() {
  const { mode, setMode } = useTheme()
  const Icon = mode === 'system' ? Monitor : mode === 'light' ? Sun : Moon

  return (
    <button
      type="button"
      aria-label={`theme: ${mode} (click to cycle)`}
      onClick={() => setMode(NEXT[mode])}
      className="p-1.5 rounded hover:bg-subtle text-fg-secondary transition-colors"
    >
      <Icon size={16} />
    </button>
  )
}
