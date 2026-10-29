"""Modelos de dados compartilhados entre os módulos. Contrato fixo: não alterar sem avisar."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path


@dataclass(frozen=True)
class Segment:
    """Trecho falado. `start`/`end` em segundos do ÁUDIO ORIGINAL (já corrigidos do fator de velocidade)."""

    start: float
    end: float
    text: str


@dataclass
class Transcript:
    language: str
    duration: float  # segundos do áudio original
    segments: list[Segment] = field(default_factory=list)
    model: str = ""

    def to_json(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def from_json(cls, path: Path) -> "Transcript":
        data = json.loads(path.read_text(encoding="utf-8"))
        data["segments"] = [Segment(**s) for s in data["segments"]]
        return cls(**data)
