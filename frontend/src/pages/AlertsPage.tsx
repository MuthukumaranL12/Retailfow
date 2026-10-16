import { useEffect, useState } from 'react'
import { acknowledgeAlert, getAlerts, resolveAlert } from '../api'

type Alert = {
  alert_id: string
  title: string
  message: string
  severity: string
  acknowledged: boolean
  resolved?: boolean
  created_at?: string
}

const severityStyle: Record<string, string> = {
  CRITICAL: 'border-red-700 bg-red-950/40 text-red-300',
  HIGH: 'border-orange-700 bg-orange-950/40 text-orange-300',
  WARNING: 'border-amber-700 bg-amber-950/40 text-amber-300',
  INFO: 'border-blue-700 bg-blue-950/40 text-blue-300',
}

export function AlertsPage() {
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = async () => {
    setError('')
    try {
      const response = await getAlerts()
      setAlerts(response.data.items)
    } catch {
      setError('Alerts could not be loaded.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void load() }, [])

  const updateAlert = async (id: string, action: 'acknowledge' | 'resolve') => {
    setError('')
    try {
      if (action === 'acknowledge') await acknowledgeAlert(id)
      else await resolveAlert(id)
      await load()
    } catch {
      setError(`Could not ${action} this alert.`)
    }
  }

  return (
    <div className="space-y-4">
      <header>
        <p className="text-sm uppercase tracking-wider text-blue-400">Exceptions & action queue</p>
        <h2 className="text-3xl font-bold text-white">Alerts</h2>
      </header>
      {error && <p role="alert" className="rounded-xl border border-red-800 bg-red-950/50 p-3 text-sm text-red-300">{error}</p>}
      {loading ? <p className="text-slate-400">Loading alerts…</p> : alerts.length === 0 ? <p className="text-slate-400">No alerts found.</p> : (
        <div className="space-y-3">
          {alerts.map((alert) => (
            <article key={alert.alert_id} className="rounded-2xl border border-slate-800 bg-slate-900 p-4">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <div className="mb-2 flex items-center gap-2">
                    <span className={`rounded-full border px-2 py-1 text-xs font-medium ${severityStyle[alert.severity] ?? severityStyle.INFO}`}>{alert.severity}</span>
                    <span className="text-xs text-slate-500">{alert.alert_id}</span>
                    {alert.acknowledged && <span className="text-xs text-emerald-400">Acknowledged</span>}
                    {alert.resolved && <span className="text-xs text-slate-400">Resolved</span>}
                  </div>
                  <h3 className="font-medium text-white">{alert.title}</h3>
                  <p className="mt-1 text-sm text-slate-300">{alert.message}</p>
                  <p className="mt-2 text-xs text-slate-500">{alert.created_at ? new Date(alert.created_at).toLocaleString() : ''}</p>
                </div>
                {!alert.resolved && <div className="flex gap-2">
                  {!alert.acknowledged && <button onClick={() => void updateAlert(alert.alert_id, 'acknowledge')} className="rounded-lg border border-slate-700 px-3 py-2 text-xs text-slate-200 hover:bg-slate-800">Acknowledge</button>}
                  <button onClick={() => void updateAlert(alert.alert_id, 'resolve')} className="rounded-lg bg-blue-600 px-3 py-2 text-xs text-white hover:bg-blue-500">Resolve</button>
                </div>}
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  )
}
