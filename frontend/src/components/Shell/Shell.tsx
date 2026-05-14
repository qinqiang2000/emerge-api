import { useState, useEffect, useRef, type ReactNode, type CSSProperties } from 'react'
import './shell.css'

type ShellProps = {
  left: ReactNode
  center: ReactNode
  leftHidden?: boolean
  /** When true, the right column collapses to 0 width. The right slot itself
   *  is always an empty spacer — the visible context panel is a fixed overlay
   *  rendered outside Shell (see App.tsx / .ctx in index.css). The spacer
   *  exists so center content doesn't slide under the overlay. */
  rightHidden?: boolean
}

const LEFT_W_KEY = 'emerge.leftW'
const LEFT_DEFAULT = 248
const LEFT_MIN = 180
const LEFT_MAX = 460

function clamp(val: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, val))
}

function readStored(key: string, fallback: number, min: number, max: number): number {
  try {
    const v = localStorage.getItem(key)
    if (v !== null) {
      const n = parseInt(v, 10)
      if (!isNaN(n)) return Math.max(min, Math.min(max, n))
    }
  } catch {
    // ignore
  }
  return fallback
}

export default function Shell({ left, center, leftHidden = false, rightHidden = false }: ShellProps) {
  const [leftW, setLeftWState] = useState<number>(() => readStored(LEFT_W_KEY, LEFT_DEFAULT, LEFT_MIN, LEFT_MAX))
  const [drag, setDrag] = useState<boolean>(false)
  const dragStartX = useRef<number>(0)
  const dragStartW = useRef<number>(0)

  function setLeftW(w: number) {
    const clamped = clamp(w, LEFT_MIN, LEFT_MAX)
    setLeftWState(clamped)
    try { localStorage.setItem(LEFT_W_KEY, String(clamped)) } catch { /* ignore */ }
  }

  useEffect(() => {
    if (!drag) return

    function onMove(clientX: number) {
      setLeftW(dragStartW.current + (clientX - dragStartX.current))
    }

    function handleMouseMove(e: MouseEvent) { onMove(e.clientX) }
    function handleTouchMove(e: TouchEvent) {
      if (e.touches.length > 0) onMove(e.touches[0].clientX)
    }
    function handleEnd() { setDrag(false) }

    window.addEventListener('mousemove', handleMouseMove)
    window.addEventListener('mouseup', handleEnd)
    window.addEventListener('touchmove', handleTouchMove)
    window.addEventListener('touchend', handleEnd)

    return () => {
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseup', handleEnd)
      window.removeEventListener('touchmove', handleTouchMove)
      window.removeEventListener('touchend', handleEnd)
    }
  }, [drag])

  function startDrag(clientX: number) {
    dragStartX.current = clientX
    dragStartW.current = leftW
    setDrag(true)
  }

  const shellClass = [
    'shell',
    leftHidden ? 'no-left' : '',
    rightHidden ? 'no-right' : '',
    drag ? 'dragging' : '',
  ].filter(Boolean).join(' ')

  const shellStyle: CSSProperties = {
    '--left-w': leftHidden ? '0px' : `${leftW}px`,
  } as CSSProperties

  return (
    <div className={shellClass} style={shellStyle}>
      <aside className="fs" style={{ overflow: 'hidden' }}>
        {left}
      </aside>

      <main className="conv" style={{ overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        {center}
      </main>

      <div
        className={`resizer left${drag ? ' active' : ''}`}
        title="Drag to resize"
        onMouseDown={(e) => { e.preventDefault(); startDrag(e.clientX) }}
        onTouchStart={(e) => { if (e.touches.length > 0) startDrag(e.touches[0].clientX) }}
      />
    </div>
  )
}
