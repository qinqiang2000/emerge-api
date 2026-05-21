import EvalMatrixBody from './EvalMatrixBody'


interface Props {
  slug: string
  ts: string
}


/** EvalMatrixPage — legacy standalone full-page variant of the matrix.
 *
 *  As of M-modal the matrix is opened as an overlay over the project shell
 *  (`EvalMatrixModal` mounted by App.tsx when `?eval=<ts>` is in the URL).
 *  This component is no longer routed but is kept around as a thin wrapper
 *  on top of `EvalMatrixBody` so anything that imports it (future debug
 *  routes, fallbacks) doesn't go stale, and the body logic stays
 *  single-sourced. */
export default function EvalMatrixPage({ slug, ts }: Props) {
  return (
    <div className="min-h-screen bg-paper text-ink p-6">
      <EvalMatrixBody slug={slug} ts={ts} />
    </div>
  )
}
