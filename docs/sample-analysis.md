# Análise do projeto de referência (`sample/transcript-ad-main`)

Registro do que o projeto de exemplo faz, para servir de base ao novo projeto.

## Objetivo

Transcrever vídeos MP4 (aulas/"jornadas" em PT-BR) para texto usando a API da OpenAI,
**reduzindo o custo** ao acelerar o áudio para 2.5x antes do envio (a API cobra por minuto de áudio).

## Pipeline

1. **Vídeo → áudio** (`downloadAudio.js`, `videoDownloader.js`, `audioExtractor.js`)
   - Lê um arquivo de lista (ex.: `jornada1.txt`) com `# Seção`, `## Título` e a URL do MP4.
   - Baixa o vídeo temporariamente em `downloads/`, extrai WAV mono 16 kHz com ffmpeg e apaga o vídeo.
   - Salva em `audio/<slug-da-seção>/`.
2. **Áudio → áudio 2.5x** (`speedupAudio.js`)
   - ffmpeg com filtro `atempo=2.5`, saída WAV mono 16 kHz em `audio_2x/<seção>/`.
3. **Transcrição** (`transcribeAudio.js`, `transcriber.js`, `audioChunker.js`)
   - Envia o áudio 2.5x para a OpenAI (`whisper-1`, `response_format: 'text'`).
   - Arquivos > 30 min ou > 20 MB são divididos em chunks e as transcrições são concatenadas.
   - Salva `transcriptions/<seção>/<título>_transcricao.txt`.

## Utilitários

| Script | Função |
|---|---|
| `transcribe-folder` / `transcribe-single` | Transcreve uma pasta ou um arquivo de áudio avulso |
| `chunk-folder` | Gera chunks de áudios grandes |
| `combine-transcriptions` | Junta as transcrições de uma seção em um único arquivo com índice |
| `calculate-cost` | Estima custo via ffprobe (fallback: tamanho do arquivo) |
| `full-process` | Encadeia download → speedup → transcribe |

## Stack

Node.js ≥ 20 (ESM), `openai` v4, `fluent-ffmpeg`, `@ffmpeg-installer/ffmpeg`, `@ffprobe-installer/ffprobe`, `dotenv`.
Configuração via `.env` com `OPENAI_API_KEY`.

## Pontos de atenção observados

- **WAV é pesado**: mono 16 kHz ≈ 1,9 MB/min, então o limite de 25 MB da API estoura com ~13 min de áudio
  (já acelerado). Um formato comprimido (mp3/opus) reduziria chunks e uploads.
- **Muita duplicação**: vários scripts reimplementam parsing da lista, loops e chunking.
- **Dependências desnecessárias**: `fs`, `path` e `url` estão no `package.json`, mas são módulos nativos do Node.
- **Sem testes** e sem retry/retomada estruturada em caso de falha no meio do lote.
- **Qualidade x velocidade**: 2.5x reduz custo, mas pode aumentar a taxa de erro dependendo do falante; vale medir.
- Usa `whisper-1`; hoje a OpenAI também oferece modelos `gpt-4o-*-transcribe` que valem comparar (preço/qualidade).
