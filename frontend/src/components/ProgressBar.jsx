export default function ProgressBar({ progress = 0 }) {
  const safeProgress = Math.min(100, Math.max(0, Number(progress) || 0))

  return (
    <div className="w-full rounded-full bg-slate-700 h-3 overflow-hidden">
      <div
        className="h-3 bg-emerald-500 transition-all duration-500"
        style={{ width: `${safeProgress}%` }}
      />
    </div>
  )
}
