import { useEffect, useState } from 'react'
import { getInventory } from '../api'

export function InventoryPage() {
  const [items, setItems] = useState<any[]>([])

  useEffect(() => {
    const load = async () => {
      const result = await getInventory()
      setItems(result.data.items ?? [])
    }
    load().catch(() => undefined)
  }, [])

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-3xl font-bold text-white">Inventory</h2>
      </div>

      <div className="overflow-hidden rounded-2xl border border-slate-800 bg-slate-900">
        <table className="min-w-full divide-y divide-slate-800 text-left text-sm text-slate-300">
          <thead className="bg-slate-950 text-slate-400">
            <tr>
              <th className="px-4 py-3">Store</th>
              <th>Product</th>
              <th>On hand</th>
              <th>Reserved</th>
              <th>Available</th>
              <th>Reorder point</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={`${item.store_id}-${item.product_id}`} className="border-t border-slate-800">
                <td className="px-4 py-3">{item.store_id}</td>
                <td>{item.product_id}</td>
                <td>{item.on_hand}</td>
                <td>{item.reserved}</td>
                <td>{Math.max(item.on_hand - item.reserved, 0)}</td>
                <td>{item.reorder_point}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
