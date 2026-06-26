#!/usr/bin/env python3
"""
DevFlow Operations Runner

Managed operations for target project initialization and delivery.
Standard library only. No third-party dependencies.

Subcommands:
    init-target       Initialize .devflow/ workspace in a target project (non-protected branch only)
    create-run        Create a new delivery run (non-protected branch only)
    launch            Launch Claude Code supervisor in a managed run worktree
    status            Show current run state
    prepare-delivery  Validate delivery readiness (approval evidence only; no real Git mutations)

Usage:
    python3 scripts/devflow_operations.py init-target --target PATH [--force]
    python3 scripts/devflow_operations.py create-run --target PATH [--objective TEXT]
    python3 scripts/devflow_operations.py launch --target PATH [--objective TEXT] [--dry-run]
    python3 scripts/devflow_operations.py status --target PATH
    python3 scripts/devflow_operations.py prepare-delivery --target PATH [--confirm-delivery]

Exit codes:
    0   Success
    1   Target path not found or not a directory
    2   Target path is the framework repo
    3   Target path is not a git repository
    4   .devflow/ not initialized or no active run
    5   Plugin build script not found (must run from framework copy)
    6   Claude binary not found
    7   Operation refused on protected branch (main/master)
    8   Forbidden git operation detected in planned command string
    9   Approval gates not passed
    10  Source register entry contains forbidden field
    11  Working tree is not clean (launch requires clean state)
    12  Run branch or worktree path already exists (collision)

IMPORTANT — validate_forbidden_git_operation:
    This function validates planned operation *strings* passed to it by callers.
    It is NOT a runtime git hook and does NOT intercept git commands executed
    elsewhere. Its purpose is to catch accidental construction of forbidden
    commands in delivery workflows, not to enforce at the OS level.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

FRAMEWORK_REPO = Path(__file__).resolve().parent.parent
DEVFLOW_DIR = ".devflow"
DEVFLOW_SCHEMA_VERSION = "1"
RUN_BRANCH_PREFIX = "devflow/run-"

FORBIDDEN_GIT_OPERATIONS = [
    "merge",
    "push --force",
    "push -f",
    "branch -d",
    "branch -D",
    "reset --hard",
    "reset --soft",
    "reset --mixed",
    "checkout -- .",
    "restore .",
    "clean -f",
]

PROTECTED_BRANCHES = frozenset({"main", "master"})

FORBIDDEN_SOURCE_FIELDS = frozenset({
    "token",
    "credential",
    "credentials",
    "password",
    "api_key",
    "apikey",
    "secret",
    "notebook_content",
    "raw_content",
    "content",
})

FORBIDDEN_NOTEBOOKLM_FIELDS = FORBIDDEN_SOURCE_FIELDS | frozenset({"url"})


# ---------------------------------------------------------------------------
# Atomic I/O helpers
# ---------------------------------------------------------------------------

def atomic_write_json(path: Path, data: dict) -> None:
    content = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    tmp_path.replace(path)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def is_git_repo(path: Path) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        cwd=str(path),
        capture_output=True,
    )
    return result.returncode == 0


def get_current_branch(repo_path: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=str(repo_path),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return "UNKNOWN"
    return result.stdout.strip()


def is_working_tree_clean(repo_path: Path) -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(repo_path),
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and not result.stdout.strip()


def get_existing_run_count(target: Path) -> int:
    """Return the highest run number among existing devflow/run-run-NNN branches."""
    result = subprocess.run(
        ["git", "branch", "--list", f"{RUN_BRANCH_PREFIX}*"],
        cwd=str(target),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return 0
    max_num = 0
    for line in result.stdout.strip().splitlines():
        branch = line.strip().lstrip("* ")
        m = re.search(r"-(\d+)$", branch)
        if m:
            max_num = max(max_num, int(m.group(1)))
    return max_num


def is_branch_exists(target: Path, branch: str) -> bool:
    result = subprocess.run(
        ["git", "branch", "--list", branch],
        cwd=str(target),
        capture_output=True,
        text=True,
    )
    return bool(result.stdout.strip())


def get_managed_worktree_root(target: Path) -> Path:
    """Return the managed worktree root adjacent to the target repo."""
    return target.parent / ".devflow-worktrees" / target.name


# ---------------------------------------------------------------------------
# Target project validation
# ---------------------------------------------------------------------------

def validate_target_path(target: Path) -> None:
    if not target.exists():
        print(f"Hata: Target path bulunamadı: {target}", file=sys.stderr)
        sys.exit(1)

    if not target.is_dir():
        print(f"Hata: Target path bir dizin olmalıdır: {target}", file=sys.stderr)
        sys.exit(1)

    framework = FRAMEWORK_REPO.resolve()
    target_resolved = target.resolve()

    if target_resolved == framework:
        print(
            f"Hata: Framework repo target olarak kullanılamaz: {target_resolved}",
            file=sys.stderr,
        )
        sys.exit(2)

    try:
        target_resolved.relative_to(framework)
        print(
            f"Hata: Target path framework repo içinde olamaz: {target_resolved}",
            file=sys.stderr,
        )
        sys.exit(2)
    except ValueError:
        pass

    if not is_git_repo(target):
        print(
            f"Hata: Target path bir Git repository olmalıdır: {target}",
            file=sys.stderr,
        )
        sys.exit(3)


def validate_not_on_protected_branch(target: Path, action: str) -> None:
    """Reject the operation if the target's current branch is protected."""
    branch = get_current_branch(target)
    if branch in PROTECTED_BRANCHES:
        print(
            f"Hata: '{action}' korumalı branch üzerinde çalışamaz: '{branch}'.",
            file=sys.stderr,
        )
        print(
            "  'launch --target ...' komutu otomatik run worktree ve yeni branch oluşturur.",
            file=sys.stderr,
        )
        print(
            "  Ya da feature branch oluşturup tekrar çalıştırın.",
            file=sys.stderr,
        )
        sys.exit(7)


def validate_delivery_safety(target: Path) -> None:
    current_branch = get_current_branch(target)
    if current_branch in PROTECTED_BRANCHES:
        print(
            f"Hata: Delivery operasyonu korumalı branch üzerinde yapılamaz: '{current_branch}'.",
            file=sys.stderr,
        )
        print(
            "  Feature branch'e geçin veya 'launch' ile yeni bir run başlatın.",
            file=sys.stderr,
        )
        sys.exit(7)


def validate_forbidden_git_operation(operation: str) -> None:
    """
    Validate a planned git operation string against the forbidden list.

    This checks the *string* passed by the caller — it is NOT a runtime git
    hook and does NOT intercept git commands executed elsewhere.
    """
    op_lower = operation.lower().strip()
    for forbidden in FORBIDDEN_GIT_OPERATIONS:
        if forbidden in op_lower:
            print(
                f"Hata: Yasak Git operasyonu tespit edildi: '{operation}'",
                file=sys.stderr,
            )
            print(
                "  merge, force push, branch silme, reset ve clean yasaktır.",
                file=sys.stderr,
            )
            sys.exit(8)


def validate_source_register_entry(entry: dict) -> None:
    source_type = entry.get("type", "")
    if source_type == "notebooklm":
        forbidden = FORBIDDEN_NOTEBOOKLM_FIELDS
    else:
        forbidden = FORBIDDEN_SOURCE_FIELDS

    for field in forbidden:
        if field in entry:
            print(
                f"Hata: Source register girişinde yasak alan '{field}' bulundu.",
                file=sys.stderr,
            )
            print(
                "  Ham token, credential, URL, raw içerik veya secret saklanamaz.",
                file=sys.stderr,
            )
            sys.exit(10)


# ---------------------------------------------------------------------------
# DevFlow workspace helpers
# ---------------------------------------------------------------------------

def get_devflow_dir(target: Path) -> Path:
    return target / DEVFLOW_DIR


def is_initialized(target: Path) -> bool:
    return (get_devflow_dir(target) / "project.json").exists()


def make_run_id(counter: int) -> str:
    return f"RUN-{counter:03d}"


def make_branch_name(run_id: str) -> str:
    run_id_normalized = run_id.lower().replace("_", "-")
    return f"{RUN_BRANCH_PREFIX}{run_id_normalized}"


# ---------------------------------------------------------------------------
# Claude binary discovery
# ---------------------------------------------------------------------------

def find_claude_binary() -> str | None:
    # Allow test override via environment variable
    override = os.environ.get("DEVFLOW_CLAUDE_BINARY")
    if override and Path(override).exists():
        return override
    candidates = [
        shutil.which("claude"),
        str(Path.home() / ".claude" / "local" / "claude"),
        "/usr/local/bin/claude",
        "/opt/homebrew/bin/claude",
    ]
    for c in candidates:
        if c and Path(c).exists():
            return c
    return None


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_init_target(args) -> int:
    target = Path(args.target).resolve()
    validate_target_path(target)
    validate_not_on_protected_branch(target, "init-target")

    devflow = get_devflow_dir(target)
    force = getattr(args, "force", False)

    if devflow.exists() and not force:
        project_json = devflow / "project.json"
        if project_json.exists():
            print(
                "Bilgi: .devflow/ zaten mevcut. Mevcut durum korunuyor. "
                "Üzerine yazmak için --force kullanın.",
            )
            return 0

    subdirs = ["context", "plans", "task-packets", "runs", "reports", "cache", "logs"]
    devflow.mkdir(parents=True, exist_ok=True)
    for subdir in subdirs:
        (devflow / subdir).mkdir(exist_ok=True)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    existing_project = devflow / "project.json"
    if not force and existing_project.exists():
        existing = read_json(existing_project)
        run_counter = existing.get("run_counter", 0)
        current_run_id = existing.get("current_run_id")
    else:
        run_counter = 0
        current_run_id = None

    project_data = {
        "schema_version": DEVFLOW_SCHEMA_VERSION,
        "initialized_at": now,
        "framework_version": "1.0.0",
        "run_counter": run_counter,
        "current_run_id": current_run_id,
        "target_project_path": str(target),
        "framework_repo_path": str(FRAMEWORK_REPO),
    }

    policy_data = {
        "schema_version": DEVFLOW_SCHEMA_VERSION,
        "forbidden_git_operations": list(FORBIDDEN_GIT_OPERATIONS),
        "require_confirm_delivery": True,
        "protected_branches": list(PROTECTED_BRANCHES),
        "run_branch_prefix": RUN_BRANCH_PREFIX,
        "dry_run_by_default": True,
        "notes": [
            "main merge insan onayı gerektirir.",
            "force push, branch silme ve reset yasaktır.",
            "prepare-delivery bu sürümde yalnızca doğrulama raporu üretir; gerçek Git mutasyonu yapmaz.",
            "main branch üzerinde init-target, create-run ve prepare-delivery çalışmaz.",
        ],
    }

    atomic_write_json(devflow / "project.json", project_data)
    atomic_write_json(devflow / "policy.json", policy_data)

    source_register_path = devflow / "source-register.json"
    if not source_register_path.exists() or force:
        source_register_data = {
            "schema_version": DEVFLOW_SCHEMA_VERSION,
            "initialized_at": now,
            "sources": [],
            "_notes": [
                "Yalnızca source metadata saklanır.",
                "Ham NotebookLM içeriği, token veya credential ekleme.",
                "NotebookLM için: label, freshness, access_mode, relevance, notes.",
                "Obsidian için yalnızca seçilmiş note label/reference kaydedilir.",
                "git_repository ve local_docs için path ve confidence metadata.",
            ],
        }
        atomic_write_json(source_register_path, source_register_data)

    gitignore_path = devflow / ".gitignore"
    if not gitignore_path.exists() or force:
        gitignore_path.write_text("cache/\nlogs/\n*.tmp\n", encoding="utf-8")

    print(f".devflow/ workspace başlatıldı: {devflow}")
    print(f"  subdirs: {', '.join(subdirs)}")
    print("  project.json: yazıldı")
    print("  policy.json: yazıldı")
    print("  source-register.json: yazıldı")
    return 0


def cmd_create_run(args) -> int:
    target = Path(args.target).resolve()
    validate_target_path(target)
    validate_not_on_protected_branch(target, "create-run")

    devflow = get_devflow_dir(target)
    if not is_initialized(target):
        print(
            "Hata: .devflow/ henüz başlatılmamış. Önce 'init-target' çalıştırın.",
            file=sys.stderr,
        )
        sys.exit(4)

    project_data = read_json(devflow / "project.json")
    run_counter = project_data.get("run_counter", 0) + 1
    run_id = make_run_id(run_counter)
    branch_name = make_branch_name(run_id)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    run_state = {
        "schema_version": DEVFLOW_SCHEMA_VERSION,
        "run_id": run_id,
        "created_at": now,
        "status": "created",
        "branch_name": branch_name,
        "objective": getattr(args, "objective", None) or "",
        "artifacts": [],
        "tasks": [],
        "approval_gates": {
            "contract_approved": False,
            "tests_passing": False,
            "security_review_complete": False,
            "qa_sign_off": False,
            "human_approval": False,
        },
    }

    runs_dir = devflow / "runs"
    runs_dir.mkdir(exist_ok=True)
    run_file = runs_dir / f"{run_id}.json"
    atomic_write_json(run_file, run_state)

    project_data["run_counter"] = run_counter
    project_data["current_run_id"] = run_id
    atomic_write_json(devflow / "project.json", project_data)

    print(f"Run oluşturuldu: {run_id}")
    print(f"  branch: {branch_name}")
    print(f"  dosya: .devflow/runs/{run_id}.json")
    return 0


def cmd_launch(args) -> int:
    target = Path(args.target).resolve()
    validate_target_path(target)
    dry_run = getattr(args, "dry_run", False)

    # Require clean working tree before creating a worktree
    if not is_working_tree_clean(target):
        print(
            "Hata: Target çalışma ağacında commit edilmemiş değişiklikler var.",
            file=sys.stderr,
        )
        print(
            "  Önce 'git commit' veya 'git stash' ile çalışma ağacını temizleyin.",
            file=sys.stderr,
        )
        sys.exit(11)

    # Derive next run number from existing branches (clash-free)
    existing_max = get_existing_run_count(target)
    run_counter = existing_max + 1
    run_id = make_run_id(run_counter)
    branch_name = make_branch_name(run_id)
    objective = getattr(args, "objective", None) or "DevFlow delivery run"

    # Managed worktree path lives NEXT TO the target repo, not inside it
    managed_root = get_managed_worktree_root(target)
    worktree_path = managed_root / f"run-{run_counter:03d}"

    build_script = FRAMEWORK_REPO / "scripts" / "build_devflow_plugin.py"
    is_framework_copy = build_script.exists()
    plugin_dir = FRAMEWORK_REPO / "dist" / "devflow-plugin"

    claude_binary = find_claude_binary()

    # --dry-run: show plan only, create nothing
    if dry_run:
        print("=== DevFlow Launch Plan (dry-run) ===")
        print(f"  run ID:     {run_id}")
        print(f"  branch:     {branch_name}")
        print(f"  worktree:   {worktree_path}")
        print(f"  plugin:     {plugin_dir}")
        print(f"  claude cmd: claude --plugin-dir {plugin_dir} <supervisor prompt>")
        print(f"  target:     {target}")
        if claude_binary:
            print(f"  claude:     {claude_binary}")
            print(
                f"  claude cmd: {claude_binary} --plugin-dir {plugin_dir} \"<supervisor prompt>\""
            )
        else:
            print("  claude:     [not found — install Claude Code CLI]")
        print(
            f"  git cmd:    git worktree add -b {branch_name} {worktree_path} HEAD"
        )
        print()
        print("  [dry-run] Hiçbir dosya, branch veya worktree oluşturulmadı.")
        return 0

    # Plugin copy guard — launch only works from framework side
    if not is_framework_copy:
        print(
            "Hata: 'launch' komutu yalnızca framework tarafında çalışır.",
            file=sys.stderr,
        )
        print(
            "  Bu script bir plugin kopyasından çalıştırılıyor "
            "(build_devflow_plugin.py bulunamadı).",
            file=sys.stderr,
        )
        print(
            "  Framework runner kullanın: "
            "python3 <framework>/scripts/devflow_operations.py launch --target ...",
            file=sys.stderr,
        )
        sys.exit(5)

    # Claude binary guard
    if not claude_binary:
        print(
            "Hata: 'claude' binary bulunamadı. Claude Code CLI kurulu olmalıdır.",
            file=sys.stderr,
        )
        sys.exit(6)

    # Collision guard — never delete, reset, or force
    if is_branch_exists(target, branch_name):
        print(
            f"Hata: Branch zaten mevcut: '{branch_name}'.",
            file=sys.stderr,
        )
        print(
            "  Silinmedi. Bir sonraki 'launch' çağrısı otomatik farklı run numarası alır.",
            file=sys.stderr,
        )
        sys.exit(12)

    if worktree_path.exists():
        print(
            f"Hata: Worktree path zaten mevcut: {worktree_path}",
            file=sys.stderr,
        )
        sys.exit(12)

    # Create managed worktree root directory (outside target repo)
    managed_root.mkdir(parents=True, exist_ok=True)

    # Create git worktree with a new branch
    print("Git worktree oluşturuluyor...")
    print(f"  branch: {branch_name}")
    print(f"  path:   {worktree_path}")
    wt_result = subprocess.run(
        ["git", "worktree", "add", "-b", branch_name, str(worktree_path), "HEAD"],
        cwd=str(target),
        capture_output=True,
        text=True,
    )
    if wt_result.returncode != 0:
        print("Hata: Git worktree oluşturulamadı.", file=sys.stderr)
        print(wt_result.stderr, file=sys.stderr)
        sys.exit(12)

    # Init .devflow/ ONLY in the run worktree — never touch main checkout
    print("Worktree içinde .devflow/ başlatılıyor...")
    init_ns = argparse.Namespace(target=str(worktree_path), force=False)
    init_result = cmd_init_target(init_ns)
    if init_result != 0:
        sys.exit(init_result)

    # Create run state in the run worktree
    print(f"Run state oluşturuluyor: {run_id}")
    create_ns = argparse.Namespace(
        target=str(worktree_path),
        objective=objective,
    )
    create_result = cmd_create_run(create_ns)
    if create_result != 0:
        sys.exit(create_result)

    # Build plugin from framework sources
    print("Plugin build çalıştırılıyor...")
    build_result = subprocess.run(
        [sys.executable, str(build_script)],
        cwd=str(FRAMEWORK_REPO),
        capture_output=True,
        text=True,
    )
    if build_result.returncode != 0:
        print("Hata: Plugin build başarısız.", file=sys.stderr)
        print(build_result.stderr, file=sys.stderr)
        sys.exit(5)

    supervisor_prompt = (
        f"DevFlow Delivery Supervisor — Run {run_id}\n"
        f"\n"
        f"Run ID: {run_id}\n"
        f"Branch: {branch_name}\n"
        f"Objective: {objective}\n"
        f"Worktree: {worktree_path}\n"
        f"Target repo: {target}\n"
        f"\n"
        f"Sen bu run'ın Delivery Lead'isin. Sorumlulukların:\n"
        f"- /orchestrate-delivery skill'ini kullanarak delivery döngüsünü yönet\n"
        f"- Managed operations için scripts/devflow_operations.py kullan\n"
        f"- main branch'e doğrudan yazma; insan approval gate'lerini koru\n"
        f"- Bu worktree dışında dosya oluşturma veya değiştirme"
    )

    print("Claude Code supervisor başlatılıyor (interaktif)...")
    print(f"  worktree:   {worktree_path}")
    print(f"  plugin-dir: {plugin_dir}")
    print(f"  binary:     {claude_binary}")

    # Change CWD to run worktree before replacing process
    os.chdir(str(worktree_path))
    os.execv(claude_binary, [
        claude_binary,
        "--plugin-dir", str(plugin_dir),
        supervisor_prompt,
    ])
    # execv replaces this process; this line is unreachable
    print("Hata: Claude başlatılamadı.", file=sys.stderr)
    sys.exit(6)


def cmd_status(args) -> int:
    target = Path(args.target).resolve()

    if not target.exists():
        print(f"Hata: Target path bulunamadı: {target}", file=sys.stderr)
        sys.exit(1)

    devflow = get_devflow_dir(target)
    if not is_initialized(target):
        print("Durum: .devflow/ başlatılmamış")
        print("  'init-target' ile başlatın.")
        return 0

    project_data = read_json(devflow / "project.json")
    run_id = project_data.get("current_run_id")
    run_counter = project_data.get("run_counter", 0)

    print(f"Target: {target}")
    print(f"  başlatıldı: {project_data.get('initialized_at', '-')}")
    print(f"  run sayısı: {run_counter}")
    print(f"  aktif run: {run_id or 'yok'}")

    if run_id:
        run_file = devflow / "runs" / f"{run_id}.json"
        if run_file.exists():
            run_data = read_json(run_file)
            print(f"  run durumu: {run_data.get('status', '-')}")
            print(f"  branch: {run_data.get('branch_name', '-')}")

    return 0


def cmd_prepare_delivery(args) -> int:
    target = Path(args.target).resolve()
    validate_target_path(target)
    validate_delivery_safety(target)

    confirm = getattr(args, "confirm_delivery", False)
    devflow = get_devflow_dir(target)

    if not is_initialized(target):
        print("Hata: .devflow/ başlatılmamış.", file=sys.stderr)
        sys.exit(4)

    project_data = read_json(devflow / "project.json")
    run_id = project_data.get("current_run_id")

    if not run_id:
        print("Hata: Aktif run yok. 'create-run' ile run başlatın.", file=sys.stderr)
        sys.exit(4)

    run_file = devflow / "runs" / f"{run_id}.json"
    run_data = read_json(run_file) if run_file.exists() else {}

    current_branch = get_current_branch(target)

    gates = run_data.get("approval_gates", {})
    all_gates_passed = (
        gates.get("tests_passing", False)
        and gates.get("security_review_complete", False)
        and gates.get("qa_sign_off", False)
    )

    print("Delivery hazırlık doğrulama raporu:")
    print(f"  run:    {run_id}")
    print(f"  branch: {current_branch}")
    print()
    print("Approval Gate Durumu:")
    for gate, status in gates.items():
        print(f"  {'[x]' if status else '[ ]'} {gate}")
    print()

    if not confirm:
        print("Mod: Doğrulama raporu (varsayılan)")
        print()
        print("NOT: Bu sürümde gerçek Git mutasyonu çalıştırılmaz.")
        print("  Commit, push ve PR insan tarafından yapılır.")
        print("  main merge insan onayı gerektirir.")
        return 0

    # --confirm-delivery: approval evidence validation only, no real git ops
    print("Mod: Onay kanıtı doğrulama (--confirm-delivery)")
    print()
    print("NOT: Bu sürümde --confirm-delivery yalnızca approval gate'lerini doğrular.")
    print("  Gerçek commit, push, PR veya merge yapılmaz.")
    print("  main merge insan tarafından yapılır.")
    print()

    if not all_gates_passed:
        print(
            "Hata: Tüm approval gate'leri geçilmemiş. Delivery engellidir.",
            file=sys.stderr,
        )
        sys.exit(9)

    print("Tüm approval gate'leri geçildi.")
    print("Sonraki adım: İnsan tarafından PR review ve main merge.")
    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="DevFlow managed operations runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_init = subparsers.add_parser("init-target", help="Target project .devflow/ başlat")
    p_init.add_argument("--target", required=True, help="Target project path")
    p_init.add_argument("--force", action="store_true", help="Mevcut state'i üzerine yaz")
    p_init.set_defaults(func=cmd_init_target)

    p_run = subparsers.add_parser("create-run", help="Yeni delivery run oluştur")
    p_run.add_argument("--target", required=True, help="Target project path")
    p_run.add_argument("--objective", default=None, help="Run hedefi")
    p_run.set_defaults(func=cmd_create_run)

    p_launch = subparsers.add_parser("launch", help="Claude Code supervisor başlat")
    p_launch.add_argument("--target", required=True, help="Target project path")
    p_launch.add_argument("--objective", default=None, help="Run hedefi")
    p_launch.add_argument("--dry-run", action="store_true", help="Plan göster, hiçbir şey oluşturma")
    p_launch.set_defaults(func=cmd_launch)

    p_status = subparsers.add_parser("status", help="Run durumunu göster")
    p_status.add_argument("--target", required=True, help="Target project path")
    p_status.set_defaults(func=cmd_status)

    p_delivery = subparsers.add_parser(
        "prepare-delivery", help="Delivery doğrulama raporu üret (gerçek Git mutasyonu yok)"
    )
    p_delivery.add_argument("--target", required=True, help="Target project path")
    p_delivery.add_argument(
        "--confirm-delivery",
        action="store_true",
        help="Approval gate'leri doğrula (bu sürümde gerçek Git operasyonu çalıştırmaz)",
    )
    p_delivery.set_defaults(func=cmd_prepare_delivery)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
