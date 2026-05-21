type Props = { size?: number; className?: string }

export function ThinkingIcon({ size = 18, className = '' }: Props) {
  return (
    <svg
      className={`thinking-bf ${className}`}
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="currentColor"
      aria-hidden="true"
    >
      <g className="bf-wing bf-l">
        <path d="M11.4 12 C 6.5 3.4, 1.6 5.2, 2.4 11 C 2.6 12.6, 6.6 12.9, 11.4 12 Z" />
        <path d="M11.4 12 C 5.8 18.4, 3.4 17.4, 4.2 13.4 C 5 12.4, 8 12, 11.4 12 Z" opacity="0.62" />
      </g>
      <g className="bf-wing bf-r">
        <path d="M12.6 12 C 17.5 3.4, 22.4 5.2, 21.6 11 C 21.4 12.6, 17.4 12.9, 12.6 12 Z" />
        <path d="M12.6 12 C 18.2 18.4, 20.6 17.4, 19.8 13.4 C 19 12.4, 16 12, 12.6 12 Z" opacity="0.62" />
      </g>
      <line x1="12" y1="6.4" x2="12" y2="17" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />
      <circle cx="12" cy="5.6" r="0.85" />
    </svg>
  )
}
