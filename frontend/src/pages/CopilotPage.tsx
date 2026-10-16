import { ChatbotPanel } from '../components/ChatbotPanel'

export function CopilotPage() {
  return (
    <div className="mx-auto max-w-5xl space-y-5">
      <header>
        <p className="text-sm uppercase tracking-wider text-blue-400">Operational assistant</p>
        <h2 className="text-3xl font-bold text-white">RetailFlow Copilot</h2>
        <p className="mt-2 text-sm text-slate-400">Answers are grounded in authorized RetailFlow tools. Write actions require your confirmation.</p>
      </header>
      <ChatbotPanel embedded />
    </div>
  )
}
