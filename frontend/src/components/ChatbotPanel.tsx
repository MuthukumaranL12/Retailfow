import { FormEvent, useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { Check, Copy, LoaderCircle, MessageSquare, Plus, Send, Sparkles, Trash2, X } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  askChatbot,
  ChatPageContext,
  confirmChatAction,
  createConversation,
  deleteConversation,
  getConversation,
  getConversations,
} from '../api'

type ChatItem = { tool: string; result: Record<string, unknown> }
type ChatMessage = {
  role: 'user' | 'assistant'
  text: string
  created_at: string
  items?: ChatItem[]
}
type ConversationSummary = { conversation_id: string; title: string }
type PendingAction = {
  action_id: string
  action: { type: string; product_id?: string; store_id?: string; quantity?: number; recommendation_id?: string }
  confirmation_required?: boolean
}

function decodePathSegment(value: string): string {
  try {
    return decodeURIComponent(value)
  } catch {
    return value
  }
}

function controlledPageContext(pathname: string): ChatPageContext {
  const order = pathname.match(/^\/orders\/([^/]+)$/)
  if (order) return { page: '/orders/:orderId', entity_type: 'order', entity_id: decodePathSegment(order[1]) }
  const warehouse = pathname.match(/^\/warehouses\/([^/]+)$/)
  if (warehouse) return { page: '/warehouses/:warehouseId', entity_type: 'warehouse', entity_id: decodePathSegment(warehouse[1]) }
  const delivery = pathname.match(/^\/deliveries\/([^/]+)$/)
  if (delivery) return { page: '/deliveries/:deliveryId', entity_type: 'delivery', entity_id: decodePathSegment(delivery[1]) }
  return { page: pathname }
}

function toChatMessages(messages: Array<{ question: string; answer: string; created_at?: string; tool_results?: ChatItem[] }>): ChatMessage[] {
  return messages.flatMap((message) => {
    const createdAt = message.created_at ?? new Date().toISOString()
    return [
      { role: 'user' as const, text: message.question, created_at: createdAt },
      { role: 'assistant' as const, text: message.answer, created_at: createdAt, items: message.tool_results ?? [] },
    ]
  })
}

function errorText(error: unknown, fallback: string): string {
  if (typeof error === 'object' && error !== null && 'response' in error) {
    const response = (error as { response?: { data?: { detail?: string } } }).response
    if (response?.data?.detail) return response.data.detail
  }
  return fallback
}

export function ChatbotPanel({ embedded = false }: { embedded?: boolean }) {
  const location = useLocation()
  const [open, setOpen] = useState(embedded)
  const [question, setQuestion] = useState('')
  const [conversationId, setConversationId] = useState<string>()
  const [conversations, setConversations] = useState<ConversationSummary[]>([])
  const [sending, setSending] = useState(false)
  const [actionId, setActionId] = useState<string>()
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      role: 'assistant',
      text: 'I can help interpret inventory risk, fulfillment decisions, delivery exceptions, forecasts, and operational KPIs.',
      created_at: new Date().toISOString(),
    },
  ])

  useEffect(() => {
    if (!open) return
    getConversations()
      .then(({ data }) => setConversations(data.conversations))
      .catch(() => setError('Conversation history is unavailable.'))
  }, [open, conversationId])

  const startNewConversation = async () => {
    setError('')
    setNotice('')
    try {
      const { data } = await createConversation()
      setConversationId(data.conversation_id)
      setConversations((items) => [
        { conversation_id: data.conversation_id, title: data.title },
        ...items.filter((item) => item.conversation_id !== data.conversation_id),
      ])
      setMessages([{
        role: 'assistant',
        text: 'New conversation. Ask about current operations or open risks.',
        created_at: data.created_at ?? new Date().toISOString(),
      }])
    } catch (cause) {
      setError(errorText(cause, 'Could not start a new conversation.'))
    }
  }

  const openConversation = async (id: string) => {
    setError('')
    try {
      const { data } = await getConversation(id)
      setConversationId(id)
      setMessages(toChatMessages(data.messages ?? []))
    } catch (cause) {
      setError(errorText(cause, 'Could not load that conversation.'))
    }
  }

  const removeConversation = async () => {
    if (!conversationId || !window.confirm('Delete this conversation and its stored history?')) return
    setError('')
    try {
      await deleteConversation(conversationId)
      setConversations((items) => items.filter((item) => item.conversation_id !== conversationId))
      setConversationId(undefined)
      setMessages([{
        role: 'assistant',
        text: 'Conversation deleted. Start a new conversation to continue.',
        created_at: new Date().toISOString(),
      }])
    } catch (cause) {
      setError(errorText(cause, 'Could not delete this conversation.'))
    }
  }

  const sendMessage = async (event?: FormEvent) => {
    event?.preventDefault()
    if (!question.trim() || sending) return
    const prompt = question.trim()
    setQuestion('')
    setError('')
    setNotice('')
    setMessages((current) => [...current, { role: 'user', text: prompt, created_at: new Date().toISOString() }])
    setSending(true)
    try {
      const { data } = await askChatbot(prompt, controlledPageContext(location.pathname), conversationId)
      setConversationId(data.conversation_id)
      setMessages((current) => [...current, {
        role: 'assistant',
        text: data.answer ?? 'The assistant returned no response.',
        created_at: new Date().toISOString(),
        items: data.items ?? [],
      }])
    } catch (cause) {
      setError(errorText(cause, 'The assistant request failed. Please retry.'))
    } finally {
      setSending(false)
    }
  }

  const resolveAction = async (action: PendingAction, confirmed: boolean) => {
    if (!conversationId || actionId) return
    setActionId(action.action_id)
    setError('')
    setNotice('')
    try {
      const { data } = await confirmChatAction(conversationId, action.action_id, confirmed)
      setMessages((current) => current.map((message) => ({
        ...message,
        items: message.items?.map((item) => item.result.action_id === action.action_id
          ? { ...item, result: { ...item.result, confirmation_required: false, confirmation_status: data.status, backend_result: data.movement ?? data.approval } }
          : item),
      })))
      if (data.status === 'confirmed') {
        if (action.action.type === 'replenishment_approval') {
          setNotice(`Replenishment ${action.action.recommendation_id} was approved.`)
        } else {
          const movement = data.movement as { quantity?: number; product_id?: string; store_id?: string } | undefined
          setNotice(
            `Backend confirmed the restock${movement?.quantity ? `: ${movement.quantity} units of ${movement.product_id} at ${movement.store_id}` : '.'}`,
          )
        }
      } else {
        setNotice('The action was declined. No inventory change was made.')
      }
      setMessages((current) => [...current, {
        role: 'assistant',
        text: data.status === 'confirmed'
          ? 'The backend confirmed the requested inventory update.'
          : 'The requested action was declined; no change was made.',
        created_at: new Date().toISOString(),
      }])
    } catch (cause) {
      setError(errorText(cause, 'The action was not confirmed. Verify its status before retrying.'))
    } finally {
      setActionId(undefined)
    }
  }

  const panel = (
    <section className={`flex flex-col overflow-hidden border border-slate-700 bg-slate-900 shadow-2xl ${embedded ? 'h-[min(78vh,900px)] rounded-2xl' : 'h-[min(72vh,720px)] w-[min(430px,calc(100vw-2rem))] rounded-2xl'}`} aria-label="RetailFlow Copilot">
      <header className="flex items-center justify-between gap-2 border-b border-slate-700 bg-slate-800 px-4 py-3">
        <div className="flex min-w-0 items-center gap-2 text-white">
          <Sparkles size={16} className="shrink-0 text-blue-400" />
          <div className="min-w-0"><h2 className="truncate font-medium">RetailFlow Copilot</h2><p className="text-[11px] text-slate-400">Operational data · role-scoped tools</p></div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <select aria-label="Previous conversations" value={conversationId ?? ''} onChange={(event) => event.target.value && void openConversation(event.target.value)} className="max-w-28 rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-300">
            <option value="">History</option>
            {conversations.map((item) => <option key={item.conversation_id} value={item.conversation_id}>{item.title}</option>)}
          </select>
          <button title="New conversation" aria-label="New conversation" onClick={() => void startNewConversation()} className="rounded p-1 text-blue-300 hover:bg-slate-700"><Plus size={16} /></button>
          {conversationId && <button title="Delete conversation" aria-label="Delete conversation" onClick={() => void removeConversation()} className="rounded p-1 text-slate-400 hover:bg-slate-700 hover:text-red-300"><Trash2 size={15} /></button>}
          {!embedded && <button aria-label="Close Copilot" className="rounded p-1 text-slate-300 hover:bg-slate-700" onClick={() => setOpen(false)}><X size={16} /></button>}
        </div>
      </header>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto bg-slate-950/60 p-4">
        {error && <p role="alert" className="rounded-xl border border-red-800 bg-red-950/60 p-3 text-xs text-red-200">{error}</p>}
        {notice && <p role="status" className="rounded-xl border border-emerald-800 bg-emerald-950/50 p-3 text-xs text-emerald-200">{notice}</p>}
        {messages.map((message, index) => (
          <article key={`${message.role}-${index}`} className={`max-w-[94%] rounded-xl px-3 py-2 text-sm ${message.role === 'user' ? 'ml-auto bg-blue-600 text-white' : 'mr-auto bg-slate-800 text-slate-200'}`}>
            <div className="[&_a]:text-blue-300 [&_a]:underline [&_blockquote]:border-l-2 [&_blockquote]:border-slate-600 [&_blockquote]:pl-3 [&_code]:rounded [&_code]:bg-slate-950 [&_code]:px-1 [&_li]:ml-4 [&_li]:list-disc [&_ol]:my-2 [&_p]:my-1 [&_pre]:overflow-x-auto [&_pre]:rounded [&_pre]:bg-slate-950 [&_pre]:p-2 [&_table]:w-full [&_table]:border-collapse [&_td]:border [&_td]:border-slate-600 [&_td]:p-1 [&_th]:border [&_th]:border-slate-600 [&_th]:p-1 [&_th]:text-left">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.text}</ReactMarkdown>
            </div>
            {message.items?.map((item, itemIndex) => {
              const result = item.result
              const pending = result.confirmation_required === true ? result as unknown as PendingAction : undefined
              return (
                <div key={`${item.tool}-${itemIndex}`} className="mt-2 rounded-lg border border-slate-700 bg-slate-950/70 p-2">
                  <p className="text-[11px] font-medium uppercase tracking-wide text-blue-300">{item.tool.replace(/_/g, ' ')}</p>
                  {pending ? (
                    <>
                      <p className="mt-1 text-xs text-slate-300">
                        {pending.action.type === 'replenishment_approval'
                          ? `Approve ${pending.action.recommendation_id} (${pending.action.quantity ?? '—'} units of ${pending.action.product_id} for ${pending.action.store_id})?`
                          : `Restock ${pending.action.quantity ?? '—'} units of ${pending.action.product_id} for ${pending.action.store_id}?`}
                      </p>
                      <p className="mt-1 text-[11px] text-amber-300">No change has been made yet.</p>
                      <div className="mt-2 flex gap-2">
                        <button disabled={Boolean(actionId)} onClick={() => void resolveAction(pending, true)} className="inline-flex items-center gap-1 rounded bg-emerald-700 px-2 py-1 text-xs text-white disabled:opacity-50"><Check size={13} />Confirm</button>
                        <button disabled={Boolean(actionId)} onClick={() => void resolveAction(pending, false)} className="inline-flex items-center gap-1 rounded bg-slate-700 px-2 py-1 text-xs text-slate-200 disabled:opacity-50"><X size={13} />Decline</button>
                      </div>
                    </>
                  ) : (
                    <pre className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap break-words text-[11px] text-slate-400">{JSON.stringify(result, null, 2)}</pre>
                  )}
                </div>
              )
            })}
            <footer className="mt-2 flex items-center justify-between gap-2 text-[10px] text-slate-500">
              <time dateTime={message.created_at}>{new Date(message.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</time>
              {message.role === 'assistant' && <button title="Copy response" aria-label="Copy response" onClick={() => void navigator.clipboard.writeText(message.text)} className="rounded p-1 hover:bg-slate-700 hover:text-white"><Copy size={12} /></button>}
            </footer>
          </article>
        ))}
        {sending && <p role="status" className="flex items-center gap-2 text-xs text-slate-400"><LoaderCircle size={14} className="animate-spin" />Checking operational data…</p>}
      </div>

      <form onSubmit={(event) => void sendMessage(event)} className="flex gap-2 border-t border-slate-700 bg-slate-900 p-3">
        <input
          aria-label="Ask RetailFlow Copilot"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          disabled={sending}
          className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white outline-none focus:border-blue-500 disabled:opacity-60"
          placeholder="Ask about orders, stock, or delivery risk…"
        />
        <button type="submit" disabled={sending || !question.trim()} aria-label="Send message" className="rounded-xl bg-blue-600 p-2 text-white hover:bg-blue-500 disabled:opacity-50">
          <Send size={16} />
        </button>
      </form>
    </section>
  )

  return embedded ? (
    <div className="h-full w-full">{panel}</div>
  ) : (
    <div className="fixed bottom-5 right-5 z-20">
      {open ? panel : (
        <button onClick={() => setOpen(true)} className="flex items-center gap-2 rounded-full bg-blue-600 px-4 py-3 text-sm font-medium text-white shadow-lg">
          <MessageSquare size={16} />RetailFlow Copilot
        </button>
      )}
    </div>
  )
}
