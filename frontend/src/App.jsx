import { useEffect, useMemo, useState } from 'react'
import UploadForm from './components/UploadForm.jsx'
import JobList from './components/JobList.jsx'

export default function App() {
  const apiBase = useMemo(() => {
    return '/api'
  }, [])

  const [jobIds, setJobIds] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem('jobIds') || '[]')
    } catch {
      return []
    }
  })

  const [jobs, setJobs] = useState([])

  useEffect(() => {
    localStorage.setItem('jobIds', JSON.stringify(jobIds))
  }, [jobIds])

  useEffect(() => {
    if (!jobIds.length) {
      setJobs([])
      return
    }

    let cancelled = false

    async function fetchJobs() {
      const results = []
      const validJobIds = []

      for (const id of jobIds) {
        try {
          const res = await fetch(`${apiBase}/status/${id}`)

          if (res.ok) {
            results.push(await res.json())
            validJobIds.push(id)
          } else if (res.status !== 404) {
            results.push({
              job_id: id,
              status: 'error',
              progress: 100,
              message: 'Erro ao consultar backend.',
            })
            validJobIds.push(id)
          }
        } catch {
          results.push({
            job_id: id,
            status: 'error',
            progress: 100,
            message: 'Erro ao consultar backend.',
          })
          validJobIds.push(id)
        }
      }

      if (!cancelled) {
        setJobs(results)

        if (validJobIds.length !== jobIds.length) {
          setJobIds(validJobIds)
        }
      }
    }

    fetchJobs()

    const timer = setInterval(fetchJobs, 2000)

    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [jobIds, apiBase])

  function handleCreated(jobId) {
    setJobIds((current) => [
      jobId,
      ...current.filter((id) => id !== jobId),
    ])
  }

  async function handleDelete(jobId) {
    try {
      await fetch(`${apiBase}/job/${jobId}`, {
        method: 'DELETE',
      })
    } finally {
      setJobIds((current) =>
        current.filter((id) => id !== jobId),
      )
    }
  }

  return (
    <main className="min-h-screen bg-[#020617] text-white">
      <div className="absolute inset-0 bg-gradient-to-b from-indigo-950/30 via-transparent to-transparent pointer-events-none" />

      <section className="relative max-w-7xl mx-auto px-4 py-10 md:py-14">
        <header className="mb-10">
          <div className="inline-flex items-center gap-2 rounded-full border border-indigo-500/30 bg-indigo-500/10 px-4 py-2 text-sm text-indigo-300 mb-5">
            FFmpeg • FastAPI • Docker • Coolify
          </div>

          <h1 className="text-4xl md:text-6xl font-black leading-tight tracking-tight max-w-5xl">
            Montador Automático
            <span className="block text-indigo-400">
              de Vídeos para YouTube
            </span>
          </h1>

          <p className="mt-6 max-w-3xl text-base md:text-lg text-slate-400 leading-relaxed">
            Envie vídeo, narração, legenda e música.
            O sistema processa automaticamente usando FFmpeg,
            gera MP4 em 1080p e libera o download quando finalizar.
          </p>
        </header>

        <div className="grid grid-cols-1 xl:grid-cols-[420px_1fr] gap-8">
          <div className="space-y-6">
            <div className="rounded-3xl border border-slate-800 bg-slate-950/70 backdrop-blur-xl p-6 shadow-2xl shadow-black/20">
              <UploadForm
                apiBase={apiBase}
                onCreated={handleCreated}
              />
            </div>

            <div className="rounded-3xl border border-slate-800 bg-slate-950/70 backdrop-blur-xl p-6">
              <h3 className="text-lg font-bold mb-3">
                Recursos atuais
              </h3>

              <ul className="space-y-3 text-sm text-slate-400">
                <li>✅ Render MP4 automático</li>
                <li>✅ FFmpeg integrado</li>
                <li>✅ Suporte a legenda</li>
                <li>✅ Música de fundo</li>
                <li>✅ Processamento em fila</li>
                <li>✅ Deploy via Coolify</li>
              </ul>
            </div>
          </div>

          <div className="rounded-3xl border border-slate-800 bg-slate-950/70 backdrop-blur-xl p-6 shadow-2xl shadow-black/20">
            <div className="flex items-center justify-between mb-6">
              <div>
                <h2 className="text-2xl font-black">
                  Tarefas
                </h2>

                <p className="text-slate-400 text-sm mt-1">
                  Status em tempo real das renderizações
                </p>
              </div>

              <div className="rounded-xl border border-slate-800 bg-slate-900 px-4 py-2 text-sm text-slate-300">
                {jobs.length} job(s)
              </div>
            </div>

            <JobList
              jobs={jobs}
              apiBase={apiBase}
              onDelete={handleDelete}
            />
          </div>
        </div>
      </section>
    </main>
  )
}