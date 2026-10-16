import { useEffect, useState } from 'react'
import { getProducts } from '../api'

type Product = {
  product_id: string
  sku: string
  name: string
  category: string
  price: number
  weight_kg?: number
}

export function ProductsPage() {
  const [products, setProducts] = useState<Product[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    getProducts()
      .then(({ data }) => setProducts(data.items))
      .catch(() => setError('Products could not be loaded from the service.'))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="space-y-4">
      <header>
        <p className="text-sm uppercase tracking-wider text-blue-400">Catalog</p>
        <h2 className="text-3xl font-bold text-white">Products</h2>
      </header>
      {loading && <p className="text-slate-400">Loading products…</p>}
      {error && <p role="alert" className="rounded-xl border border-red-800 bg-red-950/50 p-3 text-sm text-red-300">{error}</p>}
      {!loading && !error && products.length === 0 && <p className="text-slate-400">No products found.</p>}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {products.map((product) => (
          <div key={product.product_id} className="rounded-2xl border border-slate-800 bg-slate-900 p-5">
            <div className="mb-2 text-xs uppercase tracking-[0.2em] text-blue-400">{product.category}</div>
            <h3 className="text-xl font-semibold text-white">{product.name}</h3>
            <div className="mt-4 flex items-center justify-between text-sm text-slate-300">
              <span>{product.sku}</span>
              <span className="font-medium text-blue-400">{new Intl.NumberFormat(undefined, { style: 'currency', currency: 'USD' }).format(product.price)}</span>
            </div>
            <p className="mt-2 text-xs text-slate-500">{product.product_id}{product.weight_kg != null ? ` · ${product.weight_kg} kg` : ''}</p>
          </div>
        ))}
      </div>
    </div>
  )
}
