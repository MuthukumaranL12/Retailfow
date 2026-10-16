import { Navigate, Route, Routes } from 'react-router-dom'
import { ChatbotPanel } from './components/ChatbotPanel'
import { Sidebar } from './components/Sidebar'
import { AlertsPage } from './pages/AlertsPage'
import { AnalyticsPage } from './pages/AnalyticsPage'
import { DashboardPage } from './pages/DashboardPage'
import { DeliveriesPage } from './pages/DeliveriesPage'
import { ForecastingPage } from './pages/ForecastingPage'
import { FulfillmentPage } from './pages/FulfillmentPage'
import { CopilotPage } from './pages/CopilotPage'
import { InventoryPage } from './pages/InventoryPage'
import { LiveMapPage } from './pages/LiveMapPage'
import { LoginPage } from './pages/LoginPage'
import { NotFoundPage } from './pages/NotFoundPage'
import { OrderDetailsPage } from './pages/OrderDetailsPage'
import { OrdersPage } from './pages/OrdersPage'
import { ProductsPage } from './pages/ProductsPage'
import { ReplenishmentPage } from './pages/ReplenishmentPage'
import { RoutesPage } from './pages/RoutesPage'
import { StoresPage } from './pages/StoresPage'
import { WarehouseDetailPage, WarehousesPage } from './pages/WarehousesPage'

function Layout({ children, showCopilot = true }: { children: React.ReactNode; showCopilot?: boolean }) {
  if (!localStorage.getItem('retailflow_token')) return <Navigate to="/login" replace />

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <div className="flex">
        <Sidebar />
        <main className="flex-1 p-6 lg:p-8">
          {children}
        </main>
      </div>
      {showCopilot && <ChatbotPanel />}
    </div>
  )
}

export default function App() {
  const isAuthenticated = Boolean(localStorage.getItem('retailflow_token'))

  return (
    <Routes>
      <Route path="/" element={isAuthenticated ? <Navigate to="/dashboard" replace /> : <LoginPage />} />
      <Route path="/login" element={isAuthenticated ? <Navigate to="/dashboard" replace /> : <LoginPage />} />
      <Route path="/dashboard" element={<Layout><DashboardPage /></Layout>} />
      <Route path="/orders" element={<Layout><OrdersPage /></Layout>} />
      <Route path="/orders/:orderId" element={<Layout><OrderDetailsPage /></Layout>} />
      <Route path="/fulfillment" element={<Layout><FulfillmentPage /></Layout>} />
      <Route path="/deliveries" element={<Layout><DeliveriesPage /></Layout>} />
      <Route path="/live-map" element={<Layout><LiveMapPage /></Layout>} />
      <Route path="/forecasting" element={<Layout><ForecastingPage /></Layout>} />
      <Route path="/replenishment" element={<Layout><ReplenishmentPage /></Layout>} />
      <Route path="/routes" element={<Layout><RoutesPage /></Layout>} />
      <Route path="/stores" element={<Layout><StoresPage /></Layout>} />
      <Route path="/warehouses" element={<Layout><WarehousesPage /></Layout>} />
      <Route path="/warehouses/:warehouseId" element={<Layout><WarehouseDetailPage /></Layout>} />
      <Route path="/inventory" element={<Layout><InventoryPage /></Layout>} />
      <Route path="/products" element={<Layout><ProductsPage /></Layout>} />
      <Route path="/analytics" element={<Layout><AnalyticsPage /></Layout>} />
      <Route path="/alerts" element={<Layout><AlertsPage /></Layout>} />
      <Route path="/copilot" element={<Layout showCopilot={false}><CopilotPage /></Layout>} />
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  )
}
