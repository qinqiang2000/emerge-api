import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props { children: ReactNode }
interface State { err: Error | null }

/** Boundary around the chat thread so a single tool-result adapter throw
 *  (e.g. an unexpected tool_result shape) doesn't unmount the whole
 *  ChatPanel into a blank screen. Renders a small inline error pill in
 *  place of the thread; user can switch chats or refresh to recover. */
export default class ChatErrorBoundary extends Component<Props, State> {
  state: State = { err: null }

  static getDerivedStateFromError(err: Error): State { return { err } }

  componentDidCatch(err: Error, info: ErrorInfo): void {
    console.error('[ChatErrorBoundary]', err, info.componentStack)
  }

  render(): ReactNode {
    if (this.state.err) {
      return (
        <div role="alert" className="conv-inner">
          <div className="msg agent" style={{ color: 'var(--rose)' }}>
            Could not render this chat — one of its messages has an unexpected
            shape. Try switching to another chat from the history popover, or
            start a new one with the + button.
          </div>
          <div style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink-5)', marginTop: 8 }}>
            {this.state.err.message}
          </div>
        </div>
      )
    }
    return this.props.children
  }
}
