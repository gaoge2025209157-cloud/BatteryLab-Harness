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
    start_calls = 0
    resume_calls = 0

    def __init__(self, *_args, **_kwargs):
        self.thread = _FakeThread()
        _FakeClient.last_instance = self

    def thread_start(self, **_kwargs):
        type(self).start_calls += 1
        return self.thread

    def thread_resume(self, *_args, **_kwargs):
        type(self).resume_calls += 1
        return self.thread

    def close(self):
        pass


class _CandidateResult:
    status = "completed"
    error = None
    final_response = '{"claims":[{"type":"background","text":"候选事实","evidence_span_ids":["span-1"]}]}'


class _CandidateThread(_FakeThread):
    def run(self, *args, **kwargs):
        self.last_input = args[0]
        return _CandidateResult()


class _CandidateClient(_FakeClient):
    def __init__(self, *_args, **_kwargs):
        self.thread = _CandidateThread()
        type(self).last_instance = self


class CodexLiteratureSynthesisTests(unittest.TestCase):
    def test_pdf_invocation_records_exact_selected_span_text_and_hash(self):
        import hashlib
        from electrochem_harness_v2.codex_client import CodexResearchClient
        from electrochem_harness_v2.models import SourceSpan

        text = "原文证据片段"
        span = SourceSpan("span-1", "source-1", 1, "1", "text", text, "stored-hash")
        records = []
        client = CodexResearchClient(".", client_factory=_CandidateClient, invocation_recorder=records.append)
        client.extract_candidates({"project_id": "project-1"}, "source-1", [span])

        selected = records[0]["selected_pdf_spans"][0]
        self.assertEqual(selected["span_id"], "span-1")
        self.assertEqual(selected["text"], text)
        self.assertEqual(selected["text_sha256"], hashlib.sha256(text.encode("utf-8")).hexdigest())
        self.assertEqual(records[0]["local_request"]["evidence"][0]["text"], text)

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

    def test_old_thread_id_is_ignored_and_invocation_is_fully_audited(self):
        import json
        from electrochem_harness_v2.codex_client import CURATED_KNOWLEDGE_SCHEMA, CodexResearchClient

        _FakeClient.start_calls = 0
        _FakeClient.resume_calls = 0
        records = []
        managed = {
            "schema_version": "2.0",
            "task": {"task_id": "task-1"},
            "project": {"project_id": "project-1"},
            "api_key": "must-not-be-recorded-or-sent",
            "data_path": "D:\\private\\sample.csv",
        }
        client = CodexResearchClient(".", client_factory=_FakeClient, invocation_recorder=records.append)
        returned_thread, _payload, _claims, _rejected = client.synthesize_literature(
            managed,
            [],
            online_research={"sources": [{"url": "https://example.org/paper"}]},
            thread_id="thread-with-unrecorded-history",
        )

        self.assertEqual(returned_thread, "thread-test")
        self.assertEqual(_FakeClient.start_calls, 1)
        self.assertEqual(_FakeClient.resume_calls, 0)
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["thread_mode"], "fresh")
        self.assertTrue(record["ephemeral"])
        self.assertTrue(record["requested_thread_id_ignored"])
        self.assertEqual(record["status"], "COMPLETED")
        self.assertEqual(record["output_schema"], CURATED_KNOWLEDGE_SCHEMA)
        self.assertTrue(record["response_hash"])
        self.assertEqual(record["model_identity"]["model"], "sdk-default")
        rendered = json.dumps(record, ensure_ascii=False)
        self.assertNotIn("must-not-be-recorded-or-sent", rendered)
        self.assertNotIn("D:\\\\private", rendered)
        sent = json.loads(_FakeClient.last_instance.thread.last_input)
        self.assertEqual(sent["managed_context"]["api_key"], "[REDACTED]")
        self.assertEqual(sent["managed_context"]["data_path"], "sample.csv")

    def test_failed_response_creates_one_failed_invocation_record(self):
        from electrochem_harness_v2.codex_client import CodexResearchClient, CodexResearchError

        class FailedResult:
            status = "failed"
            error = "timeout at D:\\private\\secret.txt api_key=top-secret"
            final_response = None

        class FailedThread(_FakeThread):
            def run(self, *args, **kwargs):
                self.last_input = args[0]
                return FailedResult()

        class FailedClient(_FakeClient):
            def __init__(self, *_args, **_kwargs):
                self.thread = FailedThread()
                type(self).last_instance = self

        records = []
        client = CodexResearchClient(".", client_factory=FailedClient, invocation_recorder=records.append)
        with self.assertRaises(CodexResearchError):
            client.synthesize_literature(
                {"project_id": "project-1"}, [], online_research={}, thread_id="old-thread"
            )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["status"], "FAILED")
        self.assertIn("timeout", records[0]["error"])
        self.assertNotIn("D:\\private", records[0]["error"])
        self.assertNotIn("top-secret", records[0]["error"])
        self.assertIn("[REDACTED]", records[0]["error"])
        self.assertIsNone(records[0]["response_hash"])


    def test_request_hash_covers_developer_rules_and_schema(self):
        from electrochem_harness_v2.codex_client import CodexResearchClient

        first_records = []
        second_records = []
        first = CodexResearchClient(
            ".", client_factory=_FakeClient, invocation_recorder=first_records.append
        )
        second = CodexResearchClient(
            ".", client_factory=_FakeClient, invocation_recorder=second_records.append
        )
        request = {"project_context": {"project_id": "project-1"}}

        first._invoke(
            _FakeClient(),
            stage="test-stage",
            request_payload=request,
            developer_instructions="first rule",
            output_schema={"type": "object"},
        )
        second._invoke(
            _FakeClient(),
            stage="test-stage",
            request_payload=request,
            developer_instructions="second rule",
            output_schema={"type": "object"},
        )

        self.assertEqual(first_records[0]["message_hash"], second_records[0]["message_hash"])
        self.assertNotEqual(first_records[0]["request_hash"], second_records[0]["request_hash"])
        self.assertTrue(first_records[0]["output_schema_hash"])
        self.assertTrue(first_records[0]["model_identity_hash"])


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
