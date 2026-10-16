import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { cancelOrder, getOrder } from '../api'
import type { Order } from '../types'

export function OrderDetailsPage() {
  const { orderId = '' } = useParams()
  const [order, setOrder] = useState<Order | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const response = await getOrder(orderId)
      setOrder(response.data.order)
    } catch {
      setError('Order details could not be loaded or you are not authorized to view this order.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void load() }, [orderId])

  const cancel = async () => {
    if (!order || !window.confirm(`Cancel ${order.order_id}?`)) return
    setSaving(true)
    setError('')
    try {
      const response = await cancelOrder(order.order_id)
      setOrder(response.data.order)
    } catch {
      setError('The order could not be cancelled. It may already be in delivery.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-5">
      <Link to="/orders" className="text-sm text-blue-400 hover:text-blue-300">← All orders</Link>
      {loading ? <p className="text-slate-400">Loading order…</p> : !order ? (
        <p role="alert" className="rounded-xl border border-red-800 bg-red-950/50 p-3 text-sm text-red-300">{error || 'Order not found.'}</p>
      ) : (
        <>
          <header className="flex flex-wrap items-end justify-between gap-3">
            <div><p className="text-sm uppercase tracking-wider text-blue-400">Order details</p><h2 className="text-3xl font-bold text-white">{order.order_id}</h2></div>
            <span className="rounded-full bg-slate-800 px-3 py-1 text-sm text-slate-200">{order.status}</span>
          </header>
          {error && <p role="alert" className="rounded-xl border border-red-800 bg-red-950/50 p-3 text-sm text-red-300">{error}</p>}
          <section className="grid gap-4 md:grid-cols-2">
            <article className="rounded-2xl border border-slate-800 bg-slate-900 p-5">
              <h3 className="mb-3 font-semibold text-white">Fulfillment</h3>
              <dl className="space-y-2 text-sm">
                <div className="flex justify-between gap-3"><dt className="text-slate-400">Location</dt><dd className="text-right text-white">{order.fulfillment_location ?? 'Not assigned'}</dd></div>
                <div className="flex justify-between gap-3"><dt className="text-slate-400">Vehicle</dt><dd className="text-right text-white">{order.vehicle_id ?? 'Not assigned'}</dd></div>
                <div className="flex justify-between gap-3"><dt className="text-slate-400">ETA</dt><dd className="text-right text-white">{order.delivery_details?.eta_minutes == null ? 'Not available' : `${order.delivery_details.eta_minutes} min`}</dd></div>
                <div className="flex justify-between gap-3"><dt className="text-slate-400">Distance</dt><dd className="text-right text-white">{order.delivery_details?.distance_km == null ? 'Not available' : `${order.delivery_details.distance_km} km`}</dd></div>
              </dl>
              {order.fulfillment_decision && (
                <div className="mt-4 border-t border-slate-800 pt-3 text-sm">
                  <p className="font-medium text-slate-200">Assignment rationale</p>
                  <p className="mt-1 text-slate-400">{order.fulfillment_decision.reasons?.join(' · ') || 'No rationale recorded.'}</p>
                  <p className="mt-2 text-xs text-slate-500">Score {order.fulfillment_decision.score ?? 'not recorded'}</p>
                </div>
              )}
            </article>
            <article className="rounded-2xl border border-slate-800 bg-slate-900 p-5">
              <h3 className="mb-3 font-semibold text-white">Customer & destination</h3>
              <p className="text-sm text-slate-300">{order.customer_id}</p>
              {order.delivery_address && <p className="mt-2 text-sm text-slate-400">{order.delivery_address.label || order.delivery_address.city || 'Delivery destination'} · {order.delivery_address.lat}, {order.delivery_address.lng}</p>}
              <p className="mt-4 text-xs text-slate-500">Created {order.created_at ? new Date(order.created_at).toLocaleString() : 'time unavailable'}</p>
            </article>
          </section>
          <section className="rounded-2xl border border-slate-800 bg-slate-900 p-5">
            <h3 className="mb-3 font-semibold text-white">Items</h3>
            {!order.items?.length ? <p className="text-sm text-slate-400">No item details are available.</p> : (
              <ul className="divide-y divide-slate-800">
                {order.items.map((item) => <li key={item.product_id} className="flex justify-between py-3 text-sm"><span className="text-slate-200">{item.product_id}</span><span className="text-slate-400">Quantity {item.quantity}</span></li>)}
              </ul>
            )}
          </section>
          {['PROCESSING', 'ASSIGNED'].includes(order.status.toUpperCase()) && (
            <button disabled={saving} onClick={() => void cancel()} className="rounded-lg border border-red-800 px-4 py-2 text-sm text-red-300 hover:bg-red-950 disabled:opacity-50">
              {saving ? 'Cancelling…' : 'Cancel order'}
            </button>
          )}
        </>
      )}
    </div>
  )
}
