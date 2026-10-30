# Design — transcript

Pipeline em duas fases, organizado por **projeto** (ex.: "projeto-x", "projeto-y").

```
Fase 1 (áudio)      MP4 ──► MP3 (1x, referência) ──► MP3 2x
Fase 2 (texto)      MP3 2x ──► faster-whisper (local) ──► raw JSON ──► Markdown COMPLETO ──► Markdown REFINADO (IA)
```

Saída por vídeo: **dois arquivos Markdown** — `completo` (fiel à fala) e `refinado` (sem ruído, sem cortes de conteúdo).

## Estrutura de pastas

Código separado dos dados. Dados ficam em `projects/<slug>/`, uma pasta numerada por etapa:

```
transcript/
├── pyproject.toml
├── README.md
├── .env.example               # ANTHROPIC_API_KEY, WHISPER_MODEL, ...
├── prompts/refine.md          # prompt de refinamento (editável)
├── src/transcript/            # código (módulos abaixo)
├── tests/
├── docs/
├── sample/                    # projeto antigo de referência (fora do git)
└── projects/                  # DADOS (fora do git)
    └── <slug>/
        ├── project.json       # nome, criado em, config (modelo, fator de velocidade, idioma)
        ├── state.json         # estado por item/etapa (permite retomar)
        ├── 1_input/           # MP4 originais (copiados/movidos pelo `add`)
        ├── 2_audio/
        │   ├── 1x/            # <item>.mp3
        │   └── 2x/            # <item>.mp3
        ├── 3_transcripts/     # <item>.json  (segmentos + tempos do áudio original)
        ├── 4_markdown/        # <item>.md    (transcrição completa)
        └── 5_refined/         # <item>.md    (versão limpa, via IA)
```

Regras de organização:
- `<item>` = slug do nome do arquivo (sem acento, minúsculo, `-`), único dentro do projeto. O nome original fica guardado em `state.json` e no front matter do Markdown.
- Se o MP4 estiver em subpastas ao ser adicionado, a estrutura relativa vira prefixo do slug (`aula-1/parte-2.mp4` → `aula-1--parte-2`).
- **Arquivos grandes**: nenhum arquivo gerado deve virar um monolito. O Markdown completo de vídeos longos (> ~60 min) é dividido em partes `<item>/parte-01.md`, `parte-02.md`... mais um `<item>/index.md` com sumário e links; o refinado segue a mesma divisão. Limite por arquivo: ~40 mil caracteres.
- Tudo é idempotente: rodar de novo pula o que já está pronto (`--force` refaz).

## Módulos e contratos (`src/transcript/`)

Compartilhado e já pronto: `models.py` (`Segment`, `Transcript`). **Não alterar.**

### `config.py` — configuração
- `load_env()` carrega `.env` (python-dotenv).
- `@dataclass Settings`: `whisper_model="large-v3"`, `whisper_device="auto"`, `whisper_compute_type="auto"`, `language="pt"`, `speed_factor=2.0`, `mp3_bitrate="64k"`, `refine_model="claude-opus-5-5"`, `refine_effort="medium"`, `refine_chunk_chars=12000`, `max_file_chars=40000`.
- `Settings.from_env(overrides: dict | None)`; valores vêm de env `WHISPER_MODEL`, `REFINE_MODEL` etc.; `project.json` pode sobrescrever.

### `projects.py` — projetos e estado
- `ROOT` = pasta `projects/` na raiz do repositório (override por env `TRANSCRIPT_HOME`).
- `class Project`: `Project.create(name)`, `Project.open(slug)`, `Project.list_all()`; propriedades `root`, `input_dir`, `audio_1x_dir`, `audio_2x_dir`, `transcripts_dir`, `markdown_dir`, `refined_dir`; `settings` (Settings mesclado com project.json).
- `add_files(paths, *, move=False) -> list[Item]` (aceita arquivos e pastas; só `.mp4/.mkv/.mov/.webm/.m4a/.mp3/.wav`), cria o item e copia para `1_input/`.
- `items() -> list[Item]`; `Item` com `slug`, `source: Path`, e caminhos derivados (`mp3_1x`, `mp3_2x`, `raw_json`, `md_full`, `md_refined`).
- `state.json`: `get_status(item, stage)` / `set_status(item, stage, "done"|"failed"|"pending", error=None)`, gravação atômica.
- `slugify(text) -> str` público.

### `media.py` — Fase 1
- `ffmpeg_exe() -> str` (usa `ffmpeg` do sistema se existir, senão `imageio_ffmpeg.get_ffmpeg_exe()`).
- `to_mp3(src: Path, dst: Path, *, bitrate="64k") -> None` (mono, 16 kHz basta para fala; escrita atômica via arquivo temporário).
- `speed_up(src_mp3: Path, dst_mp3: Path, *, factor=2.0) -> None` (filtro `atempo`; encadear filtros se factor > 2.0 por compatibilidade).
- `probe_duration(path: Path) -> float` (segundos; parse da saída do ffmpeg, sem ffprobe).

### `transcribe.py` — Fase 2a (local)
- `class Transcriber(settings)`: carrega `faster_whisper.WhisperModel` sob demanda (lazy). Se `device="auto"`: tenta CUDA, e **se falhar (ex.: GPU Blackwell sem suporte no ctranslate2 instalado) cai para CPU `int8`** com aviso claro.
- `transcribe(audio: Path, *, speed_factor: float) -> Transcript` — usa `vad_filter=True`, `language` das settings; **converte os tempos de volta para o áudio original** (`t * speed_factor`) e preenche `duration` com a duração original.
- Barra de progresso simples no stderr.

### `render.py` — Fase 2b (Markdown completo)
- `render_full(t: Transcript, *, title, source_name, project) -> str`: front matter YAML (`title`, `source`, `project`, `language`, `duration`, `model`, `type: transcricao-completa`), parágrafos agrupados por pausa (> ~1,5 s) ou tamanho, marcador `[mm:ss]` no começo de cada parágrafo (ou de blocos de ~60 s).
- `split_parts(md_body_blocks, max_chars) -> list[str]` e `write_markdown(item_dir_or_file, ...)`: aplica a regra de arquivos grandes (partes + `index.md`).
- Sem IA nesta etapa.

### `refine.py` — Fase 2c (IA)
- Lê `prompts/refine.md` (blocos `SYSTEM` e `USER`).
- `class Backend(Protocol)`: `complete(system: str, user: str) -> str`. Implementação `AnthropicBackend(model)` (SDK `anthropic`, lê `ANTHROPIC_API_KEY`, retry com backoff em 429/5xx/overloaded). Existe também `FakeBackend` para testes.
- `refine_markdown(full_md: str, backend, *, chunk_chars, model_name, source_markdown, on_progress) -> RefineResult` (`front_matter`, `blocks`, `markdown`, `warnings`): remove front matter, **divide em trechos nas fronteiras de parágrafo/timestamp** (nunca no meio de uma frase), processa em ordem passando `contexto_anterior` (últimos ~800 chars da saída + glossário acumulado extraído do bloco `<glossario>`), remove o bloco `<glossario>` da saída, junta tudo e acrescenta front matter (`type: transcricao-refinada`, `refined_by: <modelo>`).
- **Verificação de fidelidade barata**: se o texto refinado de um trecho ficar com menos de ~45% dos caracteres da entrada, registra aviso (provável resumo indevido) e tenta de novo uma vez com um lembrete "NÃO resuma".
- Resultado é gravado com a mesma regra de partes/`index.md`.

### `pipeline.py` — orquestração
- `run_audio(project, items=None, force=False)`: MP4 → `2_audio/1x/*.mp3` → `2_audio/2x/*.mp3`.
- `run_transcribe(project, items=None, force=False)`: 2x → `3_transcripts/*.json` → `4_markdown/`.
- `run_refine(project, items=None, force=False)`: `4_markdown/` → `5_refined/`.
- `run_all(...)`. Cada etapa atualiza `state.json`; falha em um item não derruba os demais (registra e segue; código de saída ≠ 0 no final).

### `cli.py` — comando `transcript`
```
transcript new <projeto>                      # cria projects/<slug>/
transcript list                               # lista projetos
transcript add <projeto> <arquivos|pastas>... [--move]
transcript audio|transcribe|refine|run <projeto> [--item SLUG] [--force]
transcript status [projeto]                   # tabela item × etapa
```
Implementar com `argparse` (stdlib).

## Testes
- `pytest`, sem rede e sem baixar modelo: `FakeBackend`, `Transcript` sintético, ffmpeg real com um áudio de 2 s gerado em fixture (`lavfi sine`).
