interface Props {
  disabled: boolean
  pending: { filename: string }[]
  onAttach: (files: { filename: string }[]) => void
  onSubmit: (text: string) => void
}

export default function Composer(_props: Props) {
  return <div className="border-t border-subtle p-3 text-fg-muted text-sm">Composer placeholder (T37)</div>
}
