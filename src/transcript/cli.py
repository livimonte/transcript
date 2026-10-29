"""Comando `transcript`."""

from __future__ import annotations

import argparse
import sys

from . import pipeline
from .config import load_env
from .projects import STAGES, Project

_STAGE_FNS = {
    "audio": pipeline.run_audio,
    "transcribe": pipeline.run_transcribe,
    "refine": pipeline.run_refine,
    "run": pipeline.run_all,
}
_ICON = {"done": "ok", "failed": "ERRO", "pending": "-"}


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="transcript", description="MP4 → MP3 → 2x → Markdown completo → Markdown refinado")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="lista os projetos")

    s = sub.add_parser("new", help="cria um projeto")
    s.add_argument("project")

    s = sub.add_parser("add", help="adiciona vídeos/áudios (arquivos ou pastas) a um projeto")
    s.add_argument("project")
    s.add_argument("paths", nargs="+")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--move", action="store_true", help="move em vez de copiar")
    g.add_argument("--link", action="store_true", help="não copia: aponta para o original (ex.: /mnt/c/...), só os áudios ficam no projeto")

    for name, helptext in [("audio", "fase 1: MP4 → MP3 → MP3 2x"), ("transcribe", "fase 2a: 2x → transcrição → Markdown completo"),
                           ("refine", "fase 2b: Markdown completo → Markdown refinado (IA)"), ("run", "todas as etapas")]:
        s = sub.add_parser(name, help=helptext)
        s.add_argument("project")
        s.add_argument("--item", action="append", metavar="SLUG", help="só este item (repetível)")
        s.add_argument("--force", action="store_true", help="refaz mesmo se já estiver pronto")

    s = sub.add_parser("status", help="tabela item × etapa")
    s.add_argument("project", nargs="?")

    s = sub.add_parser("config", help="mostra ou altera configurações do projeto (chave=valor)")
    s.add_argument("project")
    s.add_argument("pairs", nargs="*", metavar="chave=valor")
    return p


def _status(projects: list[Project]) -> None:
    for pr in projects:
        print(f"\n{pr.name}  ({pr.root})")
        items = pr.items()
        if not items:
            print("  (vazio — use `transcript add`)")
            continue
        w = max(len(it.slug) for it in items)
        print(f"  {'item':{w}} " + " ".join(f"{st:>10}" for st in STAGES))
        for it in items:
            print(f"  {it.slug:{w}} " + " ".join(f"{_ICON[pr.get_status(it, st)]:>10}" for st in STAGES))


def main(argv: list[str] | None = None) -> int:
    load_env()
    a = _parser().parse_args(argv)
    try:
        if a.cmd == "list":
            for pr in Project.list_all():
                print(f"{pr.slug}\t{len(pr.items())} itens")
        elif a.cmd == "new":
            pr = Project.create(a.project)
            print(f"Projeto criado: {pr.root}\nAdicione vídeos com: transcript add {pr.slug} <arquivos>")
        elif a.cmd == "add":
            items = Project.open(a.project).add_files(a.paths, move=a.move, link=a.link)
            print(f"{len(items)} item(ns) no projeto:")
            for it in items:
                print(f"  {it.slug}")
        elif a.cmd == "status":
            _status([Project.open(a.project)] if a.project else Project.list_all())
        elif a.cmd == "config":
            pr = Project.open(a.project)
            if a.pairs:
                pr.update_settings(dict(p.split("=", 1) for p in a.pairs))
            for k, v in vars(pr.settings).items():
                print(f"{k} = {v}")
        else:
            failed = _STAGE_FNS[a.cmd](Project.open(a.project), a.item, force=a.force)
            if failed:
                print(f"\nFalharam {len(failed)} item(ns): {', '.join(failed)}", file=sys.stderr)
                return 1
    except (FileNotFoundError, FileExistsError, KeyError, RuntimeError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
