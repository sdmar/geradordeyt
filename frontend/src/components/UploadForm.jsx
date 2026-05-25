import { useState } from 'react'

export default function UploadForm({ onCreated, apiBase }) {
  const [video, setVideo] = useState(null)
  const [voice, setVoice] = useState(null)
  const [subtitle, setSubtitle] = useState(null)
  const [music, setMusic] = useState(null)
  const [script, setScript] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function submit(e) {
    e.preventDefault()
    setError('')

    if (!video || !voice) {
      setError('Envie pelo menos o vídeo base e o áudio de narração.')
      return
    }

    const form = new FormData()
    form.append('video', video)
    form.append('voice', voice)
    if (subtitle) form.append('subtitle', subtitle)
    if (music) form.append('music', music)
    if (script.trim()) form.append('script', script)

    try {
      setLoading(true)
      const res = await fetch(`${apiBase}/upload`, {
        method: 'POST',
        body: form,
      })

      const data = await res.json()

      if (!res.ok) {
        throw new Error(data.detail || 'Erro ao enviar arquivos.')
      }

      onCreated(data.job_id)
      setVideo(null)
      setVoice(null)
      setSubtitle(null)
      setMusic(null)
      setScript('')
      e.target.reset()
    } catch (err) {
      setError(err.message || 'Erro inesperado no upload.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <form onSubmit={submit} className="bg-slate-900 border border-slate-700 rounded-2xl p-6 shadow-xl space-y-5">
      <div>
        <h2 className="text-xl font-bold">Novo vídeo</h2>
        <p className="text-sm text-slate-400">Envie vídeo, narração, legenda e música opcional.</p>
      </div>

      <div className="grid md:grid-cols-2 gap-4">
        <label className="block">
          <span className="text-sm font-medium">Vídeo base *</span>
          <input className="mt-2 block w-full text-sm" type="file" accept=".mp4,.mov,.mkv,.webm" onChange={(e) => setVideo(e.target.files[0])} />
        </label>

        <label className="block">
          <span className="text-sm font-medium">Narração *</span>
          <input className="mt-2 block w-full text-sm" type="file" accept=".mp3,.wav,.m4a,.aac" onChange={(e) => setVoice(e.target.files[0])} />
        </label>

        <label className="block">
          <span className="text-sm font-medium">Legenda opcional</span>
          <input className="mt-2 block w-full text-sm" type="file" accept=".srt,.ass" onChange={(e) => setSubtitle(e.target.files[0])} />
        </label>

        <label className="block">
          <span className="text-sm font-medium">Música de fundo opcional</span>
          <input className="mt-2 block w-full text-sm" type="file" accept=".mp3,.wav,.m4a,.aac" onChange={(e) => setMusic(e.target.files[0])} />
        </label>
      </div>

      <label className="block">
        <span className="text-sm font-medium">Roteiro opcional</span>
        <textarea
          className="mt-2 w-full rounded-xl bg-slate-800 border border-slate-700 p-3 text-sm min-h-28"
          value={script}
          onChange={(e) => setScript(e.target.value)}
          placeholder="Cole aqui o roteiro, observações ou descrição do vídeo..."
        />
      </label>

      {error && <div className="rounded-xl bg-red-950 border border-red-700 p-3 text-sm text-red-200">{error}</div>}

      <button
        disabled={loading}
        className="w-full md:w-auto px-6 py-3 rounded-xl bg-emerald-500 text-slate-950 font-bold hover:bg-emerald-400 disabled:opacity-60"
      >
        {loading ? 'Enviando...' : 'Gerar vídeo'}
      </button>
    </form>
  )
}
