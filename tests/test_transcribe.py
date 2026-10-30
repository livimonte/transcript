import sys
from types import SimpleNamespace

import pytest

import transcript.transcribe as tr
from transcript.transcribe import Transcriber, to_original_time


class S(SimpleNamespace):
    pass


def make_settings(**kw):
    base = dict(whisper_model="tiny", whisper_device="auto", whisper_compute_type="auto",
                language="pt", speed_factor=2.0)
    base.update(kw)
    return SimpleNamespace(**base)


def test_to_original_time():
    assert to_original_time(10.0, 2.0) == 20.0
    assert to_original_time(1.25, 1.0) == 1.25


class FakeModel:
    instances = []
    fail_devices = ()

    def __init__(self, name, device="cpu", compute_type="default", **kw):
        self.name, self.device, self.compute_type = name, device, compute_type
        self.calls = []
        FakeModel.instances.append(self)
        if device in FakeModel.fail_devices and kw.get("_never"):
            raise RuntimeError("x")
        if device in FakeModel.fail_devices:
            raise RuntimeError("CUDA unsupported")

    def transcribe(self, audio, **kw):
        self.calls.append(kw)
        segs = [S(start=1.0, end=3.0, text=" Olá "), S(start=4.0, end=5.0, text="mundo")]
        return iter(segs), S(language=kw.get("language") or "en", duration=10.0)


@pytest.fixture(autouse=True)
def patch_model(monkeypatch):
    FakeModel.instances = []
    FakeModel.fail_devices = ()
    monkeypatch.setattr(tr, "_load_whisper_class", lambda: FakeModel)


def test_transcribe_converts_times(tmp_path):
    t = Transcriber(make_settings(whisper_device="cpu"))
    assert FakeModel.instances == []  # lazy
    out = t.transcribe(tmp_path / "a.mp3", speed_factor=2.0)
    assert out.duration == 20.0
    assert [(s.start, s.end, s.text) for s in out.segments] == [(2.0, 6.0, "Olá"), (8.0, 10.0, "mundo")]
    assert out.language == "pt" and out.model == "tiny"
    kw = FakeModel.instances[0].calls[0]
    assert kw["vad_filter"] is True and kw["beam_size"] == 5 and kw["language"] == "pt"
    assert FakeModel.instances[0].compute_type == "int8"


def test_language_auto(tmp_path):
    t = Transcriber(make_settings(whisper_device="cpu", language="auto"))
    out = t.transcribe(tmp_path / "a.mp3", speed_factor=1.0)
    assert FakeModel.instances[0].calls[0]["language"] is None
    assert out.language == "en"


def test_auto_falls_back_to_cpu(tmp_path, capsys):
    FakeModel.fail_devices = ("cuda",)
    t = Transcriber(make_settings())
    out = t.transcribe(tmp_path / "a.mp3", speed_factor=2.0)
    assert len(out.segments) == 2
    assert [m.device for m in FakeModel.instances] == ["cuda", "cpu"]
    assert FakeModel.instances[1].compute_type == "int8"
    assert "CPU" in capsys.readouterr().err
    # stays on cpu afterwards
    t.transcribe(tmp_path / "b.mp3", speed_factor=2.0)
    assert len(FakeModel.instances) == 2


def test_auto_falls_back_on_inference_failure(tmp_path, capsys):
    class Lazy(FakeModel):
        def transcribe(self, audio, **kw):
            if self.device == "cuda":
                def gen():
                    raise RuntimeError("cublas failed")
                    yield
                return gen(), S(language="pt", duration=10.0)
            return super().transcribe(audio, **kw)

    tr._load_whisper_class = lambda: Lazy
    t = Transcriber(make_settings())
    out = t.transcribe(tmp_path / "a.mp3", speed_factor=2.0)
    assert len(out.segments) == 2
    assert [m.device for m in Lazy.instances] == ["cuda", "cpu"]


def test_explicit_cuda_failure_raises(tmp_path):
    FakeModel.fail_devices = ("cuda",)
    t = Transcriber(make_settings(whisper_device="cuda"))
    with pytest.raises(RuntimeError):
        t.transcribe(tmp_path / "a.mp3", speed_factor=2.0)


def test_find_loops_detects_repeated_segments():
    from transcript.models import Segment
    from transcript.transcribe import find_loops

    segs = [Segment(0, 1, "oi")] + [Segment(1 + i * 60, 61 + i * 60, "Como é que começou?") for i in range(7)] + [Segment(500, 501, "fim")]
    assert find_loops(segs) == [(1, 421, 7)]
    assert find_loops(segs[:3]) == []
