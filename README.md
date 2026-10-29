# transcript

Transforma vídeos em **dois Markdown** por vídeo, organizados por projeto:

1. **Completo** — fiel à fala, com marcadores de tempo `**[mm:ss]**`.
2. **Refinado** — transcrição limpa por IA: sem vícios de fala e ruído, **sem cortes de conteúdo** (não é resumo). Prompt em [prompts/refine.md](prompts/refine.md).

```
Fase 1   MP4 ──► MP3 ──► MP3 2x
Fase 2   MP3 2x ──► faster-whisper (local, GPU/CPU) ──► Markdown completo ──► Markdown refinado (Claude)
```

Os tempos do Markdown já são corrigidos para o vídeo original (o áudio 2x é só para transcrever mais rápido).

## Instalação

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
cp .env.example .env     # preencha ANTHROPIC_API_KEY (só a etapa refine usa)
```

ffmpeg vem junto via pip. As libs CUDA também (GPU é detectada sozinha; se falhar, cai para CPU `int8`).

## Uso

```bash
transcript new "Projeto X"                       # cria projects/projeto-x/
transcript add projeto-x ~/videos/*.mp4          # copia (ou --move); aceita pastas
transcript run projeto-x                         # audio → transcribe → refine
transcript status projeto-x                      # tabela item × etapa
```

Etapas avulsas: `transcript audio|transcribe|refine <projeto> [--item SLUG] [--force]`.
Tudo é retomável: o que já está pronto é pulado; `--force` refaz. Falha em um vídeo não para os outros.
Configuração por projeto: `transcript config projeto-x whisper_model=large-v3 speed_factor=2.0`.

## Onde ficam os arquivos

```
projects/<projeto>/
├── project.json, state.json
├── 1_input/            vídeos originais
├── 2_audio/1x/  2x/    MP3 normal e MP3 2x
├── 3_transcripts/      JSON bruto (segmentos + tempos)
├── 4_markdown/         <item>.md  — transcrição completa
└── 5_refined/          <item>.md  — transcrição refinada
```

Arquivos longos (> 40 mil caracteres) viram `<item>/parte-01.md …` + `<item>/index.md` com sumário.
`projects/` fica fora do git. Para mudar o local: `TRANSCRIPT_HOME`.

## Desenvolvimento

`pytest` (sem rede, sem baixar modelos). Design e contratos dos módulos: [docs/design.md](docs/design.md).
Análise do projeto antigo que serviu de base: [docs/sample-analysis.md](docs/sample-analysis.md).
