import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))


class ResearchReportTests(unittest.TestCase):
    def test_html_is_utf8_self_contained_and_embeds_figures(self):
        from electrochem_harness.research_report import create_research_html_report

        reasoning = {
            "summary": "容量下降伴随极化增长。",
            "article_core_findings": [{"source_id": "10.1000/test", "core_finding": "界面传输影响极化", "method": "EIS", "evidence_location": "Figure 3", "limitations": "特定体系"}],
            "research_background": [],
            "electrochemistry_foundations": [],
            "data_value_assessment": [],
            "missing_experiments": [],
            "missing_characterization": [],
            "knowledge_candidates": [{"claim": "需要区分传输与接触因素。", "source_ids": ["10.1000/test"], "conditions": "同类体系"}],
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            image = root / "循环性能.png"
            image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"fake")
            target = create_research_html_report(
                root / "研究分析报告.html",
                values={"battery_system": "锂硫电池", "temperature": "60"},
                deterministic_text="平均放电电压：0.90 V",
                guidance_text="下一步进行单变量截止电压实验。",
                reasoning=reasoning,
                papers=[{"title": "真实论文", "journal": "Nature Communications", "year": 2025, "doi": "10.1000/test"}],
                image_paths=[image],
            )
            raw = target.read_bytes()
            text = raw.decode("utf-8-sig")

        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        self.assertIn('<meta charset="utf-8">', text)
        self.assertIn("锂硫电池", text)
        self.assertIn("data:image/png;base64,", text)
        self.assertIn("已学习·待复核", text)
        self.assertNotIn("<script", text.casefold())


if __name__ == "__main__":
    unittest.main()
