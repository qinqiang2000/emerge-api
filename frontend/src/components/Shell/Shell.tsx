import { useState, useEffect, useRef, type ReactNode, type CSSProperties } from 'react'
import './shell.css'

type ShellProps = {
  left: ReactNode
  center: ReactNode
  right: ReactNode
  leftHidden?: boolean
  rightHidden?: boolean
}

const LEFT_W_KEY = 'emerge.leftW'
const RIGHT_W_KEY = 'emerge.rightW'
const LEFT_DEFAULT = 248
const LEFT_MIN = 180
const LEFT_MAX = 460
const RIGHT_DEFAULT = 360
const RIGHT_MIN = 260
const RIGHT_MAX = 600

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

export default function Shell({ left, center, right, leftHidden = false, rightHidden = false }: ShellProps) {
  const [leftW, setLeftWState] = useState<number>(() => readStored(LEFT_W_KEY, LEFT_DEFAULT, LEFT_MIN, LEFT_MAX))
  const [rightW, setRightWState] = useState<number>(() => readStored(RIGHT_W_KEY, RIGHT_DEFAULT, RIGHT_MIN, RIGHT_MAX))
  const [drag, setDrag] = useState<'left' | 'right' | null>(null)
  const dragStartX = useRef<number>(0)
  const dragStartW = useRef<number>(0)

  function setLeftW(w: number) {
    const clamped = clamp(w, LEFT_MIN, LEFT_MAX)
    setLeftWState(clamped)
    try { localStorage.setItem(LEFT_W_KEY, String(clamped)) } catch { /* ignore */ }
  }

  function setRightW(w: number) {
    const clamped = clamp(w, RIGHT_MIN, RIGHT_MAX)
    setRightWState(clamped)
    try { localStorage.setItem(RIGHT_W_KEY, String(clamped)) } catch { /* ignore */ }
  }

  useEffect(() => {
    if (!drag) return

    function onMove(clientX: number) {
      if (drag === 'left') {
        setLeftW(dragStartW.current + (clientX - dragStartX.current))
      } else {
        setRightW(dragStartW.current - (clientX - dragStartX.current))
      }
    }

    function handleMouseMove(e: MouseEvent) { onMove(e.clientX) }
    function handleTouchMove(e: TouchEvent) {
      if (e.touches.length > 0) onMove(e.touches[0].clientX)
    }
    function handleEnd() { setDrag(null) }

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

  function startDrag(side: 'left' | 'right', clientX: number) {
    dragStartX.current = clientX
    dragStartW.current = side === 'left' ? leftW : rightW
    setDrag(side)
  }

  const solo = leftHidden && rightHidden
  const shellClass = [
    'shell',
    solo ? 'solo' : leftHidden ? 'no-left' : '',
    solo ? '' : rightHidden ? 'no-right' : '',
    drag ? 'dragging' : '',
  ].filter(Boolean).join(' ')

  const shellStyle: CSSProperties = {
    '--left-w': leftHidden ? '0px' : `${leftW}px`,
    '--right-w': rightHidden ? '0px' : `${rightW}px`,
  } as CSSProperties

  return (
    <div className={shellClass} style={shellStyle}>
      {/* left panel */}
      <aside className="fs" style={{ overflow: 'hidden' }}>
        {left}
      </aside>

      {/* center panel */}
      <main className="conv" style={{ overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        {center}
      </main>

      {/* right panel */}
      <aside className="ctx" style={{ overflow: 'hidden' }}>
        {right}
      </aside>

      {/* drag resizers */}
      <div
        className={`resizer left${drag === 'left' ? ' active' : ''}`}
        title="Drag to resize"
        onMouseDown={(e) => { e.preventDefault(); startDrag('left', e.clientX) }}
        onTouchStart={(e) => { if (e.touches.length > 0) startDrag('left', e.touches[0].clientX) }}
      />
      <div
        className={`resizer right${drag === 'right' ? ' active' : ''}`}
        title="Drag to resize"
        onMouseDown={(e) => { e.preventDefault(); startDrag('right', e.clientX) }}
        onTouchStart={(e) => { if (e.touches.length > 0) startDrag('right', e.touches[0].clientX) }}
      />
    </div>
  )
}
