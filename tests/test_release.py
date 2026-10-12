import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))


class ReleasePackagingTests(unittest.TestCase):
    def test_origin_launcher_is_portable(self):
        script = (PROJECT_ROOT / "run_sci_origin.ps1").read_text(encoding="utf-8-sig")

        self.assertIn("[string]$OriginExe", script)
        self.assertIn("Resolve-OriginExecutable", script)
        self.assertNotIn("D:\\Origin2026b\\Origin64.exe", script)
        self.assertIn("$PSScriptRoot", script)

    def test_release_builder_uses_allowlist_and_excludes_private_outputs(self):
        script = (PROJECT_ROOT / "build_release.ps1").read_text(encoding="utf-8-sig")

        self.assertIn("$AllowedFiles", script)
        self.assertIn("$AllowedDirectories", script)
        self.assertNotIn("Copy-Item (Join-Path $Root '*')", script)
        self.assertIn("experiences.jsonl", script)
        self.assertIn("run_gui.py", script)
        self.assertIn("start_gui.cmd", script)
        self.assertIn("Get-FileHash", script)

    def test_release_documentation_exists_and_describes_optional_origin(self):
        guide = (PROJECT_ROOT / "README_发布版.md").read_text(encoding="utf-8")

        self.assertIn("Origin 不是数据分析的必需条件", guide)
        self.assertIn("-Guided", guide)
        self.assertIn("文献证据.json", guide)
        self.assertIn("双击", guide)
        self.assertIn("交互界面", guide)
        self.assertNotIn("C:\\Users\\12470", guide)
        self.assertNotIn("D:\\AI\\电化学智能实验Harness", guide)

    def test_release_metadata_exists(self):
        self.assertEqual((PROJECT_ROOT / "VERSION").read_text(encoding="utf-8").strip(), "0.4.0")
        self.assertTrue((PROJECT_ROOT / "CHANGELOG.md").is_file())
        self.assertTrue((PROJECT_ROOT / "LICENSE.txt").is_file())

    def test_github_privacy_and_collaboration_files_exist(self):
        ignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
        for private_pattern in (
            "outputs/", "data/", "raw_data/", ".kiro/",
            "knowledge/experiences.jsonl", "*.opju", "release/",
        ):
            self.assertIn(private_pattern, ignore)
        self.assertTrue((PROJECT_ROOT / "CONTRIBUTING.md").is_file())
        self.assertTrue((PROJECT_ROOT / "SECURITY.md").is_file())
        self.assertTrue((PROJECT_ROOT / ".github" / "pull_request_template.md").is_file())
        self.assertTrue((PROJECT_ROOT / ".github" / "ISSUE_TEMPLATE" / "bug.yml").is_file())
        self.assertTrue((PROJECT_ROOT / ".github" / "ISSUE_TEMPLATE" / "feature.yml").is_file())


if __name__ == "__main__":
    unittest.main()
