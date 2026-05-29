import type { CSSProperties, ElementType, ReactNode } from 'react'

export interface BBoxRectProps {
  /** [x0, y0, x1, y1] in PDF-point units (same unit textlayer/translate/locate use). */
  bbox: [number, number, number, number]
  /** Page width in PDF points. */
  pageW: number
  /** Page height in PDF points. */
  pageH: number
  /** Render element. Defaults to a <div>; TextLayer uses <span>. */
  as?: ElementType
  className?: string
  /** Extra style merged on top of the computed left/top/width/height. */
  style?: CSSProperties
  children?: ReactNode
  /** Any other DOM passthrough (title, aria-*, etc). */
  [key: string]: unknown
}

/**
 * Shared bbox -> percentage positioning primitive.
 *
 * Single home for the `(x0/pageW)*100%` formula that TextLayer, TranslateGhost,
 * and LocateHighlight all need (hoisted per the "three patches same shape =
 * missing noun" rule). It owns ONLY left/top/width/height; every other style
 * (font-size, pointer-events, colors) is passed through by the caller so each
 * layer keeps its exact pixel behavior.
 */
export function BBoxRect({
  bbox,
  pageW,
  pageH,
  as,
  className,
  style,
  children,
  ...rest
}: BBoxRectProps) {
  const Tag = (as ?? 'div') as ElementType
  const [x0, y0, x1, y1] = bbox
  const left = (x0 / pageW) * 100
  const top = (y0 / pageH) * 100
  const width = ((x1 - x0) / pageW) * 100
  const height = ((y1 - y0) / pageH) * 100

  return (
    <Tag
      className={className}
      style={{
        position: 'absolute',
        left: `${left}%`,
        top: `${top}%`,
        width: `${width}%`,
        height: `${height}%`,
        ...style,
      }}
      {...rest}
    >
      {children}
    </Tag>
  )
}

export default BBoxRect
