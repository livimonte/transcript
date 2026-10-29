import json

import pytest

from transcript.config import Settings
from transcript.projects import Project, slugify


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("TRANSCRIPT_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


def test_slugify():
    assert slugify("Aula Número 1 — Introdução!") == "aula-numero-1-introducao"
    assert slugify("  A__b  ") == "a-b"
    assert slugify("???") == "item"


def test_create_open_list(home):
    p = Project.create("Projeto X")
    assert p.slug == "projeto-x" and p.name == "Projeto X"
    assert p.root == home / "projeto-x"
    for d in (p.input_dir, p.audio_1x_dir, p.audio_2x_dir, p.transcripts_dir, p.markdown_dir, p.refined_dir):
        assert d.is_dir()
    assert p.input_dir.name == "1_input" and p.audio_2x_dir == p.root / "2_audio" / "2x"
    assert p.refined_dir.name == "5_refined"
    data = json.loads((p.root / "project.json").read_text())
    assert data["name"] == "Projeto X" and "created_at" in data
    assert Project.open("projeto-x").name == "Projeto X"
    Project.create("Y")
    assert [x.slug for x in Project.list_all()] == ["projeto-x", "y"]


def test_create_twice_and_open_missing():
    Project.create("a")
    with pytest.raises(FileExistsError):
        Project.create("a")
    with pytest.raises(FileNotFoundError):
        Project.open("nope")
    assert Project.list_all() != []


def test_list_all_empty():
    assert Project.list_all() == []


def test_settings_overrides():
    p = Project.create("s")
    assert p.settings == Settings.from_env()
    p.update_settings({"whisper_model": "tiny", "speed_factor": 1.5})
    q = Project.open("s")
    assert q.settings.whisper_model == "tiny" and q.settings.speed_factor == 1.5


def test_add_files_and_folders(tmp_path):
    src = tmp_path / "src"
    (src / "aula 1").mkdir(parents=True)
    (src / "aula 1" / "Parte 2.MP4").write_bytes(b"a")
    (src / "aula 1" / "notes.txt").write_text("x")
    (src / "solo.mp3").write_bytes(b"b")
    p = Project.create("p")
    items = p.add_files([src / "aula 1", src / "solo.mp3"])
    assert sorted(i.slug for i in items) == ["aula-1--parte-2", "solo"]
    by = {i.slug: i for i in items}
    it = by["aula-1--parte-2"]
    assert it.original_name == "Parte 2.MP4"
    assert it.source == p.input_dir / "aula 1" / "Parte 2.MP4" and it.source.read_bytes() == b"a"
    assert (src / "solo.mp3").exists()  # copiado
    assert not (p.input_dir / "aula 1" / "notes.txt").exists()
    assert it.mp3_1x == p.audio_1x_dir / "aula-1--parte-2.mp3"
    assert it.mp3_2x == p.audio_2x_dir / "aula-1--parte-2.mp3"
    assert it.raw_json == p.transcripts_dir / "aula-1--parte-2.json"
    assert it.md_full == p.markdown_dir / "aula-1--parte-2.md"
    assert it.md_full_dir == p.markdown_dir / "aula-1--parte-2"
    assert it.md_refined == p.refined_dir / "aula-1--parte-2.md"
    assert it.md_refined_dir == p.refined_dir / "aula-1--parte-2"
    assert [i.slug for i in Project.open("p").items()] == ["aula-1--parte-2", "solo"]


def test_add_move_and_idempotent(tmp_path):
    f = tmp_path / "v.mp4"
    f.write_bytes(b"123")
    p = Project.create("p")
    (i,) = p.add_files([f], move=True)
    assert not f.exists() and i.source.read_bytes() == b"123"
    f.write_bytes(b"123")
    (j,) = p.add_files([f])
    assert j.slug == i.slug and len(p.items()) == 1


def test_slug_collision(tmp_path):
    a, b = tmp_path / "x" / "A B.mp4", tmp_path / "y" / "a-b.mp4"
    for f, c in ((a, b"1"), (b, b"22")):
        f.parent.mkdir()
        f.write_bytes(c)
    p = Project.create("p")
    items = p.add_files([a, b])
    assert [i.slug for i in items] == ["a-b", "a-b-2"]
    assert items[1].source.read_bytes() == b"22"


def test_same_name_different_content(tmp_path):
    a, b = tmp_path / "x" / "v.mp4", tmp_path / "y" / "v.mp4"
    for f, c in ((a, b"1"), (b, b"22")):
        f.parent.mkdir()
        f.write_bytes(c)
    p = Project.create("p")
    items = p.add_files([a, b])
    assert len({i.slug for i in items}) == 2 and len({i.source for i in items}) == 2


def test_add_missing_raises(tmp_path):
    p = Project.create("p")
    with pytest.raises(FileNotFoundError):
        p.add_files([tmp_path / "nada.mp4"])


def test_status_roundtrip(tmp_path):
    f = tmp_path / "v.mp4"
    f.write_bytes(b"1")
    p = Project.create("p")
    (i,) = p.add_files([f])
    assert p.get_status(i, "audio") == "pending"
    p.set_status(i, "audio", "done")
    p.set_status(i, "transcribe", "failed", error="boom")
    q = Project.open("p")
    assert q.get_status(i, "audio") == "done"
    assert q.get_status(i.slug, "transcribe") == "failed"
    assert q.get_error(i, "transcribe") == "boom"
    assert q.get_error(i, "audio") is None
    assert q.get_status(i, "refine") == "pending"
    q.set_status(i, "transcribe", "done")
    assert q.get_error(i, "transcribe") is None
    with pytest.raises(ValueError):
        q.set_status(i, "bogus", "done")
    with pytest.raises(ValueError):
        q.set_status(i, "audio", "weird")
    assert not list(q.root.glob("*.tmp"))
    assert json.loads((q.root / "state.json").read_text())["items"][i.slug]["original_name"] == "v.mp4"


def test_add_files_link_does_not_copy(tmp_path, monkeypatch):
    monkeypatch.setenv("TRANSCRIPT_HOME", str(tmp_path / "projects"))
    src = tmp_path / "ext" / "Aula 1.mp4"
    src.parent.mkdir()
    src.write_bytes(b"video")
    p = Project.create("Link")
    item = p.add_files([src], link=True)[0]
    assert item.source.is_symlink() and item.source.resolve() == src.resolve()
    assert p.add_files([src], link=True)[0].slug == item.slug  # idempotente
    assert len(p.items()) == 1
