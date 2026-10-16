import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getDashboardStats, getStockoutRisks } from '../api'

type Summary = {
  total_orders: number
  fulfilled_orders: number
  delayed_orders: number
  fulfillment_rate: number
  average_delivery_time_minutes: number
  inventory_turnover: number
  stockout_rate: number
  low_stock_items: number
  vehicle_utilization: number
}
type Risk = { store_id: string; product_id: string; risk: string; available: number; estimated_stockout_date: string | null }

export function DashboardPage() {
  const [summary, setSummary] = useState<Summary | null>(null)
  const [risks, setRisks] = useState<Risk[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    Promise.all([getDashboardStats(), getStockoutRisks()])
      .then(([statsResponse, riskResponse]) => {
        setSummary(statsResponse.data.summary)
        setRisks(riskResponse.data.items)
      })
      .catch(() => setError('Dashboard data is unavailable. Check API and database health.'))
      .finally(() => setLoading(false))
  }, [])

  const cards = summary ? [
    { label: 'Orders', value: summary.total_orders },
    { label: 'Fulfilled', value: summary.fulfilled_orders },
    { label: 'Delayed', value: summary.delayed_orders },
    { label: 'Fulfillment rate', value: `${summary.fulfillment_rate}%` },
  ] : []
  const atRisk = risks.filter((risk) => risk.risk !== 'LOW').slice(0, 8)

  return (
    <div className="space-y-6">
      <header>
        <p className="text-sm uppercase tracking-wider text-blue-400">Operations overview</p>
        <h2 className="text-3xl font-bold text-white">Supply chain dashboard</h2>
      </header>
      {error && <p role="alert" className="rounded-xl border border-red-800 bg-red-950/50 p-3 text-sm text-red-300">{error}</p>}
      {loading ? <p className="text-slate-400">Loading live operational metrics…</p> : summary && (
        <>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
            {cards.map((card) => (
              <div key={card.label} className="rounded-2xl border border-slate-800 bg-slate-900 p-5">
                <p className="text-sm text-slate-400">{card.label}</p>
                <h3 className="mt-3 text-3xl font-bold text-white">{card.value}</h3>
              </div>
            ))}
          </div>
          <div className="grid gap-6 xl:grid-cols-2">
            <section className="rounded-2xl border border-slate-800 bg-slate-900 p-5">
              <div className="mb-4 flex items-center justify-between">
                <h3 className="text-lg font-semibold text-white">Highest stockout risks</h3>
                <Link to="/forecasting" className="text-sm text-blue-400 hover:text-blue-300">View forecast</Link>
              </div>
              {atRisk.length === 0 ? <p className="text-sm text-slate-400">No products currently have an elevated stockout risk.</p> : (
                <div className="space-y-2">
                  {atRisk.map((risk) => (
                    <div key={`${risk.store_id}-${risk.product_id}`} className="flex items-center justify-between rounded-lg bg-slate-950 px-3 py-2 text-sm">
                      <span className="text-slate-200">{risk.product_id} <span className="text-slate-500">at {risk.store_id}</span></span>
                      <span className="text-right text-amber-300">{risk.risk} · {risk.estimated_stockout_date ?? 'date unavailable'}</span>
                    </div>
                  ))}
                </div>
              )}
            </section>
            <section className="rounded-2xl border border-slate-800 bg-slate-900 p-5">
              <h3 className="mb-4 text-lg font-semibold text-white">Live network indicators</h3>
              <ul className="space-y-4 text-sm text-slate-300">
                <li className="flex justify-between"><span>Average delivery duration</span><strong className="text-white">{summary.average_delivery_time_minutes} min</strong></li>
                <li className="flex justify-between"><span>Inventory movement ratio</span><strong className="text-white">{summary.inventory_turnover}</strong></li>
                <li className="flex justify-between"><span>Inventory stockout rate</span><strong className="text-white">{summary.stockout_rate}%</strong></li>
                <li className="flex justify-between"><span>Items at/below reorder point</span><strong className="text-white">{summary.low_stock_items}</strong></li>
                <li className="flex justify-between"><span>Active vehicle utilization</span><strong className="text-white">{summary.vehicle_utilization}%</strong></li>
              </ul>
            </section>
          </div>
        </>
      )}
    </div>
  )
}
