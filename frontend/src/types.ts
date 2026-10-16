export type User = {
  email: string
  role: string
  full_name?: string
}

export type DashboardSummary = {
  summary: {
    total_orders: number
    fulfilled_orders: number
    delayed_orders: number
    fulfillment_rate: number
    average_delivery_time_minutes: number
    inventory_turnover: number
    stockout_rate: number
  }
  kpis: Array<{ label: string; value: number }>
}

export type InventoryItem = {
  _id?: string
  store_id: string
  product_id: string
  on_hand: number
  reserved: number
  incoming: number
  safety_stock: number
  reorder_point: number
  updated_at?: string
}

export type Order = {
  order_id: string
  customer_id: string
  status: string
  fulfillment_location?: string
  vehicle_id?: string
  route_id?: string
  delivery_details?: { eta_minutes?: number; distance_km?: number }
  created_at?: string
  items?: Array<{ product_id: string; quantity: number }>
  delivery_address?: { lat: number; lng: number; city?: string; state?: string; label?: string }
  fulfillment_decision?: {
    selected_location?: string
    score?: number
    reasons?: string[]
    alternatives?: Array<{ location_id: string; score: number; distance_km: number }>
  }
}
