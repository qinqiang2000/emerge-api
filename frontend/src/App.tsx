// frontend/src/App.tsx
import ProjectList from './components/ProjectList/ProjectList'
import ChatPanel from './components/Chat/ChatPanel'
import DocPreview from './components/DocPreview/DocPreview'

export default function App() {
  return (
    <div className="grid grid-cols-[260px_1fr_360px] h-full bg-canvas text-fg-primary">
      <aside className="border-r border-subtle">
        <ProjectList />
      </aside>
      <main className="flex flex-col">
        <ChatPanel />
      </main>
      <aside className="border-l border-subtle">
        <DocPreview />
      </aside>
    </div>
  )
}
