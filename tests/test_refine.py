from __future__ import annotations

import pytest

from transcript import refine
from transcript.refine import (
    FakeBackend,
    load_prompt,
    refine_markdown,
    split_for_refine,
)

FM = "---\ntitle: Aula 1\ntype: transcricao-completa\nmodel: large-v3\n---\n"


def _body(n: int, size: int = 100) -> str:
    return "\n\n".join(f"**[{i:02d}:00]** " + ("palavra " * (size // 8)).strip() for i in range(n))


def test_load_prompt_default():
    system, user = load_prompt()
    assert "copidesque" in system
    assert "{contexto_anterior}" in user and "{trecho}" in user
    assert "SYSTEM:START" not in system and "USER:END" not in user


def test_load_prompt_custom(tmp_path):
    p = tmp_path / "p.md"
    p.write_text("x\n<!-- SYSTEM:START -->\nSYS\n<!-- SYSTEM:END -->\n<!-- USER:START -->\n{trecho}\n<!-- USER:END -->\n")
    assert load_prompt(p) == ("SYS", "{trecho}")


def test_split_respects_paragraphs():
    body = _body(10, 100)
    chunks = split_for_refine(body, 350)
    assert len(chunks) > 1
    assert "\n\n".join(chunks) == body
    for c in chunks:
        assert len(c) <= 350
        assert c.startswith("**[")


def test_split_oversized_block_alone():
    big = "**[00:00]** " + "x" * 500
    body = "**[00:01]** a\n\n" + big + "\n\n**[00:02]** b"
    chunks = split_for_refine(body, 100)
    assert chunks == ["**[00:01]** a", big, "**[00:02]** b"]


def test_split_empty():
    assert split_for_refine("  \n ", 100) == []


def test_continuity_and_glossary_removed():
    body = _body(6, 100)
    n_chunks = len(split_for_refine(body, 250))
    assert n_chunks >= 2
    calls = []

    def responder(system, user, i):
        calls.append(user)
        text = user.split("<trecho>\n")[1].split("\n</trecho>")[0]
        return f"## T{i}\n\n{text}\n\n<glossario>\nTermo{i}; Comum\n</glossario>"

    fb = FakeBackend(responder)
    res = refine_markdown(FM + "\n" + body, fb, chunk_chars=250, model_name="m1")
    assert len(calls) == n_chunks
    assert "<contexto_anterior>" not in calls[0]
    assert "<contexto_anterior>" in calls[1]
    assert "Termo0" in calls[1] and "## T0" in calls[1]
    assert "Termo1" in calls[2] if n_chunks > 2 else True
    assert "<glossario>" not in res.markdown and "Termo0" not in res.markdown
    # glossário sem duplicatas
    last_ctx = calls[-1].split("</contexto_anterior>")[0]
    assert last_ctx.count("Comum") == 1
    assert res.warnings == []
    assert all(b.strip() == b and b for b in res.blocks)
    assert "\n\n".join(res.blocks) in res.markdown


def test_context_tail_limited():
    long = "y" * 3000
    calls = []

    def responder(system, user, i):
        calls.append(user)
        return long if i == 0 else "ok " * 100

    body = "**[00:00]** " + "a" * 200 + "\n\n**[00:01]** " + "b" * 200
    refine_markdown(body, FakeBackend(responder), chunk_chars=250)
    ctx = calls[1].split("</contexto_anterior>")[0]
    assert ctx.count("y") <= 800


def test_fidelity_retry_keeps_longer():
    body = "**[00:00]** " + "palavra " * 100
    calls = []

    def responder(system, user, i):
        calls.append(user)
        return "curto" if i == 0 else "## Titulo\n\n" + "palavra " * 90

    res = refine_markdown(body, FakeBackend(responder), chunk_chars=5000)
    assert len(calls) == 2
    assert "ATENÇÃO: a resposta anterior ficou curta demais; NÃO resuma, preserve todo o conteúdo" in calls[1]
    assert "ATENÇÃO" not in calls[0]
    assert "curto" not in res.markdown
    assert res.warnings == [] or len(res.warnings) == 1


def test_fidelity_retry_still_short_warns():
    body = "**[00:00]** " + "palavra " * 100
    res = refine_markdown(body, FakeBackend(lambda s, u, i: "curto"), chunk_chars=5000)
    assert len(res.warnings) >= 1
    assert "curto" in res.markdown


def test_front_matter_and_fences():
    body = "**[00:00]** " + "palavra " * 20
    fb = FakeBackend(lambda s, u, i: "```markdown\n## T\n\n" + "palavra " * 20 + "\n```")
    res = refine_markdown(FM + "\n" + body, fb, chunk_chars=5000, model_name="claude-x", source_markdown="aula.md")
    assert "type: transcricao-refinada" in res.front_matter
    assert "transcricao-completa" not in res.front_matter
    assert "refined_by: claude-x" in res.front_matter
    assert "source_markdown: aula.md" in res.front_matter
    assert "title: Aula 1" in res.front_matter
    assert res.front_matter.startswith("---\n") and res.front_matter.rstrip().endswith("---")
    assert res.markdown.startswith(res.front_matter)
    assert "```" not in res.markdown


def test_no_front_matter_and_progress():
    seen = []
    body = _body(4, 100)
    res = refine_markdown(body, FakeBackend(lambda s, u, i: u.split("<trecho>\n")[1].split("\n</trecho>")[0]),
                          chunk_chars=250, on_progress=lambda i, n: seen.append((i, n)))
    assert res.front_matter.startswith("---")
    assert "type: transcricao-refinada" in res.front_matter
    assert seen[-1][0] == seen[-1][1]


def test_anthropic_backend_missing_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    b = refine.AnthropicBackend("m")
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        b.complete("s", "u")


def _rate_limit_error():
    import anthropic

    exc = anthropic.RateLimitError.__new__(anthropic.RateLimitError)
    Exception.__init__(exc, "rate limited")
    exc.status_code = 429
    return exc


def test_anthropic_backend_retries(monkeypatch):
    import anthropic

    b = refine.AnthropicBackend("m", sleep=lambda s: None)
    n = {"c": 0}

    class Block:
        type = "text"
        text = "resp"

    class Msg:
        content = [Block()]

    class Messages:
        def create(self, **kw):
            n["c"] += 1
            if n["c"] < 3:
                raise _rate_limit_error()
            return Msg()

    class Client:
        messages = Messages()

    b._client = Client()
    assert b.complete("s", "u") == "resp"
    assert n["c"] == 3

    n["c"] = -100  # sempre falha
    with pytest.raises(anthropic.RateLimitError):
        b.complete("s", "u")


def test_anthropic_backend_sends_effort_and_no_sampling_params(monkeypatch):
    from types import SimpleNamespace

    from transcript.refine import AnthropicBackend

    seen = {}

    class FakeMessages:
        def create(self, **kw):
            seen.update(kw)
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="ok")])

    b = AnthropicBackend("claude-opus-5-5")
    b._client = SimpleNamespace(messages=FakeMessages())
    assert b.complete("sys", "user") == "ok"
    assert seen["model"] == "claude-opus-5-5"
    assert seen["output_config"] == {"effort": "medium"}
    assert seen["max_tokens"] == 16000
    assert not {"temperature", "top_p", "top_k", "thinking"} & seen.keys()
