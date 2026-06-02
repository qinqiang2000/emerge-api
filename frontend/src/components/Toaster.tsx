// frontend/src/components/Toaster.tsx
//
// Renders the global toast queue in the bottom-right corner. Mounted once at
// the app root. Click a toast to dismiss it early; otherwise it self-expires
// (see stores/toast.ts).
import { useToast } from '../stores/toast'

export default function Toaster() {
  const toasts = useToast((s) => s.toasts)
  const dismiss = useToast((s) => s.dismiss)
  if (toasts.length === 0) return null
  return (
    <div className="toaster" role="status" aria-live="polite">
      {toasts.map((t) => (
        <button
          key={t.id}
          type="button"
          className={`toast ${t.kind}`}
          onClick={() => dismiss(t.id)}
        >
          {t.text}
        </button>
      ))}
    </div>
  )
}
