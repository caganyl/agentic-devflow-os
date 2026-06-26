#!/usr/bin/env python3
"""
DevFlow Operations Runner

Managed operations for target project initialization and delivery.
Standard library only. No third-party dependencies.

Subcommands:
    init-target           Initialize .devflow/ workspace in a target project (non-protected branch only)
    create-run            Create a new delivery run (non-protected branch only)
    launch                Launch Claude Code supervisor in a managed run worktree
    status                Show current run state
    prepare-delivery      Validate delivery readiness (approval evidence only; no real Git mutations)
    generate-task-graph   Generate deterministic task graph for a delivery type
    update-task-status    Update a task's status with state transition validation
    generate-run-report   Generate run evidence report with merge recommendation

Usage:
    python3 scripts/devflow_operations.py init-target --target PATH [--force]
    python3 scripts/devflow_operations.py create-run --target PATH [--objective TEXT]
    python3 scripts/devflow_operations.py launch --target PATH [--objective TEXT] [--dry-run] [--agent-teams]
    python3 scripts/devflow_operations.py status --target PATH
    python3 scripts/devflow_operations.py prepare-delivery --target PATH [--confirm-delivery]
    python3 scripts/devflow_operations.py generate-task-graph --target PATH --delivery-type TYPE [--objective TEXT] [--force]
    python3 scripts/devflow_operations.py update-task-status --target PATH --task-id ID --status STATUS
    python3 scripts/devflow_operations.py generate-run-report --target PATH

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
    10  Source register entry or task packet contains forbidden field
    11  Working tree is not clean (launch requires clean state)
    12  Run branch or worktree path already exists (collision)
    13  Unknown or unsupported delivery type
    14  Task not found in active run
    15  Invalid task state transition

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
# Task state machine
# ---------------------------------------------------------------------------

TASK_STATES = frozenset({
    "planned",
    "ready",
    "in_progress",
    "blocked",
    "completed",
    "verified",
    "failed",
    "awaiting_human_approval",
})

VALID_TASK_TRANSITIONS: dict[str, set[str]] = {
    "planned": {"ready", "failed"},
    "ready": {"in_progress", "blocked", "failed"},
    "in_progress": {"completed", "blocked", "failed", "awaiting_human_approval"},
    "blocked": {"ready", "failed"},
    "completed": {"verified", "awaiting_human_approval", "failed"},
    "verified": set(),
    "failed": {"planned"},
    "awaiting_human_approval": {"verified", "failed"},
}

FORBIDDEN_PACKET_FIELDS = frozenset({
    "token",
    "credential",
    "credentials",
    "password",
    "api_key",
    "apikey",
    "secret",
    "notebook_content",
    "raw_content",
    "url",
})

SUPPORTED_DELIVERY_TYPES = frozenset({
    "new_feature",
    "ai_rag",
    "data_dashboard",
    "bug_resolution",
    "security_response",
    "release_readiness",
    "cost_optimization",
    "new_product_discovery",
})

# ---------------------------------------------------------------------------
# Delivery type task graph templates
#
# Each template entry: (id_suffix, title, task_type, assigned_role,
#                       dep_suffixes, qa_expectation, output_path)
# ---------------------------------------------------------------------------

_T = tuple  # shorthand for template tuple

DELIVERY_TYPE_TASK_TEMPLATES: dict[str, list[dict]] = {
    "new_feature": [
        {"id_suffix": "001", "title": "Delivery Planning", "task_type": "planning",
         "assigned_role": "delivery-lead", "dep_suffixes": [],
         "qa_expectation": "Task graph ve context pack hazır",
         "output_path": ".devflow/context/"},
        {"id_suffix": "002", "title": "Acceptance Criteria Review", "task_type": "planning",
         "assigned_role": "product-analyst", "dep_suffixes": ["001"],
         "qa_expectation": "Acceptance criteria netleştirildi ve onaylandı",
         "output_path": ".devflow/context/acceptance-criteria.md"},
        {"id_suffix": "003", "title": "Architecture Decision", "task_type": "planning",
         "assigned_role": "solution-architect", "dep_suffixes": ["001"],
         "qa_expectation": "ADR taslağı üretildi",
         "output_path": "docs/architecture/adr/"},
        {"id_suffix": "004", "title": "API Contract Design", "task_type": "contract",
         "assigned_role": "contract-broker", "dep_suffixes": ["002", "003"],
         "qa_expectation": "Contract onaylandı; frontend ve backend paralel başlayabilir",
         "output_path": "docs/contracts/"},
        {"id_suffix": "005", "title": "Backend Implementation", "task_type": "implementation",
         "assigned_role": "backend-engineer", "dep_suffixes": ["004"],
         "qa_expectation": "API endpoint'ler çalışıyor; birim testler geçiyor",
         "output_path": "src/"},
        {"id_suffix": "006", "title": "Frontend Implementation", "task_type": "implementation",
         "assigned_role": "frontend-engineer", "dep_suffixes": ["004"],
         "qa_expectation": "UI bileşenleri çalışıyor; erişilebilirlik kontrol edildi",
         "output_path": "src/"},
        {"id_suffix": "007", "title": "QA Test Suite", "task_type": "qa",
         "assigned_role": "qa-automation", "dep_suffixes": ["005", "006"],
         "qa_expectation": "Tüm acceptance criteria testleri geçiyor",
         "output_path": "tests/"},
        {"id_suffix": "008", "title": "Security Review", "task_type": "security_review",
         "assigned_role": "security-red-team", "dep_suffixes": ["005", "006"],
         "qa_expectation": "Güvenlik raporu üretildi; blocker bulgu yok",
         "output_path": "docs/quality/security-reports/"},
        {"id_suffix": "009", "title": "Integration and Release Scorecard", "task_type": "release",
         "assigned_role": "integration-release", "dep_suffixes": ["007", "008"],
         "qa_expectation": "Scorecard 'merge ready' veya 'awaiting human approval'",
         "output_path": ".devflow/reports/"},
    ],
    "ai_rag": [
        {"id_suffix": "001", "title": "Delivery Planning", "task_type": "planning",
         "assigned_role": "delivery-lead", "dep_suffixes": [],
         "qa_expectation": "Task graph, eval gate noktaları ve context pack hazır",
         "output_path": ".devflow/context/"},
        {"id_suffix": "002", "title": "AI and Data Engineering", "task_type": "implementation",
         "assigned_role": "ai-data-engineer", "dep_suffixes": ["001"],
         "qa_expectation": "LLM entegrasyonu, RAG pipeline ve eval config hazır",
         "output_path": "src/"},
        {"id_suffix": "003", "title": "Backend API", "task_type": "implementation",
         "assigned_role": "backend-engineer", "dep_suffixes": ["001"],
         "qa_expectation": "AI feature backend API çalışıyor",
         "output_path": "src/"},
        {"id_suffix": "004", "title": "EvalOps Review", "task_type": "eval",
         "assigned_role": "evalops-reviewer", "dep_suffixes": ["002", "003"],
         "qa_expectation": "Golden dataset eval geçti; quality scorecard üretildi",
         "output_path": "evals/scorecards/"},
        {"id_suffix": "005", "title": "Security Review", "task_type": "security_review",
         "assigned_role": "security-red-team", "dep_suffixes": ["002", "003"],
         "qa_expectation": "Prompt injection ve data leakage riskleri değerlendirildi",
         "output_path": "docs/quality/security-reports/"},
        {"id_suffix": "006", "title": "Integration and Release Scorecard", "task_type": "release",
         "assigned_role": "integration-release", "dep_suffixes": ["004", "005"],
         "qa_expectation": "Scorecard 'merge ready' veya 'awaiting human approval'",
         "output_path": ".devflow/reports/"},
    ],
    "data_dashboard": [
        {"id_suffix": "001", "title": "Delivery Planning", "task_type": "planning",
         "assigned_role": "delivery-lead", "dep_suffixes": [],
         "qa_expectation": "Task graph, metrik/KPI tanımları ve context pack hazır",
         "output_path": ".devflow/context/"},
        {"id_suffix": "002", "title": "Data Pipeline", "task_type": "implementation",
         "assigned_role": "ai-data-engineer", "dep_suffixes": ["001"],
         "qa_expectation": "Veri pipeline çalışıyor; metrikler doğru hesaplanıyor",
         "output_path": "src/"},
        {"id_suffix": "003", "title": "Backend API", "task_type": "implementation",
         "assigned_role": "backend-engineer", "dep_suffixes": ["001"],
         "qa_expectation": "Veri API endpoint'leri çalışıyor",
         "output_path": "src/"},
        {"id_suffix": "004", "title": "Design Review", "task_type": "design",
         "assigned_role": "design-reviewer", "dep_suffixes": ["001"],
         "qa_expectation": "Dashboard layout, erişilebilirlik ve bilgi hiyerarşisi onaylandı",
         "output_path": "docs/quality/"},
        {"id_suffix": "005", "title": "QA Automation", "task_type": "qa",
         "assigned_role": "qa-automation", "dep_suffixes": ["002", "003", "004"],
         "qa_expectation": "Veri doğruluk testleri ve UI regression testleri geçiyor",
         "output_path": "tests/"},
        {"id_suffix": "006", "title": "Integration and Release Scorecard", "task_type": "release",
         "assigned_role": "integration-release", "dep_suffixes": ["005"],
         "qa_expectation": "Scorecard 'merge ready' veya 'awaiting human approval'",
         "output_path": ".devflow/reports/"},
    ],
    "bug_resolution": [
        {"id_suffix": "001", "title": "Delivery Planning and Triage", "task_type": "planning",
         "assigned_role": "delivery-lead", "dep_suffixes": [],
         "qa_expectation": "Bug severity ve kapsam belirlendi",
         "output_path": ".devflow/context/"},
        {"id_suffix": "002", "title": "QA Bug Reproduction", "task_type": "qa",
         "assigned_role": "qa-automation", "dep_suffixes": ["001"],
         "qa_expectation": "Bug repro testi yazıldı ve başarısız oluyor (kanıt)",
         "output_path": "tests/"},
        {"id_suffix": "003", "title": "Bug Fix Implementation", "task_type": "implementation",
         "assigned_role": "backend-engineer", "dep_suffixes": ["002"],
         "qa_expectation": "Fix yazıldı; repro testi geçiyor",
         "output_path": "src/"},
        {"id_suffix": "004", "title": "QA Verification", "task_type": "qa",
         "assigned_role": "qa-automation", "dep_suffixes": ["003"],
         "qa_expectation": "Repro testi geçiyor; regression suite temiz",
         "output_path": "tests/"},
        {"id_suffix": "005", "title": "Integration and Release Scorecard", "task_type": "release",
         "assigned_role": "integration-release", "dep_suffixes": ["004"],
         "qa_expectation": "Scorecard 'merge ready' veya 'awaiting human approval'",
         "output_path": ".devflow/reports/"},
    ],
    "security_response": [
        {"id_suffix": "001", "title": "Security Planning and Triage", "task_type": "planning",
         "assigned_role": "delivery-lead", "dep_suffixes": [],
         "qa_expectation": "Güvenlik severity ve kapsam belirlendi",
         "output_path": ".devflow/context/"},
        {"id_suffix": "002", "title": "Threat Analysis", "task_type": "security_review",
         "assigned_role": "security-red-team", "dep_suffixes": ["001"],
         "qa_expectation": "Tehdit modeli ve remediation planı hazır",
         "output_path": "docs/quality/security-reports/"},
        {"id_suffix": "003", "title": "Security Patch Implementation", "task_type": "implementation",
         "assigned_role": "backend-engineer", "dep_suffixes": ["002"],
         "qa_expectation": "Güvenlik patch uygulandı",
         "output_path": "src/"},
        {"id_suffix": "004", "title": "Security Fix Verification", "task_type": "qa",
         "assigned_role": "qa-automation", "dep_suffixes": ["003"],
         "qa_expectation": "Güvenlik testleri geçiyor; yeni regression yok",
         "output_path": "tests/"},
        {"id_suffix": "005", "title": "Integration and Release Scorecard", "task_type": "release",
         "assigned_role": "integration-release", "dep_suffixes": ["004"],
         "qa_expectation": "Scorecard 'merge ready' veya 'awaiting human approval'",
         "output_path": ".devflow/reports/"},
    ],
    "release_readiness": [
        {"id_suffix": "001", "title": "Release Planning", "task_type": "planning",
         "assigned_role": "delivery-lead", "dep_suffixes": [],
         "qa_expectation": "Kapsam, CI durumu ve bilinen sorunlar belgelendi",
         "output_path": ".devflow/context/"},
        {"id_suffix": "002", "title": "QA Final Review", "task_type": "qa",
         "assigned_role": "qa-automation", "dep_suffixes": ["001"],
         "qa_expectation": "Test coverage son kontrolü ve regression temiz",
         "output_path": "tests/"},
        {"id_suffix": "003", "title": "Security Final Scan", "task_type": "security_review",
         "assigned_role": "security-red-team", "dep_suffixes": ["001"],
         "qa_expectation": "Son güvenlik taraması tamamlandı; blocker yok",
         "output_path": "docs/quality/security-reports/"},
        {"id_suffix": "004", "title": "Release Scorecard", "task_type": "release",
         "assigned_role": "integration-release", "dep_suffixes": ["002", "003"],
         "qa_expectation": "Scorecard 'merge ready' veya 'awaiting human approval'",
         "output_path": ".devflow/reports/"},
    ],
    "cost_optimization": [
        {"id_suffix": "001", "title": "Delivery Planning and Baseline", "task_type": "planning",
         "assigned_role": "delivery-lead", "dep_suffixes": [],
         "qa_expectation": "Mevcut baseline (cost/latency/quality) ölçüldü",
         "output_path": ".devflow/context/"},
        {"id_suffix": "002", "title": "Architecture Analysis", "task_type": "planning",
         "assigned_role": "solution-architect", "dep_suffixes": ["001"],
         "qa_expectation": "İyileştirme seçenekleri değerlendirildi; ADR üretildi",
         "output_path": "docs/architecture/adr/"},
        {"id_suffix": "003", "title": "Cost Optimization Implementation", "task_type": "implementation",
         "assigned_role": "ai-data-engineer", "dep_suffixes": ["002"],
         "qa_expectation": "Optimizasyon uygulandı; maliyet azaldı",
         "output_path": "src/"},
        {"id_suffix": "004", "title": "Benchmark and Release Scorecard", "task_type": "release",
         "assigned_role": "integration-release", "dep_suffixes": ["003"],
         "qa_expectation": "Yeni benchmark tamamlandı; quality regression yok",
         "output_path": ".devflow/reports/"},
    ],
    "new_product_discovery": [
        {"id_suffix": "001", "title": "Discovery Planning", "task_type": "planning",
         "assigned_role": "delivery-lead", "dep_suffixes": [],
         "qa_expectation": "Problem statement ve kapsam netleştirildi",
         "output_path": ".devflow/context/"},
        {"id_suffix": "002", "title": "Product Analysis and PRD", "task_type": "planning",
         "assigned_role": "product-analyst", "dep_suffixes": ["001"],
         "qa_expectation": "PRD taslağı ve acceptance criteria üretildi",
         "output_path": "docs/product/requirements/"},
        {"id_suffix": "003", "title": "Design Review", "task_type": "design",
         "assigned_role": "design-reviewer", "dep_suffixes": ["002"],
         "qa_expectation": "Kullanıcı akışı ve UX değerlendirmesi tamamlandı",
         "output_path": "docs/quality/"},
        {"id_suffix": "004", "title": "Technical Feasibility", "task_type": "planning",
         "assigned_role": "solution-architect", "dep_suffixes": ["002"],
         "qa_expectation": "Teknik feasibility değerlendirmesi ve ADR taslağı hazır",
         "output_path": "docs/architecture/adr/"},
        {"id_suffix": "005", "title": "Human Approval Gate", "task_type": "approval",
         "assigned_role": "delivery-lead", "dep_suffixes": ["002", "003", "004"],
         "qa_expectation": "PRD ve feasibility insan tarafından review edildi ve onaylandı",
         "output_path": ".devflow/context/"},
    ],
}

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
# Task state machine utilities
# ---------------------------------------------------------------------------

def validate_task_transition(
    task_id: str,
    from_status: str,
    to_status: str,
    run_gates: dict,
) -> tuple[bool, str]:
    """Return (ok, error_message). Does not call sys.exit — caller decides."""
    if from_status not in TASK_STATES:
        return False, f"Geçersiz mevcut durum: '{from_status}'"
    if to_status not in TASK_STATES:
        return False, f"Geçersiz hedef durum: '{to_status}'"
    allowed = VALID_TASK_TRANSITIONS.get(from_status, set())
    if to_status not in allowed:
        return False, (
            f"Geçersiz durum geçişi: '{from_status}' → '{to_status}'. "
            f"İzin verilenler: {sorted(allowed) if allowed else '[]'}"
        )
    if from_status == "completed" and to_status == "verified":
        if not run_gates.get("qa_sign_off", False):
            return False, (
                "QA doğrulaması tamamlanmadan 'verified' durumuna geçilemez. "
                "approval_gates.qa_sign_off = true olmalıdır."
            )
    if from_status == "awaiting_human_approval" and to_status == "verified":
        if not run_gates.get("human_approval", False):
            return False, (
                "İnsan onayı olmadan 'verified' durumuna geçilemez. "
                "approval_gates.human_approval = true olmalıdır."
            )
    return True, ""


def generate_task_graph_nodes(run_id: str, delivery_type: str, objective: str) -> list:
    """Return a deterministic list of task node dicts for the given delivery type."""
    templates = DELIVERY_TYPE_TASK_TEMPLATES.get(delivery_type, [])
    tasks = []
    for tmpl in templates:
        task_id = f"{run_id}-TASK-{tmpl['id_suffix']}"
        dep_ids = [f"{run_id}-TASK-{s}" for s in tmpl["dep_suffixes"]]
        tasks.append({
            "id": task_id,
            "title": tmpl["title"],
            "task_type": tmpl["task_type"],
            "assigned_role": tmpl["assigned_role"],
            "dependency_ids": dep_ids,
            "acceptance_criteria_ref": f"objective: {objective[:200]}",
            "qa_expectation": tmpl["qa_expectation"],
            "status": "planned",
            "output_path": tmpl["output_path"],
            "expected_evidence_path": tmpl["output_path"],
            "delegation_status": "planned",
        })
    return tasks


def validate_task_packet_dict(packet: dict) -> None:
    """Exit 10 if the packet contains a forbidden top-level field."""
    for field in FORBIDDEN_PACKET_FIELDS:
        if field in packet:
            print(
                f"Hata: Task packet'te yasak alan '{field}' bulundu.",
                file=sys.stderr,
            )
            sys.exit(10)


def generate_task_packet_dict(task: dict, run_id: str, objective: str) -> dict:
    """Return a task packet dict with no forbidden fields."""
    return {
        "schema_version": "1",
        "run_id": run_id,
        "task_id": task["id"],
        "objective_summary": (objective or "")[:500],
        "assigned_role": task.get("assigned_role", ""),
        "title": task.get("title", ""),
        "task_type": task.get("task_type", ""),
        "context_refs": [".devflow/context/context-pack.md"],
        "dependency_ids": task.get("dependency_ids", []),
        "expected_output_paths": [task.get("output_path", "")],
        "expected_evidence_path": task.get("expected_evidence_path", ""),
        "qa_expectation": task.get("qa_expectation", ""),
        "prohibitions": [
            "main branch'e doğrudan yazma",
            "Secret, token, credential veya kişisel veri commit etme",
            "Production altyapısını veya database'i değiştirme",
            "main merge veya production deploy yapma",
            "Bu task'ın ownership alanı dışında dosya değiştirme",
        ],
        "human_approval_points": [
            "main merge insan onayı gerektirir",
            "production deploy insan onayı gerektirir",
        ],
        "delegation_status": task.get("delegation_status", "planned"),
    }


def build_run_report(run_data: dict, run_id: str) -> dict:
    """Build an evidence report dict from run state. No sys.exit."""
    tasks = run_data.get("tasks", [])
    gates = run_data.get("approval_gates", {})

    total = len(tasks)
    completed_count = sum(1 for t in tasks if t["status"] in ("completed", "verified"))
    verified_count = sum(1 for t in tasks if t["status"] == "verified")
    failed_count = sum(1 for t in tasks if t["status"] == "failed")

    pending_deps: list[dict] = []
    for task in tasks:
        if task["status"] in ("planned", "blocked"):
            for dep_id in task.get("dependency_ids", []):
                dep = next((t for t in tasks if t["id"] == dep_id), None)
                if dep and dep["status"] not in ("completed", "verified"):
                    pending_deps.append({
                        "task_id": task["id"],
                        "waiting_for": dep_id,
                        "dep_status": dep["status"],
                    })

    any_confirmed = any(
        t.get("delegation_status") == "confirmed"
        for t in tasks
    )

    qa_done = gates.get("qa_sign_off", False)
    security_done = gates.get("security_review_complete", False)
    human_done = gates.get("human_approval", False)
    tests_passing = gates.get("tests_passing", False)
    all_tasks_done = bool(tasks) and all(
        t["status"] in ("completed", "verified") for t in tasks
    )

    if all_tasks_done and qa_done and security_done and human_done and tests_passing:
        merge_recommendation = "ready"
    elif qa_done and security_done and tests_passing and not human_done:
        merge_recommendation = "awaiting_human_approval"
    else:
        merge_recommendation = "not_ready"

    boundary_note = (
        "Tüm task'lar 'planned' delegation durumunda. "
        "Gerçek agent dispatch doğrulanmadı."
        if not any_confirmed
        else "En az bir task gerçek agent session kanıtıyla doğrulandı."
    )

    return {
        "schema_version": "1",
        "run_id": run_id,
        "objective": run_data.get("objective", ""),
        "execution_mode": run_data.get("execution_mode", "subagents"),
        "requested_agent_teams": run_data.get("requested_agent_teams", False),
        "task_graph_summary": {
            "total": total,
            "completed_or_verified": completed_count,
            "verified": verified_count,
            "failed": failed_count,
            "pending": total - completed_count - failed_count,
        },
        "task_statuses": [
            {
                "id": t["id"],
                "title": t.get("title", ""),
                "status": t["status"],
                "assigned_role": t.get("assigned_role", ""),
                "delegation_status": t.get("delegation_status", "planned"),
            }
            for t in tasks
        ],
        "pending_dependencies": pending_deps,
        "approval_gates": gates,
        "qa_result": "passed" if qa_done else "not_completed",
        "human_approval_required": [
            "main merge insan tarafından yapılmalıdır",
            "production deploy insan tarafından yapılmalıdır",
        ],
        "delegation_evidence": {
            "any_delegation_confirmed": any_confirmed,
            "boundary_note": boundary_note,
        },
        "merge_recommendation": merge_recommendation,
        "report_generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


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

    agent_teams_requested = getattr(args, "agent_teams", False)
    execution_mode = "agent_teams" if agent_teams_requested else "subagents"

    run_state = {
        "schema_version": DEVFLOW_SCHEMA_VERSION,
        "run_id": run_id,
        "created_at": now,
        "status": "created",
        "branch_name": branch_name,
        "objective": getattr(args, "objective", None) or "",
        "execution_mode": execution_mode,
        "requested_agent_teams": agent_teams_requested,
        "task_graph_status": "not_started",
        "context_pack_status": "not_started",
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
    agent_teams = getattr(args, "agent_teams", False)
    execution_mode = "agent_teams" if agent_teams else "subagents"

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
        agent_teams_label = "enabled" if agent_teams else "disabled"
        env_plan = (
            f"CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1"
            if agent_teams
            else "[standard env, no agent-teams flag]"
        )
        print("=== DevFlow Launch Plan (dry-run) ===")
        print(f"  run ID:         {run_id}")
        print(f"  branch:         {branch_name}")
        print(f"  worktree:       {worktree_path}")
        print(f"  plugin:         {plugin_dir}")
        print(f"  target:         {target}")
        print(f"  execution mode: {execution_mode}")
        print(f"  agent teams:    {agent_teams_label}")
        print(f"  env (planned):  {env_plan}")
        if claude_binary:
            print(f"  claude:         {claude_binary}")
        else:
            print("  claude:         [not found — install Claude Code CLI]")
        binary_label = claude_binary or "claude"
        print(
            f"  claude cmd:     {binary_label} --plugin-dir {plugin_dir} \"<supervisor prompt>\""
        )
        print(
            f"  git cmd:        git worktree add -b {branch_name} {worktree_path} HEAD"
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
        agent_teams=agent_teams,
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
    print(f"  worktree:       {worktree_path}")
    print(f"  plugin-dir:     {plugin_dir}")
    print(f"  binary:         {claude_binary}")
    print(f"  execution mode: {execution_mode}")

    # Build child environment — copy parent env, never mutate os.environ
    child_env = os.environ.copy()

    # Set agent teams flag only in child env; remove it for default launch
    if agent_teams:
        child_env["CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"] = "1"
    else:
        child_env.pop("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", None)

    # Change CWD to run worktree before replacing process
    os.chdir(str(worktree_path))
    os.execve(claude_binary, [
        claude_binary,
        "--plugin-dir", str(plugin_dir),
        supervisor_prompt,
    ], child_env)
    # execve replaces this process; this line is unreachable
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


def cmd_generate_task_graph(args) -> int:
    target = Path(args.target).resolve()
    validate_target_path(target)
    validate_not_on_protected_branch(target, "generate-task-graph")

    delivery_type = args.delivery_type
    if delivery_type not in SUPPORTED_DELIVERY_TYPES:
        print(
            f"Hata: Desteklenmeyen delivery tipi: '{delivery_type}'.",
            file=sys.stderr,
        )
        print(
            f"  Desteklenenler: {', '.join(sorted(SUPPORTED_DELIVERY_TYPES))}",
            file=sys.stderr,
        )
        sys.exit(13)

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
    run_data = read_json(run_file)

    force = getattr(args, "force", False)
    if run_data.get("tasks") and not force:
        print(
            "Bilgi: Task graph zaten mevcut. Üzerine yazmak için --force kullanın.",
        )
        return 0

    objective = getattr(args, "objective", None) or run_data.get("objective", "")
    tasks = generate_task_graph_nodes(run_id, delivery_type, objective)

    packets_dir = devflow / "task-packets"
    packets_dir.mkdir(exist_ok=True)
    for task in tasks:
        packet = generate_task_packet_dict(task, run_id, objective)
        validate_task_packet_dict(packet)
        suffix = task["id"].split("-TASK-")[1]
        atomic_write_json(packets_dir / f"{run_id}-TASK-{suffix}.json", packet)

    run_data["tasks"] = tasks
    run_data["task_graph_status"] = "generated"
    run_data["delivery_type"] = delivery_type
    atomic_write_json(run_file, run_data)

    print(f"Task graph oluşturuldu: {run_id} / {delivery_type}")
    print(f"  task sayısı: {len(tasks)}")
    for task in tasks:
        print(f"  [{task['status']:8}] {task['id']} — {task['title']} ({task['assigned_role']})")
    print(f"  task-packets: {packets_dir}")
    return 0


def cmd_update_task_status(args) -> int:
    target = Path(args.target).resolve()
    validate_target_path(target)
    validate_not_on_protected_branch(target, "update-task-status")

    task_id = args.task_id
    new_status = args.status

    if new_status not in TASK_STATES:
        print(
            f"Hata: Geçersiz durum: '{new_status}'.",
            file=sys.stderr,
        )
        print(
            f"  Geçerli durumlar: {', '.join(sorted(TASK_STATES))}",
            file=sys.stderr,
        )
        sys.exit(15)

    devflow = get_devflow_dir(target)
    if not is_initialized(target):
        print("Hata: .devflow/ başlatılmamış.", file=sys.stderr)
        sys.exit(4)

    project_data = read_json(devflow / "project.json")
    run_id = project_data.get("current_run_id")
    if not run_id:
        print("Hata: Aktif run yok.", file=sys.stderr)
        sys.exit(4)

    run_file = devflow / "runs" / f"{run_id}.json"
    run_data = read_json(run_file)

    tasks = run_data.get("tasks", [])
    task = next((t for t in tasks if t["id"] == task_id), None)
    if task is None:
        print(
            f"Hata: Task bulunamadı: '{task_id}'.",
            file=sys.stderr,
        )
        sys.exit(14)

    from_status = task["status"]
    gates = run_data.get("approval_gates", {})
    ok, error_msg = validate_task_transition(task_id, from_status, new_status, gates)
    if not ok:
        print(f"Hata: {error_msg}", file=sys.stderr)
        sys.exit(15)

    task["status"] = new_status
    atomic_write_json(run_file, run_data)

    print(f"Task durumu güncellendi: {task_id}")
    print(f"  {from_status} → {new_status}")
    return 0


def cmd_generate_run_report(args) -> int:
    target = Path(args.target).resolve()

    if not target.exists():
        print(f"Hata: Target path bulunamadı: {target}", file=sys.stderr)
        sys.exit(1)

    devflow = get_devflow_dir(target)
    if not is_initialized(target):
        print("Hata: .devflow/ başlatılmamış.", file=sys.stderr)
        sys.exit(4)

    project_data = read_json(devflow / "project.json")
    run_id = project_data.get("current_run_id")
    if not run_id:
        print("Hata: Aktif run yok.", file=sys.stderr)
        sys.exit(4)

    run_file = devflow / "runs" / f"{run_id}.json"
    run_data = read_json(run_file)

    report = build_run_report(run_data, run_id)

    reports_dir = devflow / "reports"
    reports_dir.mkdir(exist_ok=True)
    report_path = reports_dir / f"{run_id}-report.json"
    atomic_write_json(report_path, report)

    summary = report["task_graph_summary"]
    delegation = report["delegation_evidence"]
    print(f"Run raporu: {run_id}")
    print(f"  objective: {report['objective'][:80]}")
    print(f"  execution_mode: {report['execution_mode']}")
    print(f"  tasks: {summary['total']} toplam, "
          f"{summary['completed_or_verified']} tamamlandı, "
          f"{summary['verified']} doğrulandı")
    print(f"  qa_result: {report['qa_result']}")
    print(f"  delegation_confirmed: {delegation['any_delegation_confirmed']}")
    print(f"  merge_recommendation: {report['merge_recommendation']}")
    print()
    print(f"  NOT (delegation): {delegation['boundary_note']}")
    print(f"  NOT (human gate): {report['human_approval_required'][0]}")
    print(f"  rapor kaydedildi: {report_path}")
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
    p_launch.add_argument(
        "--agent-teams",
        action="store_true",
        default=False,
        help=(
            "Bu run için CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1 aktif et. "
            "Yalnızca spawned Claude process'ini etkiler; "
            "shell environment veya settings dosyaları değişmez."
        ),
    )
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

    p_graph = subparsers.add_parser(
        "generate-task-graph",
        help="Delivery tipi için deterministik task graph üret",
    )
    p_graph.add_argument("--target", required=True, help="Target project path")
    p_graph.add_argument(
        "--delivery-type",
        required=True,
        choices=sorted(SUPPORTED_DELIVERY_TYPES),
        help="Delivery tipi",
    )
    p_graph.add_argument("--objective", default=None, help="Delivery hedefi (override)")
    p_graph.add_argument(
        "--force", action="store_true", help="Mevcut task graph'ı üzerine yaz"
    )
    p_graph.set_defaults(func=cmd_generate_task_graph)

    p_update = subparsers.add_parser(
        "update-task-status",
        help="Task durumunu geçiş doğrulamasıyla güncelle",
    )
    p_update.add_argument("--target", required=True, help="Target project path")
    p_update.add_argument("--task-id", required=True, help="Task ID")
    p_update.add_argument(
        "--status",
        required=True,
        choices=sorted(TASK_STATES),
        help="Hedef durum",
    )
    p_update.set_defaults(func=cmd_update_task_status)

    p_report = subparsers.add_parser(
        "generate-run-report",
        help="Run kanıt raporu ve merge recommendation üret",
    )
    p_report.add_argument("--target", required=True, help="Target project path")
    p_report.set_defaults(func=cmd_generate_run_report)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
