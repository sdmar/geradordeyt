import { useEffect, useMemo, useState } from 'react'
import UploadForm from './components/UploadForm.jsx'
import JobList from './components/JobList.jsx'

export default function App() {
  const apiBase = useMemo(() => {
    return import.meta.env.VITE_API_BASE_URL || '/api'
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
      for (const id of jobIds) {
        try {
          const res = await fetch(`${apiBase}/status/${id}`)
          if (res.ok) {
            results.push(await res.json())
          }
        } catch {
          results.push({
            job_id: id,
            status: 'error',
            progress: 100,
            message: 'Não foi possível consultar o backend.',
          })
        }
      }
      if (!cancelled) setJobs(results)
    }

    fetchJobs()
    const timer = setInterval(fetchJobs, 2000)

    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [jobIds, apiBase])

  function handleCreated(jobId) {
    setJobIds((current) => [jobId, ...current.filter((id) => id !== jobId)])
  }

  async function handleDelete(jobId) {
    try {
      await fetch(`${apiBase}/job/${jobId}`, { method: 'DELETE' })
    } finally {
      setJobIds((current) => current.filter((id) => id !== jobId))
    }
  }

  return (
    <main className="min-h-screen">
      <section className="max-w-5xl mx-auto px-4 py-10 space-y-8">
        <header className="space-y-3">
          <p className="text-emerald-400 font-semibold">FFmpeg + FastAPI + Docker</p>
          <h1 className="text-3xl md:text-5xl font-black tracking-tight">
            Gerador automático de vídeos para YouTube
          </h1>
          <p className="text-slate-400 max-w-3xl">
            Envie vídeo base, narração, legenda e música. O sistema processa em fila com Celery,
            gera MP4 em 1080p e libera o download quando finalizar.
          </p>
        </header>

        <UploadForm apiBase={apiBase} onCreated={handleCreated} />

        <section className="space-y-4">
          <h2 className="text-2xl font-bold">Tarefas</h2>
          <JobList jobs={jobs} apiBase={apiBase} onDelete={handleDelete} />
        </section>
      </section>
    </main>
  )
}
