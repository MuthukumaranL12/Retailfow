import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getOrders } from '../api'
import type { Order } from '../types'

export function FulfillmentPage() {
  const [orders, setOrders] = useState<Order[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    getOrders()
      .then(({ data }) => setOrders(data.items))
      .catch(() => setError('Fulfillment decisions could not be loaded.'))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="space-y-5">
      <header><p className="text-sm uppercase tracking-wider text-blue-400">Assignment decisions</p><h2 className="text-3xl font-bold text-white">Fulfillment</h2><p className="mt-2 text-sm text-slate-400">Location, selection rationale, assigned products and delivery ETA from actual orders.</p></header>
      {error && <p role="alert" className="rounded-xl border border-red-800 bg-red-950/50 p-3 text-sm text-red-300">{error}</p>}
      {loading ? <p className="text-slate-400">Loading fulfillment activity…</p> : orders.length === 0 ? (
        <p className="rounded-2xl border border-slate-800 bg-slate-900 p-5 text-sm text-slate-400">No fulfillment orders are available for your account.</p>
      ) : (
        <div className="space-y-3">
          {orders.map((order) => (
            <article key={order.order_id} className="rounded-2xl border border-slate-800 bg-slate-900 p-5">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div><Link to={`/orders/${encodeURIComponent(order.order_id)}`} className="font-semibold text-blue-300 hover:text-blue-200">{order.order_id}</Link><p className="mt-1 text-xs text-slate-500">{order.status} · {order.customer_id}</p></div>
                <div className="text-right"><p className="text-sm text-white">{order.fulfillment_location ?? 'Unassigned'}</p><p className="text-xs text-slate-400">{order.delivery_details?.eta_minutes == null ? 'ETA unavailable' : `${order.delivery_details.eta_minutes} min ETA`}</p></div>
              </div>
              <div className="mt-4 flex flex-wrap gap-2">{order.items?.map((item) => <span key={item.product_id} className="rounded-full bg-slate-800 px-3 py-1 text-xs text-slate-300">{item.product_id} × {item.quantity}</span>)}</div>
              <p className="mt-3 text-sm text-slate-400">{order.fulfillment_decision?.reasons?.join(' · ') || 'No fulfillment decision recorded for this order.'}</p>
              {order.fulfillment_decision?.score != null && <p className="mt-1 text-xs text-slate-500">Decision score: {order.fulfillment_decision.score}</p>}
            </article>
          ))}
        </div>
      )}
    </div>
  )
}
