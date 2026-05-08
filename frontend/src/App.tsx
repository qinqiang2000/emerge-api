import ProjectList from './components/ProjectList/ProjectList'
import ChatPanel from './components/Chat/ChatPanel'
import DocList from './components/DocList/DocList'
import ReviewMode from './components/ReviewMode/ReviewMode'
import { useReview } from './stores/review'

export default function App() {
  const { activeDocId } = useReview()
  if (activeDocId) return <ReviewMode />
  return (
    <div className="grid grid-cols-[260px_1fr_360px] h-full bg-canvas text-fg-primary">
      <aside className="border-r border-subtle">
        <ProjectList />
      </aside>
      <main className="flex flex-col">
        <ChatPanel />
      </main>
      <aside className="border-l border-subtle">
        <DocList />
      </aside>
    </div>
  )
}
