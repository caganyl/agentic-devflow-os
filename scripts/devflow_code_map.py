#!/usr/bin/env python3
"""
DevFlow kod haritası: Graphify'ı yalnızca yerel AST modunda çalıştıran sarmalayıcı.

Graphify (Graphify-Labs/graphify, Apache-2.0) kodu tree-sitter ile tarayıp
sembol grafiği çıkarır: kim kimi çağırıyor, neyi uyguluyor, neyi import ediyor.
DevFlow onu opsiyonel bir kanıt kaynağı olarak kullanır; mimari gerçeğin kaynağı
yine onaylı mimari profil ve devflow_arch_scan.py'dir.

Kullanım:
    devflow_code_map.py build   [--root DIR]            haritayı kur/güncelle (yazar)
    devflow_code_map.py status  [--root DIR]            var mı, güncel mi
    devflow_code_map.py affected "<Sembol>" [--depth N] [--root DIR]
    devflow_code_map.py explain  "<Sembol>" [--root DIR]
    devflow_code_map.py path     "<A>" "<B>" [--root DIR]
    devflow_code_map.py query    "<soru>" [--budget N] [--root DIR]

Güvenlik:
- Harita yalnızca <root>/.devflow/cache/code-map/ altına yazılır (gitignore'da).
- GRAPHIFY_BACKEND=none ve GRAPHIFY_NO_AUTO_REFRESH=1 ile çalışır; *_API_KEY
  ortam değişkenleri alt sürece verilmez. Kod hiçbir yere gönderilmez,
  ~/.claude veya git hook'larına dokunulmaz.
- build dışındaki komutlar salt okunurdur (Graphify yalnızca kendi önbellek
  klasörüne bir sorgu zaman damgası yazar).

Çıkış kodları: 0 cevap; 2 harita yok; 3 graphify kurulu değil veya isim
belirsiz (Graphify'ın kendi kodu); 4 eşleşen sembol yok; 1 diğer hatalar.

Stdlib only.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

GRAPHIFY_VERSION = "0.9.93"
INSTALL_HINT = f'uv tool install graphifyy=={GRAPHIFY_VERSION}  (veya: pipx install graphifyy=={GRAPHIFY_VERSION})'
MAP_REL = Path(".devflow") / "cache" / "code-map"
DEVFLOW_GITIGNORE = "cache/\nlogs/\n*.tmp\n"
SECRET_ENV = re.compile(r"(API_KEY|API_TOKEN|_SECRET|ACCESS_KEY)$", re.IGNORECASE)
READ_COMMANDS = ("affected", "explain", "path", "query")
DEFAULT_BUDGET = "1500"


def find_graphify() -> str | None:
    override = os.environ.get("DEVFLOW_GRAPHIFY_BIN")
    if override:
        return override if Path(override).exists() else None
    return shutil.which("graphify")


def child_env(root: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if not SECRET_ENV.search(k)}
    env["GRAPHIFY_BACKEND"] = "none"
    env["GRAPHIFY_NO_AUTO_REFRESH"] = "1"
    env["GRAPHIFY_OUT"] = str(root / MAP_REL)
    return env


def graph_file(root: Path) -> Path:
    return root / MAP_REL / "graph.json"


def check_version(binary: str, env: dict) -> None:
    try:
        out = subprocess.run([binary, "--version"], capture_output=True, text=True,
                             env=env, timeout=30).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return
    found = out.split()[-1] if out else "?"
    if found != GRAPHIFY_VERSION:
        print(f"Uyarı: graphify {found} kurulu; DevFlow {GRAPHIFY_VERSION} ile test edildi. "
              f"Sabitlemek için: {INSTALL_HINT}", file=sys.stderr)


def git(root: Path, *args: str) -> str:
    try:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                              text=True, timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def staleness(root: Path) -> str | None:
    """Return why the map is out of date, or None when it looks current."""
    graph = graph_file(root)
    built = graph.stat().st_mtime
    last_commit = git(root, "log", "-1", "--format=%ct").strip()
    if last_commit.isdigit() and int(last_commit) > built:
        return "haritadan sonra commit var"
    for name in git(root, "diff", "--name-only", "HEAD").splitlines():
        path = root / name
        if path.is_file() and path.stat().st_mtime > built:
            return f"commit edilmemiş değişiklik: {name}"
    return None


def ensure_gitignored(root: Path) -> None:
    devflow = root / ".devflow"
    gitignore = devflow / ".gitignore"
    if not gitignore.exists():
        devflow.mkdir(parents=True, exist_ok=True)
        gitignore.write_text(DEVFLOW_GITIGNORE, encoding="utf-8")
    elif "cache/" not in gitignore.read_text(encoding="utf-8").split():
        print("Uyarı: .devflow/.gitignore 'cache/' içermiyor; kod haritası commit edilebilir.",
              file=sys.stderr)


def cmd_build(root: Path, binary: str, env: dict) -> int:
    ensure_gitignored(root)
    (root / MAP_REL).mkdir(parents=True, exist_ok=True)
    result = subprocess.run([binary, "update", str(root)], env=env, cwd=str(root),
                            capture_output=True, text=True)
    if result.returncode != 0:
        sys.stderr.write(result.stdout + result.stderr)
        return 1
    rebuilt = [line for line in result.stdout.splitlines() if "Rebuilt:" in line]
    summary = rebuilt[-1].split("Rebuilt:", 1)[1].strip() if rebuilt else "güncellendi"
    print(f"Kod haritası: {summary} -> {MAP_REL.as_posix()}/graph.json")
    return 0


def cmd_status(root: Path) -> int:
    graph = graph_file(root)
    if not graph.is_file():
        print("Kod haritası: yok (claude-devflow map ile kurulur)")
        return 2
    reason = staleness(root)
    print(f"Kod haritası: {'eski — ' + reason if reason else 'güncel'} ({MAP_REL.as_posix()}/graph.json)")
    return 0


def cmd_read(root: Path, binary: str, env: dict, command: str, args: argparse.Namespace) -> int:
    graph = graph_file(root)
    if not graph.is_file():
        print("Kod haritası yok. İnsan veya ana oturum kurar: claude-devflow map", file=sys.stderr)
        return 2
    reason = staleness(root)
    if reason:
        print(f"Not: kod haritası eski ({reason}); sonuç doğrulanmalı.", file=sys.stderr)
    argv = [binary, command, *args.terms, "--graph", str(graph)]
    if command == "query":
        argv += ["--budget", str(args.budget or DEFAULT_BUDGET)]
    if command == "affected" and args.depth:
        argv += ["--depth", str(args.depth)]
    return subprocess.run(argv, env=env, cwd=str(root)).returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DevFlow kod haritası (Graphify, yalnızca AST).")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("build", "status"):
        sub.add_parser(name).add_argument("--root", default=".")
    arity = {"affected": 1, "explain": 1, "path": 2, "query": 1}
    for name in READ_COMMANDS:
        p = sub.add_parser(name)
        p.add_argument("terms", nargs=arity[name])
        p.add_argument("--root", default=".")
        if name == "query":
            p.add_argument("--budget", type=int)
        if name == "affected":
            p.add_argument("--depth", type=int)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    top = git(Path(args.root), "rev-parse", "--show-toplevel").strip()
    root = Path(top or args.root).resolve()

    if args.command == "status":
        return cmd_status(root)

    binary = find_graphify()
    if not binary:
        print(f"graphify kurulu değil. Kurulum: {INSTALL_HINT}", file=sys.stderr)
        return 3
    env = child_env(root)
    if args.command == "build":
        check_version(binary, env)
        return cmd_build(root, binary, env)
    return cmd_read(root, binary, env, args.command, args)


if __name__ == "__main__":
    sys.exit(main())
