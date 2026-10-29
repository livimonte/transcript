from pathlib import Path

from transcript.models import Segment, Transcript
from transcript.render import (
    build_blocks,
    format_timestamp,
    render_full,
    split_parts,
    write_markdown,
)


def test_format_timestamp():
    assert format_timestamp(0) == "00:00"
    assert format_timestamp(65.9) == "01:05"
    assert format_timestamp(3599) == "59:59"
    assert format_timestamp(3600) == "01:00:00"
    assert format_timestamp(3725) == "01:02:05"


def _t(segs):
    return Transcript(language="pt", duration=100.0, model="tiny",
                      segments=[Segment(*s) for s in segs])


def test_paragraph_split_on_pause():
    t = _t([(0, 2, "Olá."), (2.5, 4, "Tudo bem."), (7, 9, "Outro assunto.")])
    blocks = build_blocks(t)
    assert blocks == ["**[00:00]** Olá. Tudo bem.", "**[00:07]** Outro assunto."]


def test_paragraph_split_on_size():
    segs = [(i, i + 1, "palavra " * 20) for i in range(10)]
    blocks = build_blocks(_t(segs), max_chars=300)
    assert len(blocks) > 1
    assert all(b.startswith("**[") for b in blocks)
    assert all(len(b) <= 300 + 200 for b in blocks)


def test_empty_segments_skipped():
    t = _t([(0, 1, "  "), (1, 2, "Oi")])
    assert build_blocks(t) == ["**[00:01]** Oi"]


def test_hours_marker():
    t = _t([(3700, 3701, "tarde")])
    assert build_blocks(t) == ["**[01:01:40]** tarde"]


def test_render_full_front_matter():
    t = _t([(0, 1, "Oi")])
    md = render_full(t, title="Aula: 1", source_name="a.mp4", project="projeto-x")
    assert md.startswith("---\n")
    head = md.split("---\n")[1]
    for key in ("title:", "source:", "project:", "language: pt", "duration:", "model: tiny",
                "type: transcricao-completa"):
        assert key in head
    assert '"Aula: 1"' in head  # quoted because of the colon
    assert md.rstrip().endswith("**[00:00]** Oi")


def test_split_parts_never_breaks_block():
    blocks = ["a" * 10, "b" * 10, "c" * 50, "d" * 10]
    parts = split_parts(blocks, 25)
    assert parts == [["a" * 10, "b" * 10], ["c" * 50], ["d" * 10]]
    assert [b for p in parts for b in p] == blocks
    assert ["c" * 50] in parts  # oversize block alone


def test_split_parts_packs():
    parts = split_parts(["a" * 10] * 5, 32)  # 10+2+10+2+10=34 > 32 -> 2 per part
    assert [len(p) for p in parts] == [2, 2, 1]
    assert split_parts([], 100) == []


FM = "---\ntitle: X\n---"


def test_write_single(tmp_path: Path):
    item_dir = tmp_path / "item"
    md = tmp_path / "item.md"
    out = write_markdown(item_dir, md, FM, ["**[00:00]** a", "**[00:10]** b"], "X", 1000)
    assert out == [md]
    assert "**[00:10]** b" in md.read_text()
    assert not item_dir.exists()
    assert not list(tmp_path.glob("*.tmp*"))


def test_write_parts_and_index(tmp_path: Path):
    item_dir = tmp_path / "item"
    md = tmp_path / "item.md"
    md.write_text("antigo")
    blocks = [f"**[{format_timestamp(i * 60)}]** " + "x" * 100 for i in range(6)]
    out = write_markdown(item_dir, md, FM, blocks, "Título", 260)
    assert not md.exists()
    names = sorted(p.name for p in item_dir.iterdir())
    assert names[0] == "index.md" and "parte-01.md" in names and "parte-03.md" in names
    assert out[0] == item_dir / "index.md" or item_dir / "index.md" in out
    idx = (item_dir / "index.md").read_text()
    assert "[parte-01.md](parte-01.md)" in idx
    assert "00:00" in idx and "05:00" in idx
    assert "Título" in idx
    p1 = (item_dir / "parte-01.md").read_text()
    assert p1.startswith("---\n") and "title: X" in p1


def test_switch_formats_cleans_old(tmp_path: Path):
    item_dir = tmp_path / "item"
    md = tmp_path / "item.md"
    blocks = ["x" * 100] * 6
    write_markdown(item_dir, md, FM, blocks, "T", 250)
    assert item_dir.exists() and not md.exists()
    write_markdown(item_dir, md, FM, blocks[:1], "T", 250)
    assert md.exists() and not item_dir.exists()
    write_markdown(item_dir, md, FM, blocks, "T", 250)
    assert not md.exists()
    # shrink part count: stale parts removed
    write_markdown(item_dir, md, FM, blocks[:3], "T", 250)
    names = sorted(p.name for p in item_dir.iterdir())
    assert names == ["index.md", "parte-01.md", "parte-02.md", "parte-03.md"]
    write_markdown(item_dir, md, FM, blocks[:3] + ["y" * 5], "T", 320)
    assert sorted(p.name for p in item_dir.iterdir()) == ["index.md", "parte-01.md", "parte-02.md"]
