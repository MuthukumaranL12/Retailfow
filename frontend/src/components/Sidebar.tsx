import { Activity, AlertTriangle, BarChart3, Bot, Boxes, Building2, ClipboardCheck, ClipboardList, Map, MapPin, Package, TrendingUp, Truck, Warehouse } from 'lucide-react'
import { NavLink } from 'react-router-dom'

const items = [
  { label: 'Dashboard', to: '/dashboard', icon: Activity },
  { label: 'Orders', to: '/orders', icon: ClipboardList },
  { label: 'Fulfillment', to: '/fulfillment', icon: ClipboardCheck },
  { label: 'Inventory', to: '/inventory', icon: Boxes },
  { label: 'Products', to: '/products', icon: Package },
  { label: 'Stores', to: '/stores', icon: Warehouse },
  { label: 'Warehouses', to: '/warehouses', icon: Building2 },
  { label: 'Deliveries', to: '/deliveries', icon: Truck },
  { label: 'Live Map', to: '/live-map', icon: MapPin },
  { label: 'Routes', to: '/routes', icon: Map },
  { label: 'Forecasting', to: '/forecasting', icon: TrendingUp },
  { label: 'Replenishment', to: '/replenishment', icon: ClipboardCheck },
  { label: 'Analytics', to: '/analytics', icon: BarChart3 },
  { label: 'Alerts', to: '/alerts', icon: AlertTriangle },
  { label: 'RetailFlow Copilot', to: '/copilot', icon: Bot },
]

export function Sidebar() {
  return (
    <aside className="hidden min-h-screen w-64 border-r border-slate-800 bg-slate-950/80 p-5 lg:block">
      <div className="mb-8 flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-600 font-bold text-white">R</div>
        <div>
          <h1 className="text-lg font-semibold text-white">RetailFlow</h1>
          <p className="text-xs text-slate-400">Control Tower</p>
        </div>
      </div>

      <nav className="space-y-2">
        {items.map(({ label, to, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              `flex items-center gap-3 rounded-xl px-3 py-2 text-sm transition ${
                isActive ? 'bg-blue-600 text-white' : 'text-slate-300 hover:bg-slate-800 hover:text-white'
              }`
            }
          >
            <Icon size={16} />
            {label}
          </NavLink>
        ))}
      </nav>
    </aside>
  )
}
