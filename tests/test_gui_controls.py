from __future__ import annotations

import unittest

from electrochem_harness_v2.gui import (
    analysis_condition_hint,
    build_run_options,
    build_send_scope_summary,
    default_replicate_metric,
    format_claim_review_details,
    format_research_state_items,
    format_review_audit,
    format_stage_statuses,
    normalize_analysis_type,
    parse_condition_value,
    parse_research_state_items,
)
from electrochem_harness_v2.models import KnowledgeClaim, ReviewEvent, SourceSpan


class GuiRunControlTests(unittest.TestCase):
    def test_switches_map_independently_to_run_all_options(self):
        self.assertEqual(
            build_run_options(True, False, True),
            {
                "use_codex_candidates": True,
                "use_online_research": False,
                "use_codex_assessment": True,
            },
        )

    def test_all_switches_off_disable_every_codex_route(self):
        options = build_run_options(False, False, False)
        self.assertFalse(any(options.values()))
        summary = build_send_scope_summary(False, False, False, has_pdf=True)
        self.assertIn("不调用任何 Codex 路径", summary)

    def test_send_scope_summary_cannot_expose_paths(self):
        summary = build_send_scope_summary(True, True, True, has_pdf=True)
        self.assertNotIn("D:\\private", summary)
        self.assertNotIn("sample.csv", summary)
        self.assertIn("文件路径：不发送", summary)
        self.assertIn("不发送逐行原始数据", summary)


class GuiAnalysisControlTests(unittest.TestCase):
    def test_analysis_methods_have_safe_hints_and_replicate_metrics(self):
        for method in ("gcd", "cv", "eis", "gitt"):
            self.assertEqual(normalize_analysis_type(method.upper()), method)
            self.assertTrue(analysis_condition_hint(method))
            self.assertTrue(default_replicate_metric(method))
        with self.assertRaises(ValueError):
            normalize_analysis_type("unknown")

    def test_condition_values_parse_numbers_and_nested_units(self):
        self.assertEqual(parse_condition_value("0.5"), 0.5)
        self.assertEqual(
            parse_condition_value('{"potential_V":"V","current_A":"A"}'),
            {"potential_V": "V", "current_A": "A"},
        )
        self.assertEqual(parse_condition_value("half-cell"), "half-cell")

    def test_stage_status_summary_keeps_attempts(self):
        text = format_stage_statuses([
            {"stage": "DATA", "status": "COMPLETED", "attempt": 1},
            {"stage": "ORIGIN", "status": "PARTIAL", "attempt": 2},
        ])
        self.assertIn("DATA=COMPLETED", text)
        self.assertIn("ORIGIN=PARTIAL(第2次)", text)


class GuiResearchStateTests(unittest.TestCase):
    def test_line_editor_round_trips_strings_and_structured_rejections(self):
        values = [
            "先复测平行电池",
            {"claim": "时间倒退", "reason": "原始时间单调"},
        ]
        rendered = format_research_state_items(values)
        self.assertEqual(parse_research_state_items(rendered), values)

    def test_empty_lines_are_ignored_and_latest_forty_are_kept(self):
        rendered = "\n".join("item-{}".format(index) for index in range(45)) + "\n\n"
        parsed = parse_research_state_items(rendered)
        self.assertEqual(len(parsed), 40)
        self.assertEqual(parsed[0], "item-5")
        self.assertEqual(parsed[-1], "item-44")


class GuiReviewFormattingTests(unittest.TestCase):
    def test_claim_details_include_review_fields_sources_and_local_span(self):
        claim = KnowledgeClaim.new(
            "project-1",
            "source-1",
            "performance",
            "容量为 152.2 mAh/g",
            conditions={
                "temperature_C": 60,
                "source_urls": ["https://example.org/paper"],
            },
            evidence_span_ids=["span-1"],
            limitations=["单次测试"],
        )
        span = SourceSpan(
            span_id="span-1",
            source_id="source-1",
            page_index=3,
            page_label="4",
            block_type="text",
            text="Reported capacity was 152.2 mAh/g.",
            text_hash="hash",
        )
        details = format_claim_review_details(claim, [span])
        self.assertIn(claim.text, details)
        self.assertIn("状态：candidate", details)
        self.assertIn("temperature_C", details)
        self.assertIn("单次测试", details)
        self.assertIn("source-1", details)
        self.assertIn("https://example.org/paper", details)
        self.assertIn("span-1｜页 4", details)
        self.assertIn(span.text, details)

    def test_persisted_review_event_is_visible_in_audit(self):
        claim = KnowledgeClaim.new("project-1", "source-1", "background", "候选结论")
        event = ReviewEvent(
            "review-1",
            claim.claim_id,
            "candidate",
            "approved",
            "researcher",
            "已核对原文",
            "2026-11-11T12:00:00+00:00",
        )
        audit = format_review_audit([(claim, event)])
        self.assertIn("candidate → approved", audit)
        self.assertIn("researcher", audit)
        self.assertIn("已核对原文", audit)


if __name__ == "__main__":
    unittest.main()
