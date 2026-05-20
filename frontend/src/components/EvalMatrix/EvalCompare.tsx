interface Props {
  slug: string
  a: string | null
  b: string | null
}


export default function EvalCompare({ slug, a, b }: Props) {
  return (
    <div className="min-h-screen bg-paper text-ink p-6">
      <h1 className="text-xl font-semibold">eval compare</h1>
      <div className="text-sm text-ink-3 mt-2">
        slug={slug} · a={a ?? '—'} · b={b ?? '—'}
      </div>
      <div className="text-ink-3 text-sm mt-4">compare 视图待 T13 实现</div>
    </div>
  )
}
