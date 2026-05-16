// frontend/src/components/Chat/ConvHeader.tsx
//
// Main shell chat header — floating top-right chip cluster (history popover
// + new chat). The actual chip + popover lives in `ChatHistoryActions`
// (variant="full") so the review overlay can reuse the same affordance.

import ChatHistoryActions from './ChatHistoryActions'
import type { ChatSummary } from '../../lib/api'

interface Props {
  activeProject: string
  currentChatId: string
  chats: ChatSummary[]
  onNew: () => void
  onSwitch: (chatId: string) => void
  /** Called when the history popover transitions to open — parent refreshes the list. */
  onOpen?: () => void
}

export default function ConvHeader(props: Props) {
  return <ChatHistoryActions {...props} variant="full" />
}
