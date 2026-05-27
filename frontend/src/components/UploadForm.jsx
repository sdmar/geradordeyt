import { useState } from 'react'

export default function UploadForm({ apiBase, onCreated }) {
  const [video, setVideo] = useState(null)
  const [voice, setVoice] = useState(null)
  const [subtitle, setSubtitle] = useState(null)
  const [music, setMusic] = useState(null)
  const [script, setScript] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  async function handleSubmit(e) {
    e.preventDefault()

    setError('')
    setSuccess('')

    if (!video || !voice) {
      setError('Selecione vídeo e narração.')
      return
    }

    try {
      setLoading(true)

      const form = new FormData()

      form.append('video', video)
      form.append('voice', voice)

      if (subtitle) {
        form.append('subtitle', subtitle)
      }

      if (music) {
        form.append('music', music)
      }

      if (script.trim()) {
        form.append('script', script)
      }

      const res = await fetch(`${apiBase}/upload`, {
        method: 'POST',
        body: form,
      })

      if (!res.ok) {
        throw new Error('Falha no upload.')
      }

      const data = await res.json()

      setSuccess('Job criado com sucesso.')

      onCreated(data.job_id)

      setVideo(null)
      setVoice(null)
      setSubtitle(null)
      setMusic(null)
      setScript('')

      document.getElementById('video-input').value = ''
      document.getElementById('voice-input').value = ''
      document.getElementById('subtitle-input').value = ''
      document.getElementById('music-input').value = ''

    } catch (err) {
      setError(err.message || 'Erro inesperado.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <div className="mb-6">
        <h2 className="text-2xl font-black">
          Novo Projeto
        </h2>

        <p className="text-slate-400 text-sm mt-2">
          Envie os arquivos necessários para gerar o vídeo final.
        </p>
      </div>

      <form
        onSubmit={handleSubmit}
        className="space-y-5"
      >

        <div>
          <label className="block mb-2 text-sm font-semibold text-slate-300">
            Vídeo Base *
          </label>

          <input
            id="video-input"
            type="file"
            accept="video/*"
            onChange={(e) => setVideo(e.target.files[0])}
            className="w-full rounded-2xl border border-slate-800 bg-slate-900 p-4 text-sm"
          />
        </div>

        <div>
          <label className="block mb-2 text-sm font-semibold text-slate-300">
            Narração *
          </label>

          <input
            id="voice-input"
            type="file"
            accept="audio/*"
            onChange={(e) => setVoice(e.target.files[0])}
            className="w-full rounded-2xl border border-slate-800 bg-slate-900 p-4 text-sm"
          />
        </div>

        <div>
          <label className="block mb-2 text-sm font-semibold text-slate-300">
            Legenda
          </label>

          <input
            id="subtitle-input"
            type="file"
            accept=".srt,.ass"
            onChange={(e) => setSubtitle(e.target.files[0])}
            className="w-full rounded-2xl border border-slate-800 bg-slate-900 p-4 text-sm"
          />
        </div>

        <div>
          <label className="block mb-2 text-sm font-semibold text-slate-300">
            Música de Fundo
          </label>

          <input
            id="music-input"
            type="file"
            accept="audio/*"
            onChange={(e) => setMusic(e.target.files[0])}
            className="w-full rounded-2xl border border-slate-800 bg-slate-900 p-4 text-sm"
          />
        </div>

        <div>
          <label className="block mb-2 text-sm font-semibold text-slate-300">
            Roteiro / Observações
          </label>

          <textarea
            rows="5"
            value={script}
            onChange={(e) => setScript(e.target.value)}
            placeholder="Observações opcionais..."
            className="w-full rounded-2xl border border-slate-800 bg-slate-900 p-4 text-sm outline-none focus:border-indigo-500"
          />
        </div>

        {error && (
          <div className="rounded-2xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
            {error}
          </div>
        )}

        {success && (
          <div className="rounded-2xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-300">
            {success}
          </div>
        )}

        <button
          type="submit"
          disabled={loading}
          className="w-full rounded-2xl bg-indigo-600 px-6 py-4 text-sm font-bold transition hover:bg-indigo-500 disabled:opacity-50"
        >
          {loading
            ? 'Processando...'
            : 'Gerar Vídeo'}
        </button>

      </form>
    </div>
  )
}