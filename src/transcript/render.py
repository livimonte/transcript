"""Markdown completo (sem IA) e escrita de Markdown com a regra de arquivos grandes."""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from .models import Transcript

PAUSE_SECONDS = 1.5
PARAGRAPH_MAX_CHARS = 700
_SEP = "\n\n"
_TS_RE = re.compile(r"^(?:\*\*|#+ )\[((?:\d+:)?\d{2}:\d{2})\]")  # parágrafo **[mm:ss]** ou título ## [mm:ss]


def format_timestamp(seconds: float) -> str:
    total = int(max(seconds, 0))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def build_blocks(t: Transcript, *, pause: float = PAUSE_SECONDS,
                 max_chars: int = PARAGRAPH_MAX_CHARS) -> list[str]:
    """Agrupa segmentos em parágrafos `**[mm:ss]** texto`."""
    blocks: list[str] = []
    cur: list[str] = []
    cur_start = 0.0
    cur_len = 0
    last_end = 0.0

    def flush() -> None:
        nonlocal cur, cur_len
        if cur:
            blocks.append(f"**[{format_timestamp(cur_start)}]** " + " ".join(cur))
        cur, cur_len = [], 0

    for seg in t.segments:
        text = seg.text.strip()
        if not text:
            continue
        if cur and (seg.start - last_end > pause or cur_len + len(text) > max_chars):
            flush()
        if not cur:
            cur_start = seg.start
        cur.append(text)
        cur_len += len(text) + 1
        last_end = seg.end
    flush()
    return blocks


def _yaml(value: object) -> str:
    s = str(value)
    if s == "" or re.search(r"[:#\"'\[\]{}&*!|>%@`,]|^\s|\s$|^[-?]", s):
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return s


def build_front_matter(t: Transcript, *, title: str, source_name: str, project: str) -> str:
    fields = [
        ("title", title),
        ("source", source_name),
        ("project", project),
        ("language", t.language),
        ("duration", format_timestamp(t.duration)),
        ("model", t.model),
        ("type", "transcricao-completa"),
    ]
    return "---\n" + "\n".join(f"{k}: {_yaml(v)}" for k, v in fields) + "\n---"


def render_full(t: Transcript, *, title: str, source_name: str, project: str) -> str:
    fm = build_front_matter(t, title=title, source_name=source_name, project=project)
    return fm + _SEP + _SEP.join(build_blocks(t)) + "\n"


def split_parts(blocks: list[str], max_chars: int) -> list[list[str]]:
    """Agrupa blocos em partes de até max_chars; nunca quebra um bloco."""
    parts: list[list[str]] = []
    cur: list[str] = []
    size = 0
    for b in blocks:
        add = len(b) + (len(_SEP) if cur else 0)
        if cur and size + add > max_chars:
            parts.append(cur)
            cur, size, add = [], 0, len(b)
        cur.append(b)
        size += add
    if cur:
        parts.append(cur)
    return parts


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _with_fm_fields(front_matter: str, extra: dict[str, object]) -> str:
    lines = "\n".join(f"{k}: {v}" for k, v in extra.items())
    if front_matter.rstrip().endswith("---") and front_matter.startswith("---"):
        body = front_matter.rstrip()[:-3].rstrip("\n")
        return f"{body}\n{lines}\n---"
    return front_matter


def _first_ts(block: str) -> str | None:
    m = _TS_RE.match(block)
    return m.group(1) if m else None


def _range(part: list[str]) -> str:
    stamps = [ts for ts in map(_first_ts, part) if ts]
    if not stamps:
        return ""
    return stamps[0] if len(stamps) == 1 else f"{stamps[0]} – {stamps[-1]}"


def write_markdown(item_dir: Path, md_file: Path, front_matter: str, blocks: list[str],
                   title: str, max_chars: int) -> list[Path]:
    """Grava `md_file` se couber em max_chars; senão `item_dir/parte-NN.md` + `index.md`.

    Remove o formato anterior ao trocar. Retorna os arquivos gravados.
    """
    item_dir, md_file = Path(item_dir), Path(md_file)
    total = len(front_matter) + sum(len(b) + len(_SEP) for b in blocks)
    if total <= max_chars:
        _atomic_write(md_file, front_matter + _SEP + _SEP.join(blocks) + "\n")
        _remove_parts(item_dir)
        return [md_file]

    # Reserva espaço para o front matter em cada parte.
    budget = max(max_chars - len(front_matter) - 40, 1)
    parts = split_parts(blocks, budget)
    n = len(parts)
    written: list[Path] = []
    index_lines = [f"# {title}", "", "Transcrição dividida em partes:", ""]
    for i, part in enumerate(parts, 1):
        name = f"parte-{i:02d}.md"
        fm = _with_fm_fields(front_matter, {"part": i, "parts": n})
        _atomic_write(item_dir / name, fm + _SEP + _SEP.join(part) + "\n")
        written.append(item_dir / name)
        rng = _range(part)
        index_lines.append(f"- [{name}]({name})" + (f" — {rng}" if rng else ""))
    index_fm = _with_fm_fields(front_matter, {"parts": n})
    index = item_dir / "index.md"
    _atomic_write(index, index_fm + _SEP + "\n".join(index_lines) + "\n")
    for stale in item_dir.glob("parte-*.md"):
        if stale not in written:
            stale.unlink()
    md_file.unlink(missing_ok=True)
    return [index, *written]


def _remove_parts(item_dir: Path) -> None:
    if not item_dir.is_dir():
        return
    for p in item_dir.glob("parte-*.md"):
        p.unlink()
    (item_dir / "index.md").unlink(missing_ok=True)
    try:
        item_dir.rmdir()
    except OSError:
        pass
