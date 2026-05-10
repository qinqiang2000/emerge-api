interface Props {
  field: string
  oldDesc: string
  newDesc: string
}

export default function ProposalDiff({ field, oldDesc, newDesc }: Props) {
  return (
    <div className="diff">
      <div className="row">
        <span className="field">{field}</span>
        <span className="col">
          <span className="old">{oldDesc}</span>
          <span className="new">{newDesc}</span>
        </span>
      </div>
    </div>
  )
}
