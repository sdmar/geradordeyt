# Gerador automático de vídeos para YouTube

Sistema full stack para gerar vídeos MP4 usando FastAPI, Celery, Redis, FFmpeg, React, TailwindCSS e Docker Compose.

## Visão geral

O app recebe:

- vídeo base;
- áudio de narração;
- legenda `.srt` ou `.ass`, opcional;
- música de fundo, opcional;
- roteiro em texto, opcional.

Depois cria um job assíncrono no Celery. O worker executa FFmpeg e gera um arquivo `output.mp4` em 1080p, H.264 e AAC.

## Estrutura

```text
.
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py
│   ├── tasks.py
│   ├── ffmpeg_utils.py
│   ├── config.py
│   └── cleanup.py
├── frontend/
│   ├── Dockerfile
│   ├── nginx.conf
│   ├── package.json
│   ├── vite.config.js
│   ├── index.html
│   ├── src/
│   │   ├── App.jsx
│   │   ├── main.jsx
│   │   ├── index.css
│   │   └── components/
│   │       ├── UploadForm.jsx
│   │       ├── JobList.jsx
│   │       └── ProgressBar.jsx
│   └── public/
├── docker-compose.yml
├── .env.example
├── .gitignore
└── README.md
```

## Pré-requisitos

Para rodar localmente:

- Docker;
- Docker Compose;
- Git.

Para deploy:

- VPS;
- Coolify instalado;
- GitHub.

## Rodar localmente

Copie o `.env.example`:

```bash
cp .env.example .env
```

Suba os containers:

```bash
docker compose up --build
```

Acesse:

```text
http://localhost:3000
```

## Teste com curl

```bash
curl -X POST http://localhost:3000/api/upload \
  -F "video=@video.mp4" \
  -F "voice=@voice.mp3" \
  -F "subtitle=@subtitle.srt" \
  -F "music=@music.mp3" \
  -F "script=Meu roteiro de teste"
```

Consultar status:

```bash
curl http://localhost:3000/api/status/SEU_JOB_ID
```

Baixar:

```bash
curl -L http://localhost:3000/api/download/SEU_JOB_ID -o output.mp4
```

## Deploy no Coolify

1. Crie um repositório no GitHub.
2. Suba todos os arquivos deste projeto.
3. No Coolify, clique em `New Resource`.
4. Escolha `Docker Compose`.
5. Conecte o repositório GitHub.
6. Confirme que o arquivo principal é `docker-compose.yml`.
7. Configure as variáveis com base no `.env.example`.
8. Garanta volume persistente para `./data:/data`.
9. Clique em `Deploy`.

O frontend será o serviço público. O Nginx do frontend encaminha chamadas `/api/` para o backend.

## Variáveis de ambiente

```env
BACKEND_PORT=8000
FRONTEND_PORT=3000
REDIS_URL=redis://redis:6379/0
DATA_DIR=/data
MAX_FILE_SIZE=2147483648
OUTPUT_DIR=/data/jobs
CLEANUP_AFTER_HOURS=24
VOICE_VOLUME=1.0
MUSIC_VOLUME=0.18
CORS_ORIGINS=*
```

## Como funciona o FFmpeg

O worker monta comandos diferentes para:

1. vídeo + narração;
2. vídeo + narração + legenda;
3. vídeo + narração + música;
4. vídeo + narração + música + legenda.

A saída usa:

- `libx264`;
- `aac`;
- `1920x1080`;
- `pix_fmt yuv420p`;
- `movflags +faststart`.

## Limpeza automática

O serviço `celery-beat` roda a task `cleanup_old_jobs_task` a cada hora e remove jobs mais antigos que `CLEANUP_AFTER_HOURS`.

## Possíveis erros

### Upload falha com arquivo grande

Verifique:

- `MAX_FILE_SIZE`;
- `client_max_body_size` no `frontend/nginx.conf`;
- limite de proxy/domínio no Coolify.

### Vídeo não gera

Veja logs:

```bash
docker compose logs -f celery-worker
```

### Backend não responde

Veja logs:

```bash
docker compose logs -f backend
```

### Frontend abre mas upload falha

Confirme se o Nginx está encaminhando `/api/` para `backend:8000`.

## Segurança

- Containers rodam como usuário não-root.
- Upload é salvo por streaming.
- Cada job tem pasta própria.
- Extensões são validadas.
- Paths são sanitizados.
