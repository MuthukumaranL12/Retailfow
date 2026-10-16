import axios from 'axios'

export const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

const api = axios.create({ baseURL: apiBaseUrl })

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('retailflow_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

export const login = async (email: string, password: string) => {
  const response = await api.post('/api/v1/auth/login', { email, password })
  return response.data
}

export const getDashboardStats = async (params?: Record<string, string>) => api.get('/api/v1/analytics/dashboard', { params })
export const getInventory = async () => api.get('/api/v1/inventory')
export const getOrders = async () => api.get('/api/v1/orders')
export const getOrder = async (orderId: string) => api.get(`/api/v1/orders/${encodeURIComponent(orderId)}`)
export const getFulfillmentDecision = async (orderId: string) => api.get(`/api/v1/orders/${encodeURIComponent(orderId)}/fulfillment`)
export const getProducts = async () => api.get('/api/v1/products')
export const getDeliveries = async () => api.get('/api/v1/deliveries')
export const getRoutes = async () => api.get('/api/v1/routes')
export const getStores = async () => api.get('/api/v1/stores')
export const getWarehouses = async () => api.get('/api/v1/warehouses')
export const getWarehouse = async (warehouseId: string) =>
  api.get(`/api/v1/warehouses/${encodeURIComponent(warehouseId)}`)
export const getWarehouseDecisions = async (warehouseId: string) =>
  api.get(`/api/v1/warehouses/${encodeURIComponent(warehouseId)}/decisions`)
export const compareWarehouses = async (warehouseIds: string[]) =>
  api.get('/api/v1/warehouses/compare', {
    params: { warehouse_ids: warehouseIds },
    paramsSerializer: { indexes: null },
  })
export const getDelivery = async (deliveryId: string) => api.get(`/api/v1/deliveries/${deliveryId}`)
export const getDeliveryLiveTicket = async (deliveryId: string) => api.post(`/api/v1/deliveries/${deliveryId}/live-ticket`)
export const getAlerts = async () => api.get('/api/v1/alerts')
export const acknowledgeAlert = async (alertId: string) => api.post(`/api/v1/alerts/${alertId}/acknowledge`)
export const resolveAlert = async (alertId: string) => api.post(`/api/v1/alerts/${alertId}/resolve`)
export const getForecast = async (productId: string, storeId?: string) => api.get(`/api/v1/forecast/${productId}`, { params: storeId ? { store_id: storeId } : undefined })
export const getStockoutRisks = async () => api.get('/api/v1/forecast/risks')
export const getReplenishment = async () => api.get('/api/v1/replenishment')
export const approveReplenishment = async (id: string) => api.post(`/api/v1/replenishment/${encodeURIComponent(id)}/approve`)
export const rejectReplenishment = async (id: string) => api.post(`/api/v1/replenishment/${encodeURIComponent(id)}/reject`)
export const modifyReplenishment = async (id: string, quantity: number) => api.post(`/api/v1/replenishment/${encodeURIComponent(id)}/modify`, { quantity })
export const createOrder = async (order: {
  customer_id: string
  items: Array<{ product_id: string; quantity: number }>
  delivery_address: { lat: number; lng: number; city?: string; state?: string; label?: string }
}) => api.post('/api/v1/orders', order, { headers: { 'Idempotency-Key': crypto.randomUUID() } })
export const cancelOrder = async (orderId: string) => api.post(`/api/v1/orders/${orderId}/cancel`)
export const startDelivery = async (deliveryId: string) => api.post(`/api/v1/deliveries/${deliveryId}/start`)
export const advanceDelivery = async (deliveryId: string) => api.post(`/api/v1/deliveries/${deliveryId}/advance`)
export const completeDelivery = async (deliveryId: string) => api.post(`/api/v1/deliveries/${deliveryId}/complete`)
export const deliveryWebSocketUrl = (deliveryId: string, ticket: string) => {
  const url = new URL(`/api/v1/deliveries/${deliveryId}/live`, apiBaseUrl)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  url.searchParams.set('ticket', ticket)
  return url.toString()
}
export type ChatPageContext = {
  page: string
  entity_type?: 'order' | 'store' | 'warehouse' | 'product' | 'delivery'
  entity_id?: string
}
export const askChatbot = async (question: string, pageContext?: ChatPageContext, conversationId?: string) =>
  api.post('/api/v1/chat/query', { question, page_context: pageContext, conversation_id: conversationId })
export const getConversations = async () => api.get('/api/v1/chat/conversations')
export const createConversation = async () => api.post('/api/v1/chat/conversations')
export const getConversation = async (id: string) => api.get(`/api/v1/chat/conversations/${encodeURIComponent(id)}`)
export const deleteConversation = async (id: string) => api.delete(`/api/v1/chat/conversations/${encodeURIComponent(id)}`)
export const confirmChatAction = async (conversationId: string, actionId: string, confirmed: boolean) =>
  api.post(`/api/v1/chat/conversations/${encodeURIComponent(conversationId)}/confirm`, { action_id: actionId, confirmed })

export default api
