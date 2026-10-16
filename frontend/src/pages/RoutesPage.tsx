import { useEffect, useState } from 'react'
import { getRoutes } from '../api'

type Route = {
  route_id: string
  delivery_id?: string
  baseline_distance_km: number
  optimized_distance_km: number
  improvement_percent: number
  estimated_minutes: number
  stops: Array<{ stop_id: string; name: string; eta_minutes: number; status: string }>
}

export function RoutesPage() {
  const [routes, setRoutes] = useState<Route[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    getRoutes().then(({ data }) => setRoutes(data.items))
      .catch(() => setError('Route plans could not be loaded.'))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="space-y-5">
      <header>
        <p className="text-sm uppercase tracking-wider text-blue-400">Network planning</p>
        <h2 className="text-3xl font-bold text-white">Optimized routes</h2>
      </header>
      {error && <p role="alert" className="rounded-xl border border-red-800 bg-red-950/50 p-3 text-sm text-red-300">{error}</p>}
      {loading ? <p className="text-slate-400">Loading routes…</p> : routes.length === 0 ? <p className="text-slate-400">No route plans have been generated yet. Create an order to generate a route.</p> : (
        <div className="space-y-3">
          {routes.map((route) => (
            <article key={route.route_id} className="rounded-2xl border border-slate-800 bg-slate-900 p-5">
              <div className="flex flex-wrap items-center justify-between gap-4">
                <div><h3 className="font-semibold text-white">{route.route_id}</h3><p className="text-xs text-slate-500">{route.delivery_id ? `Delivery ${route.delivery_id}` : 'Manually optimized'}</p></div>
                <div className="flex gap-5 text-sm text-slate-300"><span>{route.optimized_distance_km} km</span><span>{Math.round(route.estimated_minutes)} min</span><span className="text-emerald-300">{route.improvement_percent}% saved</span></div>
              </div>
              <ol className="mt-4 flex flex-wrap gap-2">
                {route.stops.map((stop, index) => <li key={stop.stop_id} className="rounded-lg bg-slate-950 px-3 py-2 text-xs text-slate-300">{index + 1}. {stop.name} · ETA {Math.round(stop.eta_minutes)} min · {stop.status}</li>)}
              </ol>
            </article>
          ))}
        </div>
      )}
    </div>
  )
}
