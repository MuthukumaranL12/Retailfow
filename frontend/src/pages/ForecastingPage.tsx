import { useEffect, useMemo, useState } from 'react'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { getForecast, getProducts, getStockoutRisks } from '../api'

type Product = { product_id: string; name: string }
type Forecast = { actual_daily: number[]; forecast_daily: number; forecast_7d: number; baseline_7d: number; forecast_30d: number; mae: number; rmse: number; sample_days: number }
type Risk = { product_id: string; store_id: string; risk: string; available: number; estimated_stockout_date: string | null; days_to_stockout: number | null }

export function ForecastingPage() {
  const [products, setProducts] = useState<Product[]>([])
  const [productId, setProductId] = useState('')
  const [forecast, setForecast] = useState<Forecast | null>(null)
  const [risks, setRisks] = useState<Risk[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([getProducts(), getStockoutRisks()])
      .then(([productResponse, riskResponse]) => {
        setProducts(productResponse.data.items)
        setRisks(riskResponse.data.items)
        if (productResponse.data.items.length) setProductId(productResponse.data.items[0].product_id)
      })
      .catch(() => setError('Forecast data could not be loaded.'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    if (!productId) return
    getForecast(productId)
      .then(({ data }) => setForecast(data.forecast))
      .catch(() => setError('Could not generate this product forecast.'))
  }, [productId])

  const chartData = useMemo(() => {
    if (!forecast) return []
    const recent = forecast.actual_daily.slice(-14)
    const history: Array<{ period: string; actual: number | null; forecast: number | null }> = recent.map((actual, index) => ({
      period: `-${recent.length - index}d`,
      actual,
      forecast: null,
    }))
    const projection = Array.from({ length: 7 }, (_, index) => ({
        period: `+${index + 1}d`,
        actual: null,
        forecast: forecast.forecast_daily,
      }))
    return [...history, ...projection]
  }, [forecast])

  return (
    <div className="space-y-6">
      <header>
        <p className="text-sm uppercase tracking-wider text-blue-400">Demand planning</p>
        <h2 className="text-3xl font-bold text-white">Forecasting & stockout risk</h2>
      </header>
      {error && <p role="alert" className="rounded-xl border border-red-800 bg-red-950/50 p-3 text-sm text-red-300">{error}</p>}
      <section className="rounded-2xl border border-slate-800 bg-slate-900 p-5">
        <label className="mb-4 block max-w-sm space-y-1 text-sm text-slate-300">Product
          <select value={productId} onChange={(event) => setProductId(event.target.value)} className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white">
            {products.map((product) => <option key={product.product_id} value={product.product_id}>{product.name} ({product.product_id})</option>)}
          </select>
        </label>
        {loading ? <p className="text-slate-400">Loading historical sales…</p> : forecast && (
          <>
            <div className="mb-5 grid gap-3 md:grid-cols-2 xl:grid-cols-5">
              {[['7-day forecast', forecast.forecast_7d], ['7-day moving average', forecast.baseline_7d], ['30-day forecast', forecast.forecast_30d], ['MAE', forecast.mae], ['RMSE', forecast.rmse]].map(([label, value]) => (
                <div key={label} className="rounded-xl bg-slate-950 p-3"><p className="text-xs text-slate-400">{label}</p><strong className="mt-1 block text-xl text-white">{value}</strong></div>
              ))}
            </div>
            <p className="mb-2 text-xs text-slate-500">Based on {forecast.sample_days} daily sales observations; actual history and projected daily demand.</p>
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartData}><CartesianGrid strokeDasharray="3 3" stroke="#334155" /><XAxis dataKey="period" stroke="#94a3b8" /><YAxis stroke="#94a3b8" /><Tooltip /><Line dataKey="actual" name="Actual sales" stroke="#22c55e" connectNulls={false} /><Line dataKey="forecast" name="Forecast" stroke="#3b82f6" strokeDasharray="5 5" connectNulls={false} /></LineChart>
              </ResponsiveContainer>
            </div>
          </>
        )}
      </section>
      <section className="rounded-2xl border border-slate-800 bg-slate-900 p-5">
        <h3 className="mb-3 text-lg font-semibold text-white">Stockout risk by location</h3>
        <div className="overflow-x-auto">
          <table className="min-w-full text-left text-sm text-slate-300">
            <thead className="text-slate-400"><tr><th className="py-2">Risk</th><th>Store</th><th>Product</th><th>Available</th><th>Days to stockout</th><th>Estimated date</th></tr></thead>
            <tbody>{risks.map((risk) => <tr key={`${risk.store_id}-${risk.product_id}`} className="border-t border-slate-800"><td className="py-2 font-medium text-amber-300">{risk.risk}</td><td>{risk.store_id}</td><td>{risk.product_id}</td><td>{risk.available}</td><td>{risk.days_to_stockout ?? '—'}</td><td>{risk.estimated_stockout_date ?? '—'}</td></tr>)}</tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
