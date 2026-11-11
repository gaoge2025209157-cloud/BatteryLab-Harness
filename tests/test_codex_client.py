from __future__ import annotations

import unittest

from electrochem_harness_v2.codex_client import candidate_payload_to_claims


class CodexCandidateValidationTests(unittest.TestCase):
    def test_only_allowlisted_span_and_finite_values_become_candidates(self):
        payload = {"claims": [{
            "type": "performance", "text": "Capacity reported", "metric_id": "discharge_specific_capacity_mAh_g",
            "value": 152.2, "unit": "mAh/g", "conditions": {"rate": "1 C"}, "evidence_span_ids": ["span-1"],
        }, {
            "type": "performance", "text": "Bad", "metric_id": "discharge_specific_capacity_mAh_g",
            "value": "NaN", "unit": "mAh/g", "evidence_span_ids": ["forged"],
        }]}
        claims, rejected = candidate_payload_to_claims("project-1", "source-1", {"span-1"}, payload)
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0].status, "candidate")
        self.assertEqual(len(rejected), 1)


class _FakeResult:
    status = "completed"
    error = None
    final_response = '{"knowledge_items":[{"title":"Key paper","claim":"Interface testing is needed.","priority":"high","why_selected":"Directly relevant","candidate_claim_ids":[],"source_urls":["https://example.org/paper"],"tests":["XPS"],"question":"What changes?","finding":"The interface changes.","how_to_borrow":"Compare before and after cycling."}],"rejected_items":[],"research_gaps":[]}'


class _FakeThread:
    id = "thread-test"

    def __init__(self):
        self.last_input = None

    def run(self, *args, **_kwargs):
        self.last_input = args[0] if args else None
        return _FakeResult()


class _FakeClient:
    last_instance = None

    def __init__(self, *_args, **_kwargs):
        self.thread = _FakeThread()
        _FakeClient.last_instance = self

    def thread_start(self, **_kwargs):
        return self.thread

    def thread_resume(self, *_args, **_kwargs):
        return self.thread

    def close(self):
        pass


class CodexLiteratureSynthesisTests(unittest.TestCase):
    def test_parses_codex_response_before_building_curated_claims(self):
        from electrochem_harness_v2.codex_client import CodexResearchClient

        client = CodexResearchClient(".", client_factory=_FakeClient)
        thread_id, payload, claims, rejected = client.synthesize_literature(
            {"project_id": "project-1"},
            [],
            online_research={"sources": [{"title": "Key paper", "url": "https://example.org/paper"}]},
        )
        self.assertEqual(thread_id, "thread-test")
        self.assertEqual(payload["knowledge_items"][0]["title"], "Key paper")
        self.assertEqual(len(claims), 1)
        self.assertEqual(rejected, [])
        self.assertIsInstance(_FakeClient.last_instance.thread.last_input, str)

    def test_managed_context_is_the_single_synthesis_context(self):
        import json
        from electrochem_harness_v2.codex_client import CodexResearchClient

        managed = {
            "schema_version": "2.0",
            "task": {"task_id": "task-1"},
            "project": {"project_id": "project-1"},
            "candidate_knowledge": [],
            "candidate_online_research": {"sources": [{"url": "https://example.org/paper"}]},
        }
        client = CodexResearchClient(".", client_factory=_FakeClient)
        client.synthesize_literature(
            managed,
            [],
            online_research={"sources": [{"title": "Key paper", "url": "https://example.org/paper"}]},
        )
        sent = json.loads(_FakeClient.last_instance.thread.last_input)
        self.assertEqual(sent["managed_context"]["schema_version"], "2.0")
        self.assertNotIn("project_context", sent)
        self.assertNotIn("local_pdf_candidates", sent)
        self.assertNotIn("codex_web_research", sent)


class CodexSchemaTests(unittest.TestCase):
    def test_guidance_schema_requires_every_declared_nested_property(self):
        from electrochem_harness_v2.codex_client import GUIDANCE_OUTPUT_SCHEMA

        def assert_strict_object(schema):
            if schema.get("type") == "object" and schema.get("properties"):
                self.assertEqual(set(schema["properties"]), set(schema.get("required") or []))
            for child in schema.get("properties", {}).values():
                assert_strict_object(child)
                assert_strict_object(child.get("items", {}))

        assert_strict_object(GUIDANCE_OUTPUT_SCHEMA)
