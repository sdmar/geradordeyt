import ProgressBar from './ProgressBar.jsx'

export default function JobList({ jobs, apiBase, onDelete }) {
  if (!jobs.length) {
    return (
      <div className="bg-slate-900 border border-slate-700 rounded-2xl p-6 text-slate-400">
        Nenhum job criado ainda.
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {jobs.map((job) => (
        <div key={job.job_id} className="bg-slate-900 border border-slate-700 rounded-2xl p-5 space-y-3">
          <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-2">
            <div>
              <p className="font-bold">Job {job.job_id}</p>
              <p className="text-sm text-slate-400">{job.message || job.status}</p>
            </div>
            <span className="text-xs rounded-full bg-slate-800 px-3 py-1 border border-slate-700 w-fit">
              {job.status}
            </span>
          </div>

          <ProgressBar progress={job.progress} />

          {job.error && (
            <pre className="text-xs bg-red-950 border border-red-800 text-red-100 rounded-xl p-3 overflow-auto max-h-40">
              {job.error}
            </pre>
          )}

          <div className="flex flex-wrap gap-2">
            {job.status === 'completed' && (
              <a
                href={`${apiBase}/download/${job.job_id}`}
                className="px-4 py-2 rounded-xl bg-blue-500 text-white font-semibold hover:bg-blue-400"
              >
                Baixar vídeo
              </a>
            )}

            <button
              onClick={() => onDelete(job.job_id)}
              className="px-4 py-2 rounded-xl bg-slate-800 border border-slate-700 hover:bg-slate-700"
            >
              Limpar job
            </button>
          </div>
        </div>
      ))}
    </div>
  )
}
