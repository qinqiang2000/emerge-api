interface Props { text: string }

export default function UserBubble({ text }: Props) {
  return (
    <div className="flex justify-end">
      <div
        data-role="user-bubble"
        className="max-w-[70%] bg-bubble-user text-fg-primary rounded-2xl px-4 py-2 font-body whitespace-pre-wrap break-words"
      >
        {text}
      </div>
    </div>
  )
}
