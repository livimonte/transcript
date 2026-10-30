"""Projetos, itens e estado (`state.json`)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import unicodedata
from typing import Any, Iterable

from .config import Settings

EXTENSIONS = {".mp4", ".mkv", ".mov", ".webm", ".m4a", ".mp3", ".wav"}
STAGES = ("audio", "transcribe", "refine")
STATUSES = ("done", "failed", "pending")


def get_root() -> Path:
    """Pasta `projects/` (override por env TRANSCRIPT_HOME, lido a cada chamada)."""
    env = os.environ.get("TRANSCRIPT_HOME")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "projects"


def __getattr__(name: str):  # `projects.ROOT` sempre reflete o ambiente atual
    if name == "ROOT":
        return get_root()
    raise AttributeError(name)


def slugify(text: str) -> str:
    s = unicodedata.normalize("NFKD", text)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "item"


def _atomic_write_json(path: Path, data: Any) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


@dataclass(frozen=True)
class Item:
    slug: str
    source: Path  # arquivo em 1_input/
    original_name: str
    project: "Project"

    @property
    def mp3_1x(self) -> Path:
        return self.project.audio_1x_dir / f"{self.slug}.mp3"

    @property
    def mp3_2x(self) -> Path:
        return self.project.audio_2x_dir / f"{self.slug}.mp3"

    @property
    def raw_json(self) -> Path:
        return self.project.transcripts_dir / f"{self.slug}.json"

    @property
    def md_full(self) -> Path:
        return self.project.markdown_dir / f"{self.slug}.md"

    @property
    def md_full_dir(self) -> Path:
        return self.project.markdown_dir / self.slug

    @property
    def md_refined(self) -> Path:
        return self.project.refined_dir / f"{self.slug}.md"

    @property
    def md_refined_dir(self) -> Path:
        return self.project.refined_dir / self.slug


class Project:
    def __init__(self, slug: str, root: Path):
        self.slug = slug
        self.root = root

    # --- construção -------------------------------------------------
    @classmethod
    def create(cls, name: str) -> "Project":
        slug = slugify(name)
        root = get_root() / slug
        if root.exists():
            raise FileExistsError(f"projeto já existe: {slug}")
        p = cls(slug, root)
        for d in (p.input_dir, p.audio_1x_dir, p.audio_2x_dir, p.transcripts_dir,
                  p.markdown_dir, p.refined_dir):
            d.mkdir(parents=True)
        _atomic_write_json(root / "project.json", {
            "name": name,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "settings": {},
        })
        _atomic_write_json(root / "state.json", {"items": {}})
        return p

    @classmethod
    def open(cls, slug: str) -> "Project":
        root = get_root() / slug
        if not (root / "project.json").is_file():
            raise FileNotFoundError(f"projeto não encontrado: {slug}")
        return cls(slug, root)

    @classmethod
    def list_all(cls) -> list["Project"]:
        base = get_root()
        if not base.is_dir():
            return []
        return [cls(d.name, d) for d in sorted(base.iterdir()) if (d / "project.json").is_file()]

    # --- pastas -----------------------------------------------------
    @property
    def input_dir(self) -> Path:
        return self.root / "1_input"

    @property
    def audio_1x_dir(self) -> Path:
        return self.root / "2_audio" / "1x"

    @property
    def audio_2x_dir(self) -> Path:
        return self.root / "2_audio" / "2x"

    @property
    def transcripts_dir(self) -> Path:
        return self.root / "3_transcripts"

    @property
    def markdown_dir(self) -> Path:
        return self.root / "4_markdown"

    @property
    def refined_dir(self) -> Path:
        return self.root / "5_refined"

    # --- project.json -----------------------------------------------
    def _meta(self) -> dict:
        return json.loads((self.root / "project.json").read_text(encoding="utf-8"))

    @property
    def name(self) -> str:
        return self._meta().get("name", self.slug)

    @property
    def created_at(self) -> str:
        return self._meta().get("created_at", "")

    @property
    def settings(self) -> Settings:
        return Settings.from_env(self._meta().get("settings") or {})

    def update_settings(self, overrides: dict) -> None:
        meta = self._meta()
        meta.setdefault("settings", {}).update(overrides)
        _atomic_write_json(self.root / "project.json", meta)

    # --- estado -----------------------------------------------------
    def _state(self) -> dict:
        path = self.root / "state.json"
        if not path.is_file():
            return {"items": {}}
        return json.loads(path.read_text(encoding="utf-8"))

    def _save_state(self, state: dict) -> None:
        _atomic_write_json(self.root / "state.json", state)

    def _item_from(self, slug: str, entry: dict) -> Item:
        return Item(slug, self.input_dir / entry["source"], entry.get("original_name", ""), self)

    def items(self) -> list[Item]:
        return [self._item_from(s, e) for s, e in self._state()["items"].items()]

    def get_item(self, slug: str) -> Item:
        entry = self._state()["items"].get(slug)
        if entry is None:
            raise KeyError(f"item não encontrado: {slug}")
        return self._item_from(slug, entry)

    @staticmethod
    def _slug_of(item: Item | str) -> str:
        return item.slug if isinstance(item, Item) else item

    def get_status(self, item: Item | str, stage: str) -> str:
        if stage not in STAGES:
            raise ValueError(f"etapa inválida: {stage}")
        entry = self._state()["items"].get(self._slug_of(item), {})
        return entry.get("stages", {}).get(stage, {}).get("status", "pending")

    def get_error(self, item: Item | str, stage: str) -> str | None:
        entry = self._state()["items"].get(self._slug_of(item), {})
        return entry.get("stages", {}).get(stage, {}).get("error")

    def set_status(self, item: Item | str, stage: str, status: str, error: str | None = None) -> None:
        if stage not in STAGES:
            raise ValueError(f"etapa inválida: {stage}")
        if status not in STATUSES:
            raise ValueError(f"status inválido: {status}")
        state = self._state()
        entry = state["items"].get(self._slug_of(item))
        if entry is None:
            raise KeyError(f"item não encontrado: {self._slug_of(item)}")
        rec: dict[str, Any] = {"status": status}
        if error:
            rec["error"] = error
        entry.setdefault("stages", {})[stage] = rec
        self._save_state(state)

    # --- adicionar arquivos -----------------------------------------
    def add_files(self, paths: Iterable[Path | str], *, move: bool = False, link: bool = False) -> list[Item]:
        """`link=True` não copia: cria um link simbólico em 1_input apontando para o original."""
        # (arquivo, caminho relativo dentro de 1_input, caminho que define as subpastas das saídas)
        found: list[tuple[Path, Path, Path]] = []
        for raw in paths:
            p = Path(raw)
            if not p.exists():
                raise FileNotFoundError(str(p))
            if p.is_dir():
                for f in sorted(p.rglob("*")):
                    if f.is_file() and f.suffix.lower() in EXTENSIONS:
                        found.append((f, Path(p.name) / f.relative_to(p), f.relative_to(p)))
            elif p.suffix.lower() in EXTENSIONS:
                found.append((p, Path(p.name), Path(p.name)))

        state = self._state()
        entries = state["items"]
        by_source = {e["source"]: s for s, e in entries.items()}
        result: list[Item] = []
        for src, rel, layout in found:
            rel = self._free_rel(src, rel, by_source)
            key = rel.as_posix()
            if key in by_source:  # já adicionado (mesmo conteúdo)
                result.append(self._item_from(by_source[key], entries[by_source[key]]))
                continue
            dest = self.input_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if link:
                dest.symlink_to(src.resolve())
            elif move:
                shutil.move(str(src), dest)
            else:
                shutil.copy2(src, dest)
            slug = self._unique_slug(
                "/".join(slugify(part) for part in (*layout.parts[:-1], layout.stem)), entries)
            entries[slug] = {"source": key, "original_name": src.name, "stages": {}}
            by_source[key] = slug
            result.append(self._item_from(slug, entries[slug]))
        self._save_state(state)
        return result

    def _free_rel(self, src: Path, rel: Path, by_source: dict[str, str]) -> Path:
        """Mesmo destino com mesmo tamanho = mesmo arquivo; senão acrescenta -2, -3..."""
        n = 1
        cand = rel
        while (self.input_dir / cand).exists():
            if (self.input_dir / cand).stat().st_size == src.stat().st_size and cand.as_posix() in by_source:
                return cand
            n += 1
            cand = rel.with_name(f"{rel.stem}-{n}{rel.suffix}")
        return cand

    @staticmethod
    def _unique_slug(base: str, entries: dict) -> str:
        slug, n = base, 1
        while slug in entries:
            n += 1
            slug = f"{base}-{n}"
        return slug
