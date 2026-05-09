import { useEffect } from 'react'

import ProjectList from './components/ProjectList/ProjectList'
import ChatPanel from './components/Chat/ChatPanel'
import DocList from './components/DocList/DocList'
import ReviewMode from './components/ReviewMode/ReviewMode'
import ApiKeyRevealModal from './components/Publish/ApiKeyRevealModal'
import ThemeToggle from './components/Theme/ThemeToggle'
import { useReview } from './stores/review'
import { useTheme } from './stores/theme'

export default function App() {
  const { activeDocId } = useReview()
  const hydrate = useTheme(s => s.hydrate)
  useEffect(() => { hydrate() }, [hydrate])

  if (activeDocId) return <ReviewMode />
  return (
    <>
      <ApiKeyRevealModal />
      <div className="fixed right-3 top-3 z-10">
        <ThemeToggle />
      </div>
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
    </>
  )
}
