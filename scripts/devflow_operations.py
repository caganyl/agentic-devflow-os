#!/usr/bin/env python3
"""
DevFlow Operations Runner

Managed operations for target project initialization and delivery.
Standard library only. No third-party dependencies.

Subcommands:
    init-target               Initialize .devflow/ workspace in a target project (non-protected branch only)
    create-run                Create a new delivery run (non-protected branch only)
    launch                    Launch Claude Code supervisor in a managed run worktree
    status                    Show current run state
    prepare-delivery          Validate delivery readiness (approval evidence only; no real Git mutations)
    generate-task-graph       Generate deterministic task graph for a delivery type
    update-task-status        Update a task's status with state transition validation
    record-qa-evidence        Record QA test results authoritatively and update approval gates
    record-security-evidence  Record security review evidence authoritatively
    record-contract-evidence      Record contract evidence authoritatively for new_feature runs
    record-work-product-evidence  Record verifiable implementation or QA work-product evidence
    generate-run-report           Generate run evidence report with merge recommendation

Usage:
    python3 scripts/devflow_operations.py init-target --target PATH [--force]
    python3 scripts/devflow_operations.py create-run --target PATH [--objective TEXT]
    python3 scripts/devflow_operations.py launch --target PATH [--objective TEXT] [--dry-run] [--agent-teams]
    python3 scripts/devflow_operations.py status --target PATH
    python3 scripts/devflow_operations.py prepare-delivery --target PATH [--confirm-delivery]
    python3 scripts/devflow_operations.py generate-task-graph --target PATH --delivery-type TYPE [--objective TEXT] [--force]
    python3 scripts/devflow_operations.py update-task-status --target PATH --task-id ID --status STATUS
    python3 scripts/devflow_operations.py record-qa-evidence --target PATH --total N --passed N --failed N --exit-code N [--evidence-path PATH]
    python3 scripts/devflow_operations.py record-security-evidence --target PATH --run-id RUN-NNN --verdict pass|blocked --max-severity none|low|medium|high|critical --evidence-path RELATIVE_PATH
    python3 scripts/devflow_operations.py record-contract-evidence --target PATH --run-id RUN-NNN --evidence-path RELATIVE_PATH
    python3 scripts/devflow_operations.py record-work-product-evidence --target PATH --run-id RUN-NNN --task-id TASK-ID --evidence-path RELATIVE_PATH
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
    16  generate-task-graph --force rejected: run is active (tasks progressed, events, or artifacts exist)
    17  Security evidence recording rejected (review not required, invalid verdict/severity, or invalid path)
    18  Contract evidence recording rejected (not required for this delivery type, or invalid path)
    19  Work product evidence recording rejected (invalid path, not a git change, task type mismatch, or task not in run)

IMPORTANT — validate_forbidden_git_operation:
    This function validates planned operation *strings* passed to it by callers.
    It is NOT a runtime git hook and does NOT intercept git commands executed
    elsewhere. Its purpose is to catch accidental construction of forbidden
    commands in delivery workflows, not to enforce at the OS level.
"""

# PEP 563: keep annotations as strings instead of evaluating them at import.
# Without this, `list[dict] | None` and `str | None` below are evaluated on
# import and raise TypeError on Python 3.9 — the interpreter macOS ships as
# /usr/bin/python3 — so `python3 scripts/devflow_operations.py` aborted before
# argparse ever ran. The hooks stayed unaffected (they use typing.Optional),
# which is why this only ever broke the operations runner.
from __future__ import annotations

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
    "backend_utility",
})

# ---------------------------------------------------------------------------
# Objective risk signal detection
#
# Deterministic keyword-based classification.  No LLM interpretation.
# Each category maps to a frozenset of lowercase signal words.
# Signals drive delivery type selection and task graph omission decisions.
# ---------------------------------------------------------------------------

OBJECTIVE_RISK_SIGNALS: dict[str, frozenset[str]] = {
    "api_surface": frozenset({
        "api", "http", "https", "endpoint", "rest", "graphql",
        "webhook", "route", "openapi", "swagger",
    }),
    "auth": frozenset({
        "auth", "authentication", "authorization", "login", "oauth",
        "jwt", "session", "token", "permission", "role", "rbac",
        "privilege",
    }),
    "payment": frozenset({
        "payment", "billing", "stripe", "subscription", "invoice",
        "checkout", "purchase", "transaction", "charge",
    }),
    "external_service": frozenset({
        "integrate", "integration", "email", "sms", "slack",
        "twilio", "sendgrid", "notification", "push",
    }),
    "sensitive_data": frozenset({
        "sensitive", "pii", "personal", "gdpr", "privacy",
        "credential", "confidential", "private",
    }),
    "deployment": frozenset({
        "deploy", "kubernetes", "docker", "production", "infrastructure",
        "cloud", "aws", "gcp", "azure", "k8s", "container",
    }),
    "schema_migration": frozenset({
        "migration", "database", "schema", "db", "sql", "postgres",
        "mysql", "sqlite", "alembic", "table",
    }),
    "significant_architecture": frozenset({
        "architecture", "microservice", "refactor", "redesign",
        "modular", "distributed",
    }),
    "frontend": frozenset({
        "frontend", "ui", "ux", "react", "vue", "angular", "component",
        "page", "form", "button", "html", "css", "web", "browser",
    }),
    "dependency_change": frozenset({
        "pip", "npm", "yarn",
    }),
}

# Negation phrases: removed from objective text before signal matching.
# Longer / more-specific phrases are listed first.
_OBJECTIVE_NEGATION_PHRASES: list[tuple[str, frozenset]] = [
    ("no third-party dependencies", frozenset({"external_service", "dependency_change"})),
    ("no third party dependencies", frozenset({"external_service", "dependency_change"})),
    ("no external dependencies",    frozenset({"external_service", "dependency_change"})),
    ("no external dependency",      frozenset({"external_service", "dependency_change"})),
    ("local deterministic",         frozenset({"external_service"})),
    ("no external service",         frozenset({"external_service"})),
    ("no filesystem io",            frozenset({"filesystem_io"})),
    ("no external api",             frozenset({"external_service", "api_surface"})),
    ("no network io",               frozenset({"external_service"})),
    ("no filesystem",               frozenset({"filesystem_io"})),
    ("pure python",                 frozenset({"external_service", "dependency_change"})),
    ("stdlib-only",                 frozenset({"external_service", "dependency_change"})),
    ("stdlib only",                 frozenset({"external_service", "dependency_change"})),
    ("no network",                  frozenset({"external_service"})),
    ("no file io",                  frozenset({"filesystem_io"})),
    ("no api",                      frozenset({"api_surface", "external_service"})),
]

# Positive multi-word phrases matched against the objective *after* negation removal.
_OBJECTIVE_POSITIVE_PHRASES: list[tuple[str, str]] = [
    ("external service",       "external_service"),
    ("external api",           "external_service"),
    ("third-party service",    "external_service"),
    ("third party service",    "external_service"),
    ("third-party api",        "external_service"),
    ("third party api",        "external_service"),
    ("add dependency",         "dependency_change"),
    ("third-party dependency", "dependency_change"),
    ("third party dependency", "dependency_change"),
]

# ---------------------------------------------------------------------------
# Security review applicability model
#
# Three concepts are kept strictly separate:
#   security_review_required      — bool, written at task-graph generation time
#   security_review_status        — "not_applicable" | "pending" | "completed"
#   security_gate_satisfied       — bool, drives auto_gates_pass in build_run_report
#
# Applicability is written to canonical run state by generate-task-graph and
# MUST NOT be changed by finalization or free-form JSON writes.  The target
# guard blocks direct Write/Edit to .devflow/runs/ and .devflow/reports/.
# ---------------------------------------------------------------------------

# Delivery types whose task template always includes a security_review task.
# For these, security_review_required is always True.
DELIVERY_TYPES_WITH_MANDATORY_SECURITY_REVIEW = frozenset({
    "new_feature",
    "ai_rag",
    "security_response",
    "release_readiness",
})

# Risk signal categories (from OBJECTIVE_RISK_SIGNALS) that trigger
# security_review_required = True for non-mandatory delivery types.
SECURITY_TRIGGERING_RISK_SIGNALS = frozenset({
    "api_surface",
    "auth",
    "payment",
    "external_service",
    "sensitive_data",
    "deployment",
    "schema_migration",
    "dependency_change",
})

# Closed enum for security_applicability_reason written to canonical run state.
# Set only by determine_security_applicability(); never by LLM or free text.
SECURITY_APPLICABILITY_REASONS = frozenset({
    "low_risk_local_utility",
    "api_or_http_surface",
    "auth_or_authorization",
    "external_integration",
    "sensitive_or_user_data",
    "database_or_migration",
    "deployment_or_infrastructure",
    "filesystem_or_network_io",
    "dependency_change",
    "explicit_security_signal",
})

# Closed enum for security_review_status in run reports.
SECURITY_REVIEW_STATUS_ENUM = frozenset({
    "not_applicable",
    "pending",
    "completed",
})

# ---------------------------------------------------------------------------
# Security evidence recording
#
# record-security-evidence writes narrow metadata to canonical run state.
# It does NOT copy evidence file content, session IDs, or free text.
# ---------------------------------------------------------------------------

SECURITY_EVIDENCE_VERDICTS = frozenset({"pass", "blocked"})
SECURITY_EVIDENCE_SEVERITIES = frozenset({"none", "low", "medium", "high", "critical"})
SECURITY_EVIDENCE_PATH_PREFIX = "docs/quality/security-reports/"

# Verdict → allowed max-severity values (closed enum; enforced at record time)
VALID_VERDICT_SEVERITY_COMBOS: dict[str, frozenset] = {
    "pass": frozenset({"none", "low"}),
    "blocked": frozenset({"medium", "high", "critical"}),
}

# ---------------------------------------------------------------------------
# Contract gate applicability model
#
# contract_required is written at generate-task-graph time for new_feature runs.
# Three-state machine mirroring security gate:
#   contract_required=False → status="not_applicable", gate satisfied
#   contract_required=True + record-contract-evidence ran → status="completed", gate satisfied
#   contract_required=True + no evidence → status="pending", gate NOT satisfied
#
# Implementation tasks in contract-gated runs cannot enter in_progress/completed/verified
# until contract_gate_satisfied=True.
# ---------------------------------------------------------------------------

# Delivery types that require a contract gate.  Only new_feature for now.
DELIVERY_TYPES_WITH_CONTRACT_GATE = frozenset({"new_feature"})

CONTRACT_EVIDENCE_PATH_PREFIX = "docs/quality/contracts/"

CONTRACT_REVIEW_STATUS_ENUM = frozenset({
    "not_applicable",
    "pending",
    "completed",
})

# Task states that are blocked for implementation tasks when contract gate is unsatisfied.
CONTRACT_GATE_BLOCKED_STATUSES = frozenset({"in_progress", "completed", "verified"})

# ---------------------------------------------------------------------------
# Work product evidence gate
#
# Blocks implementation and QA tasks from reaching completed/verified without
# a verifiable local work-product file that is an active Git worktree change.
# This gate verifies local work-product presence, not causal attribution to a
# specific agent session.
# ---------------------------------------------------------------------------

WORK_PRODUCT_GATE_EXIT_CODE = 19

# Task types that require verifiable work-product evidence before completion.
WORK_PRODUCT_REQUIRED_TASK_TYPES = frozenset({"implementation", "qa"})

# Statuses blocked for impl/QA tasks without recorded work-product evidence.
WORK_PRODUCT_GATE_BLOCKED_STATUSES = frozenset({"completed", "verified"})

# Valid path prefixes for implementation work-product evidence (source/template assets).
IMPLEMENTATION_EVIDENCE_PREFIXES = (
    "src/",
    "app/",
    "lib/",
    "pkg/",
    "cmd/",
    "templates/",
)

# Valid path prefixes for QA work-product evidence (test assets).
QA_EVIDENCE_PREFIXES = (
    "tests/",
    "test/",
    "spec/",
    "__tests__/",
    "e2e/",
)

# Path prefixes that are NEVER accepted as work-product (docs, devflow state, scorecards).
_WORK_PRODUCT_FORBIDDEN_DOC_PREFIXES = (
    ".devflow/",
    ".claude/",
    "docs/",
    "evals/scorecards/",
)

# File names that are never accepted (lockfiles, dependency specs, build/config files).
_WORK_PRODUCT_FORBIDDEN_FILENAMES = frozenset({
    "package-lock.json",
    "yarn.lock",
    "poetry.lock",
    "Pipfile.lock",
    "composer.lock",
    "Gemfile.lock",
    "requirements.txt",
    "setup.py",
    "setup.cfg",
    "pyproject.toml",
    "Gemfile",
    "Makefile",
    "Dockerfile",
    ".dockerignore",
    "docker-compose.yml",
    "docker-compose.yaml",
    ".gitignore",
    ".gitattributes",
})

# Directory component names that are never accepted (migrations, devflow internals).
_WORK_PRODUCT_FORBIDDEN_PATH_COMPONENTS = frozenset({
    ".devflow",
    ".claude",
    "migrations",
    "migration",
})

# Exact file names that are always classified as test assets (not implementation evidence).
_TEST_FILENAME_EXACT = frozenset({"tests.py", "test.py"})

# Source/template file extensions whose presence (outside test naming) indicates impl evidence.
_SOURCE_ASSET_EXTENSIONS = frozenset({
    ".py", ".js", ".ts", ".jsx", ".tsx",
    ".html", ".css", ".scss", ".sass", ".less",
    ".vue", ".svelte", ".go", ".rb", ".java",
    ".kt", ".swift", ".rs", ".c", ".cpp", ".h", ".hpp",
})


def _is_test_filename(filename: str) -> bool:
    """Return True if filename matches conventional test asset naming patterns."""
    name = filename.lower()
    return (
        name in _TEST_FILENAME_EXACT
        or name.startswith("test_")
        or name.endswith("_test.py")
        or name.endswith("_tests.py")
        or name.endswith("_spec.py")
        or name.endswith(".spec.js")
        or name.endswith(".test.js")
        or name.endswith(".test.ts")
        or name.endswith(".spec.ts")
        or name.endswith(".spec.jsx")
        or name.endswith(".test.jsx")
        or name.endswith(".spec.tsx")
        or name.endswith(".test.tsx")
    )


def _is_source_asset(filename: str) -> bool:
    """Return True if filename has a recognised source code or template asset extension."""
    from pathlib import Path as _Path
    return _Path(filename).suffix.lower() in _SOURCE_ASSET_EXTENSIONS

# File name prefixes indicating sensitive content (.env*).
_WORK_PRODUCT_FORBIDDEN_NAME_PREFIXES = (".env",)

# Substrings in file names that indicate secrets or credentials.
_WORK_PRODUCT_FORBIDDEN_NAME_SENSITIVE = frozenset({
    "secret",
    "credential",
    "password",
    "apikey",
    "api_key",
    "private_key",
    "id_rsa",
    "id_ed25519",
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
        {"id_suffix": "004", "title": "Contract Definition", "task_type": "contract_definition",
         "assigned_role": "contract-broker", "dep_suffixes": ["002", "003"],
         "qa_expectation": "Contract kanıtı kaydedildi; frontend ve backend paralel başlayabilir",
         "output_path": "docs/quality/contracts/"},
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
    # Minimal profile for low-risk, local, pure-Python backend utility objectives.
    # Omits: frontend implementation, API contract design, ADR, standalone security review.
    # Add-on tasks (security, contract, ADR) are included only when risk signals are detected.
    "backend_utility": [
        {"id_suffix": "001", "title": "Delivery Planning", "task_type": "planning",
         "assigned_role": "delivery-lead", "dep_suffixes": [],
         "qa_expectation": "Task graph ve context pack hazır",
         "output_path": ".devflow/context/"},
        {"id_suffix": "002", "title": "Backend Implementation", "task_type": "implementation",
         "assigned_role": "backend-engineer", "dep_suffixes": ["001"],
         "qa_expectation": "Implementation tamamlandı; birim testler geçiyor",
         "output_path": "src/"},
        {"id_suffix": "003", "title": "QA Verification", "task_type": "qa",
         "assigned_role": "qa-automation", "dep_suffixes": ["002"],
         "qa_expectation": "Tüm testler geçiyor; regression temiz",
         "output_path": "tests/"},
        {"id_suffix": "004", "title": "Integration and Release Evidence", "task_type": "release",
         "assigned_role": "integration-release", "dep_suffixes": ["003"],
         "qa_expectation": "Scorecard ve merge recommendation hazır; human approval bekleniyor",
         "output_path": ".devflow/reports/"},
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
# Objective risk signal detection
# ---------------------------------------------------------------------------

def detect_objective_risk_signals(objective: str) -> frozenset[str]:
    """
    Return risk signal categories detected in objective text.
    Deterministic phrase-precedence matching — no LLM interpretation.

    Negation phrases are removed from the normalized text first; positive phrases
    and word-level signals are matched only on what remains.  A positive signal
    that co-occurs with a negation phrase wins only if it appears outside it.
    """
    normalized = re.sub(r"\bi[/\\]o\b", "io", objective.lower())
    remaining = normalized
    for phrase, _ in _OBJECTIVE_NEGATION_PHRASES:
        remaining = remaining.replace(phrase, " ")

    found: set[str] = set()
    for phrase, category in _OBJECTIVE_POSITIVE_PHRASES:
        if phrase in remaining:
            found.add(category)

    words = frozenset(re.findall(r"\b\w+\b", remaining))
    for signal_name, keywords in OBJECTIVE_RISK_SIGNALS.items():
        if words & keywords:
            found.add(signal_name)

    return frozenset(found)


# ---------------------------------------------------------------------------
# Security applicability helpers
# ---------------------------------------------------------------------------

def _security_reason_from_signals(triggering: frozenset) -> str:
    """Return the highest-priority closed-enum reason from triggering risk signals."""
    if "auth" in triggering:
        return "auth_or_authorization"
    if "payment" in triggering:
        return "sensitive_or_user_data"
    if "external_service" in triggering:
        return "external_integration"
    if "api_surface" in triggering:
        return "api_or_http_surface"
    if "sensitive_data" in triggering:
        return "sensitive_or_user_data"
    if "deployment" in triggering:
        return "deployment_or_infrastructure"
    if "schema_migration" in triggering:
        return "database_or_migration"
    if "dependency_change" in triggering:
        return "dependency_change"
    return "explicit_security_signal"


def determine_security_applicability(delivery_type: str, objective: str) -> dict:
    """
    Determine whether security review is required for this delivery run.

    Returns:
        {
            "security_review_required": bool,
            "security_applicability_reason": str  — from SECURITY_APPLICABILITY_REASONS
        }

    Rules (deterministic; no LLM interpretation):
    - Delivery types in DELIVERY_TYPES_WITH_MANDATORY_SECURITY_REVIEW → required=True.
    - Other types: required=True only when the objective contains at least one signal
      from SECURITY_TRIGGERING_RISK_SIGNALS.
    - Pure local / stdlib-only utility with no triggering signals → required=False,
      reason="low_risk_local_utility".

    This is the authoritative applicability gate.  Same inputs → same output.
    """
    risk_signals = detect_objective_risk_signals(objective)
    triggering = risk_signals & SECURITY_TRIGGERING_RISK_SIGNALS

    if delivery_type in DELIVERY_TYPES_WITH_MANDATORY_SECURITY_REVIEW:
        reason = _security_reason_from_signals(triggering) if triggering else "explicit_security_signal"
        return {
            "security_review_required": True,
            "security_applicability_reason": reason,
        }

    if triggering:
        return {
            "security_review_required": True,
            "security_applicability_reason": _security_reason_from_signals(triggering),
        }

    return {
        "security_review_required": False,
        "security_applicability_reason": "low_risk_local_utility",
    }


# ---------------------------------------------------------------------------
# Delegation evidence loader and event validation
# ---------------------------------------------------------------------------

VALID_HOOK_EVENTS = frozenset({"SubagentStart", "SubagentStop"})
VALID_LIFECYCLE_STATES = frozenset({"started", "stopped"})


def _is_valid_delegation_event(event: dict, run_id: str) -> bool:
    """
    Return True if event passes schema and run_id validation.

    Criteria:
    - hook_event must be SubagentStart or SubagentStop
    - lifecycle_state must be started or stopped
    - if run_id field is present AND not the recorder's "unknown" fallback sentinel,
      it must match the run's run_id
    - agent_type may be "unknown" (unattributed) or any string; does not affect validity
    """
    if event.get("hook_event") not in VALID_HOOK_EVENTS:
        return False
    if event.get("lifecycle_state") not in VALID_LIFECYCLE_STATES:
        return False
    event_run_id = event.get("run_id")
    # "unknown" is the recorder's fallback sentinel when project.json was unreadable
    # at hook-fire time.  Treat it as absent — the event belongs to this project's
    # delegation-events/ directory and should still be counted as unattributed.
    if event_run_id is not None and event_run_id != "unknown" and event_run_id != run_id:
        return False
    return True


def load_delegation_events(devflow_dir: Path) -> tuple[list[dict], str]:
    """
    Load sanitized delegation evidence events from .devflow/delegation-events/.

    Returns (events, status) where status is one of:
        "unavailable"  — delegation-events/ directory does not exist
        "not_observed" — directory exists but no SubagentStart events found
        "observed"     — at least one SubagentStart event was recorded
    """
    events_dir = devflow_dir / "delegation-events"
    if not events_dir.exists():
        return [], "unavailable"

    events: list[dict] = []
    for event_file in sorted(events_dir.glob("*.json")):
        try:
            data = json.loads(event_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                events.append(data)
        except Exception:
            pass

    subagent_starts = [e for e in events if e.get("hook_event") == "SubagentStart"]
    if not subagent_starts:
        return events, "not_observed"
    return events, "observed"


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


def is_path_git_worktree_change(target: Path, evidence_path: str) -> bool:
    """Return True if evidence_path appears in 'git status --short' output, including untracked."""
    result = subprocess.run(
        ["git", "status", "--short", "--", evidence_path],
        cwd=str(target),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False
    return bool(result.stdout.strip())


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


def _inject_security_review_task(tasks: list, run_id: str, objective: str) -> list:
    """
    Insert a Security Review task before the final release/approval task.

    Called only for delivery types that gain security_review_required=True
    from objective risk signals but do NOT already have a security_review task
    in their template (i.e. non-mandatory types like backend_utility,
    bug_resolution, etc.).

    Security Review depends on all implementation + qa tasks that precede the
    release task.  The release task is renumbered one position up and gains
    Security Review as an additional dependency.
    """
    if not tasks:
        return tasks

    release_task = tasks[-1]
    pre_release = tasks[:-1]

    # Deps: all implementation and QA tasks in the pre-release list
    sec_dep_types = frozenset({"implementation", "qa"})
    sec_dep_ids = [t["id"] for t in pre_release if t["task_type"] in sec_dep_types]
    if not sec_dep_ids and pre_release:
        sec_dep_ids = [pre_release[-1]["id"]]

    # Security Review gets the position of the current release task;
    # release task is shifted one position up.
    sec_suffix = f"{len(tasks):03d}"
    release_new_suffix = f"{len(tasks) + 1:03d}"

    sec_task_id = f"{run_id}-TASK-{sec_suffix}"
    new_release_id = f"{run_id}-TASK-{release_new_suffix}"

    sec_task = {
        "id": sec_task_id,
        "title": "Security Review",
        "task_type": "security_review",
        "assigned_role": "security-red-team",
        "dependency_ids": sec_dep_ids,
        "acceptance_criteria_ref": f"objective: {objective[:200]}",
        "qa_expectation": "Güvenlik raporu üretildi; blocker bulgu yok",
        "status": "planned",
        "output_path": SECURITY_EVIDENCE_PATH_PREFIX,
        "expected_evidence_path": SECURITY_EVIDENCE_PATH_PREFIX,
        "delegation_status": "planned",
    }

    # Release task: new ID + security review added to its dependencies
    updated_release = dict(release_task)
    updated_release["id"] = new_release_id
    updated_release["dependency_ids"] = list(
        release_task.get("dependency_ids", [])
    ) + [sec_task_id]

    return pre_release + [sec_task, updated_release]


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

    # Inject a Security Review task for delivery types not already having one
    # in their template, when the objective triggers risk signals.
    if delivery_type not in DELIVERY_TYPES_WITH_MANDATORY_SECURITY_REVIEW:
        already_has_security = any(t["task_type"] == "security_review" for t in tasks)
        if not already_has_security:
            sec_app = determine_security_applicability(delivery_type, objective)
            if sec_app["security_review_required"]:
                tasks = _inject_security_review_task(tasks, run_id, objective)

    return tasks


def validate_security_evidence_path(target: Path, evidence_path: str) -> tuple[bool, str]:
    """
    Validate a security evidence path for record-security-evidence.

    Rules (all enforced before existence check):
    - Must not be empty
    - Must not be absolute
    - Must not contain '..' traversal
    - Must not contain wildcards (* or ?)
    - Must start with docs/quality/security-reports/
    - File must exist at target/evidence_path

    Returns (ok, error_message).
    """
    if not evidence_path:
        return False, "evidence-path gereklidir"

    # Must not be absolute
    if Path(evidence_path).is_absolute():
        return False, f"evidence-path mutlak yol olamaz: {evidence_path!r}"

    # Normalize separators for consistent checks
    normalized = evidence_path.replace("\\", "/")

    # Must not contain path traversal
    parts = normalized.split("/")
    if ".." in parts or any(p.startswith("..") for p in parts):
        return False, f"evidence-path '..' traversal içeremez: {evidence_path!r}"

    # Must not contain wildcards
    if "*" in normalized or "?" in normalized:
        return False, f"evidence-path wildcard içeremez: {evidence_path!r}"

    # Must start with the allowed prefix
    if not normalized.startswith(SECURITY_EVIDENCE_PATH_PREFIX):
        return False, (
            f"evidence-path yalnızca '{SECURITY_EVIDENCE_PATH_PREFIX}' altında kabul edilir. "
            f"Verilen: {evidence_path!r}"
        )

    # File must exist inside target
    full_path = (target / evidence_path).resolve()
    try:
        full_path.relative_to(target.resolve())
    except ValueError:
        return False, f"evidence-path target dizini dışına çıkıyor: {evidence_path!r}"

    if not full_path.exists():
        return False, f"evidence-path dosyası bulunamadı: {evidence_path!r}"

    if not full_path.is_file():
        return False, f"evidence-path bir dosya olmalıdır: {evidence_path!r}"

    return True, ""


def validate_contract_evidence_path(target: Path, evidence_path: str) -> tuple[bool, str]:
    """
    Validate a contract evidence path for record-contract-evidence.

    Rules (all enforced before existence check):
    - Must not be empty
    - Must not be absolute
    - Must not contain '..' traversal
    - Must not contain wildcards (* or ?)
    - Must not start with .devflow/ or .claude/
    - Must start with docs/quality/contracts/
    - File must exist at target/evidence_path

    Returns (ok, error_message).
    """
    if not evidence_path:
        return False, "evidence-path gereklidir"

    if Path(evidence_path).is_absolute():
        return False, f"evidence-path mutlak yol olamaz: {evidence_path!r}"

    normalized = evidence_path.replace("\\", "/")

    parts = normalized.split("/")
    if ".." in parts or any(p.startswith("..") for p in parts):
        return False, f"evidence-path '..' traversal içeremez: {evidence_path!r}"

    if "*" in normalized or "?" in normalized:
        return False, f"evidence-path wildcard içeremez: {evidence_path!r}"

    if normalized.startswith(".devflow/") or normalized.startswith(".claude/"):
        return False, (
            f"evidence-path yalnızca '{CONTRACT_EVIDENCE_PATH_PREFIX}' altında kabul edilir. "
            f"Verilen: {evidence_path!r}"
        )

    if not normalized.startswith(CONTRACT_EVIDENCE_PATH_PREFIX):
        return False, (
            f"evidence-path yalnızca '{CONTRACT_EVIDENCE_PATH_PREFIX}' altında kabul edilir. "
            f"Verilen: {evidence_path!r}"
        )

    full_path = (target / evidence_path).resolve()
    try:
        full_path.relative_to(target.resolve())
    except ValueError:
        return False, f"evidence-path target dizini dışına çıkıyor: {evidence_path!r}"

    if not full_path.exists():
        return False, f"evidence-path dosyası bulunamadı: {evidence_path!r}"

    if not full_path.is_file():
        return False, f"evidence-path bir dosya olmalıdır: {evidence_path!r}"

    return True, ""


def validate_work_product_evidence_path(
    target: Path,
    task_type: str,
    evidence_path: str,
) -> tuple[bool, str]:
    """
    Validate a work-product evidence path for record-work-product-evidence.

    Enforced rules (in order):
    1. Not empty
    2. Not absolute
    3. No '..' traversal
    4. No wildcards
    5. Resolves inside target
    6. Not under .devflow/, .claude/, docs/, or evals/scorecards/
    7. Not a forbidden file name (lockfile, dep spec, build/config file)
    8. No forbidden path component (migrations, .devflow, .claude)
    9. Not a sensitive file name (.env*, *secret*, *credential*, ...)
    10. For implementation: must start with an implementation prefix
    11. For QA: must start with a QA prefix
    12. File must exist

    Returns (ok, error_message).
    """
    if not evidence_path:
        return False, "evidence-path gereklidir"

    if Path(evidence_path).is_absolute():
        return False, f"evidence-path mutlak yol olamaz: {evidence_path!r}"

    normalized = evidence_path.replace("\\", "/")
    parts = normalized.split("/")

    if ".." in parts or any(p.startswith("..") for p in parts):
        return False, f"evidence-path '..' traversal içeremez: {evidence_path!r}"

    if "*" in normalized or "?" in normalized:
        return False, f"evidence-path wildcard içeremez: {evidence_path!r}"

    full_path = (target / evidence_path).resolve()
    try:
        full_path.relative_to(target.resolve())
    except ValueError:
        return False, f"evidence-path target dizini dışına çıkıyor: {evidence_path!r}"

    for forbidden_prefix in _WORK_PRODUCT_FORBIDDEN_DOC_PREFIXES:
        if normalized.startswith(forbidden_prefix):
            return False, (
                f"evidence-path '{forbidden_prefix}' altındaki yollar work-product kanıtı "
                f"sayılamaz. Kaynak kodu ({', '.join(IMPLEMENTATION_EVIDENCE_PREFIXES)}) "
                f"veya test dosyası ({', '.join(QA_EVIDENCE_PREFIXES)}) olmalıdır: "
                f"{evidence_path!r}"
            )

    filename = Path(normalized).name
    if filename in _WORK_PRODUCT_FORBIDDEN_FILENAMES:
        return False, (
            f"evidence-path '{filename}' bağımlılık, konfigürasyon veya lockfile olarak "
            f"work-product kanıtı sayılamaz: {evidence_path!r}"
        )

    for comp in parts[:-1]:
        if comp in _WORK_PRODUCT_FORBIDDEN_PATH_COMPONENTS:
            return False, (
                f"evidence-path yasak dizin bileşeni '{comp}' içeriyor "
                f"(migration, .devflow, .claude kabul edilmez): {evidence_path!r}"
            )

    filename_lower = filename.lower()
    for prefix in _WORK_PRODUCT_FORBIDDEN_NAME_PREFIXES:
        if filename_lower.startswith(prefix):
            return False, (
                f"evidence-path '{filename}' gizli/konfigürasyon dosyası olarak "
                f"work-product kanıtı sayılamaz: {evidence_path!r}"
            )

    for sensitive in _WORK_PRODUCT_FORBIDDEN_NAME_SENSITIVE:
        if sensitive in filename_lower:
            return False, (
                f"evidence-path '{filename}' gizli veri içerdiği için "
                f"work-product kanıtı sayılamaz: {evidence_path!r}"
            )

    if task_type == "implementation":
        starts_with_impl_prefix = any(normalized.startswith(p) for p in IMPLEMENTATION_EVIDENCE_PREFIXES)
        # Also accept source/template assets nested inside application packages (e.g. jobs/views.py),
        # but never accept a file whose name marks it as a test asset.
        is_nested_source = _is_source_asset(filename) and not _is_test_filename(filename)
        if not (starts_with_impl_prefix or is_nested_source):
            impl_list = ", ".join(sorted(IMPLEMENTATION_EVIDENCE_PREFIXES))
            return False, (
                f"Implementation work-product kanıtı şu prefixlerden birinde olmalıdır: "
                f"{impl_list}. Verilen: {evidence_path!r}"
            )
    elif task_type == "qa":
        starts_with_qa_prefix = any(normalized.startswith(p) for p in QA_EVIDENCE_PREFIXES)
        # Also accept conventional test modules inside application packages (e.g. jobs/tests.py).
        is_nested_test = _is_test_filename(filename)
        if not (starts_with_qa_prefix or is_nested_test):
            qa_list = ", ".join(sorted(QA_EVIDENCE_PREFIXES))
            return False, (
                f"QA work-product kanıtı şu prefixlerden birinde olmalıdır: "
                f"{qa_list}. Verilen: {evidence_path!r}"
            )

    if not full_path.exists():
        return False, f"evidence-path dosyası bulunamadı: {evidence_path!r}"

    if not full_path.is_file():
        return False, f"evidence-path bir dosya olmalıdır: {evidence_path!r}"

    return True, ""


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
    task_type = task.get("task_type", "")
    packet: dict = {
        "schema_version": "1",
        "run_id": run_id,
        "task_id": task["id"],
        "objective_summary": (objective or "")[:500],
        "assigned_role": task.get("assigned_role", ""),
        "title": task.get("title", ""),
        "task_type": task_type,
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
    if task_type in WORK_PRODUCT_REQUIRED_TASK_TYPES:
        if task_type == "implementation":
            allowed_prefixes = ", ".join(sorted(IMPLEMENTATION_EVIDENCE_PREFIXES))
        else:
            allowed_prefixes = ", ".join(sorted(QA_EVIDENCE_PREFIXES))
        packet["work_product_requirements"] = {
            "required": True,
            "instructions": [
                f"Bu task '{task_type}' türündedir ve work-product kanıtı zorunludur.",
                "Önce gerçek kaynak/test dosyasını oluştur veya değiştir.",
                f"Kabul edilen yol prefixleri: {allowed_prefixes}",
                "Ardından CLI komutu ile kanıtı kaydet:",
                (
                    f"  python3 scripts/devflow_operations.py record-work-product-evidence "
                    f"--target <TARGET> --task-id {task['id']} --evidence-path <RELATIVE_PATH>"
                ),
                "Self-reported completion yeterli değildir. Kanıt kaydedilmeden task completed/verified yapılamaz.",
                "Kanıt yolu: docs/, .devflow/, lockfile, credential veya config dosyaları kabul edilmez.",
            ],
            "gate": "record-work-product-evidence CLI çalıştırılmadan completed/verified durumuna geçilemez.",
        }
    return packet


def is_run_active(run_data: dict, devflow_dir: Path) -> bool:
    """
    Return True if the run has begun work that makes the task graph immutable.

    A run is considered active when any of these conditions hold:
    - Any task has a status other than 'planned'
    - The artifacts list is non-empty
    - QA evidence has been recorded via record-qa-evidence
    - context_pack_status is 'ready' (context was prepared for this graph)
    - Delegation events exist in .devflow/delegation-events/
    """
    tasks = run_data.get("tasks", [])
    if any(t.get("status") != "planned" for t in tasks):
        return True
    if run_data.get("artifacts"):
        return True
    if run_data.get("qa_evidence"):
        return True
    if run_data.get("context_pack_status") == "ready":
        return True
    events_dir = devflow_dir / "delegation-events"
    if events_dir.exists() and any(events_dir.glob("*.json")):
        return True
    return False


def build_run_report(
    run_data: dict,
    run_id: str,
    delegation_events: list[dict] | None = None,
    target: "Path | None" = None,
) -> dict:
    """
    Build an evidence report dict from run state. No sys.exit.

    delegation_events: list of sanitized delegation event dicts loaded from
        .devflow/delegation-events/, or None when the directory was absent
        (status=unavailable).  Pass [] for "directory exists but no events".
    """
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

    # ---------------------------------------------------------------------------
    # Security gate applicability
    #
    # security_review_required is written to run state by generate-task-graph.
    # Default True for backward compatibility with run states that predate this field.
    #
    # Three-state machine (checked in this order):
    #   1. required=False → status="not_applicable", gate satisfied
    #   2. required=True + record-security-evidence wrote completed status
    #      → status="completed", gate satisfied iff verdict=pass
    #   3. required=True + backward-compat security_review_complete gate=True
    #      → status="completed", gate satisfied (legacy path)
    #   4. required=True + no evidence → status="pending", gate NOT satisfied
    # ---------------------------------------------------------------------------
    security_review_required = run_data.get("security_review_required", True)
    security_applicability_reason = run_data.get(
        "security_applicability_reason", "explicit_security_signal"
    )
    if not security_review_required:
        security_review_status = "not_applicable"
        security_gate_satisfied = True
    else:
        # Check for security evidence written by record-security-evidence.
        # A stored "completed" status with an explicit gate value takes precedence
        # over the backward-compat approval gate flag.
        _stored_sec_status = run_data.get("security_review_status")
        _stored_sec_gate = run_data.get("security_gate_satisfied")
        if _stored_sec_status == "completed" and _stored_sec_gate is not None:
            security_review_status = "completed"
            security_gate_satisfied = bool(_stored_sec_gate)
        elif security_done:
            # Backward compat: approval_gates.security_review_complete=True
            security_review_status = "completed"
            security_gate_satisfied = True
        else:
            security_review_status = "pending"
            security_gate_satisfied = False

    # ---------------------------------------------------------------------------
    # Contract gate applicability
    #
    # contract_required is written at generate-task-graph time.
    # Default False for backward compatibility with runs that predate this field.
    #
    # Three-state machine (checked in this order):
    #   1. required=False → status="not_applicable", gate satisfied
    #   2. required=True + record-contract-evidence wrote completed status
    #      → status="completed", gate satisfied
    #   3. required=True + no evidence → status="pending", gate NOT satisfied
    # ---------------------------------------------------------------------------
    contract_required = run_data.get("contract_required", False)
    if not contract_required:
        contract_status = "not_applicable"
        contract_gate_satisfied = True
    else:
        _stored_contract_status = run_data.get("contract_status")
        _stored_contract_gate = run_data.get("contract_gate_satisfied")
        if _stored_contract_status == "completed" and _stored_contract_gate is not None:
            contract_status = "completed"
            contract_gate_satisfied = bool(_stored_contract_gate)
        else:
            contract_status = "pending"
            contract_gate_satisfied = False

    _contract_evidence_meta = run_data.get("contract_evidence")

    # ---------------------------------------------------------------------------
    # Work product gate
    #
    # Requires each completed/verified implementation or QA task to have a
    # recorded evidence path that is (or was) an active Git worktree change.
    # When target is provided, staleness is checked live; otherwise it is marked
    # as unknown (None).
    #
    # LIMITATION: this gate verifies local work-product presence only.
    # It does not establish causal attribution to a specific agent session.
    # ---------------------------------------------------------------------------
    _work_product_evidence = run_data.get("work_product_evidence", {})
    _required_wp_tasks = [
        t for t in tasks
        if t.get("task_type") in WORK_PRODUCT_REQUIRED_TASK_TYPES
    ]
    _wp_task_statuses: list[dict] = []
    _wp_gate_satisfied = True

    for _wpt in _required_wp_tasks:
        _wpt_id = _wpt["id"]
        _wpt_status = _wpt.get("status", "planned")
        _ev = _work_product_evidence.get(_wpt_id)
        if _ev:
            _ep = _ev.get("evidence_path", "")
            _git_active: "bool | None" = None
            if target is not None and _ep:
                _git_active = is_path_git_worktree_change(target, _ep)
            _wp_task_statuses.append({
                "task_id": _wpt_id,
                "task_type": _wpt.get("task_type"),
                "task_status": _wpt_status,
                "evidence_recorded": True,
                "evidence_path": _ep,
                "recorded_at": _ev.get("recorded_at"),
                "git_change_active": _git_active,
            })
            if _git_active is False:
                _wp_gate_satisfied = False
        else:
            _wp_task_statuses.append({
                "task_id": _wpt_id,
                "task_type": _wpt.get("task_type"),
                "task_status": _wpt_status,
                "evidence_recorded": False,
                "evidence_path": None,
                "recorded_at": None,
                "git_change_active": None,
            })
            if _wpt_status in WORK_PRODUCT_GATE_BLOCKED_STATUSES:
                _wp_gate_satisfied = False

    if not _required_wp_tasks:
        _wp_gate_status = "not_applicable"
        _wp_gate_satisfied = True
    elif all(s["evidence_recorded"] for s in _wp_task_statuses):
        _wp_gate_status = "completed"
    else:
        _wp_gate_status = "pending"

    _wp_limitation_note = (
        "Work Product Gate yerel work-product varlığını doğrular. "
        "Bu gate belirli bir agent session'a causal attribution iddiası taşımaz. "
        "Git worktree değişiklik kontrolü kayıt anında gerçekleştirildi; "
        "raporlama anında yol artık değişmemiş olabilir."
    )

    # Technical readiness: all auto gates + tasks done (human approval is separate)
    auto_gates_pass = (
        all_tasks_done and qa_done and security_gate_satisfied and tests_passing
        and contract_gate_satisfied and _wp_gate_satisfied
    )
    technical_readiness = "ready" if auto_gates_pass else "not_ready"

    if auto_gates_pass and human_done:
        merge_recommendation = "ready_for_human_merge"
        run_status = "ready_for_human_merge"
    elif auto_gates_pass and not human_done:
        merge_recommendation = "awaiting_human_approval"
        run_status = "awaiting_human_approval"
    else:
        merge_recommendation = "not_ready"
        run_status = "not_ready"

    # ---------------------------------------------------------------------------
    # Delegation evidence: requested/configured vs observed distinction
    #
    # "requested_execution_mode" / "agent_teams_requested" — what was configured
    # "native_delegation_observed" / "observed_delegation_count" — from hook events
    # "delegation_evidence_status" — "unavailable" | "not_observed" | "observed"
    # "observed_agent_types" — distinct non-unknown agent types seen in events
    # "unattributed_event_count" — events with agent_type == "unknown"
    #
    # Rules:
    # - delegation_events=None  → status="unavailable" (hook not running)
    # - delegation_events=[]    → status="not_observed" (hook ran; no subagent started)
    # - SubagentStart in events → status="observed"
    # Never claim delegation success without a native hook event.
    # observed_delegation_count counts ALL valid lifecycle event files loaded.
    # ---------------------------------------------------------------------------
    # Backward-compat: prefer new canonical names, fall back to legacy fields.
    execution_mode = run_data.get(
        "requested_execution_mode",
        run_data.get("execution_mode", "subagents"),
    )
    agent_teams_requested = run_data.get(
        "agent_teams_requested",
        run_data.get("requested_agent_teams", False),
    )

    if delegation_events is None:
        delegation_status = "unavailable"
        native_observed = False
        observed_count = 0
        start_count = 0
        observed_agent_types: list[str] = []
        unattributed_event_count = 0
    else:
        subagent_starts = [e for e in delegation_events if e.get("hook_event") == "SubagentStart"]
        start_count = len(subagent_starts)
        observed_count = len(delegation_events)  # ALL loaded lifecycle event files
        native_observed = start_count > 0
        delegation_status = "observed" if native_observed else "not_observed"
        observed_agent_types = sorted({
            e.get("agent_type", "unknown")
            for e in delegation_events
            if e.get("agent_type", "unknown") != "unknown"
        })
        unattributed_event_count = sum(
            1 for e in delegation_events
            if e.get("agent_type", "unknown") == "unknown"
        )

    limitation_note = (
        "Native lifecycle event kayıtları local, sanitize edilmiş çalışma kanıtıdır. "
        "Cryptographic audit trail veya tamper-proof storage içermez. "
        "Session ID saklanmadığından start-stop eşleşmesi veya "
        "artifact-to-session causal binding kesin olarak iddia edilemez."
    )

    boundary_note: str
    if native_observed:
        boundary_note = (
            f"{observed_count} lifecycle event kayıtlı "
            f"({start_count} SubagentStart). "
            "Native role lifecycle gözlemlendi. "
            "Session ID saklanmadığından start-stop eşleşmesi veya "
            "artifact-to-session causal binding doğrulanamaz."
        )
    elif delegation_status == "not_observed":
        boundary_note = (
            "Delegation events dizini mevcut ancak SubagentStart kaydı yok. "
            "Gerçek agent dispatch gözlemlenmedi."
        )
    else:
        boundary_note = (
            "Tüm task'lar 'planned' delegation durumunda. "
            "Gerçek agent dispatch doğrulanmadı."
            if not any_confirmed
            else "En az bir task gerçek agent session kanıtıyla doğrulandı."
        )

    # ---------------------------------------------------------------------------
    # Evidence provenance — each source category is classified independently.
    #
    # "user_provided"    — supplied by the user outside this run
    # "generated_in_run" — produced by an agent within this same run
    # "test_command"     — verified by a test runner command (tests_passing gate)
    # "native_hook_event"— recorded by the native hook mechanism
    # "human_review"     — confirmed by a human (human_approval gate)
    # "unavailable"      — not present or not verifiable
    #
    # AC generated in the same run is never presented as user-approved or
    # independent sign-off.  Security checklists from the same run are never
    # presented as a separate security-agent session without native evidence.
    # ---------------------------------------------------------------------------
    _sec_evidence_meta = run_data.get("security_evidence")
    evidence_provenance = {
        "acceptance_criteria": "generated_in_run",
        "qa_result": "test_command" if qa_done else "unavailable",
        "security_review": (
            "not_applicable" if not security_review_required
            else "generated_in_run" if security_review_status == "completed"
            else "unavailable"
        ),
        "contract_review": (
            "not_applicable" if not contract_required
            else "generated_in_run" if contract_status == "completed"
            else "unavailable"
        ),
        "human_approval": "human_review" if human_done else "unavailable",
        "native_delegation": "native_hook_event" if native_observed else "unavailable",
    }

    return {
        "schema_version": "1",
        "run_id": run_id,
        "objective": run_data.get("objective", ""),
        "execution_mode": execution_mode,
        "agent_teams_requested": agent_teams_requested,
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
        "technical_readiness": technical_readiness,
        "status": run_status,
        "human_approval_required": [
            "main merge insan tarafından yapılmalıdır",
            "production deploy insan tarafından yapılmalıdır",
        ],
        "delegation_evidence": {
            "requested_execution_mode": execution_mode,
            "agent_teams_requested": agent_teams_requested,
            "native_delegation_observed": native_observed,
            "observed_delegation_count": observed_count,
            "delegation_evidence_status": delegation_status,
            "any_delegation_confirmed": any_confirmed,
            "observed_agent_types": observed_agent_types,
            "unattributed_event_count": unattributed_event_count,
            "limitation_note": limitation_note,
            "boundary_note": boundary_note,
        },
        "evidence_provenance": evidence_provenance,
        "security_applicability": {
            "security_review_required": security_review_required,
            "security_review_status": security_review_status,
            "security_gate_satisfied": security_gate_satisfied,
            "security_applicability_reason": security_applicability_reason,
            "security_evidence": _sec_evidence_meta,
            "launch_risk_floor_required": run_data.get("launch_risk_floor_required", None),
            "launch_risk_floor_reason": run_data.get("launch_risk_floor_reason", None),
        },
        "contract_applicability": {
            "contract_required": contract_required,
            "contract_status": contract_status,
            "contract_gate_satisfied": contract_gate_satisfied,
            "contract_evidence": _contract_evidence_meta,
        },
        "work_product_gate": {
            "required": bool(_required_wp_tasks),
            "status": _wp_gate_status,
            "gate_satisfied": _wp_gate_satisfied,
            "tasks": _wp_task_statuses,
            "limitation_note": _wp_limitation_note,
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

    launch_objective = getattr(args, "objective", None) or ""
    _launch_signals = detect_objective_risk_signals(launch_objective)
    _launch_triggering = _launch_signals & SECURITY_TRIGGERING_RISK_SIGNALS
    if _launch_triggering:
        launch_risk_floor_required = True
        launch_risk_floor_reason = _security_reason_from_signals(_launch_triggering)
    else:
        launch_risk_floor_required = False
        launch_risk_floor_reason = "low_risk_local_utility"

    run_state = {
        "schema_version": DEVFLOW_SCHEMA_VERSION,
        "run_id": run_id,
        "created_at": now,
        "status": "created",
        "branch_name": branch_name,
        "objective": launch_objective,
        "execution_mode": execution_mode,
        "requested_execution_mode": execution_mode,
        "agent_teams_requested": agent_teams_requested,
        # "requested_agent_teams" intentionally omitted — backward compat on read only
        "native_delegation_observed": False,
        "observed_delegation_count": 0,
        "delegation_evidence_status": "unavailable",
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
        "launch_risk_floor_required": launch_risk_floor_required,
        "launch_risk_floor_reason": launch_risk_floor_reason,
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
        f"\n"
        f"DEVFLOW_RUN_WORKTREE is the sole writable repository root for this managed run.\n"
        f"Do not write to or modify any path outside DEVFLOW_RUN_WORKTREE.\n"
        f"\n"
        f"Sen bu run'ın Delivery Lead'isin. Sorumlulukların:\n"
        f"- /orchestrate-delivery skill'ini kullanarak delivery döngüsünü yönet\n"
        f'- Managed operations için: python3 "$DEVFLOW_OPERATIONS_SCRIPT" ... --target "$DEVFLOW_RUN_WORKTREE"\n'
        f"- Yazma öncesi konumu doğrula: pwd, git rev-parse --show-toplevel, git branch --show-current\n"
        f"- Kök DEVFLOW_RUN_WORKTREE ve branch DEVFLOW_RUN_BRANCH ile eşleşmeli; uyuşmazlıkta yaz yapma, raporla\n"
        f"- main branch'e doğrudan yazma; insan approval gate'lerini koru\n"
        f"- DEVFLOW_RUN_WORKTREE dışında dosya oluşturma veya değiştirme"
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

    # Run boundary env vars — set before execve so the guard and agents can enforce them
    child_env["DEVFLOW_RUN_WORKTREE"] = str(worktree_path)
    child_env["DEVFLOW_RUN_BRANCH"] = branch_name
    child_env["DEVFLOW_OPERATIONS_SCRIPT"] = str(plugin_dir / "scripts" / "devflow_operations.py")

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

    if run_data.get("tasks") and force:
        if is_run_active(run_data, devflow):
            print(
                "Hata: Aktif run için task graph yeniden oluşturulamaz.",
                file=sys.stderr,
            )
            print(
                "  Görevler ilerletilmiş, delegation event'ları, QA kanıtı veya artefaktlar mevcut.",
                file=sys.stderr,
            )
            print(
                "  Farklı delivery routing için yeni run başlatın: "
                "'create-run --target ...'",
                file=sys.stderr,
            )
            sys.exit(16)

    objective = getattr(args, "objective", None) or run_data.get("objective", "")
    tasks = generate_task_graph_nodes(run_id, delivery_type, objective)

    # ---------------------------------------------------------------------------
    # Launch risk floor enforcement
    #
    # launch_risk_floor_required is set at create-run time from the launch objective.
    # It can only raise security_review_required — never lower it.
    # Legacy run states without the floor fields default to False (backward compat).
    # ---------------------------------------------------------------------------
    launch_floor_required = run_data.get("launch_risk_floor_required", False)
    launch_floor_reason = run_data.get("launch_risk_floor_reason", "low_risk_local_utility")

    sec_app = determine_security_applicability(delivery_type, objective)
    graph_required = sec_app["security_review_required"]
    graph_reason = sec_app["security_applicability_reason"]

    effective_required = launch_floor_required or graph_required
    if effective_required:
        # Floor triggered but graph didn't → use floor reason; else prefer graph reason
        effective_reason = graph_reason if graph_required else launch_floor_reason
    else:
        effective_reason = "low_risk_local_utility"

    # Inject security task when floor requires it but graph didn't include one
    if effective_required and not any(t["task_type"] == "security_review" for t in tasks):
        # Use the launch objective (canonical risk source) for task ref
        tasks = _inject_security_review_task(tasks, run_id, run_data.get("objective", objective))

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

    # Write effective security applicability (floor-enforced) to canonical run state.
    # Not overridden by finalization; not writable via direct JSON edit
    # (target guard blocks .devflow/runs/ writes except via this CLI).
    run_data["security_review_required"] = effective_required
    run_data["security_applicability_reason"] = effective_reason

    # Write contract gate state to canonical run state.
    # contract_required is deterministic from delivery_type; only new_feature requires it.
    # Implementation tasks cannot enter in_progress/completed/verified until gate is satisfied.
    _contract_required = delivery_type in DELIVERY_TYPES_WITH_CONTRACT_GATE
    run_data["contract_required"] = _contract_required
    run_data["contract_status"] = "pending" if _contract_required else "not_applicable"
    run_data["contract_gate_satisfied"] = not _contract_required

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

    # Contract gate enforcement: implementation tasks cannot advance to
    # in_progress/completed/verified until contract evidence is recorded.
    # Only applies when contract_required=True (set by generate-task-graph for new_feature).
    if new_status in CONTRACT_GATE_BLOCKED_STATUSES:
        if task.get("task_type") == "implementation":
            if run_data.get("contract_required", False):
                if not run_data.get("contract_gate_satisfied", False):
                    print(
                        f"Hata: Contract evidence kaydedilmeden implementation görevi "
                        f"'{new_status}' durumuna geçirilemiyor. "
                        "'record-contract-evidence' CLI kullanın.",
                        file=sys.stderr,
                    )
                    sys.exit(15)

    # Work product gate enforcement: implementation and QA tasks cannot reach
    # completed/verified without a recorded work-product evidence entry.
    if new_status in WORK_PRODUCT_GATE_BLOCKED_STATUSES:
        if task.get("task_type") in WORK_PRODUCT_REQUIRED_TASK_TYPES:
            _wp_evidence = run_data.get("work_product_evidence", {})
            if task_id not in _wp_evidence:
                print(
                    f"Hata: Work-product kanıtı kaydedilmeden "
                    f"'{task.get('task_type')}' görevi '{new_status}' durumuna geçirilemiyor. "
                    "'record-work-product-evidence' CLI kullanın.",
                    file=sys.stderr,
                )
                sys.exit(15)

    task["status"] = new_status
    atomic_write_json(run_file, run_data)

    print(f"Task durumu güncellendi: {task_id}")
    print(f"  {from_status} → {new_status}")
    return 0


def cmd_record_qa_evidence(args) -> int:
    target = Path(args.target).resolve()
    validate_target_path(target)
    validate_not_on_protected_branch(target, "record-qa-evidence")

    total = args.total
    passed = args.passed
    failed = args.failed
    exit_code_val = args.exit_code
    evidence_path = getattr(args, "evidence_path", None) or ""

    if evidence_path:
        ep = Path(evidence_path)
        if ep.is_absolute() or ".." in ep.parts:
            print(
                "Hata: evidence_path göreli ve güvenli bir yol olmalıdır "
                "(mutlak yol veya '..' yasak).",
                file=sys.stderr,
            )
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

    qa_passed = (exit_code_val == 0 and failed == 0)

    run_data.setdefault("approval_gates", {})
    run_data["approval_gates"]["tests_passing"] = qa_passed
    run_data["approval_gates"]["qa_sign_off"] = qa_passed

    run_data["qa_evidence"] = {
        "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total": total,
        "passed": passed,
        "failed": failed,
        "exit_code": exit_code_val,
        "evidence_path": evidence_path,
        "qa_passed": qa_passed,
    }

    atomic_write_json(run_file, run_data)

    status_str = "GEÇTİ" if qa_passed else "BAŞARISIZ"
    print(f"QA kanıtı kaydedildi: {run_id} [{status_str}]")
    print(f"  toplam: {total}, geçen: {passed}, başarısız: {failed}, exit code: {exit_code_val}")
    print(f"  tests_passing: {qa_passed}")
    print(f"  qa_sign_off: {qa_passed}")
    if evidence_path:
        print(f"  evidence_path: {evidence_path}")
    return 0


def cmd_record_security_evidence(args) -> int:
    target = Path(args.target).resolve()
    validate_target_path(target)
    validate_not_on_protected_branch(target, "record-security-evidence")

    verdict = args.verdict
    max_severity = args.max_severity
    run_id_override = getattr(args, "run_id", None)
    evidence_path = args.evidence_path

    # Validate verdict (argparse choices already enforce this; double-check)
    if verdict not in SECURITY_EVIDENCE_VERDICTS:
        print(
            f"Hata: Geçersiz verdict: '{verdict}'. "
            f"Geçerliler: {sorted(SECURITY_EVIDENCE_VERDICTS)}",
            file=sys.stderr,
        )
        sys.exit(17)

    # Validate severity
    if max_severity not in SECURITY_EVIDENCE_SEVERITIES:
        print(
            f"Hata: Geçersiz max-severity: '{max_severity}'. "
            f"Geçerliler: {sorted(SECURITY_EVIDENCE_SEVERITIES)}",
            file=sys.stderr,
        )
        sys.exit(17)

    # Validate verdict+severity combination
    allowed_severities = VALID_VERDICT_SEVERITY_COMBOS.get(verdict, frozenset())
    if max_severity not in allowed_severities:
        print(
            f"Hata: Geçersiz verdict+severity kombinasyonu: "
            f"verdict='{verdict}' max-severity='{max_severity}'.",
            file=sys.stderr,
        )
        if verdict == "pass":
            print(
                "  'pass' yalnızca max-severity='none' veya 'low' ile geçerlidir.",
                file=sys.stderr,
            )
        else:
            print(
                "  'blocked' yalnızca max-severity='medium', 'high' veya 'critical' ile geçerlidir.",
                file=sys.stderr,
            )
        sys.exit(17)

    devflow = get_devflow_dir(target)
    if not is_initialized(target):
        print("Hata: .devflow/ başlatılmamış.", file=sys.stderr)
        sys.exit(4)

    project_data = read_json(devflow / "project.json")
    run_id = project_data.get("current_run_id")
    if not run_id:
        print("Hata: Aktif run yok.", file=sys.stderr)
        sys.exit(4)

    # Optional run-id override: must match the current run
    if run_id_override and run_id_override != run_id:
        print(
            f"Hata: --run-id '{run_id_override}' aktif run '{run_id}' ile eşleşmiyor. "
            "Yalnızca aktif/current run için evidence kaydedilebilir.",
            file=sys.stderr,
        )
        sys.exit(17)

    run_file = devflow / "runs" / f"{run_id}.json"
    if not run_file.exists():
        print(f"Hata: Run state dosyası bulunamadı: {run_file}", file=sys.stderr)
        sys.exit(4)

    run_data = read_json(run_file)

    # Reject if security review is not required for this run.
    # Default False so that runs without generate-task-graph are also rejected.
    if not run_data.get("security_review_required", False):
        print(
            "Hata: Bu run için security review gerekli değil "
            "(security_review_required=false veya henüz belirlenmemiş). "
            "Low-risk run'a security evidence kaydedilemez.",
            file=sys.stderr,
        )
        sys.exit(17)

    # Validate evidence path (relative, safe, under allowed prefix, file must exist)
    path_ok, path_err = validate_security_evidence_path(target, evidence_path)
    if not path_ok:
        print(f"Hata: {path_err}", file=sys.stderr)
        sys.exit(17)

    security_gate_satisfied = verdict == "pass"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Write narrow canonical metadata to run state.
    # Never copies evidence file content, session IDs, or free text.
    run_data["security_review_status"] = "completed"
    run_data["security_gate_satisfied"] = security_gate_satisfied
    run_data["security_evidence"] = {
        "evidence_path": evidence_path,
        "verdict": verdict,
        "max_severity": max_severity,
        "recorded_at": now,
        "provenance": "generated_in_run",
    }
    # Update approval gate for backward compatibility with report logic
    run_data.setdefault("approval_gates", {})
    run_data["approval_gates"]["security_review_complete"] = security_gate_satisfied

    atomic_write_json(run_file, run_data)

    gate_str = "SAĞLANDI" if security_gate_satisfied else "BAŞARISIZ (blocked)"
    print(f"Security evidence kaydedildi: {run_id} [{gate_str}]")
    print(f"  verdict: {verdict}")
    print(f"  max_severity: {max_severity}")
    print(f"  evidence_path: {evidence_path}")
    print(f"  security_gate_satisfied: {security_gate_satisfied}")
    print(f"  provenance: generated_in_run")
    return 0


def cmd_record_contract_evidence(args) -> int:
    """
    Record contract evidence for a new_feature delivery run.

    Validates the evidence path (must be under docs/quality/contracts/),
    checks that contract_required=True for this run, confirms the run-id
    matches the active run, then writes contract_status=completed and
    contract_gate_satisfied=True to canonical run state.

    Exit code 18 for all rejections.
    """
    target = Path(args.target).resolve()
    validate_target_path(target)
    validate_not_on_protected_branch(target, "record-contract-evidence")

    run_id_override = getattr(args, "run_id", None)
    evidence_path = args.evidence_path

    devflow = get_devflow_dir(target)
    if not is_initialized(target):
        print("Hata: .devflow/ başlatılmamış.", file=sys.stderr)
        sys.exit(4)

    project_data = read_json(devflow / "project.json")
    run_id = project_data.get("current_run_id")
    if not run_id:
        print("Hata: Aktif run yok.", file=sys.stderr)
        sys.exit(4)

    # --run-id, if provided, must match the current active run.
    if run_id_override and run_id_override != run_id:
        print(
            f"Hata: --run-id '{run_id_override}' aktif run '{run_id}' ile eşleşmiyor. "
            "Yalnızca aktif/current run için contract evidence kaydedilebilir.",
            file=sys.stderr,
        )
        sys.exit(18)

    run_file = devflow / "runs" / f"{run_id}.json"
    if not run_file.exists():
        print(f"Hata: Run state dosyası bulunamadı: {run_file}", file=sys.stderr)
        sys.exit(4)

    run_data = read_json(run_file)

    # Reject if contract gate is not required for this run.
    if not run_data.get("contract_required", False):
        print(
            "Hata: Bu run için contract gate gerekli değil (contract_required=false). "
            "Contract evidence yalnızca new_feature delivery runs için kaydedilebilir.",
            file=sys.stderr,
        )
        sys.exit(18)

    # Validate evidence path: must be under docs/quality/contracts/, exist, be relative, no traversal.
    path_ok, path_err = validate_contract_evidence_path(target, evidence_path)
    if not path_ok:
        print(f"Hata: {path_err}", file=sys.stderr)
        sys.exit(18)

    # Locate the unique contract_definition task.
    # Reject before any state mutation if the task is absent or ambiguous.
    _all_tasks = run_data.get("tasks", [])
    _contract_def_tasks = [t for t in _all_tasks if t.get("task_type") == "contract_definition"]

    if len(_contract_def_tasks) == 0:
        print(
            "Hata: Aktif run içinde contract_definition task bulunamadı. "
            "Contract evidence kaydedilemez.",
            file=sys.stderr,
        )
        sys.exit(18)

    if len(_contract_def_tasks) > 1:
        print(
            f"Hata: Aktif run içinde {len(_contract_def_tasks)} adet contract_definition task "
            "bulundu. Belirsizlik nedeniyle işlem reddedildi; state güncellenmedi.",
            file=sys.stderr,
        )
        sys.exit(18)

    _contract_task = _contract_def_tasks[0]

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Authoritative task status update — idempotent if already verified.
    # Bypasses general validate_task_transition deliberately; this is an
    # authoritative evidence command, not a free-form status transition.
    if _contract_task["status"] != "verified":
        _contract_task["status"] = "verified"

    # Atomic state write: contract metadata, gate, evidence, and task status together.
    run_data["contract_status"] = "completed"
    run_data["contract_gate_satisfied"] = True
    run_data["contract_evidence"] = {
        "evidence_path": evidence_path,
        "recorded_at": now,
        "provenance": "generated_in_run",
    }
    # Update backward-compatible approval gate.
    run_data.setdefault("approval_gates", {})
    run_data["approval_gates"]["contract_approved"] = True

    atomic_write_json(run_file, run_data)

    print(f"Contract evidence kaydedildi: {run_id} [TAMAMLANDI]")
    print(f"  evidence_path: {evidence_path}")
    print(f"  contract_status: completed")
    print(f"  contract_gate_satisfied: True")
    print(f"  provenance: generated_in_run")
    print("  NOTE: Bu artefakt bu run içinde üretilmiştir.")
    print("  Belirli bir native session'a causal binding iddiası taşımaz.")
    return 0


def cmd_record_work_product_evidence(args) -> int:
    """
    Record verifiable work-product evidence for an implementation or QA task.

    Validates:
    - Run is active and task belongs to it
    - Task type is implementation or qa
    - Evidence path is relative, safe, and appropriate for the task type
    - File exists inside the target
    - File is currently an active Git worktree change (modified, staged, or untracked)
    - Forbidden path categories are rejected (.devflow/, docs/, lockfiles, secrets, migrations)

    LIMITATION: Verifies local work-product presence only.
    Does not establish causal attribution to a specific agent session.

    Exit code 19 for all rejections.
    """
    target = Path(args.target).resolve()
    validate_target_path(target)
    validate_not_on_protected_branch(target, "record-work-product-evidence")

    run_id_override = getattr(args, "run_id", None)
    task_id = args.task_id
    evidence_path = args.evidence_path

    devflow = get_devflow_dir(target)
    if not is_initialized(target):
        print("Hata: .devflow/ başlatılmamış.", file=sys.stderr)
        sys.exit(4)

    project_data = read_json(devflow / "project.json")
    run_id = project_data.get("current_run_id")
    if not run_id:
        print("Hata: Aktif run yok.", file=sys.stderr)
        sys.exit(4)

    if run_id_override and run_id_override != run_id:
        print(
            f"Hata: --run-id '{run_id_override}' aktif run '{run_id}' ile eşleşmiyor. "
            "Yalnızca aktif/current run için work-product evidence kaydedilebilir.",
            file=sys.stderr,
        )
        sys.exit(WORK_PRODUCT_GATE_EXIT_CODE)

    run_file = devflow / "runs" / f"{run_id}.json"
    if not run_file.exists():
        print(f"Hata: Run state dosyası bulunamadı: {run_file}", file=sys.stderr)
        sys.exit(4)

    run_data = read_json(run_file)

    tasks = run_data.get("tasks", [])
    task = next((t for t in tasks if t["id"] == task_id), None)
    if task is None:
        print(
            f"Hata: Task '{task_id}' aktif run '{run_id}' içinde bulunamadı.",
            file=sys.stderr,
        )
        sys.exit(WORK_PRODUCT_GATE_EXIT_CODE)

    task_type = task.get("task_type", "")
    if task_type not in WORK_PRODUCT_REQUIRED_TASK_TYPES:
        print(
            f"Hata: Task '{task_id}' türü '{task_type}' work-product evidence gerektirmiyor. "
            f"Yalnızca {sorted(WORK_PRODUCT_REQUIRED_TASK_TYPES)} türleri desteklenir.",
            file=sys.stderr,
        )
        sys.exit(WORK_PRODUCT_GATE_EXIT_CODE)

    path_ok, path_err = validate_work_product_evidence_path(target, task_type, evidence_path)
    if not path_ok:
        print(f"Hata: {path_err}", file=sys.stderr)
        sys.exit(WORK_PRODUCT_GATE_EXIT_CODE)

    if not is_path_git_worktree_change(target, evidence_path):
        print(
            f"Hata: '{evidence_path}' dosyası target worktree'de aktif Git değişikliği olarak "
            "görünmüyor (modified, staged veya untracked olmalıdır). "
            "'git status' çıktısında bu dosya bulunmuyor.",
            file=sys.stderr,
        )
        sys.exit(WORK_PRODUCT_GATE_EXIT_CODE)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    run_data.setdefault("work_product_evidence", {})[task_id] = {
        "task_type": task_type,
        "evidence_path": evidence_path,
        "recorded_at": now,
        "git_change_verified_at_record_time": True,
    }

    atomic_write_json(run_file, run_data)

    print(f"Work-product kanıtı kaydedildi: {task_id} [{task_type.upper()}]")
    print(f"  run_id: {run_id}")
    print(f"  task_id: {task_id}")
    print(f"  task_type: {task_type}")
    print(f"  evidence_path: {evidence_path}")
    print(f"  git_change_verified: True")
    print(
        "  SINIR: Bu gate yerel work-product varlığını doğrular. "
        "Belirli bir agent session'a causal attribution iddiası taşımaz."
    )
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

    raw_events, _delegation_status = load_delegation_events(devflow)
    # Filter to valid events (schema + run_id validation) before projecting.
    # Pass None when the directory is absent so build_run_report can distinguish
    # "hook not configured" (unavailable) from "hook ran but no subagent started" (not_observed).
    if _delegation_status == "unavailable":
        events_arg = None
    else:
        events_arg = [e for e in raw_events if _is_valid_delegation_event(e, run_id)]
    report = build_run_report(run_data, run_id, delegation_events=events_arg, target=target)

    reports_dir = devflow / "reports"
    reports_dir.mkdir(exist_ok=True)
    report_path = reports_dir / f"{run_id}-report.json"
    atomic_write_json(report_path, report)

    # Write canonical Markdown scorecard
    scorecard_path = reports_dir / f"{run_id}-scorecard.md"
    delegation = report["delegation_evidence"]
    sec_app = report.get("security_applicability", {})
    sec_required = sec_app.get("security_review_required", True)
    sec_status = sec_app.get("security_review_status", "pending")
    sec_satisfied = sec_app.get("security_gate_satisfied", False)
    sec_reason = sec_app.get("security_applicability_reason", "explicit_security_signal")
    sec_evidence = sec_app.get("security_evidence") or {}
    sec_verdict = sec_evidence.get("verdict", "")
    sec_max_severity = sec_evidence.get("max_severity", "")
    sec_evidence_path = sec_evidence.get("evidence_path", "")
    sec_evidence_provenance = sec_evidence.get("provenance", "")

    if not sec_required:
        security_gate_lines = [
            f"- security_review_required: {sec_required}",
            f"- security_review_status: {sec_status}",
            f"- security_gate_satisfied: {sec_satisfied}",
            f"- security_applicability_reason: {sec_reason}",
            "- NOTE: Security review not applicable for this deterministic low-risk profile.",
            "  Security gate satisfied: yes",
            "  This is NOT a claim that a Security Red Team session occurred.",
        ]
    elif sec_evidence:
        security_gate_lines = [
            f"- security_review_required: {sec_required}",
            f"- security_review_status: {sec_status}",
            f"- security_gate_satisfied: {sec_satisfied}",
            f"- security_applicability_reason: {sec_reason}",
            f"- evidence_verdict: {sec_verdict}",
            f"- evidence_max_severity: {sec_max_severity}",
            f"- evidence_path: {sec_evidence_path}",
            f"- evidence_provenance: {sec_evidence_provenance or 'generated_in_run'}",
            "- NOTE: Security evidence is a local artifact generated within this run.",
            "  Native lifecycle event observation (if any) does not constitute",
            "  causal binding to this specific evidence artifact or Security Red Team session.",
        ]
    else:
        security_gate_lines = [
            f"- security_review_required: {sec_required}",
            f"- security_review_status: {sec_status}",
            f"- security_gate_satisfied: {sec_satisfied}",
            f"- security_applicability_reason: {sec_reason}",
        ]

    contract_app = report.get("contract_applicability", {})
    cont_required = contract_app.get("contract_required", False)
    cont_status = contract_app.get("contract_status", "not_applicable")
    cont_satisfied = contract_app.get("contract_gate_satisfied", True)
    cont_evidence = contract_app.get("contract_evidence") or {}
    cont_evidence_path = cont_evidence.get("evidence_path", "")
    cont_evidence_provenance = cont_evidence.get("provenance", "")

    if not cont_required:
        contract_gate_lines = [
            f"- contract_required: {cont_required}",
            f"- contract_status: {cont_status}",
            f"- contract_gate_satisfied: {cont_satisfied}",
            "- NOTE: Contract gate not applicable for this delivery type.",
            "  Contract gate satisfied: yes",
            "  This is NOT a claim that a Contract Broker session occurred.",
        ]
    elif cont_evidence:
        contract_gate_lines = [
            f"- contract_required: {cont_required}",
            f"- contract_status: {cont_status}",
            f"- contract_gate_satisfied: {cont_satisfied}",
            f"- evidence_path: {cont_evidence_path}",
            f"- evidence_provenance: {cont_evidence_provenance or 'generated_in_run'}",
            "- NOTE: Contract evidence is a local artifact generated within this run.",
            "  This is NOT a claim of causal binding to a specific Contract Broker session.",
        ]
    else:
        contract_gate_lines = [
            f"- contract_required: {cont_required}",
            f"- contract_status: {cont_status}",
            f"- contract_gate_satisfied: {cont_satisfied}",
        ]

    wp_gate = report.get("work_product_gate", {})
    wp_required = wp_gate.get("required", False)
    wp_status = wp_gate.get("status", "not_applicable")
    wp_satisfied = wp_gate.get("gate_satisfied", True)
    wp_tasks = wp_gate.get("tasks", [])
    wp_limitation = wp_gate.get("limitation_note", "")

    wp_gate_lines = [
        f"- required: {wp_required}",
        f"- status: {wp_status}",
        f"- gate_satisfied: {wp_satisfied}",
    ]
    for _wpt in wp_tasks:
        _wpt_id = _wpt.get("task_id", "")
        _wpt_type = _wpt.get("task_type", "")
        _wpt_ev = _wpt.get("evidence_path")
        _wpt_git = _wpt.get("git_change_active")
        _wpt_recorded = _wpt.get("evidence_recorded", False)
        if _wpt_recorded:
            _git_label = f"git_change_active={_wpt_git}" if _wpt_git is not None else "git_change_active=not_checked"
            wp_gate_lines.append(
                f"- task {_wpt_id} ({_wpt_type}): evidence_path={_wpt_ev} [{_git_label}]"
            )
        else:
            wp_gate_lines.append(
                f"- task {_wpt_id} ({_wpt_type}): evidence_recorded=False [MISSING]"
            )
    if wp_required:
        wp_gate_lines.append(
            "- NOTE: This is NOT a claim of causal attribution to a specific agent session."
        )
        wp_gate_lines.append(f"- LIMITATION: {wp_limitation}")

    scorecard_lines = [
        f"# DevFlow Scorecard: {run_id}",
        "",
        f"**objective:** {report.get('objective', '')[:120]}",
        f"**execution_mode:** {report.get('execution_mode', '')}",
        f"**technical_readiness:** {report.get('technical_readiness', '')}",
        f"**status:** {report.get('status', '')}",
        f"**merge_recommendation:** {report.get('merge_recommendation', '')}",
        "",
        "## Security Gate",
    ] + security_gate_lines + [
        "",
        "## Contract Gate",
    ] + contract_gate_lines + [
        "",
        "## Work Product Gate",
    ] + wp_gate_lines + [
        "",
        "## Delegation Evidence",
        f"- agent_teams_requested: {delegation.get('agent_teams_requested')}",
        f"- native_delegation_observed: {delegation.get('native_delegation_observed')}",
        f"- observed_delegation_count: {delegation.get('observed_delegation_count')}",
        f"- delegation_evidence_status: {delegation.get('delegation_evidence_status')}",
        f"- observed_agent_types: {delegation.get('observed_agent_types', [])}",
        f"- unattributed_event_count: {delegation.get('unattributed_event_count', 0)}",
        "",
        "## Limitations",
        delegation.get("limitation_note", ""),
        "",
        "## Human Approval Required",
    ] + [f"- {item}" for item in report.get("human_approval_required", [])] + [
        "",
        f"*generated_at: {report.get('report_generated_at', '')}*",
    ]
    scorecard_path.write_text("\n".join(scorecard_lines) + "\n", encoding="utf-8")

    # Authoritative state writeback — all derived fields from single projection, atomically.
    # security_review_required and security_applicability_reason are written at
    # generate-task-graph time and are preserved here without override.
    now_updated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    run_data["technical_readiness"] = report["technical_readiness"]
    run_data["status"] = report["status"]
    run_data["merge_recommendation"] = report["merge_recommendation"]
    run_data["security_review_status"] = sec_app.get("security_review_status")
    run_data["security_gate_satisfied"] = sec_app.get("security_gate_satisfied")
    run_data["contract_status"] = contract_app.get("contract_status")
    run_data["contract_gate_satisfied"] = contract_app.get("contract_gate_satisfied")
    run_data["native_delegation_observed"] = delegation["native_delegation_observed"]
    run_data["observed_delegation_count"] = delegation["observed_delegation_count"]
    run_data["delegation_evidence_status"] = delegation["delegation_evidence_status"]
    run_data["observed_agent_types"] = delegation["observed_agent_types"]
    run_data["unattributed_event_count"] = delegation["unattributed_event_count"]
    run_data["work_product_gate_status"] = wp_gate.get("status")
    run_data["work_product_gate_satisfied"] = wp_gate.get("gate_satisfied")
    run_data["updated_at"] = now_updated

    # Add canonical artifact paths to state.artifacts (no duplicates)
    report_artifact = f".devflow/reports/{run_id}-report.json"
    scorecard_artifact = f".devflow/reports/{run_id}-scorecard.md"
    existing_artifacts = run_data.get("artifacts", [])
    for art in [report_artifact, scorecard_artifact]:
        if art not in existing_artifacts:
            existing_artifacts.append(art)
    run_data["artifacts"] = existing_artifacts

    atomic_write_json(run_file, run_data)

    summary = report["task_graph_summary"]
    delegation = report["delegation_evidence"]
    provenance = report["evidence_provenance"]
    print(f"Run raporu: {run_id}")
    print(f"  objective: {report['objective'][:80]}")
    print(f"  execution_mode: {report['execution_mode']}")
    print(f"  tasks: {summary['total']} toplam, "
          f"{summary['completed_or_verified']} tamamlandı, "
          f"{summary['verified']} doğrulandı")
    print(f"  qa_result: {report['qa_result']}")
    print(f"  delegation_evidence_status: {delegation['delegation_evidence_status']}")
    print(f"  native_delegation_observed: {delegation['native_delegation_observed']}")
    print(f"  agent_teams_requested: {delegation['agent_teams_requested']}")
    print(f"  merge_recommendation: {report['merge_recommendation']}")
    print()
    print(f"  NOT (delegation): {delegation['boundary_note']}")
    print(f"  NOT (human gate): {report['human_approval_required'][0]}")
    print(f"  provenance.acceptance_criteria: {provenance['acceptance_criteria']}")
    print(f"  provenance.human_approval: {provenance['human_approval']}")
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

    p_qa = subparsers.add_parser(
        "record-qa-evidence",
        help="QA test sonuçlarını authoritative olarak kaydet ve approval gate'leri güncelle",
    )
    p_qa.add_argument("--target", required=True, help="Target project path")
    p_qa.add_argument("--total", type=int, required=True, help="Toplam test sayısı")
    p_qa.add_argument("--passed", type=int, required=True, help="Geçen test sayısı")
    p_qa.add_argument("--failed", type=int, required=True, help="Başarısız test sayısı")
    p_qa.add_argument(
        "--exit-code",
        type=int,
        required=True,
        dest="exit_code",
        help="Test runner exit kodu (0 = başarılı)",
    )
    p_qa.add_argument(
        "--evidence-path",
        default=None,
        help="Test kanıtı dosyasına göreli yol (opsiyonel)",
    )
    p_qa.set_defaults(func=cmd_record_qa_evidence)

    p_sec_ev = subparsers.add_parser(
        "record-security-evidence",
        help="Security review kanıtını authoritative olarak kaydet",
    )
    p_sec_ev.add_argument("--target", required=True, help="Target project path")
    p_sec_ev.add_argument(
        "--run-id",
        default=None,
        dest="run_id",
        help="Run ID (varsayılan: aktif/current run)",
    )
    p_sec_ev.add_argument(
        "--verdict",
        required=True,
        choices=sorted(SECURITY_EVIDENCE_VERDICTS),
        help="Security review sonucu (pass veya blocked)",
    )
    p_sec_ev.add_argument(
        "--max-severity",
        required=True,
        choices=sorted(SECURITY_EVIDENCE_SEVERITIES),
        dest="max_severity",
        help=(
            f"Bulunan maksimum severity "
            f"(pass ile: none/low; blocked ile: medium/high/critical)"
        ),
    )
    p_sec_ev.add_argument(
        "--evidence-path",
        required=True,
        dest="evidence_path",
        help=(
            f"Security raporu dosyasına göreli yol "
            f"(yalnızca '{SECURITY_EVIDENCE_PATH_PREFIX}' altında)"
        ),
    )
    p_sec_ev.set_defaults(func=cmd_record_security_evidence)

    p_cont_ev = subparsers.add_parser(
        "record-contract-evidence",
        help="Contract kanıtını authoritative olarak kaydet (yalnızca new_feature runs)",
    )
    p_cont_ev.add_argument("--target", required=True, help="Target project path")
    p_cont_ev.add_argument(
        "--run-id",
        default=None,
        dest="run_id",
        help="Run ID (aktif run ile eşleşmeli; varsayılan: aktif run)",
    )
    p_cont_ev.add_argument(
        "--evidence-path",
        required=True,
        dest="evidence_path",
        help=(
            "docs/quality/contracts/ altında bir dosyaya repository-relative göreli yol. "
            "Mutlak yol, '..', wildcard, .devflow/ ve .claude/ yasak."
        ),
    )
    p_cont_ev.set_defaults(func=cmd_record_contract_evidence)

    p_wp_ev = subparsers.add_parser(
        "record-work-product-evidence",
        help=(
            "Implementation veya QA görevi için doğrulanabilir work-product kanıtı kaydet. "
            "Kanıt yolu aktif Git worktree değişikliği olmalıdır."
        ),
    )
    p_wp_ev.add_argument("--target", required=True, help="Target project path")
    p_wp_ev.add_argument(
        "--run-id",
        default=None,
        dest="run_id",
        help="Run ID (aktif run ile eşleşmeli; varsayılan: aktif run)",
    )
    p_wp_ev.add_argument(
        "--task-id",
        required=True,
        dest="task_id",
        help="Kanıt kaydedilecek implementation veya QA task ID",
    )
    p_wp_ev.add_argument(
        "--evidence-path",
        required=True,
        dest="evidence_path",
        help=(
            "Target içinde kaynak kodu veya test dosyasına repository-relative göreli yol. "
            f"Implementation için: {', '.join(sorted(IMPLEMENTATION_EVIDENCE_PREFIXES))} — "
            f"QA için: {', '.join(sorted(QA_EVIDENCE_PREFIXES))}. "
            "Aktif Git worktree değişikliği olmalıdır (modified, staged veya untracked). "
            ".devflow/, docs/, lockfile, credential, migration kabul edilmez."
        ),
    )
    p_wp_ev.set_defaults(func=cmd_record_work_product_evidence)

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
