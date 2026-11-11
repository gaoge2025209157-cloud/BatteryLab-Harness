from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from electrochem_harness_v2.report import write_report


class ReportTests(unittest.TestCase):
    def test_report_escapes_dynamic_html_and_uses_relative_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "report.html"
            write_report(target, {"project_name": "<script>alert(1)</script>", "status": "NEEDS_REVIEW"}, [], [])
            html = target.read_text(encoding="utf-8")
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script>alert", html)
        self.assertIn("一、课题背景与研究问题", html)
        self.assertIn("二、实验数据分析", html)
        self.assertIn("三、当前课题阶段定位", html)
        self.assertIn("四、文献与知识依据", html)
        self.assertIn("本轮没有可展示的联网文献结果", html)
        self.assertIn("五、综合结论与下一步实验", html)
        self.assertNotIn("运行审计", html)
        self.assertNotIn("Codex 工作记录", html)

    def test_generic_project_report_contains_no_material_specific_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "report.html"
            write_report(
                target,
                {"project_name": "Generic electrochemistry", "material_system": "Material-A|Electrolyte-B"},
                [],
                [],
                analysis={"gcd_summary": {
                    "first_complete_discharge_capacity_mAh_g": 2000.0,
                    "latest_polarization_voltage_V": 0.8,
                }},
            )
            html = target.read_text(encoding="utf-8")
        for forbidden in ("P₂O₅", "P2O5", "LiTaCl6", "LiTaCl₆", "LPSC", "1675", "宁德时代", "麒麟"):
            self.assertNotIn(forbidden, html)


if __name__ == "__main__":
    unittest.main()
