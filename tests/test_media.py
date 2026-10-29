import subprocess

import pytest

from transcript.media import MediaError, ffmpeg_exe, probe_duration, speed_up, to_mp3


def _gen(path, *extra):
    subprocess.run([ffmpeg_exe(), "-nostdin", "-y", "-loglevel", "error", *extra, str(path)],
                   check=True)


@pytest.fixture(scope="module")
def wav(tmp_path_factory):
    p = tmp_path_factory.mktemp("m") / "a.wav"
    _gen(p, "-f", "lavfi", "-i", "sine=frequency=440:duration=3")
    return p


@pytest.fixture(scope="module")
def mp4(tmp_path_factory):
    p = tmp_path_factory.mktemp("v") / "v.mp4"
    _gen(p, "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
         "-f", "lavfi", "-i", "testsrc=duration=3:size=160x120:rate=10",
         "-c:v", "mpeg4", "-c:a", "aac", "-shortest")
    return p


def test_to_mp3_from_wav(wav, tmp_path):
    dst = tmp_path / "sub" / "a.mp3"
    to_mp3(wav, dst)
    assert dst.stat().st_size > 0
    assert probe_duration(dst) == pytest.approx(3.0, abs=0.15)
    assert not list(dst.parent.glob("*.part"))


def test_to_mp3_from_video(mp4, tmp_path):
    dst = tmp_path / "v.mp3"
    to_mp3(mp4, dst)
    assert probe_duration(dst) == pytest.approx(3.0, abs=0.15)


@pytest.mark.parametrize("factor,expected", [(2.0, 1.5), (2.5, 1.2)])
def test_speed_up(wav, tmp_path, factor, expected):
    src = tmp_path / "s.mp3"
    to_mp3(wav, src)
    dst = tmp_path / "out" / "f.mp3"
    speed_up(src, dst, factor=factor)
    assert probe_duration(dst) == pytest.approx(expected, abs=0.15)
    assert not list(dst.parent.glob("*.part"))


def test_missing_file_raises(tmp_path):
    dst = tmp_path / "x.mp3"
    with pytest.raises(MediaError):
        to_mp3(tmp_path / "nope.wav", dst)
    with pytest.raises(MediaError):
        speed_up(tmp_path / "nope.mp3", dst)
    with pytest.raises(MediaError):
        probe_duration(tmp_path / "nope.mp3")
    assert not dst.exists()
    assert not list(tmp_path.glob("*.part"))
