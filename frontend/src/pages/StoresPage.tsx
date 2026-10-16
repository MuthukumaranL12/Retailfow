import { useEffect, useState } from 'react'
import { getStores } from '../api'

type Store = { store_id: string; name: string; city: string; state: string; region: string; lat: number; lng: number; product_count: number; low_stock_count: number }

export function StoresPage() {
  const [stores, setStores] = useState<Store[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    getStores().then(({ data }) => setStores(data.items))
      .catch(() => setError('Store locations could not be loaded.'))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="space-y-5">
      <header><p className="text-sm uppercase tracking-wider text-blue-400">Fulfillment network</p><h2 className="text-3xl font-bold text-white">Stores & fulfillment locations</h2></header>
      {error && <p role="alert" className="rounded-xl border border-red-800 bg-red-950/50 p-3 text-sm text-red-300">{error}</p>}
      {loading ? <p className="text-slate-400">Loading locations…</p> : stores.length === 0 ? <p className="text-slate-400">No locations found.</p> : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {stores.map((store) => (
            <article key={store.store_id} className="rounded-2xl border border-slate-800 bg-slate-900 p-5">
              <p className="text-xs uppercase tracking-wider text-blue-400">{store.region}</p>
              <h3 className="mt-2 text-lg font-semibold text-white">{store.name}</h3>
              <p className="text-sm text-slate-400">{store.city}, {store.state} · {store.store_id}</p>
              <div className="mt-4 flex justify-between text-sm"><span className="text-slate-400">Catalog lines</span><strong className="text-white">{store.product_count}</strong></div>
              <div className="mt-2 flex justify-between text-sm"><span className="text-slate-400">At/below reorder point</span><strong className={store.low_stock_count ? 'text-amber-300' : 'text-emerald-300'}>{store.low_stock_count}</strong></div>
              <p className="mt-3 text-xs text-slate-500">Coordinates: {store.lat.toFixed(4)}, {store.lng.toFixed(4)}</p>
            </article>
          ))}
        </div>
      )}
    </div>
  )
}
