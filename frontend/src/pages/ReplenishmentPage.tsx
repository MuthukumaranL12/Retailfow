import { useEffect, useState } from 'react'
import { approveReplenishment, getReplenishment, modifyReplenishment, rejectReplenishment } from '../api'

type Recommendation = { recommendation_id: string; store_id: string; product_id: string; recommended_qty: number; forecast_7d: number; current_available: number; incoming: number; status: string }

export function ReplenishmentPage() {
  const [items, setItems] = useState<Recommendation[]>([])
  const [quantities, setQuantities] = useState<Record<string, number>>({})
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState('')

  const load = async () => {
    setError('')
    const response = await getReplenishment()
    setItems(response.data.items)
    setQuantities(Object.fromEntries(response.data.items.map((item: Recommendation) => [item.recommendation_id, item.recommended_qty])))
  }

  useEffect(() => {
    load().catch(() => setError('Could not load replenishment recommendations.')).finally(() => setLoading(false))
  }, [])

  const act = async (id: string, action: 'approve' | 'reject' | 'modify') => {
    setBusy(id)
    setError('')
    try {
      if (action === 'approve') await approveReplenishment(id)
      else if (action === 'reject') await rejectReplenishment(id)
      else await modifyReplenishment(id, quantities[id])
      await load()
    } catch (cause) {
      const detail = (cause as { response?: { data?: { detail?: string } } }).response?.data?.detail
      setError(detail ?? `Could not ${action} the recommendation.`)
    } finally {
      setBusy('')
    }
  }

  return (
    <div className="space-y-5">
      <header>
        <p className="text-sm uppercase tracking-wider text-blue-400">Inventory planning</p>
        <h2 className="text-3xl font-bold text-white">Replenishment</h2>
      </header>
      {error && <p role="alert" className="rounded-xl border border-red-800 bg-red-950/50 p-3 text-sm text-red-300">{error}</p>}
      {loading ? <p className="text-slate-400">Loading recommendations…</p> : items.length === 0 ? <p className="text-slate-400">No replenishment recommendations are currently needed.</p> : (
        <div className="space-y-3">
          {items.map((item) => (
            <article key={item.recommendation_id} className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-slate-800 bg-slate-900 p-4">
              <div><h3 className="font-medium text-white">{item.product_id} · {item.store_id}</h3><p className="mt-1 text-xs text-slate-400">7-day demand {item.forecast_7d} · available {item.current_available} · incoming {item.incoming} · {item.status}</p></div>
              <div className="flex flex-wrap items-center gap-2">
                <label className="text-xs text-slate-400">Quantity<input aria-label={`Quantity for ${item.recommendation_id}`} type="number" min={1} value={quantities[item.recommendation_id] ?? item.recommended_qty} onChange={(event) => setQuantities((previous) => ({ ...previous, [item.recommendation_id]: Number(event.target.value) }))} className="ml-2 w-24 rounded-lg border border-slate-700 bg-slate-950 px-2 py-2 text-white" /></label>
                {item.status === 'PENDING' && <>
                  <button disabled={busy === item.recommendation_id} onClick={() => void act(item.recommendation_id, 'modify')} className="rounded-lg border border-slate-700 px-3 py-2 text-xs text-slate-200 disabled:opacity-50">Save quantity</button>
                  <button disabled={busy === item.recommendation_id} onClick={() => void act(item.recommendation_id, 'approve')} className="rounded-lg bg-emerald-700 px-3 py-2 text-xs text-white disabled:opacity-50">Approve</button>
                  <button disabled={busy === item.recommendation_id} onClick={() => void act(item.recommendation_id, 'reject')} className="rounded-lg bg-slate-700 px-3 py-2 text-xs text-white disabled:opacity-50">Reject</button>
                </>}
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  )
}
