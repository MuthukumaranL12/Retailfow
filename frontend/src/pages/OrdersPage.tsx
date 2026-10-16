import { FormEvent, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { cancelOrder, createOrder, getOrders, getProducts } from '../api'
import type { Order } from '../types'

type Product = { product_id: string; name: string; price: number }

export function OrdersPage() {
  const [orders, setOrders] = useState<Order[]>([])
  const [products, setProducts] = useState<Product[]>([])
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [productId, setProductId] = useState('')
  const [quantity, setQuantity] = useState(1)
  const [customerId, setCustomerId] = useState(() => {
    const user = localStorage.getItem('retailflow_user')
    return user ? JSON.parse(user).email as string : ''
  })
  const [city, setCity] = useState('')
  const [state, setState] = useState('')
  const [latitude, setLatitude] = useState('')
  const [longitude, setLongitude] = useState('')

  const loadData = async () => {
    setError('')
    try {
      const [orderResponse, productResponse] = await Promise.all([getOrders(), getProducts()])
      setOrders(orderResponse.data.items)
      setProducts(productResponse.data.items)
      if (!productId && productResponse.data.items.length) setProductId(productResponse.data.items[0].product_id)
    } catch {
      setError('Could not load orders or products. Check your connection and try again.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadData()
  }, [])

  const submitOrder = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setSubmitting(true)
    setError('')
    setNotice('')
    try {
      const response = await createOrder({
        customer_id: customerId.trim(),
        items: [{ product_id: productId, quantity }],
        delivery_address: {
          city: city.trim() || undefined,
          state: state.trim() || undefined,
          lat: Number(latitude),
          lng: Number(longitude),
        },
      })
      setNotice(`Order ${response.data.order.order_id} assigned to ${response.data.order.fulfillment_location}.`)
      await loadData()
    } catch (cause) {
      const detail = (cause as { response?: { data?: { detail?: string } } }).response?.data?.detail
      setError(detail ?? 'Order could not be placed. Please verify inventory and delivery coordinates.')
    } finally {
      setSubmitting(false)
    }
  }

  const cancel = async (orderId: string) => {
    setError('')
    try {
      await cancelOrder(orderId)
      await loadData()
    } catch (cause) {
      const detail = (cause as { response?: { data?: { detail?: string } } }).response?.data?.detail
      setError(detail ?? 'This order cannot be cancelled.')
    }
  }

  return (
    <div className="space-y-6">
      <header>
        <p className="text-sm uppercase tracking-wider text-blue-400">Order management</p>
        <h2 className="text-3xl font-bold text-white">Orders</h2>
      </header>

      <section className="rounded-2xl border border-slate-800 bg-slate-900 p-5">
        <h3 className="mb-4 text-lg font-semibold text-white">Create and fulfill an order</h3>
        <form onSubmit={submitOrder} className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <label className="space-y-1 text-sm text-slate-300">
            Customer ID
            <input required value={customerId} onChange={(event) => setCustomerId(event.target.value)} className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white" />
          </label>
          <label className="space-y-1 text-sm text-slate-300">
            Product
            <select required value={productId} onChange={(event) => setProductId(event.target.value)} className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white">
              {products.map((product) => <option key={product.product_id} value={product.product_id}>{product.name} ({product.product_id})</option>)}
            </select>
          </label>
          <label className="space-y-1 text-sm text-slate-300">
            Quantity
            <input required min={1} type="number" value={quantity} onChange={(event) => setQuantity(Number(event.target.value))} className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white" />
          </label>
          <label className="space-y-1 text-sm text-slate-300">
            City
            <input value={city} onChange={(event) => setCity(event.target.value)} className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white" />
          </label>
          <label className="space-y-1 text-sm text-slate-300">
            State / region
            <input value={state} onChange={(event) => setState(event.target.value)} className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white" />
          </label>
          <label className="space-y-1 text-sm text-slate-300">
            Delivery latitude
            <input required type="number" step="any" min={-90} max={90} value={latitude} onChange={(event) => setLatitude(event.target.value)} className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white" />
          </label>
          <label className="space-y-1 text-sm text-slate-300">
            Delivery longitude
            <input required type="number" step="any" min={-180} max={180} value={longitude} onChange={(event) => setLongitude(event.target.value)} className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white" />
          </label>
          <div className="flex items-end">
            <button disabled={submitting || !products.length} className="w-full rounded-lg bg-blue-600 px-4 py-2 font-medium text-white hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-50">
              {submitting ? 'Assigning fulfillment…' : 'Place order'}
            </button>
          </div>
        </form>
        {error && <p role="alert" className="mt-4 rounded-lg border border-red-800 bg-red-950/50 p-3 text-sm text-red-300">{error}</p>}
        {notice && <p role="status" className="mt-4 rounded-lg border border-emerald-800 bg-emerald-950/50 p-3 text-sm text-emerald-300">{notice}</p>}
      </section>

      <section className="overflow-hidden rounded-2xl border border-slate-800 bg-slate-900">
        <div className="border-b border-slate-800 px-4 py-3 font-semibold text-white">Recent orders</div>
        {loading ? <p className="p-5 text-slate-400">Loading orders…</p> : orders.length === 0 ? <p className="p-5 text-slate-400">No orders found.</p> : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-800 text-left text-sm text-slate-300">
              <thead className="bg-slate-950 text-slate-400">
                <tr><th className="px-4 py-3">Order ID</th><th>Customer</th><th>Status</th><th>Fulfillment</th><th>Vehicle / route</th><th>ETA</th><th>Action</th></tr>
              </thead>
              <tbody>
                {orders.map((order) => (
                  <tr key={order.order_id} className="border-t border-slate-800">
                    <td className="px-4 py-3 font-medium"><Link to={`/orders/${encodeURIComponent(order.order_id)}`} className="text-blue-300 hover:text-blue-200">{order.order_id}</Link></td>
                    <td>{order.customer_id}</td>
                    <td><span className="rounded-full bg-blue-500/10 px-2 py-1 text-xs text-blue-300">{order.status}</span></td>
                    <td>{order.fulfillment_location ?? 'Pending assignment'}</td>
                    <td>{order.vehicle_id ?? '—'}{order.route_id ? ` / ${order.route_id}` : ''}</td>
                    <td>{order.delivery_details?.eta_minutes != null ? `${Math.round(order.delivery_details.eta_minutes)} min` : '—'}</td>
                    <td>{order.status === 'ASSIGNED' && <button onClick={() => void cancel(order.order_id)} className="text-xs text-red-300 hover:text-red-200">Cancel</button>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}
