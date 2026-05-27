export default function ProgressBar({
  progress = 0,
}) {
  const safeProgress = Math.min(
    100,
    Math.max(0, progress),
  )

  return (
    <div>
      <div className="mb-2 flex items-center justify-between text-xs text-slate-400">
        <span>Progresso</span>

        <span>
          {safeProgress}%
        </span>
      </div>

      <div className="h-3 overflow-hidden rounded-full bg-slate-800">
        <div
          className="h-full rounded-full bg-indigo-500 transition-all duration-500"
          style={{
            width: `${safeProgress}%`,
          }}
        />
      </div>
    </div>
  )
}
