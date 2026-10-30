"""Orquestração das etapas. Cada etapa é idempotente, retomável e isola falhas por item."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
import re
import sys

from . import media
from .models import Transcript
from .projects import Item, Project
from .refine import AnthropicBackend, Backend, refine_markdown
from .render import build_blocks, build_front_matter, write_markdown
from .transcribe import Transcriber

Log = Callable[[str], None]
_FRONT_MATTER = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _select(project: Project, slugs: Iterable[str] | None) -> list[Item]:
    if not slugs:
        return project.items()
    return [project.get_item(s) for s in slugs]


def _is_done(project: Project, item: Item, stage: str, outputs: list[Path], force: bool) -> bool:
    return not force and project.get_status(item, stage) == "done" and all(p.exists() for p in outputs)


def _run_stage(project: Project, items: list[Item], stage: str, fn: Callable[[Item], None],
               outputs: Callable[[Item], list[Path]], force: bool, log: Log) -> list[str]:
    """Roda `fn` por item; devolve os slugs que falharam."""
    failed: list[str] = []
    for n, item in enumerate(items, 1):
        tag = f"[{stage} {n}/{len(items)}] {item.slug}"
        if _is_done(project, item, stage, outputs(item), force):
            log(f"{tag}: já pronto, pulando")
            continue
        log(f"{tag}: processando")
        try:
            fn(item)
        except Exception as exc:  # um item ruim não derruba o lote
            project.set_status(item, stage, "failed", error=f"{type(exc).__name__}: {exc}")
            log(f"{tag}: FALHOU — {exc}")
            failed.append(item.slug)
        else:
            project.set_status(item, stage, "done")
    return failed


def run_audio(project: Project, slugs: Iterable[str] | None = None, *, force: bool = False,
              log: Log = _log) -> list[str]:
    s = project.settings

    def work(item: Item) -> None:
        media.to_mp3(item.source, item.mp3_1x, bitrate=s.mp3_bitrate)
        media.speed_up(item.mp3_1x, item.mp3_2x, factor=s.speed_factor)

    return _run_stage(project, _select(project, slugs), "audio", work,
                      lambda i: [i.mp3_1x, i.mp3_2x], force, log)


def run_transcribe(project: Project, slugs: Iterable[str] | None = None, *, force: bool = False,
                   log: Log = _log) -> list[str]:
    s = project.settings
    transcriber = Transcriber(s)  # modelo só é carregado na primeira chamada

    def outputs(item: Item) -> list[Path]:
        return [item.raw_json, item.md_full if item.md_full.exists() else item.md_full_dir / "index.md"]

    def work(item: Item) -> None:
        if not item.mp3_2x.exists():
            raise FileNotFoundError(f"{item.mp3_2x} não existe — rode a etapa 'audio' antes")
        t = transcriber.transcribe(item.mp3_2x, speed_factor=s.speed_factor)
        item.raw_json.parent.mkdir(parents=True, exist_ok=True)
        t.to_json(item.raw_json)
        title = Path(item.original_name).stem
        write_markdown(item.md_full_dir, item.md_full,
                       build_front_matter(t, title=title, source_name=item.original_name, project=project.name),
                       build_blocks(t), title, s.max_file_chars)

    return _run_stage(project, _select(project, slugs), "transcribe", work, outputs, force, log)


def read_markdown(single: Path, parts_dir: Path) -> str:
    """Lê o Markdown de um item, seja arquivo único ou dividido em partes (`parte-NN.md`)."""
    if single.exists():
        return single.read_text(encoding="utf-8")
    parts = sorted(parts_dir.glob("parte-*.md"))
    if not parts:
        raise FileNotFoundError(f"nenhum Markdown em {single} ou {parts_dir}")
    head = parts[0].read_text(encoding="utf-8")
    m = _FRONT_MATTER.match(head)
    bodies = [_FRONT_MATTER.sub("", p.read_text(encoding="utf-8"), count=1).strip() for p in parts]
    return (m.group(0) if m else "") + "\n" + "\n\n".join(bodies) + "\n"


def run_refine(project: Project, slugs: Iterable[str] | None = None, *, force: bool = False,
               backend: Backend | None = None, log: Log = _log) -> list[str]:
    s = project.settings
    backend = backend or AnthropicBackend(s.refine_model, effort=s.refine_effort)

    def outputs(item: Item) -> list[Path]:
        return [item.md_refined if item.md_refined.exists() else item.md_refined_dir / "index.md"]

    def work(item: Item) -> None:
        full = read_markdown(item.md_full, item.md_full_dir)
        result = refine_markdown(full, backend, chunk_chars=s.refine_chunk_chars, model_name=s.refine_model,
                                 source_markdown=item.md_full.name,
                                 on_progress=lambda *a: log(f"    refinando… {' '.join(map(str, a))}"))
        for w in result.warnings:
            log(f"    AVISO {item.slug}: {w}")
        write_markdown(item.md_refined_dir, item.md_refined, result.front_matter, result.blocks,
                       Path(item.original_name).stem, s.max_file_chars)

    return _run_stage(project, _select(project, slugs), "refine", work, outputs, force, log)


def run_all(project: Project, slugs: Iterable[str] | None = None, *, force: bool = False,
            backend: Backend | None = None, log: Log = _log) -> list[str]:
    failed = run_audio(project, slugs, force=force, log=log)
    ok = [i.slug for i in _select(project, slugs) if i.slug not in failed]
    failed += run_transcribe(project, ok, force=force, log=log)
    ok = [s for s in ok if s not in failed]
    failed += run_refine(project, ok, force=force, backend=backend, log=log)
    return failed
