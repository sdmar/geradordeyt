import ProgressBar from './ProgressBar.jsx'

export default function JobList({
  jobs,
  apiBase,
  onDelete,
}) {
  if (!jobs.length) {
    return (
      <div className="rounded-3xl border border-dashed border-slate-800 p-10 text-center">
        <p className="text-slate-400">
          Nenhuma tarefa criada ainda.
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-5">
      {jobs.map((job) => {
        const statusColor = {
          pending: 'text-yellow-400',
          processing: 'text-blue-400',
          completed: 'text-emerald-400',
          error: 'text-red-400',
        }

        const progress =
          typeof job.progress === 'number'
            ? job.progress
            : 0

        return (
          <div
            key={job.job_id}
            className="rounded-3xl border border-slate-800 bg-slate-900/60 p-5"
          >

            <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">

              <div className="flex-1">

                <div className="flex flex-wrap items-center gap-3 mb-3">
                  <h3 className="text-lg font-bold">
                    Job
                  </h3>

                  <span
                    className={`text-sm font-semibold capitalize ${
                      statusColor[job.status] ||
                      'text-slate-300'
                    }`}
                  >
                    {job.status}
                  </span>
                </div>

                <div className="mb-4 rounded-2xl border border-slate-800 bg-slate-950 p-3">
                  <p className="break-all text-xs text-slate-400">
                    {job.job_id}
                  </p>
                </div>

                <ProgressBar progress={progress} />

                {job.message && (
                  <p className="mt-4 text-sm text-slate-400">
                    {job.message}
                  </p>
                )}

              </div>

              <div className="flex flex-col gap-3 md:w-[180px]">

                {job.status === 'completed' && (
                  <a
                    href={`${apiBase}/download/${job.job_id}`}
                    className="rounded-2xl bg-emerald-600 px-5 py-3 text-center text-sm font-bold transition hover:bg-emerald-500"
                  >
                    Download
                  </a>
                )}

                <button
                  onClick={() => onDelete(job.job_id)}
                  className="rounded-2xl border border-red-500/30 bg-red-500/10 px-5 py-3 text-sm font-bold text-red-300 transition hover:bg-red-500/20"
                >
                  Remover
                </button>

              </div>

            </div>

          </div>
        )
      })}
    </div>
  )
}