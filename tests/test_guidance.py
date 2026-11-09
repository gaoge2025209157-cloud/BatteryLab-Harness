from __future__ import annotations

import unittest

from electrochem_harness_v2.guidance import validate_guidance_payload


class GuidanceValidationTests(unittest.TestCase):
    def test_accepts_structured_codex_assessment(self):
        payload = {
            "assessment": "The data require mass-basis review before formal performance claims.",
            "data_facts": ["Instrument-exported capacity was analysed deterministically."],
            "hypotheses": [{"claim": "Anomalous first discharge may reflect normalization or side reactions.", "support": ["first-segment anomaly"], "against": [], "test": "Verify active mass and repeat with a blank cell."}],
            "cannot_determine": ["Intrinsic capacity without confirmed mass basis."],
            "benchmark_comparisons": [{"metric": "discharge capacity", "observed": "90 mAh/g", "reference": "150–200 mAh/g", "comparability": "context_only", "conclusion": "仅作背景参考", "source_urls": ["https://example.org/review"]}],
            "theoretical_energy_assessment": {"status": "candidate", "conclusion": "理论值依赖十电子反应假设。"},
            "next_experiments": [{"action": "Confirm active mass", "variable": "normalization basis", "expected_evidence": "traceable mAh/g"}],
        }
        result = validate_guidance_payload(payload)
        self.assertEqual(result["assessment"], payload["assessment"])
        self.assertEqual(len(result["hypotheses"]), 1)

    def test_accepts_omitted_empty_comparison_array(self):
        payload = {
            "assessment": "需要核验质量口径。",
            "data_facts": ["已完成确定性分析。"],
            "hypotheses": [],
            "cannot_determine": ["质量分母。"],
            "theoretical_energy_assessment": {"conclusion": "反应模型待确认。"},
            "next_experiments": [{"action": "核对称量记录。"}],
        }
        result = validate_guidance_payload(payload)
        self.assertEqual(result["benchmark_comparisons"], [])
        with self.assertRaises(ValueError):
            validate_guidance_payload({"assessment": "incomplete"})


if __name__ == "__main__":
    unittest.main()
