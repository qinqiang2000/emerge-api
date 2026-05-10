// frontend/tailwind.config.js
/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  // darkMode dropped for M7
  theme: {
    extend: {
      colors: {
        paper: 'var(--paper)',
        'paper-2': 'var(--paper-2)',
        'paper-3': 'var(--paper-3)',
        rule: 'var(--rule)',
        'rule-soft': 'var(--rule-soft)',
        ink: 'var(--ink)',
        'ink-2': 'var(--ink-2)',
        'ink-3': 'var(--ink-3)',
        'ink-4': 'var(--ink-4)',
        'ink-5': 'var(--ink-5)',
        ochre: 'var(--ochre)',
        'ochre-2': 'var(--ochre-2)',
        'ochre-soft': 'var(--ochre-soft)',
        moss: 'var(--moss)',
        'moss-soft': 'var(--moss-soft)',
        rose: 'var(--rose)',
        'rose-soft': 'var(--rose-soft)',
      },
      fontFamily: {
        serif: 'var(--serif)',
        mono:  'var(--mono)',
        sans:  'var(--sans)',
      },
    },
  },
  plugins: [],
}
