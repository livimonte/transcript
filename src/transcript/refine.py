"""Fase 2c: refinamento do Markdown completo via IA (transcrição limpa, sem resumo)."""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

DEFAULT_PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "refine.md"
CONTEXT_TAIL_CHARS = 800
MIN_RATIO = 0.45
SHORT_REMINDER = (
    "ATENÇÃO: a resposta anterior ficou curta demais; NÃO resuma, preserve todo o conteúdo"
)


class Backend(Protocol):
    def complete(self, system: str, user: str) -> str: ...


class AnthropicBackend:
    """Backend usando o SDK `anthropic`; cliente lazy e retry com backoff exponencial."""

    def __init__(self, model: str, max_tokens: int = 16000, *, effort: str = "medium", max_attempts: int = 5,
                 base_delay: float = 2.0, sleep: Callable[[float], None] = time.sleep):
        self.model = model
        self.max_tokens = max_tokens
        self.effort = effort  # low|medium|high|xhigh|max; thinking é sempre adaptativo no Opus 5.5
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self._sleep = sleep
        self._client = None

    def _get_client(self):
        if self._client is None:
            key = os.environ.get("ANTHROPIC_API_KEY")
            if not key:
                raise RuntimeError(
                    "ANTHROPIC_API_KEY não definida. Defina a chave da API da Anthropic "
                    "no ambiente ou no arquivo .env (veja .env.example) para usar o refinamento."
                )
            import anthropic

            self._client = anthropic.Anthropic(api_key=key)
        return self._client

    @staticmethod
    def _retryable(exc: Exception) -> bool:
        import anthropic

        if isinstance(exc, (anthropic.RateLimitError, anthropic.APITimeoutError,
                            anthropic.APIConnectionError, anthropic.InternalServerError)):
            return True
        status = getattr(exc, "status_code", None)
        return isinstance(exc, anthropic.APIStatusError) and status is not None and (
            status >= 500 or status == 429
        )

    def complete(self, system: str, user: str) -> str:
        client = self._get_client()
        for attempt in range(1, self.max_attempts + 1):
            try:
                msg = client.messages.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    # Opus 5.5: sem temperature/top_p/top_k (400); thinking não pode ser desligado
                    output_config={"effort": self.effort},
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )
                return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
            except Exception as exc:  # noqa: BLE001
                if attempt >= self.max_attempts or not self._retryable(exc):
                    raise
                self._sleep(self.base_delay * 2 ** (attempt - 1))
        raise AssertionError("inalcançável")


class FakeBackend:
    """Backend determinístico para testes: `responder(system, user, indice_da_chamada) -> str`."""

    def __init__(self, responder: Callable[[str, str, int], str]):
        self.responder = responder
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str) -> str:
        i = len(self.calls)
        self.calls.append((system, user))
        return self.responder(system, user, i)


def load_prompt(path: Path | str | None = None) -> tuple[str, str]:
    text = Path(path or DEFAULT_PROMPT_PATH).read_text(encoding="utf-8")

    def block(name: str) -> str:
        m = re.search(rf"^<!-- {name}:START -->\n(.*?)\n<!-- {name}:END -->$", text, re.S | re.M)
        if not m:
            raise ValueError(f"Bloco {name} não encontrado no prompt")
        return m.group(1).strip()

    return block("SYSTEM"), block("USER")


def split_for_refine(body: str, chunk_chars: int) -> list[str]:
    """Agrupa parágrafos (separados por linha em branco) em trechos de até chunk_chars."""
    blocks = [b.strip() for b in re.split(r"\n\s*\n", body) if b.strip()]
    chunks: list[str] = []
    cur: list[str] = []
    cur_len = 0
    for b in blocks:
        add = len(b) + (2 if cur else 0)
        if cur and cur_len + add > chunk_chars:
            chunks.append("\n\n".join(cur))
            cur, cur_len, add = [], 0, len(b)
        cur.append(b)
        cur_len += add
    if cur:
        chunks.append("\n\n".join(cur))
    return chunks


@dataclass
class RefineResult:
    front_matter: str
    blocks: list[str]
    markdown: str
    warnings: list[str] = field(default_factory=list)


_FM_RE = re.compile(r"\A---\n(.*?)\n---[ \t]*\n?", re.S)
_GLOSS_RE = re.compile(r"<glossario>(.*?)</glossario>", re.S | re.I)
_FENCE_RE = re.compile(r"\A```[\w-]*\n(.*?)\n?```\s*\Z", re.S)


def _split_front_matter(md: str) -> tuple[list[str], str]:
    m = _FM_RE.match(md)
    if not m:
        return [], md
    return m.group(1).splitlines(), md[m.end():]


def _build_front_matter(lines: list[str], model_name: str, source_markdown: str) -> str:
    out = [l for l in lines if not re.match(r"(type|refined_by|source_markdown):", l)]
    out.append("type: transcricao-refinada")
    out.append(f"refined_by: {model_name}")
    if source_markdown:
        out.append(f"source_markdown: {source_markdown}")
    return "---\n" + "\n".join(out) + "\n---\n"


def _clean_output(text: str) -> tuple[str, list[str]]:
    terms: list[str] = []
    for m in _GLOSS_RE.finditer(text):
        terms += [t.strip() for t in re.split(r"[;\n]", m.group(1)) if t.strip()]
    text = _GLOSS_RE.sub("", text).strip()
    fm = _FENCE_RE.match(text)
    if fm:
        text = fm.group(1).strip()
    return text, terms


def _context(prev_out: str, glossary: list[str]) -> str:
    if not prev_out and not glossary:
        return ""
    parts = []
    if prev_out:
        parts.append(prev_out[-CONTEXT_TAIL_CHARS:])
    if glossary:
        parts.append("Glossário: " + "; ".join(glossary))
    return "<contexto_anterior>\n" + "\n\n".join(parts) + "\n</contexto_anterior>\n\n"


def refine_markdown(
    full_md: str,
    backend: Backend,
    *,
    chunk_chars: int = 12000,
    model_name: str = "",
    source_markdown: str = "",
    on_progress: Callable[[int, int], None] | None = None,
    prompt_path: Path | str | None = None,
) -> RefineResult:
    system, user_tpl = load_prompt(prompt_path)
    fm_lines, body = _split_front_matter(full_md)
    chunks = split_for_refine(body, chunk_chars)
    glossary: list[str] = []
    seen: set[str] = set()
    outputs: list[str] = []
    warnings: list[str] = []

    for i, chunk in enumerate(chunks, 1):
        prev = outputs[-1] if outputs else ""
        user = user_tpl.replace("{contexto_anterior}", _context(prev, glossary)).replace("{trecho}", chunk)
        text, terms = _clean_output(backend.complete(system, user))
        if len(text) < MIN_RATIO * len(chunk):
            warnings.append(
                f"Trecho {i}/{len(chunks)}: saída com {len(text)} de {len(chunk)} caracteres "
                "(provável resumo indevido); tentando novamente."
            )
            text2, terms2 = _clean_output(backend.complete(system, user + "\n\n" + SHORT_REMINDER))
            terms += terms2
            if len(text2) > len(text):
                text = text2
            if len(text) < MIN_RATIO * len(chunk):
                warnings.append(f"Trecho {i}/{len(chunks)}: continua curto após nova tentativa.")
        for t in terms:
            if t.lower() not in seen:
                seen.add(t.lower())
                glossary.append(t)
        outputs.append(text)
        if on_progress:
            on_progress(i, len(chunks))

    blocks = [b.strip() for o in outputs for b in re.split(r"\n\s*\n", o) if b.strip()]
    front = _build_front_matter(fm_lines, model_name, source_markdown)
    markdown = front + "\n" + "\n\n".join(blocks) + "\n"
    return RefineResult(front, blocks, markdown, warnings)
