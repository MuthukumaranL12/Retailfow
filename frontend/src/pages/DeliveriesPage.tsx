import { useEffect, useMemo, useState } from 'react'
import { advanceDelivery, completeDelivery, deliveryWebSocketUrl, getDeliveries, getDelivery, getDeliveryLiveTicket, startDelivery } from '../api'

type Point = { name: string; lat: number; lng: number }
type Delivery = {
  delivery_id: string
  order_id: string
  status: string
  progress: number
  eta_minutes: number
  current_location?: Point
  route_id: string
}
type RouteData = { starting_location: Point; stops: Array<Point & { status: string }> }

const wait = (duration: number) => new Promise((resolve) => window.setTimeout(resolve, duration))

export function DeliveriesPage() {
  const [deliveries, setDeliveries] = useState<Delivery[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [route, setRoute] = useState<RouteData | null>(null)
  const [livePoint, setLivePoint] = useState<Point | null>(null)
  const [loading, setLoading] = useState(true)
  const [simulating, setSimulating] = useState(false)
  const [error, setError] = useState('')

  const refresh = async () => {
    const response = await getDeliveries()
    const rows = response.data.items as Delivery[]
    setDeliveries(rows)
    if (!selectedId && rows.length) setSelectedId(rows[0].delivery_id)
  }

  useEffect(() => {
    refresh().catch(() => setError('Could not load delivery data.'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    if (!selectedId) return
    getDelivery(selectedId).then(({ data }) => {
      setRoute(data.route)
      setLivePoint(data.delivery.current_location ?? data.route?.starting_location ?? null)
    }).catch(() => setError('Could not load the selected route.'))
  }, [selectedId])

  useEffect(() => {
    if (!selectedId) return
    let socket: WebSocket | undefined
    let cancelled = false
    getDeliveryLiveTicket(selectedId).then(({ data }) => {
      if (cancelled) return
      socket = new WebSocket(deliveryWebSocketUrl(selectedId, data.ticket))
      socket.onmessage = (event) => {
        const update = JSON.parse(event.data) as { current_location?: Point; progress?: number; eta_minutes?: number }
        if (update.current_location) setLivePoint(update.current_location)
        setDeliveries((rows) => rows.map((row) => row.delivery_id === selectedId ? { ...row, ...update } : row))
      }
    }).catch(() => setError('Live tracking connection could not be authorized.'))
    return () => {
      cancelled = true
      socket?.close()
    }
  }, [selectedId])

  const selected = deliveries.find((delivery) => delivery.delivery_id === selectedId)
  const mapPoints = useMemo(() => {
    const points = [route?.starting_location, ...(route?.stops ?? []), livePoint].filter((point): point is Point => Boolean(point))
    if (!points.length) return []
    const lats = points.map((point) => point.lat)
    const lngs = points.map((point) => point.lng)
    const minLat = Math.min(...lats)
    const maxLat = Math.max(...lats)
    const minLng = Math.min(...lngs)
    const maxLng = Math.max(...lngs)
    const latSpan = maxLat - minLat || 0.01
    const lngSpan = maxLng - minLng || 0.01
    return points.map((point) => ({
      ...point,
      x: 40 + ((point.lng - minLng) / lngSpan) * 520,
      y: 250 - ((point.lat - minLat) / latSpan) * 210,
    }))
  }, [route, livePoint])
  const lastMapPoint = mapPoints[mapPoints.length - 1]

  const runSimulation = async () => {
    if (!selected) return
    setSimulating(true)
    setError('')
    try {
      if (selected.status === 'ASSIGNED') await startDelivery(selected.delivery_id)
      for (let step = 0; step < 5; step += 1) {
        const { data } = await advanceDelivery(selected.delivery_id)
        setLivePoint(data.current_location)
        setDeliveries((rows) => rows.map((row) => row.delivery_id === selected.delivery_id ? { ...row, ...data } : row))
        if (data.progress >= 1) break
        await wait(350)
      }
      await completeDelivery(selected.delivery_id)
      await refresh()
    } catch (cause) {
      const detail = (cause as { response?: { data?: { detail?: string } } }).response?.data?.detail
      setError(detail ?? 'Delivery simulation failed.')
    } finally {
      setSimulating(false)
    }
  }

  return (
    <div className="space-y-6">
      <header>
        <p className="text-sm uppercase tracking-wider text-blue-400">Fleet operations</p>
        <h2 className="text-3xl font-bold text-white">Deliveries & live tracking</h2>
      </header>
      {error && <p role="alert" className="rounded-lg border border-red-800 bg-red-950/50 p-3 text-sm text-red-300">{error}</p>}
      <div className="grid gap-6 xl:grid-cols-[340px_1fr]">
        <section className="rounded-2xl border border-slate-800 bg-slate-900 p-4">
          <h3 className="mb-3 font-semibold text-white">Delivery queue</h3>
          {loading ? <p className="text-sm text-slate-400">Loading…</p> : deliveries.length === 0 ? <p className="text-sm text-slate-400">No deliveries recorded.</p> : (
            <div className="space-y-2">
              {deliveries.map((delivery) => (
                <button key={delivery.delivery_id} onClick={() => setSelectedId(delivery.delivery_id)} className={`w-full rounded-xl border p-3 text-left ${selectedId === delivery.delivery_id ? 'border-blue-500 bg-blue-950/40' : 'border-slate-800 bg-slate-950 hover:border-slate-600'}`}>
                  <div className="flex justify-between gap-2 text-sm font-medium text-white"><span>{delivery.delivery_id}</span><span className="text-blue-300">{delivery.status}</span></div>
                  <p className="mt-1 text-xs text-slate-400">Order {delivery.order_id} · {Math.round((delivery.progress ?? 0) * 100)}% · {Math.round(delivery.eta_minutes ?? 0)} min ETA</p>
                </button>
              ))}
            </div>
          )}
        </section>
        <section className="rounded-2xl border border-slate-800 bg-slate-900 p-4">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div>
              <h3 className="font-semibold text-white">{selected ? `Route ${selected.route_id}` : 'Live route map'}</h3>
              <p className="text-sm text-slate-400">{selected ? `${selected.delivery_id} · ${selected.status}` : 'Select a delivery to inspect'}</p>
            </div>
            {selected && ['ASSIGNED', 'IN_TRANSIT'].includes(selected.status) && (
              <button disabled={simulating} onClick={runSimulation} className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">
                {simulating ? 'Vehicle moving…' : selected.status === 'ASSIGNED' ? 'Start delivery simulation' : 'Continue simulation'}
              </button>
            )}
          </div>
          {mapPoints.length ? (
            <svg viewBox="0 0 600 300" role="img" aria-label="Route map showing current vehicle and delivery stops" className="h-[320px] w-full rounded-xl border border-slate-800 bg-slate-950">
              {mapPoints.length > 1 && <polyline points={mapPoints.slice(0, -1).map((point) => `${point.x},${point.y}`).join(' ')} fill="none" stroke="#3b82f6" strokeWidth="4" strokeDasharray="8 7" />}
              {mapPoints.slice(0, -1).map((point, index) => <circle key={`${point.name}-${index}`} cx={point.x} cy={point.y} r="7" fill={index === 0 ? '#22c55e' : '#94a3b8'} />)}
              {lastMapPoint && <g><circle cx={lastMapPoint.x} cy={lastMapPoint.y} r="10" fill="#f59e0b" /><text x={lastMapPoint.x + 12} y={lastMapPoint.y - 10} fill="#e2e8f0" fontSize="12">Vehicle</text></g>}
              {mapPoints.slice(0, -1).map((point, index) => <text key={`label-${point.name}-${index}`} x={point.x + 9} y={point.y + 4} fill="#cbd5e1" fontSize="11">{index === 0 ? 'Start' : point.name}</text>)}
            </svg>
          ) : <p className="rounded-xl border border-slate-800 bg-slate-950 p-8 text-center text-slate-400">Route coordinates will appear when a delivery has a generated route.</p>}
          {route && <div className="mt-4 flex flex-wrap gap-4 text-xs text-slate-400"><span>Origin: {route.starting_location.name}</span>{route.stops.map((stop) => <span key={stop.name}>Stop: {stop.name} · {stop.status}</span>)}{livePoint && <span>Live coordinates: {livePoint.lat.toFixed(4)}, {livePoint.lng.toFixed(4)}</span>}</div>}
        </section>
      </div>
    </div>
  )
}
