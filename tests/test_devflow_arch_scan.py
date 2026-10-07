"""Tests for scripts/devflow_arch_scan.py (read-only architecture scanner)."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCANNER = REPO_ROOT / "scripts" / "devflow_arch_scan.py"

BODY = "\n".join(f"    // line {i}" for i in range(80))


def csproj(refs=(), packages=(), sdk="Microsoft.NET.Sdk"):
    items = "".join(f'<ProjectReference Include="..\\{r}\\{r}.csproj" />' for r in refs)
    items += "".join(f'<PackageReference Include="{p}" Version="1.0.0" />' for p in packages)
    return (f'<Project Sdk="{sdk}"><PropertyGroup><TargetFramework>net9.0</TargetFramework>'
            f"</PropertyGroup><ItemGroup>{items}</ItemGroup></Project>")


class ArchScanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def w(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def run_scan(self, *args):
        result = subprocess.run([sys.executable, str(SCANNER), "--root", str(self.root), *args],
                                capture_output=True, text=True)
        return result.returncode, json.loads(result.stdout)

    def build_dotnet(self, domain_refs=()):
        self.w("src/Shop.Domain/Shop.Domain.csproj", csproj(domain_refs))
        self.w("src/Shop.Application/Shop.Application.csproj",
               csproj(["Shop.Domain"], ["MediatR", "FluentValidation"]))
        self.w("src/Shop.Infrastructure/Shop.Infrastructure.csproj",
               csproj(["Shop.Application"], ["Microsoft.EntityFrameworkCore.SqlServer"]))
        self.w("src/Shop.Api/Shop.Api.csproj",
               csproj(["Shop.Application", "Shop.Infrastructure"], sdk="Microsoft.NET.Sdk.Web"))
        self.w("src/Shop.Api/Controllers/OrdersController.cs",
               "[ApiController]\npublic class OrdersController : ControllerBase {\n" + BODY + "\n}\n")
        self.w("src/Shop.Infrastructure/Persistence/ShopDbContext.cs",
               "public class ShopDbContext : DbContext {\n" + BODY + "\n}\n")

    def build_next(self):
        self.w("web/package.json", json.dumps({
            "dependencies": {"next": "16.2.0", "react": "19.0.0", "@tanstack/react-query": "5", "zod": "3"},
            "devDependencies": {"typescript": "5", "vitest": "3"}}))
        self.w("web/tsconfig.json", '{ // c\n "compilerOptions": { "paths": { "@/*": ["./src/*"] }, },\n}')
        self.w("web/src/app/page.tsx", "export default function Page() { return null }\n")
        self.w("web/src/features/orders/index.ts", "export * from './api/orders'\n")
        self.w("web/src/features/orders/api/orders.ts", "export const getOrders = () => 1\n")

    def profile(self, rules):
        self.w("docs/architecture/profile/architecture-profile.json",
               json.dumps({"schema_version": 1, "status": "confirmed", "rules": rules}))

    # -- scan ------------------------------------------------------------

    def test_empty_project(self):
        code, report = self.run_scan()
        self.assertEqual(code, 0)
        self.assertEqual(report["project_state"], "empty")
        self.assertIsNone(report["dotnet"])
        self.assertEqual(report["frontend"], [])

    def test_dotnet_layers_and_patterns(self):
        self.build_dotnet()
        _, report = self.run_scan()
        d = report["dotnet"]
        layers = {p["name"]: p["layer"] for p in d["projects"]}
        self.assertEqual(layers["Shop.Domain"], "domain")
        self.assertEqual(layers["Shop.Application"], "application")
        self.assertEqual(layers["Shop.Infrastructure"], "infrastructure")
        self.assertEqual(layers["Shop.Api"], "presentation")
        self.assertEqual(d["patterns"]["api_style"], "controllers")
        self.assertTrue(d["patterns"]["cqrs_mediator"])
        self.assertTrue(d["patterns"]["ef_core"])
        self.assertTrue(d["patterns"]["fluent_validation"])
        self.assertIn("Shop.Api", d["samples"])

    def test_dotnet_reverse_reference_flagged(self):
        self.build_dotnet(domain_refs=["Shop.Infrastructure"])
        _, report = self.run_scan()
        messages = " ".join(f["message"] for f in report["dotnet"]["findings"])
        self.assertIn("Shop.Domain (domain) -> Shop.Infrastructure (infrastructure)", messages)

    def test_next_app_detected(self):
        self.build_next()
        _, report = self.run_scan()
        app = report["frontend"][0]
        self.assertEqual(app["framework"], "next")
        self.assertEqual(app["router"], "app")
        self.assertEqual(app["structure_style"], "feature_based")
        self.assertEqual(app["import_aliases"], {"@/*": ["./src/*"]})
        self.assertIn("@tanstack/react-query", app["data_fetching"])
        self.assertTrue(report["proposed_rules"]["frontend"][0]["forbid_cross_feature_imports"])

    def test_vite_react_detected(self):
        self.w("client/package.json", json.dumps({"dependencies": {"react": "18"}, "devDependencies": {"vite": "5"}}))
        self.w("client/src/components/Button.tsx", "export const Button = () => null\n")
        _, report = self.run_scan()
        app = report["frontend"][0]
        self.assertEqual(app["framework"], "vite")
        self.assertEqual(app["structure_style"], "type_based")

    # -- check -----------------------------------------------------------

    def test_check_clean_passes(self):
        self.build_dotnet()
        self.profile({"dotnet": {
            "layer_by_project": {"Shop.Domain": "domain", "Shop.Application": "application",
                                 "Shop.Infrastructure": "infrastructure", "Shop.Api": "presentation"},
            "allowed_references": {"domain": [], "application": ["domain"],
                                   "infrastructure": ["application", "domain"],
                                   "presentation": ["application", "infrastructure"]}}})
        code, result = self.run_scan("--check", "docs/architecture/profile/architecture-profile.json")
        self.assertEqual(code, 0, result)
        self.assertTrue(result["ok"])

    def test_check_detects_forbidden_reference_and_new_project(self):
        self.build_dotnet(domain_refs=["Shop.Infrastructure"])
        self.w("src/Shop.Reporting/Shop.Reporting.csproj", csproj())
        self.profile({"dotnet": {
            "layer_by_project": {"Shop.Domain": "domain", "Shop.Application": "application",
                                 "Shop.Infrastructure": "infrastructure", "Shop.Api": "presentation"},
            "allowed_references": {"domain": [], "application": ["domain"],
                                   "infrastructure": ["application", "domain"],
                                   "presentation": ["application", "infrastructure"]}}})
        code, result = self.run_scan("--check", "docs/architecture/profile/architecture-profile.json")
        self.assertEqual(code, 1)
        joined = " ".join(result["violations"])
        self.assertIn("Shop.Domain (domain) -> Shop.Infrastructure", joined)
        self.assertIn("Shop.Reporting", joined)

    def test_check_cross_feature_imports(self):
        self.build_next()
        self.w("web/src/features/cart/Cart.tsx",
               "import { a } from '@/features/orders'\n"
               "import { b } from '@/features/orders/api/orders'\n"
               "import c from '../orders/api/orders'\n"
               "import d from './local'\n")
        self.profile({"frontend": [{"app": "web", "features_dir": "web/src/features",
                                    "forbid_cross_feature_imports": True}]})
        code, result = self.run_scan("--check", "docs/architecture/profile/architecture-profile.json")
        self.assertEqual(code, 1)
        self.assertEqual(len(result["violations"]), 2, result["violations"])

    def test_known_deviation_reported_but_not_failing(self):
        self.build_dotnet(domain_refs=["Shop.Infrastructure"])
        rules = {"dotnet": {
            "layer_by_project": {"Shop.Domain": "domain", "Shop.Application": "application",
                                 "Shop.Infrastructure": "infrastructure", "Shop.Api": "presentation"},
            "allowed_references": {"domain": [], "application": ["domain"],
                                   "infrastructure": ["application", "domain"],
                                   "presentation": ["application", "infrastructure"]}}}
        self.w("docs/architecture/profile/architecture-profile.json", json.dumps({
            "schema_version": 1, "status": "confirmed", "rules": rules,
            "known_deviations": ["Shop.Domain (domain) -> Shop.Infrastructure"]}))
        code, result = self.run_scan("--check", "docs/architecture/profile/architecture-profile.json")
        self.assertEqual(code, 0, result)
        self.assertEqual(len(result["known_deviations"]), 1)

    def test_scanner_writes_nothing(self):
        self.build_dotnet()
        self.build_next()
        before = sorted(p.as_posix() for p in self.root.rglob("*"))
        self.run_scan()
        after = sorted(p.as_posix() for p in self.root.rglob("*"))
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
