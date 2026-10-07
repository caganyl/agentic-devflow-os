#!/usr/bin/env python3
"""
DevFlow architecture scanner (stdlib only, read-only).

Extracts the architecture of a .NET backend and/or a Next.js / React frontend
deterministically, so an agent does not have to read the whole repository:

  python3 devflow_arch_scan.py --root PATH            # JSON scan report on stdout
  python3 devflow_arch_scan.py --root PATH --check docs/architecture/profile/architecture-profile.json
                                                      # rule check, exit 1 on violations

The scan reports facts with evidence paths (project references, packages,
folder structure, API style, router, state libraries...) plus a few
representative sample files per layer. Inferences are labelled as such; a
human confirms them in the architecture profile before agents treat them as
rules. The script never writes files.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath

SCHEMA_VERSION = 1

EXCLUDED_DIRS = {
    ".git", "bin", "obj", "node_modules", ".next", "dist", "build", "out",
    "coverage", ".devflow", ".devflow-worktrees", "packages", ".vs", ".idea",
    ".vscode", ".turbo", ".cache", "TestResults", "wwwroot",
}
MAX_SOURCE_FILES = 6000
SAMPLE_MIN_BYTES = 300
SAMPLE_MAX_BYTES = 8000

LAYER_TOKENS = [
    ("tests", ("tests", "test", "unittests", "integrationtests", "functionaltests", "architecturetests", "specs")),
    ("domain", ("domain", "entities", "model", "models")),
    ("application", ("application", "usecases", "services", "app")),
    ("infrastructure", ("infrastructure", "infra", "persistence", "data", "dataaccess", "repositories")),
    ("presentation", ("api", "webapi", "web", "host", "server", "presentation", "gateway", "functions", "grpc")),
    ("shared", ("contracts", "shared", "common", "sharedkernel", "abstractions", "core.shared", "dtos")),
    ("core", ("core",)),
]

# Canonical Clean Architecture dependency direction, used only as a proposal.
PROPOSED_ALLOWED_REFERENCES = {
    "domain": ["shared"],
    "core": ["shared"],
    "application": ["domain", "core", "shared"],
    "infrastructure": ["application", "domain", "core", "shared"],
    "presentation": ["application", "infrastructure", "domain", "core", "shared"],
    "shared": [],
    "tests": ["*"],
}

DOTNET_PACKAGE_SIGNALS = {
    "cqrs_mediator": ("MediatR", "Mediator.SourceGenerator", "Mediator.Abstractions", "WolverineFx", "Brighter"),
    "ef_core": ("Microsoft.EntityFrameworkCore",),
    "dapper": ("Dapper",),
    "fluent_validation": ("FluentValidation",),
    "mapping": ("AutoMapper", "Mapster", "Riok.Mapperly"),
    "arch_tests": ("NetArchTest.Rules", "TngTech.ArchUnitNET", "ArchUnitNET"),
    "test_frameworks": ("xunit", "NUnit", "MSTest.TestFramework", "TUnit"),
    "testcontainers": ("Testcontainers",),
    "result_pattern": ("ErrorOr", "FluentResults", "Ardalis.Result", "OneOf"),
}

FRONTEND_SIGNALS = {
    "state": ("@reduxjs/toolkit", "redux", "zustand", "jotai", "mobx", "recoil", "valtio", "xstate"),
    "data_fetching": ("@tanstack/react-query", "react-query", "swr", "@apollo/client", "urql", "@trpc/client"),
    "ui": ("@mui/material", "antd", "@chakra-ui/react", "tailwindcss", "@radix-ui/react-slot",
           "@mantine/core", "react-bootstrap", "styled-components", "@emotion/react"),
    "forms": ("react-hook-form", "formik", "@tanstack/react-form"),
    "validation": ("zod", "yup", "valibot", "joi"),
    "testing": ("vitest", "jest", "@testing-library/react", "@playwright/test", "cypress"),
    "api_client": ("axios", "ky", "openapi-fetch", "openapi-typescript", "orval", "nswag",
                   "@hey-api/openapi-ts", "openapi-typescript-codegen"),
    "i18n": ("next-intl", "react-i18next", "i18next", "next-i18next"),
}

IMPORT_RE = re.compile(r"""(?:import\s[^'"]*?from\s*|import\s*\(\s*|require\s*\(\s*|export\s[^'"]*?from\s*)['"]([^'"]+)['"]""")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def walk(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDED_DIRS and not d.startswith(".devflow"))
        for name in sorted(filenames):
            yield Path(dirpath) / name


def read_text(path: Path, limit: int = 400_000) -> str:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            return fh.read(limit)
    except OSError:
        return ""


def load_jsonc(path: Path):
    """Parse JSON that may contain // and /* */ comments and trailing commas."""
    text = read_text(path)
    out, i, in_str, n = [], 0, False, len(text)
    while i < n:
        ch = text[i]
        if in_str:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1]); i += 2; continue
            if ch == '"':
                in_str = False
            i += 1; continue
        if ch == '"':
            in_str = True; out.append(ch); i += 1; continue
        if text.startswith("//", i):
            j = text.find("\n", i); i = n if j == -1 else j; continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2); i = n if j == -1 else j + 2; continue
        out.append(ch); i += 1
    cleaned = re.sub(r",(\s*[}\]])", r"\1", "".join(out))
    try:
        return json.loads(cleaned)
    except ValueError:
        return None


def classify_layer(project_name: str, is_test: bool) -> str:
    if is_test:
        return "tests"
    tokens = [t.lower() for t in project_name.split(".")]
    for token in reversed(tokens):
        for layer, names in LAYER_TOKENS:
            if token in names:
                return layer
    return "unknown"


# ---------------------------------------------------------------------------
# .NET
# ---------------------------------------------------------------------------

def parse_csproj(path: Path) -> dict:
    info = {"sdk": "", "target_frameworks": [], "output_type": "", "packages": [],
            "project_references": [], "is_test_flag": False, "nullable": "", "warnings_as_errors": False}
    try:
        tree = ET.parse(path)
    except (ET.ParseError, OSError):
        return info
    root = tree.getroot()
    info["sdk"] = root.attrib.get("Sdk", "")
    for el in root.iter():
        tag = el.tag.split("}")[-1]
        text = (el.text or "").strip()
        if tag in ("TargetFramework", "TargetFrameworks") and text:
            info["target_frameworks"] += [t for t in text.split(";") if t]
        elif tag == "OutputType" and text:
            info["output_type"] = text
        elif tag == "IsTestProject" and text.lower() == "true":
            info["is_test_flag"] = True
        elif tag == "Nullable" and text:
            info["nullable"] = text
        elif tag == "TreatWarningsAsErrors" and text.lower() == "true":
            info["warnings_as_errors"] = True
        elif tag == "PackageReference":
            name = el.attrib.get("Include") or el.attrib.get("Update")
            if name:
                info["packages"].append(name)
        elif tag == "ProjectReference":
            inc = el.attrib.get("Include", "")
            if inc:
                info["project_references"].append(PurePosixPath(inc.replace("\\", "/")).stem)
    return info


def scan_dotnet(root: Path, files: list[Path]) -> dict | None:
    csprojs = [f for f in files if f.suffix == ".csproj"]
    if not csprojs:
        return None
    solutions = [rel(root, f) for f in files if f.suffix in (".sln", ".slnx")]
    projects, by_name = [], {}
    for path in csprojs:
        info = parse_csproj(path)
        name = path.stem
        is_test = info["is_test_flag"] or any(
            p.lower() in ("microsoft.net.test.sdk",) or p.lower().startswith(("xunit", "nunit", "mstest"))
            for p in info["packages"]) or name.lower().endswith((".tests", ".test", "tests"))
        project = {
            "name": name,
            "path": rel(root, path),
            "dir": rel(root, path.parent) if path.parent != root else ".",
            "sdk": info["sdk"],
            "target_frameworks": sorted(set(info["target_frameworks"])),
            "output_type": info["output_type"],
            "is_test": is_test,
            "layer": classify_layer(name, is_test),
            "packages": sorted(set(info["packages"])),
            "project_references": sorted(set(info["project_references"])),
        }
        projects.append(project)
        by_name[name] = project

    cs_files = [f for f in files if f.suffix == ".cs"][:MAX_SOURCE_FILES]
    evidence: dict[str, list[str]] = {}

    def note(key: str, path: Path):
        lst = evidence.setdefault(key, [])
        if len(lst) < 5:
            lst.append(rel(root, path))

    controllers = minimal = handlers = dbcontexts = repositories = 0
    for f in cs_files:
        text = read_text(f, 60_000)
        if re.search(r":\s*(Controller|ControllerBase)\b", text) or "[ApiController]" in text:
            controllers += 1; note("controllers", f)
        if re.search(r"\.Map(Get|Post|Put|Patch|Delete|Group)\s*\(", text):
            minimal += 1; note("minimal_api", f)
        if re.search(r"IRequestHandler<|ICommandHandler<|IQueryHandler<", text):
            handlers += 1; note("handlers", f)
        if re.search(r":\s*(Identity)?DbContext\b", text):
            dbcontexts += 1; note("dbcontext", f)
        if f.stem.endswith("Repository") or re.search(r"\binterface\s+I\w*Repository\b", text):
            repositories += 1; note("repositories", f)

    all_packages = {p for pr in projects for p in pr["packages"]}

    def has_pkg(names):
        return sorted({p for p in all_packages for n in names if p == n or p.startswith(n + ".")})

    api_style = "unknown"
    if controllers and minimal:
        api_style = "mixed"
    elif controllers:
        api_style = "controllers"
    elif minimal:
        api_style = "minimal_api"

    folder_names = {p.name.lower() for f in cs_files for p in f.relative_to(root).parents}
    vertical_slice = "features" in folder_names and bool({"commands", "queries"} & folder_names or handlers)

    patterns = {
        "api_style": api_style,
        "cqrs_mediator": bool(has_pkg(DOTNET_PACKAGE_SIGNALS["cqrs_mediator"]) or handlers),
        "ef_core": bool(has_pkg(DOTNET_PACKAGE_SIGNALS["ef_core"]) or dbcontexts),
        "dapper": bool(has_pkg(DOTNET_PACKAGE_SIGNALS["dapper"])),
        "repository_pattern": repositories > 0,
        "fluent_validation": bool(has_pkg(DOTNET_PACKAGE_SIGNALS["fluent_validation"])),
        "mapping": has_pkg(DOTNET_PACKAGE_SIGNALS["mapping"]),
        "result_pattern": has_pkg(DOTNET_PACKAGE_SIGNALS["result_pattern"]),
        "vertical_slice_folders": vertical_slice,
        "arch_tests": has_pkg(DOTNET_PACKAGE_SIGNALS["arch_tests"]),
        "test_frameworks": has_pkg(DOTNET_PACKAGE_SIGNALS["test_frameworks"]),
        "testcontainers": bool(has_pkg(DOTNET_PACKAGE_SIGNALS["testcontainers"])),
    }

    names = {f.name for f in files}
    dbp = [f for f in files if f.name == "Directory.Build.props"]
    build_settings = {
        "directory_build_props": bool(dbp),
        "central_package_management": "Directory.Packages.props" in names,
        "editorconfig": ".editorconfig" in names,
        "treat_warnings_as_errors": any("<TreatWarningsAsErrors>true" in read_text(f) for f in dbp)
        or any(parse_csproj(p)["warnings_as_errors"] for p in csprojs[:50]),
        "nullable_enabled": any("<Nullable>enable" in read_text(f) for f in dbp + csprojs[:50]),
    }

    layer_graph: dict[str, set[str]] = {}
    for pr in projects:
        for ref in pr["project_references"]:
            target = by_name.get(ref)
            if target:
                layer_graph.setdefault(pr["layer"], set()).add(target["layer"])

    findings = []
    for violation in reference_violations(projects, by_name, PROPOSED_ALLOWED_REFERENCES):
        findings.append({"severity": "warning", "message": "Clean Architecture yönüne aykırı referans (öneri kuralına göre): " + violation})
    unknown = [p["name"] for p in projects if p["layer"] == "unknown"]
    if unknown:
        findings.append({"severity": "info", "message": "Katmanı isimden çıkarılamayan projeler; profilde elle eşleyin: " + ", ".join(unknown)})
    if not patterns["arch_tests"]:
        findings.append({"severity": "info", "message": "Mimari test paketi yok (NetArchTest/ArchUnitNET); onaylı kurallar teste çevrilmeli."})

    return {
        "solutions": solutions,
        "projects": projects,
        "layer_graph": {k: sorted(v) for k, v in sorted(layer_graph.items())},
        "patterns": patterns,
        "build_settings": build_settings,
        "evidence": evidence,
        "findings": findings,
        "samples": dotnet_samples(root, projects, cs_files),
    }


def reference_violations(projects, by_name, allowed, layer_overrides=None) -> list[str]:
    layer_overrides = layer_overrides or {}
    out = []
    for pr in projects:
        src_layer = layer_overrides.get(pr["name"], pr["layer"])
        allowed_targets = allowed.get(src_layer)
        if allowed_targets is None or "*" in allowed_targets:
            continue
        for ref in pr["project_references"]:
            target = by_name.get(ref)
            if not target:
                continue
            dst_layer = layer_overrides.get(target["name"], target["layer"])
            if dst_layer == src_layer or dst_layer == "unknown":
                continue
            if dst_layer not in allowed_targets:
                out.append(f"{pr['name']} ({src_layer}) -> {target['name']} ({dst_layer})")
    return out


def pick_samples(root: Path, candidates: list[Path], limit: int = 2) -> list[str]:
    sized = []
    for f in candidates:
        try:
            size = f.stat().st_size
        except OSError:
            continue
        if SAMPLE_MIN_BYTES <= size <= SAMPLE_MAX_BYTES:
            sized.append((abs(size - 2500), rel(root, f)))
    return [p for _, p in sorted(sized)[:limit]]


def dotnet_samples(root: Path, projects, cs_files) -> dict:
    samples = {}
    for pr in projects:
        if pr["layer"] == "tests":
            continue
        base = root / pr["dir"] if pr["dir"] != "." else root
        files = [f for f in cs_files if base in f.parents]
        kinds = {
            "endpoint": [f for f in files if f.stem.endswith(("Controller", "Endpoint", "Endpoints"))],
            "handler": [f for f in files if f.stem.endswith(("Handler", "Command", "Query"))],
            "entity_or_service": [f for f in files if f.parent.name.lower() in ("entities", "services", "aggregates", "models")],
            "configuration": [f for f in files if f.stem.endswith(("Configuration", "DbContext", "DependencyInjection", "ServiceCollectionExtensions"))],
        }
        picked = {k: pick_samples(root, v, 1) for k, v in kinds.items()}
        picked = {k: v for k, v in picked.items() if v}
        if picked:
            samples[pr["name"]] = picked
    return samples


# ---------------------------------------------------------------------------
# Frontend (Next.js / React)
# ---------------------------------------------------------------------------

def scan_frontend(root: Path, files: list[Path]) -> list[dict]:
    apps = []
    for pkg in [f for f in files if f.name == "package.json"]:
        data = load_jsonc(pkg) or {}
        deps = {**(data.get("dependencies") or {}), **(data.get("devDependencies") or {})}
        if "react" not in deps and "next" not in deps:
            continue
        base = pkg.parent
        if "next" in deps:
            framework = "next"
        elif "vite" in deps:
            framework = "vite"
        elif "react-scripts" in deps:
            framework = "cra"
        else:
            framework = "react"
        src = base / "src" if (base / "src").is_dir() else base
        router = "none"
        if framework == "next":
            has_app = (base / "app").is_dir() or (base / "src" / "app").is_dir()
            has_pages = (base / "pages").is_dir() or (base / "src" / "pages").is_dir()
            router = "both" if has_app and has_pages else "app" if has_app else "pages" if has_pages else "none"
        top_dirs = sorted(d.name for d in src.iterdir() if d.is_dir() and d.name not in EXCLUDED_DIRS
                          and not d.name.startswith(".")) if src.is_dir() else []
        dirset = set(top_dirs)
        if {"features", "entities", "shared"} <= dirset or {"features", "widgets", "shared"} <= dirset:
            structure = "feature_sliced_design"
        elif "features" in dirset or "modules" in dirset:
            structure = "feature_based"
        elif "components" in dirset:
            structure = "type_based"
        else:
            structure = "unknown"

        def present(group):
            return sorted(n for n in FRONTEND_SIGNALS[group] if n in deps)

        aliases = {}
        tsconfig = base / "tsconfig.json"
        if tsconfig.is_file():
            ts = load_jsonc(tsconfig) or {}
            paths = (ts.get("compilerOptions") or {}).get("paths") or {}
            aliases = {k: v for k, v in paths.items() if isinstance(v, list)}
        eslint_files = sorted(f.name for f in base.iterdir() if f.is_file() and f.name.startswith((".eslintrc", "eslint.config")))
        lint = {
            "eslint_config": eslint_files,
            "boundaries_plugin": "eslint-plugin-boundaries" in deps,
            "dependency_cruiser": "dependency-cruiser" in deps,
            "prettier": "prettier" in deps,
        }
        features_dir = None
        for cand in ("src/features", "features", "src/modules", "modules"):
            if (base / cand).is_dir():
                features_dir = rel(root, base / cand)
                break
        app_files = [f for f in files if base in f.parents and f.suffix in (".ts", ".tsx", ".js", ".jsx")
                     and "node_modules" not in f.parts]
        apps.append({
            "path": rel(root, base) if base != root else ".",
            "framework": framework,
            "versions": {k: deps[k] for k in ("next", "react", "typescript") if k in deps},
            "router": router,
            "typescript": tsconfig.is_file() or "typescript" in deps,
            "src_dir": (base / "src").is_dir(),
            "top_level_dirs": top_dirs,
            "structure_style": structure,
            "features_dir": features_dir,
            "import_aliases": aliases,
            "lint": lint,
            **{group: present(group) for group in FRONTEND_SIGNALS},
            "samples": frontend_samples(root, base, app_files),
        })
    return apps


def frontend_samples(root: Path, base: Path, app_files: list[Path]) -> dict:
    kinds = {
        "page_or_route": [f for f in app_files if f.stem in ("page", "layout") or "pages" in f.parts or "routes" in f.parts],
        "component": [f for f in app_files if "components" in f.parts and f.suffix in (".tsx", ".jsx")],
        "hook": [f for f in app_files if f.stem.startswith("use")],
        "api_or_service": [f for f in app_files if {"api", "services", "lib"} & set(f.parts) and f.suffix in (".ts", ".js")],
        "state": [f for f in app_files if {"store", "stores", "state", "slices"} & set(f.parts)],
    }
    out = {k: pick_samples(root, v, 1) for k, v in kinds.items()}
    return {k: v for k, v in out.items() if v}


def resolve_import(spec: str, importer: Path, app_base: Path, aliases: dict) -> Path | None:
    if spec.startswith("."):
        return (importer.parent / spec).resolve()
    for alias, targets in aliases.items():
        prefix = alias[:-1] if alias.endswith("*") else alias
        if targets and spec.startswith(prefix):
            target = targets[0]
            tprefix = target[:-1] if target.endswith("*") else target
            return (app_base / (tprefix + spec[len(prefix):])).resolve()
    return None


def cross_feature_violations(root: Path, app: dict, features_dir: str) -> list[str]:
    base = (root / app["path"]).resolve()
    fdir = (root / features_dir).resolve()
    if not fdir.is_dir():
        return []
    out = []
    for dirpath, dirnames, filenames in os.walk(fdir):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]
        for name in filenames:
            f = Path(dirpath) / name
            if f.suffix not in (".ts", ".tsx", ".js", ".jsx"):
                continue
            own = f.resolve().relative_to(fdir).parts[0]
            for spec in IMPORT_RE.findall(read_text(f, 200_000)):
                target = resolve_import(spec, f.resolve(), base, app.get("import_aliases") or {})
                if target is None:
                    continue
                try:
                    parts = target.relative_to(fdir).parts
                except ValueError:
                    continue
                if not parts or parts[0] == own:
                    continue
                rest = [p for p in parts[1:]]
                if not rest or (len(rest) == 1 and PurePosixPath(rest[0]).stem == "index"):
                    continue
                out.append(f"{rel(root, f)} -> '{spec}' ({parts[0]} feature'ının iç dosyası; public index üzerinden import edin)")
    return out


# ---------------------------------------------------------------------------
# entry points
# ---------------------------------------------------------------------------

def scan(root: Path) -> dict:
    files = list(walk(root))
    dotnet = scan_dotnet(root, files)
    frontend = scan_frontend(root, files)
    state = "brownfield" if (dotnet or frontend) else "empty"
    proposed = {}
    if dotnet:
        proposed["dotnet"] = {
            "layer_by_project": {p["name"]: p["layer"] for p in dotnet["projects"]},
            "allowed_references": PROPOSED_ALLOWED_REFERENCES,
        }
    if frontend:
        proposed["frontend"] = [
            {"app": a["path"], "features_dir": a["features_dir"],
             "forbid_cross_feature_imports": bool(a["features_dir"])}
            for a in frontend
        ]
    return {
        "schema_version": SCHEMA_VERSION,
        "project_state": state,
        "dotnet": dotnet,
        "frontend": frontend,
        "proposed_rules": proposed,
        "note": "Bu rapor gözlemdir. 'proposed_rules' bir öneridir; insan onaylayıp profile yazmadan kural sayılmaz.",
    }


def check(root: Path, profile_path: Path) -> tuple[list[str], dict]:
    profile = load_jsonc(profile_path)
    if not isinstance(profile, dict):
        return [f"Profil okunamadı: {profile_path}"], {}
    rules = profile.get("rules") or {}
    files = list(walk(root))
    violations = []
    d_rules = rules.get("dotnet") or {}
    if d_rules:
        dotnet = scan_dotnet(root, files)
        if dotnet:
            by_name = {p["name"]: p for p in dotnet["projects"]}
            for v in reference_violations(dotnet["projects"], by_name,
                                          d_rules.get("allowed_references") or {},
                                          d_rules.get("layer_by_project") or {}):
                violations.append("dotnet: yasak proje referansı: " + v)
            known = set((d_rules.get("layer_by_project") or {}).keys())
            if known:
                for p in dotnet["projects"]:
                    if p["name"] not in known:
                        violations.append(f"dotnet: profilde olmayan yeni proje: {p['name']} ({p['path']}) — katmanı onaylanmalı")
    f_rules = rules.get("frontend") or []
    if f_rules:
        apps = {a["path"]: a for a in scan_frontend(root, files)}
        for rule in f_rules:
            app = apps.get(rule.get("app", "."))
            if app and rule.get("forbid_cross_feature_imports") and rule.get("features_dir"):
                violations += ["frontend: " + v for v in cross_feature_violations(root, app, rule["features_dir"])]
    return violations, profile


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="DevFlow architecture scanner (read-only)")
    parser.add_argument("--root", default=".", help="Taranacak proje kökü")
    parser.add_argument("--check", metavar="PROFILE_JSON", help="Onaylı profile karşı kural kontrolü")
    parser.add_argument("--compact", action="store_true", help="Örnek dosya ve evidence listelerini çıkar")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"Hata: kök bulunamadı: {root}", file=sys.stderr)
        return 2
    if args.check:
        profile_path = Path(args.check)
        if not profile_path.is_absolute():
            profile_path = root / profile_path
        violations, profile = check(root, profile_path)
        status = profile.get("status", "draft") if isinstance(profile, dict) else "unknown"
        known_markers = [m for m in (profile.get("known_deviations") or []) if m] if isinstance(profile, dict) else []
        known = [v for v in violations if any(m in v for m in known_markers)]
        new = [v for v in violations if v not in known]
        result = {"profile_status": status, "violations": new, "known_deviations": known, "ok": not new}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if not new else 1
    report = scan(root)
    if args.compact:
        if report["dotnet"]:
            report["dotnet"].pop("samples", None)
            report["dotnet"].pop("evidence", None)
        for app in report["frontend"]:
            app.pop("samples", None)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
