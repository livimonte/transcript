"""Fase 2a: transcrição local com faster-whisper."""

from __future__ import annotations

import sys
from pathlib import Path

from .models import Segment, Transcript


def to_original_time(t: float, speed_factor: float) -> float:
    """Converte tempo do áudio acelerado para o do áudio original."""
    return t * speed_factor


def preload_cuda_libs() -> None:
    """Carrega as libs CUDA instaladas por pip (nvidia-cublas-cu12, nvidia-cudnn-cu12).

    O ctranslate2 as procura via dlopen; alterar LD_LIBRARY_PATH depois que o processo
    iniciou não surte efeito, então carregamos por caminho absoluto. Sem as libs, não faz nada.
    """
    import ctypes
    import importlib.util

    spec = importlib.util.find_spec("nvidia")
    for base in (spec.submodule_search_locations or []) if spec else []:
        for lib in sorted(Path(base).glob("*/lib/lib*.so*")):
            try:
                ctypes.CDLL(str(lib), mode=ctypes.RTLD_GLOBAL)
            except OSError:
                pass  # lib opcional/incompatível; o fallback para CPU cobre o resto


def _load_whisper_class():
    preload_cuda_libs()
    from faster_whisper import WhisperModel

    return WhisperModel


def find_loops(segments: list[Segment], min_repeats: int = 3) -> list[tuple[float, float, int]]:
    """Sequências de >= min_repeats trechos consecutivos com o mesmo texto (alucinação típica do Whisper)."""
    loops, i = [], 0
    while i < len(segments):
        j = i
        while j + 1 < len(segments) and segments[j + 1].text.strip() == segments[i].text.strip():
            j += 1
        if j - i + 1 >= min_repeats:
            loops.append((segments[i].start, segments[j].end, j - i + 1))
        i = j + 1
    return loops


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


class Transcriber:
    def __init__(self, settings) -> None:
        self.settings = settings
        self._model = None
        self._device: str | None = None  # dispositivo efetivo após o carregamento

    # -- carregamento -----------------------------------------------------
    def _language(self) -> str | None:
        lang = getattr(self.settings, "language", None)
        if lang is None or str(lang).strip().lower() in ("", "auto"):
            return None
        return lang

    def _load(self, device: str, compute_type: str):
        cls = _load_whisper_class()
        _log(f"[whisper] carregando '{self.settings.whisper_model}' em {device} ({compute_type})...")
        model = cls(self.settings.whisper_model, device=device, compute_type=compute_type)
        self._model, self._device = model, device
        return model

    def _compute_for(self, device: str) -> str:
        ct = self.settings.whisper_compute_type
        if ct and ct != "auto":
            return ct
        return "float16" if device == "cuda" else "int8"

    def _fallback_cpu(self, reason: Exception):
        _log(f"[whisper] AVISO: falha no CUDA ({reason}); usando CPU com int8 (mais lento).")
        return self._load("cpu", "int8")

    def _ensure_model(self):
        if self._model is not None:
            return self._model
        device = self.settings.whisper_device
        if device == "auto":
            try:
                return self._load("cuda", self._compute_for("cuda"))
            except Exception as e:  # noqa: BLE001 - qualquer falha de GPU cai para CPU
                return self._fallback_cpu(e)
        return self._load(device, self._compute_for(device))

    # -- transcrição ------------------------------------------------------
    def _run(self, model, audio: Path):
        segments, info = model.transcribe(
            str(audio), vad_filter=True, language=self._language(), beam_size=5,
            # sem isso o modelo pode entrar em loop repetindo a frase anterior por minutos
            condition_on_previous_text=False,
        )
        return list(self._consume(segments, info)), info

    @staticmethod
    def _consume(segments, info):
        total = getattr(info, "duration", 0) or 0
        last_pct = -1
        for seg in segments:
            if total:
                pct = int(min(seg.end / total, 1.0) * 100) // 10 * 10
                if pct != last_pct:
                    last_pct = pct
                    _log(f"[whisper] {pct}%")
            yield seg

    def transcribe(self, audio: Path, *, speed_factor: float) -> Transcript:
        model = self._ensure_model()
        try:
            raw, info = self._run(model, audio)
        except Exception as e:  # noqa: BLE001
            if self.settings.whisper_device != "auto" or self._device == "cpu":
                raise
            raw, info = self._run(self._fallback_cpu(e), audio)
        segments = [
            Segment(
                start=to_original_time(s.start, speed_factor),
                end=to_original_time(s.end, speed_factor),
                text=s.text.strip(),
            )
            for s in raw
        ]
        for start, end, n in find_loops(segments):
            _log(f"[whisper] AVISO: possível loop de {start:.0f}s a {end:.0f}s ({n} trechos iguais) — confira o áudio")
        return Transcript(
            language=getattr(info, "language", None) or self._language() or "",
            duration=to_original_time(info.duration, speed_factor),
            segments=segments,
            model=self.settings.whisper_model,
        )
