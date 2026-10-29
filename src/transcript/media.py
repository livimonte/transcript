"""Conversão de mídia com ffmpeg (sem ffprobe)."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path


class MediaError(RuntimeError):
    """Falha ao executar o ffmpeg."""


def ffmpeg_exe() -> str:
    """ffmpeg do sistema se existir, senão o binário do imageio_ffmpeg."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def _tail(text: str, n: int = 10) -> str:
    return "\n".join(text.strip().splitlines()[-n:])


def _run(args: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            [ffmpeg_exe(), *args],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            errors="replace",
        )
    except OSError as e:
        raise MediaError(f"não foi possível executar o ffmpeg: {e}") from e


def _atomic_encode(src: Path, dst: Path, pre: list[str], post: list[str]) -> None:
    src, dst = Path(src), Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".part")
    try:
        proc = _run(["-nostdin", "-y", "-loglevel", "error", *pre, "-i", str(src),
                     *post, "-f", "mp3", str(tmp)])
        if proc.returncode != 0:
            raise MediaError(
                f"ffmpeg falhou (código {proc.returncode}) em {src}:\n{_tail(proc.stderr)}"
            )
        os.replace(tmp, dst)
    finally:
        tmp.unlink(missing_ok=True)


def to_mp3(src: Path, dst: Path, *, bitrate: str = "64k") -> None:
    """Extrai o áudio de `src` (áudio ou vídeo) para mp3 mono 16 kHz."""
    _atomic_encode(src, dst, [], ["-vn", "-ac", "1", "-ar", "16000",
                                  "-c:a", "libmp3lame", "-b:a", bitrate])


def _atempo_chain(factor: float) -> str:
    if factor <= 0:
        raise ValueError("factor deve ser > 0")
    parts: list[float] = []
    f = factor
    while f > 2.0:
        parts.append(2.0)
        f /= 2.0
    while f < 0.5:
        parts.append(0.5)
        f /= 0.5
    parts.append(f)
    return ",".join(f"atempo={p:.6g}" for p in parts)


def speed_up(src_mp3: Path, dst_mp3: Path, *, factor: float = 2.0) -> None:
    """Acelera o áudio por `factor` (pitch preservado), saída mp3 mono 16 kHz."""
    _atomic_encode(src_mp3, dst_mp3, [], [
        "-vn", "-filter:a", _atempo_chain(factor), "-ac", "1", "-ar", "16000",
        "-c:a", "libmp3lame", "-b:a", "64k"])


_DUR = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


def probe_duration(path: Path) -> float:
    """Duração em segundos, lida do stderr de `ffmpeg -i`."""
    path = Path(path)
    if not path.exists():
        raise MediaError(f"arquivo não encontrado: {path}")
    proc = _run(["-nostdin", "-hide_banner", "-i", str(path)])
    m = _DUR.search(proc.stderr)
    if not m:
        raise MediaError(f"não foi possível obter a duração de {path}:\n{_tail(proc.stderr)}")
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)
