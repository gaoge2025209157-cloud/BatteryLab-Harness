import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))


class AcademicSearchPlanTests(unittest.TestCase):
    def _request(self):
        from electrochem_harness.academic_search import AcademicSearchRequest

        return AcademicSearchRequest(
            domain="卤化物固态电解质",
            research_question="Li3ScCl6正极界面稳定性如何影响循环？",
            concept_groups=(
                ("halide solid electrolyte", "chloride electrolyte"),
                ("cathode interface", "interfacial stability"),
            ),
            exact_phrases=("Li3ScCl6",),
            exclusions=("liquid electrolyte",),
            year_from=2020,
            year_to=2026,
            databases=(
                "crossref",
                "openalex",
                "web_of_science",
                "scopus",
                "cnki",
                "google_scholar",
            ),
            max_results=5,
        )

    def test_builds_stable_advanced_queries_for_major_databases(self):
        from electrochem_harness.academic_search import build_advanced_search_plan

        first = build_advanced_search_plan(self._request())
        second = build_advanced_search_plan(self._request())
        self.assertEqual(first.plan_hash, second.plan_hash)
        self.assertIn("TS=(", first.database_queries["web_of_science"])
        self.assertIn("TITLE-ABS-KEY(", first.database_queries["scopus"])
        self.assertIn("Li3ScCl6", first.database_queries["cnki"])
        self.assertIn("2020", first.database_queries["web_of_science"])
        self.assertTrue(first.browser_urls["web_of_science"].startswith("https://"))
        self.assertTrue(first.browser_urls["scopus"].startswith("https://"))
        self.assertEqual(first.automatic_sources, ("crossref", "openalex"))

    def test_opens_only_user_selected_guided_database_pages(self):
        from electrochem_harness.academic_search import (
            build_advanced_search_plan,
            open_guided_search_pages,
        )

        opened = []
        plan = build_advanced_search_plan(self._request())
        result = open_guided_search_pages(plan, opener=lambda url: opened.append(url) or True)
        self.assertEqual(set(result), {"web_of_science", "scopus", "cnki", "google_scholar"})
        self.assertEqual(len(opened), 4)


class FullTextEvidenceTests(unittest.TestCase):
    def test_html_extractor_prioritizes_background_figures_and_tables(self):
        from electrochem_harness.fulltext import extract_html_evidence

        html = """
        <html><body>
          <h2>Introduction</h2>
          <p>Halide solid electrolytes offer high ionic conductivity but cathode interfaces remain unstable.</p>
          <h2>Results</h2>
          <figure><figcaption>Figure 2. Conductivity reaches 2.1 mS cm-1 at 25 C.</figcaption></figure>
          <table><tr><th>Pressure</th><th>Capacity</th></tr><tr><td>50 MPa</td><td>145 mAh g-1</td></tr></table>
        </body></html>
        """
        evidence = extract_html_evidence(
            html,
            source_uri="https://example.invalid/paper",
            title="Example",
            doi="10.1000/example",
        )
        self.assertIn("cathode interfaces", evidence.background_excerpt)
        joined = " ".join(evidence.figure_table_evidence)
        self.assertIn("2.1 mS cm-1", joined)
        self.assertIn("50 MPa", joined)
        self.assertEqual(evidence.evidence_level, "fulltext_html")

    def test_data_summary_removes_large_raw_arrays_and_is_bounded(self):
        from electrochem_harness.fulltext import summarize_data_file

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "analysis.json"
            path.write_text(
                json.dumps(
                    {
                        "experiment_context": {"system": "halide"},
                        "report": {"capacity": 120},
                        "points": list(range(10000)),
                    }
                ),
                encoding="utf-8",
            )
            summary = summarize_data_file(path, max_chars=2000)
        self.assertIn("capacity", summary.text)
        self.assertNotIn("9999", summary.text)
        self.assertLessEqual(len(summary.text), 2000)
        self.assertIn("points", summary.omitted_fields)


class LLMProviderTests(unittest.TestCase):
    def test_openai_compatible_provider_returns_json_and_tracks_usage(self):
        from electrochem_harness.llm_provider import LLMConfig, OpenAICompatibleProvider

        captured = {}

        def transport(url, headers, body, timeout):
            captured.update(url=url, headers=headers, body=body, timeout=timeout)
            return {
                "choices": [{"message": {"content": "```json\n{\"summary\": \"ok\"}\n```"}}],
                "usage": {"prompt_tokens": 123, "completion_tokens": 45, "total_tokens": 168},
                "model": "test-model",
            }

        os.environ["TEST_ELECTROCHEM_LLM_KEY"] = "secret-value"
        try:
            provider = OpenAICompatibleProvider(
                LLMConfig(
                    base_url="https://llm.example.invalid/v1",
                    model="test-model",
                    api_key_env="TEST_ELECTROCHEM_LLM_KEY",
                    max_tokens=1000,
                ),
                transport=transport,
            )
            result = provider.generate_json("system", {"input": "evidence"})
        finally:
            os.environ.pop("TEST_ELECTROCHEM_LLM_KEY", None)
        self.assertEqual(result.payload["summary"], "ok")
        self.assertEqual(result.total_tokens, 168)
        self.assertEqual(captured["headers"]["Authorization"], "Bearer secret-value")
        self.assertNotIn("secret-value", json.dumps(result.to_dict()))
        self.assertEqual(captured["body"]["response_format"], {"type": "json_object"})

    def test_cc_switch_uses_responses_without_reading_upstream_key(self):
        from electrochem_harness.llm_provider import LLMConfig, OpenAICompatibleProvider

        captured = {}

        def transport(url, headers, body, timeout):
            captured.update(url=url, headers=headers, body=body, timeout=timeout)
            return {
                "id": "resp_test",
                "object": "response",
                "status": "completed",
                "model": "gpt-5.6-sol",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {"type": "output_text", "text": "{\"summary\":\"ok\"}"}
                        ],
                    }
                ],
                "usage": {"input_tokens": 22, "output_tokens": 9, "total_tokens": 31},
            }

        os.environ.pop("ELECTROCHEM_LLM_API_KEY", None)
        config = LLMConfig(
            base_url="http://127.0.0.1:15721/v1",
            model="gpt-5.6-sol",
            max_tokens=1000,
        )
        provider = OpenAICompatibleProvider(config, transport=transport)
        result = provider.generate_json("Return JSON.", {"input": "evidence"})

        self.assertEqual(config.protocol, "responses")
        self.assertEqual(config.auth_mode, "cc_switch")
        self.assertEqual(captured["url"], "http://127.0.0.1:15721/v1/responses")
        self.assertEqual(captured["headers"]["Authorization"], "Bearer PROXY_MANAGED")
        self.assertEqual(captured["body"]["instructions"], "Return JSON.")
        self.assertIn("evidence", captured["body"]["input"])
        self.assertNotIn("messages", captured["body"])
        self.assertEqual(result.payload, {"summary": "ok"})
        self.assertEqual(result.total_tokens, 31)


class KnowledgeAssistantTests(unittest.TestCase):
    def _request(self, **overrides):
        from electrochem_harness.academic_search import AcademicSearchRequest
        from electrochem_harness.knowledge_assistant import KnowledgeAssistantRequest

        search = AcademicSearchRequest(
            domain="卤化物固态电解质",
            research_question="界面阻抗增长是否限制循环？",
            concept_groups=(("halide electrolyte", "chloride electrolyte"), ("interface",)),
            databases=("crossref", "openalex", "web_of_science"),
            max_results=5,
        )
        values = dict(search=search, max_documents=5, max_evidence_chars=20000)
        values.update(overrides)
        return KnowledgeAssistantRequest(**values)

    def _reasoning(self):
        return {
            "summary": "现有数据提示容量衰减，但不能单独确定界面阻抗增长。",
            "recommended_search_terms": ["operando EIS", "stack pressure"],
            "article_core_findings": [
                {
                    "source_id": "10.1000/a",
                    "research_question": "卤化物正极界面如何演化？",
                    "method": "循环测试与原位阻抗",
                    "core_finding": "界面过程随循环发生变化。",
                    "evidence_location": "Results, Figure 2",
                    "limitations": "仅适用于文中电池构型。",
                }
            ],
            "research_background": [
                {
                    "claim": "卤化物电解质正极界面可能持续演化。",
                    "source_ids": ["10.1000/a"],
                    "evidence_level": "fulltext_html",
                    "limitations": "需保持文中测试边界。",
                }
            ],
            "electrochemistry_foundations": [
                {
                    "concept": "界面阻抗",
                    "explanation": "界面反应和接触变化会改变交流响应。",
                    "source_ids": ["10.1000/a"],
                    "evidence_level": "fulltext_html",
                    "boundaries": "需要频率区间、温度和压力条件共同解释。",
                }
            ],
            "key_figures_tables": [
                {
                    "source_id": "10.1000/a",
                    "location": "Figure 2",
                    "parameter": "ionic conductivity",
                    "value": "2.1",
                    "unit": "mS cm-1",
                    "conditions": "25 C",
                    "scientific_logic": "电导率决定体相离子传输能力。",
                    "relevance_to_experiment": "需在相同温度下比较。",
                }
            ],
            "learning_delta": [
                {
                    "new_understanding": "需要把界面阻抗变化与压力条件联动解释。",
                    "relationship_to_prior": "当前没有已批准知识，属于首轮认识。",
                    "source_ids": ["10.1000/a"],
                    "unresolved_question": "阻抗变化来自化学副反应还是接触损失？",
                }
            ],
            "data_value_assessment": [
                {
                    "finding": "容量随循环降低",
                    "value": "可作为失效起点证据",
                    "evidence": "用户数据摘要",
                    "confidence": "medium",
                    "limitations": "单电池且无EIS",
                }
            ],
            "missing_experiments": [
                {
                    "question": "阻抗是否增长？",
                    "experiment": "循环前后及分阶段EIS",
                    "variables": "频率、扰动、温度、压力",
                    "expected_evidence": "界面相关阻抗随循环变化",
                    "priority": "high",
                }
            ],
            "missing_characterization": [
                {
                    "question": "界面产物是什么？",
                    "characterization": "循环后XPS与截面SEM/EDS",
                    "sampling": "首圈、衰减中期、失效后",
                    "expected_evidence": "化学态与接触形貌变化",
                    "priority": "high",
                }
            ],
            "cannot_determine": ["不能仅由充放电曲线得到电荷转移电阻。"],
            "knowledge_candidates": [
                {
                    "claim": "需要用分阶段EIS区分界面阻抗贡献。",
                    "source_ids": ["10.1000/a"],
                    "conditions": "卤化物固态电池",
                    "confidence": "medium",
                    "verification_needed": "核对正文方法与等效电路。",
                }
            ],
        }

    def test_validator_requires_data_value_and_missing_research_work(self):
        from electrochem_harness.knowledge_assistant import validate_reasoning_result

        with self.assertRaises(ValueError):
            validate_reasoning_result({"summary": "too little"})
        validated = validate_reasoning_result(self._reasoning())
        self.assertTrue(validated["data_value_assessment"])
        self.assertTrue(validated["missing_experiments"])
        self.assertTrue(validated["missing_characterization"])

    def test_run_writes_auditable_files_and_candidate_markdown(self):
        from electrochem_harness.fulltext import DocumentEvidence
        from electrochem_harness.knowledge_assistant import run_knowledge_assistant
        from electrochem_harness.llm_provider import LLMResult

        class FakeProvider:
            def generate_json(self, system_prompt, payload):
                self.payload = payload
                return LLMResult(
                    payload=self_result,
                    model="fake-model",
                    prompt_tokens=100,
                    completion_tokens=80,
                    total_tokens=180,
                )

        self_result = self._reasoning()
        provider = FakeProvider()
        records = [
            {
                "id": "10.1000/a",
                "doi": "10.1000/a",
                "title": "Halide electrolyte interface study",
                "year": 2025,
                "journal": "Nature Communications",
                "abstract": "Halide electrolyte interface resistance increased during cycling.",
                "evidence_level": "abstract",
                "source": "crossref",
            }
        ]
        documents = [
            DocumentEvidence(
                source_id="10.1000/a",
                title="Halide electrolyte interface study",
                doi="10.1000/a",
                source_uri="local.html",
                evidence_level="fulltext_html",
                background_excerpt="Halide electrolyte interface background " * 20,
                methods_excerpt="Electrochemical impedance method " * 20,
                figure_table_evidence=("Figure 2: 2.1 mS cm-1 at 25 C",),
                body_excerpt="Halide electrolyte interface full-text results and discussion. " * 40,
                content_hash="a" * 64,
                limitations=(),
            )
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            knowledge_path = root / "research_knowledge.md"
            result = run_knowledge_assistant(
                self._request(),
                provider,
                run_root=root / "runs",
                knowledge_path=knowledge_path,
                metadata_searcher=lambda request: records,
                document_collector=lambda request, metadata: documents,
            )
            for name in (
                "plan.json",
                "evidence_packet.json",
                "context_bundle.json",
                "context_manifest.json",
                "reasoning_result.json",
                "run_record.json",
            ):
                self.assertTrue((result.run_dir / name).is_file(), name)
            record = json.loads((result.run_dir / "run_record.json").read_text(encoding="utf-8"))
            manifest = json.loads((result.run_dir / "context_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(result.context_hash, record["context_hash"])
            self.assertEqual(result.context_hash, manifest["context_hash"])
            text = knowledge_path.read_text(encoding="utf-8")
        self.assertIn("状态：candidate", text)
        self.assertIn("数据价值判断", text)
        self.assertIn("需要补充的实验", text)
        self.assertIn("需要补充的表征", text)
        self.assertIn("Figure 2", text)
        self.assertEqual(result.total_tokens, 180)
        self.assertIn("candidate_evidence_packet", provider.payload)
        self.assertIn("task", provider.payload)
        self.assertIn("permissions", provider.payload)
        self.assertIn("data_observations", provider.payload)
        self.assertNotIn("raw_documents", provider.payload)
        self.assertNotIn(str(root), json.dumps(provider.payload, ensure_ascii=False))


class KnowledgeAssistantCacheTests(unittest.TestCase):
    def test_identical_evidence_packet_calls_provider_only_once(self):
        from electrochem_harness.academic_search import AcademicSearchRequest
        from electrochem_harness.knowledge_assistant import KnowledgeAssistantRequest, run_knowledge_assistant
        from electrochem_harness.llm_provider import LLMResult

        reasoning = KnowledgeAssistantTests()._reasoning()

        class CountingProvider:
            def __init__(self):
                self.calls = 0

            def generate_json(self, system_prompt, payload):
                self.calls += 1
                return LLMResult(reasoning, "fake", 10, 10, 20)

        search = AcademicSearchRequest(
            domain="solid electrolyte",
            research_question="stability",
            concept_groups=(("solid electrolyte",),),
            databases=("crossref",),
            max_results=1,
        )
        request = KnowledgeAssistantRequest(search=search, max_documents=1, max_evidence_chars=10000)
        provider = CountingProvider()
        from electrochem_harness.fulltext import DocumentEvidence
        records = [{
            "id": "10.1000/a",
            "doi": "10.1000/a",
            "title": "Solid electrolyte stability",
            "year": 2025,
            "journal": "Nature Communications",
            "abstract": "Solid electrolyte stability and interface behavior.",
        }]
        documents = [DocumentEvidence(
            source_id="10.1000/a",
            title="Solid electrolyte stability",
            doi="10.1000/a",
            source_uri="paper.html",
            evidence_level="fulltext_html",
            background_excerpt="Solid electrolyte stability background. " * 20,
            methods_excerpt="Electrochemical method. " * 20,
            figure_table_evidence=("Figure 2 full-text evidence",),
            body_excerpt="Solid electrolyte stability full-text discussion. " * 40,
            content_hash="b" * 64,
            limitations=(),
        )]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = run_knowledge_assistant(
                request,
                provider,
                run_root=root / "runs",
                knowledge_path=root / "knowledge.md",
                metadata_searcher=lambda _: records,
                document_collector=lambda *_: documents,
            )
            second = run_knowledge_assistant(
                request,
                provider,
                run_root=root / "runs",
                knowledge_path=root / "knowledge.md",
                metadata_searcher=lambda _: records,
                document_collector=lambda *_: documents,
            )
        self.assertEqual(provider.calls, 1)
        self.assertFalse(first.cache_hit)
        self.assertTrue(second.cache_hit)


class ReleaseIntegrationTests(unittest.TestCase):
    def test_private_llm_knowledge_and_runs_are_git_ignored(self):
        ignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("knowledge/research_knowledge.md", ignore)
        self.assertIn("knowledge/runs/", ignore)

    def test_release_uses_empty_research_knowledge_template(self):
        script = (PROJECT_ROOT / "build_release.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("research_knowledge_template.md", script)
        self.assertIn("research_knowledge.md", script)
        template = PROJECT_ROOT / "knowledge" / "research_knowledge_template.md"
        self.assertTrue(template.is_file())
        self.assertIn("candidate", template.read_text(encoding="utf-8"))

    def test_readme_documents_llm_and_campus_search_boundaries(self):
        readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("自动调研与知识库", readme)
        self.assertIn("Web of Science", readme)
        self.assertIn("ELECTROCHEM_LLM_API_KEY", readme)
        self.assertIn("不会读取账号、密码或Cookie", readme)


if __name__ == "__main__":
    unittest.main()
