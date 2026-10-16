import { useEffect, useState } from 'react'
import { getDashboardStats } from '../api'

type Summary = Record<string, number | null>

export function AnalyticsPage() {
  const [summary, setSummary] = useState<Summary | null>(null)
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const response = await getDashboardStats({
        ...(start ? { start: new Date(`${start}T00:00:00`).toISOString() } : {}),
        ...(end ? { end: new Date(`${end}T23:59:59`).toISOString() } : {}),
      })
      setSummary(response.data.summary)
    } catch {
      setError('Analytics could not be loaded.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void load() }, [])

  const entries = summary ? [
    ['Orders', summary.total_orders],
    ['Fulfilled orders', summary.fulfilled_orders],
    ['Delayed orders', summary.delayed_orders],
    ['Fulfillment rate', `${summary.fulfillment_rate}%`],
    ['Average delivery duration', `${summary.average_delivery_time_minutes} min`],
    ['Inventory movement ratio', summary.inventory_turnover],
    ['Stockout rate', `${summary.stockout_rate}%`],
    ['Low-stock items', summary.low_stock_items],
    ['Completed deliveries', summary.completed_deliveries],
    ['Delayed deliveries', summary.delayed_deliveries],
    ['Vehicle utilization', `${summary.vehicle_utilization}%`],
  ] : []

  return (
    <div className="space-y-5">
      <header>
        <p className="text-sm uppercase tracking-wider text-blue-400">Operational reporting</p>
        <h2 className="text-3xl font-bold text-white">Analytics</h2>
      </header>
      <form onSubmit={(event) => { event.preventDefault(); void load() }} className="flex flex-wrap items-end gap-3 rounded-2xl border border-slate-800 bg-slate-900 p-4">
        <label className="space-y-1 text-sm text-slate-300">From<input type="date" value={start} onChange={(event) => setStart(event.target.value)} className="block rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white" /></label>
        <label className="space-y-1 text-sm text-slate-300">To<input type="date" value={end} onChange={(event) => setEnd(event.target.value)} className="block rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white" /></label>
        <button disabled={loading} className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">{loading ? 'Updating…' : 'Apply filters'}</button>
      </form>
      {error && <p role="alert" className="rounded-xl border border-red-800 bg-red-950/50 p-3 text-sm text-red-300">{error}</p>}
      {loading && !summary ? <p className="text-slate-400">Loading analytics…</p> : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {entries.map(([label, value]) => (
            <div key={label} className="rounded-2xl border border-slate-800 bg-slate-900 p-5">
              <p className="text-sm text-slate-400">{label}</p>
              <h3 className="mt-3 text-3xl font-bold text-white">{value ?? 'Not available'}</h3>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
