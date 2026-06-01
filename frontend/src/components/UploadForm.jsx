import { useState } from 'react'

const CHUNK_SIZE_FALLBACK = 10 * 1024 * 1024

export default function UploadForm({ apiBase, onCreated }) {
  const [video, setVideo] = useState(null)
  const [voice, setVoice] = useState(null)
  const [subtitle, setSubtitle] = useState(null)
  const [music, setMusic] = useState(null)
  const [script, setScript] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [uploadProgress, setUploadProgress] = useState(0)
  const [uploadMessage, setUploadMessage] = useState('')

  async function postForm(path, form) {
    const res = await fetch(`${apiBase}${path}`, {
      method: 'POST',
      body: form,
    })

    if (!res.ok) {
      let message = `Falha na requisição ${path}. Status: ${res.status}`
      const contentType = res.headers.get('content-type') || ''

      try {
        if (contentType.includes('application/json')) {
          const data = await res.json()
          message = data.detail || data.message || message
        } else {
          const text = await res.text()
          if (text) {
            message = text
          }
        }
      } catch {
        // mantém a mensagem padrão
      }

      throw new Error(message)
    }

    return res.json()
  }

  async function uploadFileInChunks(file, fileType, onFileProgress) {
    if (!file) {
      return null
    }

    const totalChunks = Math.ceil(file.size / CHUNK_SIZE_FALLBACK)

    const startForm = new FormData()
    startForm.append('filename', file.name)
    startForm.append('file_type', fileType)
    startForm.append('total_size', String(file.size))
    startForm.append('total_chunks', String(totalChunks))

    const startData = await postForm('/upload/start', startForm)

    const uploadId = startData.upload_id
    const chunkSize = startData.chunk_size || CHUNK_SIZE_FALLBACK

    for (let index = 0; index < totalChunks; index += 1) {
      const start = index * chunkSize
      const end = Math.min(start + chunkSize, file.size)
      const blob = file.slice(start, end)

      const chunkForm = new FormData()
      chunkForm.append('upload_id', uploadId)
      chunkForm.append('chunk_index', String(index))
      chunkForm.append('chunk', blob, `${file.name}.part.${index}`)

      await postForm('/upload/chunk', chunkForm)

      const percent = Math.round(((index + 1) / totalChunks) * 100)
      onFileProgress(percent)
    }

    return uploadId
  }

  async function handleSubmit(e) {
    e.preventDefault()

    setError('')
    setSuccess('')
    setUploadProgress(0)
    setUploadMessage('')

    if (!video || !voice) {
      setError('Selecione vídeo e narração.')
      return
    }

    try {
      setLoading(true)

      let completedFiles = 0
      const totalFiles = [video, voice, subtitle, music].filter(Boolean).length

      function updateGlobalProgress(currentFilePercent) {
        const global = Math.round(
          ((completedFiles * 100 + currentFilePercent) / totalFiles)
        )

        setUploadProgress(global)
      }

      setUploadMessage('Enviando vídeo base em partes...')
      const videoUploadId = await uploadFileInChunks(video, 'video', updateGlobalProgress)
      completedFiles += 1
      updateGlobalProgress(0)

      setUploadMessage('Enviando narração em partes...')
      const voiceUploadId = await uploadFileInChunks(voice, 'voice', updateGlobalProgress)
      completedFiles += 1
      updateGlobalProgress(0)

      let subtitleUploadId = null
      if (subtitle) {
        setUploadMessage('Enviando legenda em partes...')
        subtitleUploadId = await uploadFileInChunks(subtitle, 'subtitle', updateGlobalProgress)
        completedFiles += 1
        updateGlobalProgress(0)
      }

      let musicUploadId = null
      if (music) {
        setUploadMessage('Enviando música em partes...')
        musicUploadId = await uploadFileInChunks(music, 'music', updateGlobalProgress)
        completedFiles += 1
        updateGlobalProgress(0)
      }

      setUploadMessage('Montando arquivos no servidor e criando job...')

      const finishForm = new FormData()
      finishForm.append('video_upload_id', videoUploadId)
      finishForm.append('voice_upload_id', voiceUploadId)

      if (subtitleUploadId) {
        finishForm.append('subtitle_upload_id', subtitleUploadId)
      }

      if (musicUploadId) {
        finishForm.append('music_upload_id', musicUploadId)
      }

      if (script.trim()) {
        finishForm.append('script', script)
      }

      const data = await postForm('/upload/finish', finishForm)

      setUploadProgress(100)
      setUploadMessage('')
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
            onChange={(e) => setVideo(e.target.files[0] || null)}
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
            onChange={(e) => setVoice(e.target.files[0] || null)}
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
            onChange={(e) => setSubtitle(e.target.files[0] || null)}
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
            onChange={(e) => setMusic(e.target.files[0] || null)}
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

        {loading && (
          <div className="rounded-2xl border border-indigo-500/30 bg-indigo-500/10 px-4 py-3 text-sm text-indigo-200">
            <div className="mb-2 font-semibold">
              {uploadMessage || 'Enviando arquivos...'}
            </div>

            <div className="h-3 w-full overflow-hidden rounded-full bg-slate-800">
              <div
                className="h-full rounded-full bg-indigo-500 transition-all"
                style={{ width: `${uploadProgress}%` }}
              />
            </div>

            <div className="mt-2 text-xs text-slate-300">
              {uploadProgress}%
            </div>
          </div>
        )}

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
            ? 'Enviando em partes...'
            : 'Gerar Vídeo'}
        </button>
      </form>
    </div>
  )
}