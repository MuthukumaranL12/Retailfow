import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getDeliveries } from '../api'

type LiveDelivery = {
  delivery_id: string
  order_id: string
  status: string
  vehicle_id: string
  current_location?: { lat?: number; lng?: number; name?: string }
  updated_at?: string
  eta_minutes?: number
}

export function LiveMapPage() {
  const [deliveries, setDeliveries] = useState<LiveDelivery[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setError('')
    try {
      const { data } = await getDeliveries()
      setDeliveries(data.items)
    } catch {
      setError('Live vehicle locations could not be loaded.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
    const timer = window.setInterval(() => void load(), 15000)
    return () => window.clearInterval(timer)
  }, [load])

  const active = deliveries.filter((delivery) => !['COMPLETED', 'CANCELLED'].includes(delivery.status.toUpperCase()))

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div><p className="text-sm uppercase tracking-wider text-blue-400">Vehicle tracking</p><h2 className="text-3xl font-bold text-white">Live Map</h2><p className="mt-2 text-sm text-slate-400">Live coordinates refresh every 15 seconds; location data is sourced from active deliveries.</p></div>
        <button onClick={() => void load()} className="rounded-lg border border-slate-700 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800">Refresh now</button>
      </header>
      {error && <p role="alert" className="rounded-xl border border-red-800 bg-red-950/50 p-3 text-sm text-red-300">{error}</p>}
      {loading ? <p className="text-slate-400">Loading vehicle positions…</p> : active.length === 0 ? (
        <p className="rounded-2xl border border-slate-800 bg-slate-900 p-5 text-sm text-slate-400">No active deliveries have a live vehicle position right now.</p>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {active.map((delivery) => (
            <article key={delivery.delivery_id} className="rounded-2xl border border-slate-800 bg-slate-900 p-5">
              <div className="flex items-start justify-between gap-2"><h3 className="font-semibold text-white">{delivery.vehicle_id}</h3><span className="rounded-full bg-blue-950 px-2 py-1 text-xs text-blue-300">{delivery.status}</span></div>
              <p className="mt-2 text-sm text-slate-400">Order {delivery.order_id}</p>
              <p className="mt-4 text-sm text-slate-200">{delivery.current_location?.name ?? 'Current position'}</p>
              <p className="mt-1 font-mono text-xs text-slate-400">{delivery.current_location?.lat ?? '—'}, {delivery.current_location?.lng ?? '—'}</p>
              <p className="mt-3 text-xs text-slate-500">Updated {delivery.updated_at ? new Date(delivery.updated_at).toLocaleTimeString() : 'timestamp unavailable'}{delivery.eta_minutes == null ? '' : ` · ETA ${delivery.eta_minutes} min`}</p>
              <Link to="/deliveries" className="mt-4 inline-block text-sm text-blue-400 hover:text-blue-300">Open delivery control →</Link>
            </article>
          ))}
        </div>
      )}
    </div>
  )
}
