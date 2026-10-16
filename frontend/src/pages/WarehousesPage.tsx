import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, Building2, GitCompareArrows } from 'lucide-react'
import { compareWarehouses, getWarehouse, getWarehouseDecisions, getWarehouses } from '../api'

type Warehouse = {
  warehouse_id: string
  name: string
  status: string
  city?: string
  state?: string
  region?: string
  address?: string
}

type Summary = {
  inventory: {
    product_count: number
    on_hand_units: number
    reserved_units: number
    available_units: number
    low_stock_items: number
    stockout_items: number
  }
  orders: { total: number; active: number; completed: number; completion_rate: number | null }
  deliveries: {
    total: number
    active: number
    completed: number
    delayed: number
    average_duration_minutes: number | null
  }
  alerts: { total: number; open: number; critical: number }
}

type WarehouseListItem = Warehouse & { summary: Summary }
type ComparisonItem = { warehouse: Warehouse; summary: Summary }
type InventoryRow = { product_id: string; on_hand: number; reserved: number; reorder_point?: number }
type OrderDecision = {
  order_id: string
  status?: string
  decision?: { selected_location?: string; score?: number; reasons?: string[] }
  items?: Array<{ product_id: string; quantity: number }>
}

const formatNumber = (value: number) => new Intl.NumberFormat().format(value)
const formatRate = (value: number | null) => value == null ? '—' : `${value}%`

function Metric({ label, value, detail }: { label: string; value: string | number; detail?: string }) {
  return (
    <article className="rounded-2xl border border-slate-800 bg-slate-900 p-5">
      <p className="text-sm text-slate-400">{label}</p>
      <p className="mt-2 text-2xl font-bold text-white">{value}</p>
      {detail && <p className="mt-1 text-xs text-slate-500">{detail}</p>}
    </article>
  )
}

function WarehouseCard({ warehouse }: { warehouse: WarehouseListItem }) {
  const summary = warehouse.summary
  return (
    <Link
      to={`/warehouses/${encodeURIComponent(warehouse.warehouse_id)}`}
      className="block rounded-2xl border border-slate-800 bg-slate-900 p-5 transition hover:border-blue-700"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-wider text-blue-400">{warehouse.region || warehouse.warehouse_id}</p>
          <h3 className="mt-2 text-lg font-semibold text-white">{warehouse.name}</h3>
          <p className="mt-1 text-sm text-slate-400">
            {[warehouse.city, warehouse.state].filter(Boolean).join(', ') || 'Location not provided'}
          </p>
        </div>
        <span className="rounded-full bg-slate-800 px-2.5 py-1 text-xs text-slate-300">{warehouse.status}</span>
      </div>
      <div className="mt-5 grid grid-cols-2 gap-3 text-sm">
        <div><span className="block text-slate-500">Available units</span><strong className="text-white">{formatNumber(summary.inventory.available_units)}</strong></div>
        <div><span className="block text-slate-500">Orders</span><strong className="text-white">{formatNumber(summary.orders.total)}</strong></div>
        <div><span className="block text-slate-500">Low stock / stockout</span><strong className="text-amber-300">{summary.inventory.low_stock_items} / {summary.inventory.stockout_items}</strong></div>
        <div><span className="block text-slate-500">Delayed deliveries</span><strong className="text-white">{summary.deliveries.delayed}</strong></div>
      </div>
    </Link>
  )
}

export function WarehousesPage() {
  const [warehouses, setWarehouses] = useState<WarehouseListItem[]>([])
  const [selected, setSelected] = useState<string[]>([])
  const [comparison, setComparison] = useState<ComparisonItem[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [comparing, setComparing] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    getWarehouses()
      .then(({ data }) => setWarehouses(data.items))
      .catch(() => setError('Warehouses could not be loaded.'))
      .finally(() => setLoading(false))
  }, [])

  const toggleSelected = (warehouseId: string) => {
    setComparison(null)
    setSelected((current) => current.includes(warehouseId)
      ? current.filter((id) => id !== warehouseId)
      : current.length < 10 ? [...current, warehouseId] : current)
  }

  const compare = async () => {
    setComparing(true)
    setError('')
    try {
      const { data } = await compareWarehouses(selected)
      setComparison(data.items)
    } catch {
      setError('Warehouse comparison could not be loaded.')
    } finally {
      setComparing(false)
    }
  }

  return (
    <div className="space-y-5">
      <header>
        <p className="text-sm uppercase tracking-wider text-blue-400">Fulfillment network</p>
        <h2 className="mt-1 text-3xl font-bold text-white">Warehouses</h2>
        <p className="mt-2 text-sm text-slate-400">Inventory, fulfillment outcomes, delivery performance, and alerts by distribution center.</p>
      </header>
      {error && <p role="alert" className="rounded-xl border border-red-800 bg-red-950/50 p-3 text-sm text-red-300">{error}</p>}
      {loading ? <p className="text-slate-400">Loading warehouses…</p> : warehouses.length === 0 ? (
        <p className="rounded-2xl border border-slate-800 bg-slate-900 p-5 text-sm text-slate-400">No warehouses are available for your account.</p>
      ) : (
        <>
          <section className="rounded-2xl border border-slate-800 bg-slate-900 p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-sm text-slate-300">Select 2–10 sites to compare their current operational metrics.</p>
              <button
                disabled={selected.length < 2 || comparing}
                onClick={() => void compare()}
                className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50"
              >
                <GitCompareArrows size={16} />{comparing ? 'Comparing…' : `Compare (${selected.length})`}
              </button>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              {warehouses.map((warehouse) => (
                <label key={warehouse.warehouse_id} className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-slate-700 px-3 py-2 text-xs text-slate-300">
                  <input type="checkbox" checked={selected.includes(warehouse.warehouse_id)} onChange={() => toggleSelected(warehouse.warehouse_id)} />
                  {warehouse.name}
                </label>
              ))}
            </div>
          </section>
          {comparison && (
            <section className="overflow-x-auto rounded-2xl border border-slate-800 bg-slate-900 p-4">
              <h3 className="mb-3 font-semibold text-white">Warehouse comparison</h3>
              <table className="w-full min-w-[680px] text-left text-sm">
                <thead className="text-xs uppercase text-slate-500"><tr><th className="p-2">Warehouse</th><th className="p-2">Available units</th><th className="p-2">Low stock</th><th className="p-2">Stockouts</th><th className="p-2">Orders completed</th><th className="p-2">Delayed deliveries</th><th className="p-2">Open alerts</th></tr></thead>
                <tbody>{comparison.map(({ warehouse, summary }) => (
                  <tr key={warehouse.warehouse_id} className="border-t border-slate-800 text-slate-300">
                    <td className="p-2"><Link className="text-blue-300 hover:text-blue-200" to={`/warehouses/${encodeURIComponent(warehouse.warehouse_id)}`}>{warehouse.name}</Link></td>
                    <td className="p-2">{formatNumber(summary.inventory.available_units)}</td><td className="p-2">{summary.inventory.low_stock_items}</td><td className="p-2">{summary.inventory.stockout_items}</td><td className="p-2">{summary.orders.completed}/{summary.orders.total} ({formatRate(summary.orders.completion_rate)})</td><td className="p-2">{summary.deliveries.delayed}</td><td className="p-2">{summary.alerts.open}</td>
                  </tr>
                ))}</tbody>
              </table>
            </section>
          )}
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {warehouses.map((warehouse) => (
              <div key={warehouse.warehouse_id} className="relative">
                <WarehouseCard warehouse={warehouse} />
                <label className="absolute right-4 top-4 flex items-center gap-2 rounded bg-slate-950/90 px-2 py-1 text-xs text-slate-300" onClick={(event) => event.stopPropagation()}>
                  <input type="checkbox" checked={selected.includes(warehouse.warehouse_id)} onChange={() => toggleSelected(warehouse.warehouse_id)} />
                  Compare
                </label>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

export function WarehouseDetailPage() {
  const { warehouseId = '' } = useParams()
  const [dashboard, setDashboard] = useState<{ warehouse: Warehouse; summary: Summary; inventory_items: InventoryRow[]; orders: Array<Record<string, unknown>>; deliveries: Array<Record<string, unknown>>; alerts: Array<Record<string, unknown>> } | null>(null)
  const [decisions, setDecisions] = useState<OrderDecision[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    setLoading(true)
    setError('')
    Promise.all([getWarehouse(warehouseId), getWarehouseDecisions(warehouseId)])
      .then(([warehouseResponse, decisionResponse]) => {
        setDashboard(warehouseResponse.data)
        setDecisions(decisionResponse.data.items)
      })
      .catch(() => setError('Warehouse performance details could not be loaded.'))
      .finally(() => setLoading(false))
  }, [warehouseId])

  if (loading) return <p className="text-slate-400">Loading warehouse performance…</p>
  if (error || !dashboard) return (
    <div className="space-y-4">
      <Link to="/warehouses" className="inline-flex items-center gap-2 text-sm text-blue-300"><ArrowLeft size={16} />All warehouses</Link>
      <p role="alert" className="rounded-xl border border-red-800 bg-red-950/50 p-3 text-sm text-red-300">{error || 'Warehouse not found.'}</p>
    </div>
  )

  const { warehouse, summary } = dashboard
  return (
    <div className="space-y-6">
      <Link to="/warehouses" className="inline-flex items-center gap-2 text-sm text-blue-300 hover:text-blue-200"><ArrowLeft size={16} />All warehouses</Link>
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div><p className="text-sm uppercase tracking-wider text-blue-400">{warehouse.region || warehouse.warehouse_id}</p><h2 className="mt-1 text-3xl font-bold text-white">{warehouse.name}</h2><p className="mt-2 text-sm text-slate-400">{[warehouse.city, warehouse.state].filter(Boolean).join(', ') || warehouse.address || 'Location not provided'} · {warehouse.status}</p></div>
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-3 text-slate-300"><Building2 size={20} /><span className="mt-1 block text-xs">{warehouse.warehouse_id}</span></div>
      </header>
      <section>
        <h3 className="mb-3 text-lg font-semibold text-white">Inventory</h3>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          <Metric label="Product lines" value={formatNumber(summary.inventory.product_count)} />
          <Metric label="On hand" value={formatNumber(summary.inventory.on_hand_units)} detail="units" />
          <Metric label="Reserved" value={formatNumber(summary.inventory.reserved_units)} detail="units" />
          <Metric label="Available" value={formatNumber(summary.inventory.available_units)} detail="units" />
          <Metric label="Low stock" value={summary.inventory.low_stock_items} detail="Positive availability at or below reorder point" />
          <Metric label="Stockouts" value={summary.inventory.stockout_items} detail="No available units" />
        </div>
      </section>
      <section>
        <h3 className="mb-3 text-lg font-semibold text-white">Fulfillment & delivery</h3>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Metric label="Orders" value={summary.orders.total} detail={`${summary.orders.active} active · ${summary.orders.completed} completed`} />
          <Metric label="Order completion" value={formatRate(summary.orders.completion_rate)} />
          <Metric label="Delayed deliveries" value={summary.deliveries.delayed} detail={`${summary.deliveries.active} active · ${summary.deliveries.completed} completed`} />
          <Metric label="Average delivery duration" value={summary.deliveries.average_duration_minutes == null ? '—' : `${summary.deliveries.average_duration_minutes} min`} />
        </div>
      </section>
      <section>
        <h3 className="mb-3 text-lg font-semibold text-white">Alerts</h3>
        <div className="grid gap-3 sm:grid-cols-3"><Metric label="Total" value={summary.alerts.total} /><Metric label="Open" value={summary.alerts.open} /><Metric label="Critical" value={summary.alerts.critical} /></div>
      </section>
      <section className="overflow-x-auto rounded-2xl border border-slate-800 bg-slate-900 p-4">
        <h3 className="mb-3 font-semibold text-white">Recent fulfillment decisions</h3>
        {decisions.length === 0 ? <p className="text-sm text-slate-400">No orders have been assigned to this warehouse.</p> : (
          <table className="w-full min-w-[640px] text-left text-sm">
            <thead className="text-xs uppercase text-slate-500"><tr><th className="p-2">Order</th><th className="p-2">Status</th><th className="p-2">Decision score</th><th className="p-2">Items</th><th className="p-2">Rationale</th></tr></thead>
            <tbody>{decisions.map((order) => (
              <tr key={order.order_id} className="border-t border-slate-800 text-slate-300">
                <td className="p-2"><Link className="text-blue-300 hover:text-blue-200" to={`/orders/${encodeURIComponent(order.order_id)}`}>{order.order_id}</Link></td><td className="p-2">{order.status || '—'}</td><td className="p-2">{order.decision?.score ?? '—'}</td><td className="p-2">{order.items?.map((item) => `${item.product_id} × ${item.quantity}`).join(', ') || '—'}</td><td className="p-2">{order.decision?.reasons?.join(' · ') || '—'}</td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </section>
    </div>
  )
}
