import subprocess

import pytest

from transcript import pipeline
from transcript.media import ffmpeg_exe
from transcript.models import Segment, Transcript
from transcript.projects import Project
from transcript.refine import FakeBackend


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("TRANSCRIPT_HOME", str(tmp_path / "projects"))
    video = tmp_path / "aula 1.mp4"
    subprocess.run([ffmpeg_exe(), "-nostdin", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
                    "-f", "lavfi", "-i", "testsrc=size=64x64:rate=5:duration=4", "-shortest", str(video)], check=True)
    p = Project.create("Projeto X")
    p.add_files([video])
    return p


class FakeTranscriber:
    calls = 0

    def __init__(self, settings):
        pass

    def transcribe(self, audio, *, speed_factor):
        FakeTranscriber.calls += 1
        segs = [Segment(i * 10.0, i * 10.0 + 9, f"Frase número {i} com bastante conteúdo para ocupar espaço. " * 3) for i in range(40)]
        return Transcript(language="pt", duration=400.0, segments=segs, model="fake")


def refine_backend():
    return FakeBackend(lambda system, user, n: "## Tema\n\nTexto limpo " + "x" * 400 + "\n\n<glossario>\nTermo\n</glossario>")


def test_full_flow_resume_and_large_split(project, monkeypatch):
    monkeypatch.setattr(pipeline, "Transcriber", FakeTranscriber)
    project.update_settings({"max_file_chars": 2500, "refine_chunk_chars": 3000})
    project = Project.open(project.slug)
    item = project.items()[0]
    logs = []

    assert pipeline.run_audio(project, log=logs.append) == []
    assert item.mp3_1x.exists() and item.mp3_2x.exists()
    assert pipeline.run_transcribe(project, log=logs.append) == []
    assert item.raw_json.exists()
    assert (item.md_full_dir / "index.md").exists()  # grande demais → dividido em partes
    assert pipeline.run_refine(project, backend=refine_backend(), log=logs.append) == []
    assert (item.md_refined_dir / "index.md").exists() or item.md_refined.exists()
    assert "type: transcricao-refinada" in pipeline.read_markdown(item.md_refined, item.md_refined_dir)

    calls = FakeTranscriber.calls
    pipeline.run_all(project, backend=refine_backend(), log=logs.append)  # tudo pronto → pula
    assert FakeTranscriber.calls == calls
    assert any("já pronto" in m for m in logs)
    pipeline.run_transcribe(project, force=True, log=logs.append)
    assert FakeTranscriber.calls == calls + 1


def test_failure_is_isolated_and_recorded(project, monkeypatch):
    project.items()[0].source.unlink()
    failed = pipeline.run_audio(project, log=lambda m: None)
    assert failed == [project.items()[0].slug]
    assert project.get_status(project.items()[0], "audio") == "failed"
    assert project.get_error(project.items()[0], "audio")
