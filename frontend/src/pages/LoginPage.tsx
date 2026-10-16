import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { login } from '../api'

export function LoginPage() {
  const navigate = useNavigate()
  const [email, setEmail] = useState('admin@retailflow.local')
  const [password, setPassword] = useState('admin123')
  const [error, setError] = useState('')

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault()
    try {
      const result = await login(email, password)
      localStorage.setItem('retailflow_token', result.access_token)
      localStorage.setItem('retailflow_user', JSON.stringify(result.user))
      navigate('/dashboard')
    } catch (err) {
      setError('Authentication failed. Please try the demo credentials.')
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950 p-6">
      <div className="w-full max-w-md rounded-2xl border border-slate-800 bg-slate-900 p-8 shadow-2xl">
        <div className="mb-6 text-center">
          <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-blue-600 text-xl font-bold text-white">R</div>
          <h1 className="text-2xl font-bold text-white">RetailFlow</h1>
          <p className="mt-2 text-sm text-slate-400">Supply chain command center</p>
        </div>

        <form className="space-y-4" onSubmit={handleSubmit}>
          <div>
            <label className="mb-1 block text-sm text-slate-300">Email</label>
            <input value={email} onChange={(e) => setEmail(e.target.value)} className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none" />
          </div>
          <div>
            <label className="mb-1 block text-sm text-slate-300">Password</label>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none" />
          </div>

          {error && <div className="rounded-xl border border-red-500 bg-red-500/10 px-3 py-2 text-sm text-red-300">{error}</div>}

          <button type="submit" className="w-full rounded-xl bg-blue-600 px-4 py-3 font-medium text-white hover:bg-blue-500">Sign in</button>
        </form>

        <div className="mt-6 rounded-xl border border-slate-700 bg-slate-950 p-3 text-xs text-slate-400">
          Demo credentials: admin@retailflow.local / admin123
        </div>
      </div>
    </div>
  )
}
