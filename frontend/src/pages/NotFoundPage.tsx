export function NotFoundPage() {
  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <div className="rounded-2xl border border-slate-800 bg-slate-900 p-8 text-center">
        <h2 className="text-2xl font-bold text-white">Page not found</h2>
        <p className="mt-2 text-slate-400">The route you requested is unavailable.</p>
      </div>
    </div>
  )
}
