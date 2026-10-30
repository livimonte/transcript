"""Configuração: Settings com defaults, variáveis de ambiente e overrides por projeto."""

from __future__ import annotations

from dataclasses import dataclass, fields
import os
from typing import Any


def load_env() -> None:
    """Carrega `.env` (se python-dotenv estiver disponível)."""
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover
        return
    load_dotenv()


# `LANGUAGE` é uma variável do sistema (gettext, ex.: pt_BR:en); por isso o idioma usa WHISPER_LANGUAGE.
ENV_NAMES = {"language": "WHISPER_LANGUAGE"}


@dataclass
class Settings:
    whisper_model: str = "large-v3"
    whisper_device: str = "auto"
    whisper_compute_type: str = "auto"
    language: str = "pt"
    speed_factor: float = 2.0
    mp3_bitrate: str = "64k"
    refine_model: str = "claude-opus-5-5"
    refine_effort: str = "medium"
    refine_chunk_chars: int = 12000
    max_file_chars: int = 40000

    @classmethod
    def from_env(cls, overrides: dict[str, Any] | None = None) -> "Settings":
        """Defaults < variáveis de ambiente (WHISPER_MODEL, REFINE_MODEL, ...) < overrides."""
        values: dict[str, Any] = {}
        for f in fields(cls):
            raw = os.environ.get(ENV_NAMES.get(f.name, f.name.upper()))
            if raw is not None and raw != "":
                values[f.name] = _coerce(f.type, raw)
        for key, val in (overrides or {}).items():
            if key in {f.name for f in fields(cls)} and val is not None:
                values[key] = val
        return cls(**values)


def _coerce(type_: Any, raw: str) -> Any:
    name = type_ if isinstance(type_, str) else getattr(type_, "__name__", "")
    if name == "int":
        return int(raw)
    if name == "float":
        return float(raw)
    return raw
