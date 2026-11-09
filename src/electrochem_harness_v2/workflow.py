"""Single, staged orchestration for the Harness-v2 research workflow."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from .benchmarks import build_benchmark_topics
from .gcd_metrics import build_codex_feature_packet
from .codex_client import CodexResearchClient
from .csv_importer import GcdCsvImporter
from .origin_adapter import OriginAdapter
from .origin_data import prepare_origin_tables
from .pdf_reader import LocalPdfReader
from .report import write_report
from .storage import ResearchStore
from .theoretical_energy import derive_theoretical_energy


@dataclass(frozen=True)
class ExperimentRun:
    run_id: str
    project_id: str
    raw_data_sha256: str
    status: str
    output_dir: Path


class ResearchWorkflow:
    """Coordinates local evidence and data processing without granting model authority."""

    def __init__(self, database_path: Path | str, output_root: Path | str):
        self.store = ResearchStore(database_path)
        self.output_root = Path(output_root)
        self.project_root = Path(__file__).resolve().parents[2]
        self.pdf_reader = LocalPdfReader()
        self.csv_importer = GcdCsvImporter()
        self._source_newness: dict[str, bool] = {}
        origin_executable = None
        config_path = self.project_root / "config.json"
        if config_path.is_file():
            try:
                origin_executable = (json.loads(config_path.read_text(encoding="utf-8")) or {}).get("origin_executable")
            except json.JSONDecodeError as error:
                raise ValueError("config.json is not valid JSON.") from error
        self.origin_adapter = OriginAdapter(self.project_root / "scripts" / "run_origin.ps1", origin_executable=origin_executable)

    def create_project(self, name: str, material_system: str, keywords: list[str]) -> str:
        return self.store.create_project(name, material_system, keywords)

    def update_project(self, project_id: str, name: str, material_system: str, keywords: list[str]) -> dict:
        return self.store.update_project(project_id, name, material_system, keywords)

    @staticmethod
    def _update_manifest(output_dir: Path, *, artifact: str | None = None, **fields) -> None:
        path = output_dir / "manifest.json"
        payload = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        payload.update(fields)
        artifacts = list(payload.get("artifacts") or [])
        if artifact and artifact not in artifacts:
            artifacts.append(artifact)
        payload["artifacts"] = artifacts
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _record_codex_activity(output_dir: Path, stage: str, status: str, message: str, details: dict | None = None) -> None:
        """Persist a bounded, human-readable trace of every Codex stage."""
        path = output_dir / "codex_activity.json"
        try:
            records = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []
        except (OSError, json.JSONDecodeError):
            records = []
        if not isinstance(records, list):
            records = []
        safe_details = dict(details or {})
        try:
            json.dumps(safe_details, ensure_ascii=False)
        except (TypeError, ValueError):
            safe_details = {"text": str(safe_details)}
        records.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "stage": str(stage),
            "status": str(status),
            "message": str(message),
            "details": safe_details,
        })
        path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        ResearchWorkflow._update_manifest(output_dir, artifact="codex_activity.json")

    @staticmethod
    def _record_summaries(records: list[dict], limit: int = 20) -> list[dict]:
        summaries = []
        for row in records[:limit]:
            summaries.append({
                key: row.get(key) for key in ("title", "source", "source_level", "doi", "url", "openalex_id") if row.get(key)
            })
        return summaries

    def learn_local_pdf(self, project_id: str, path: Path | str):
        source_hash = self.pdf_reader.file_sha256(path)
        existing = self.store.find_source(project_id, source_hash)
        if existing is not None:
            self._source_newness[existing.source_id] = False
            return existing
        result = self.pdf_reader.read(path, project_id=project_id)
        self.store.save_source(result.document, result.spans)
        self._source_newness[result.document.source_id] = True
        return result.document

    def was_new_source(self, source_id: str) -> bool:
        return self._source_newness.get(source_id, False)

    def _build_research_context(self, project_id: str, conditions: dict | None = None, analysis: dict | None = None) -> dict:
        """Build the bounded scientific brief supplied to Codex research stages."""
        project = next((item for item in self.store.list_projects() if item["project_id"] == project_id), None)
        if project is None:
            raise KeyError("Project does not exist.")
        context = {
            "project_id": project_id,
            "project_name": project["name"],
            "material_system": project["material_system"],
            "keywords": list(project["keywords"]),
            "experiment_conditions": dict(conditions or {}),
            "research_objective": "基于实验数据、可追溯文献与受控对照，识别性能信号、数据边界、竞争解释和下一轮判别实验。",
        }
        if analysis:
            context["deterministic_features"] = build_codex_feature_packet(analysis)
        return context

    def search_literature(self, project_id: str, keywords: list[str]):
        from .search import LiteratureSearchAdapter
        result = LiteratureSearchAdapter().search(keywords)
        target = self.output_root / project_id / "searches"
        target.mkdir(parents=True, exist_ok=True)
        (target / "literature_search.json").write_text(json.dumps({"query": result.query, "searched_at": result.searched_at, "status": result.status, "error": result.error, "records": result.records}, ensure_ascii=False, indent=2), encoding="utf-8")
        return result

    def extract_pdf_candidates(self, project_id: str, source_id: str, thread_id: str | None = None):
        spans = self.store.list_source_spans(source_id)
        client = CodexResearchClient(str(self.project_root))
        returned_thread_id, claims, rejected = client.extract_candidates(
            self._build_research_context(project_id),
            source_id,
            spans,
            thread_id=thread_id,
        )
        for claim in claims:
            self.store.save_claim(claim)
        return returned_thread_id, claims, rejected

    def curate_literature(self, project_id: str, run_id: str | None = None, online_research: dict | None = None, thread_id: str | None = None, research_context: dict | None = None) -> dict:
        """Have Codex compress raw evidence into a small, source-linked approval queue."""
        raw_candidates = [
            claim for claim in self.store.list_claims(project_id)
            if claim.status == "candidate" and (claim.conditions or {}).get("review_stage") != "codex_curated"
        ]
        online = dict(online_research or {})
        output_dir = self.output_root / project_id / "runs" / run_id if run_id else None
        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
            self._record_codex_activity(output_dir, "CODEX_KNOWLEDGE", "STARTED", "开始筛选关键文献并提炼精选知识", {"raw_candidate_count": len(raw_candidates), "online_digest_count": len(online.get("knowledge_digest") or [])})
        if not raw_candidates and not online.get("knowledge_digest"):
            if output_dir:
                self._record_codex_activity(output_dir, "CODEX_KNOWLEDGE", "SKIPPED", "没有可供 Codex 提炼的文献候选", {})
            return {"status": "NO_REVIEW_ITEMS", "knowledge_items": [], "claims": [], "rejected": [], "research_gaps": []}
        client = CodexResearchClient(str(self.project_root))
        try:
            returned_thread_id, digest, claims, rejected = client.synthesize_literature(
                research_context or self._build_research_context(project_id),
                raw_candidates,
                online_research=online,
                thread_id=thread_id,
            )
        except Exception as error:
            if output_dir:
                self._record_codex_activity(output_dir, "CODEX_KNOWLEDGE", "FAILED", "精选知识提炼失败", {"error": str(error)})
            raise
        for claim in claims:
            self.store.save_claim(claim)
        result = {
            "status": "REVIEW_REQUIRED" if claims else "NO_REVIEW_ITEMS",
            "thread_id": returned_thread_id,
            "knowledge_items": digest.get("knowledge_items") or [],
            "rejected": list(rejected) + [str(value) for value in digest.get("rejected_items") or []],
            "research_gaps": [str(value) for value in digest.get("research_gaps") or []],
            "claims": claims,
        }
        if output_dir:
            self._record_codex_activity(output_dir, "CODEX_KNOWLEDGE", "COMPLETED", "Codex 精选知识提炼完成", {
                "selected_count": len(claims),
                "rejected_count": len(result["rejected"]),
                "selected_items": [{key: item.get(key) for key in ("title", "priority", "claim", "question", "finding", "how_to_borrow", "source_urls") if item.get(key)} for item in result["knowledge_items"][:6]],
                "research_gaps": result["research_gaps"],
            })
        if run_id:
            output_dir = self.output_root / project_id / "runs" / run_id
            output_dir.mkdir(parents=True, exist_ok=True)
            serializable = dict(result)
            serializable["claims"] = [claim.to_dict() for claim in claims]
            (output_dir / "literature_review.json").write_text(json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8")
            self._update_manifest(output_dir, artifact="literature_review.json", literature_review_status=result["status"], codex_curated_count=len(claims))
        return result

    def analyze_data(self, project_id: str, path: Path | str, conditions: dict) -> ExperimentRun:
        imported = self.csv_importer.read(path)
        approved = self.store.list_approved_claims(project_id)
        status = "DATA_ANALYZED" if approved else "NEEDS_REVIEW"
        run_id = self.store.create_run(project_id, imported.metadata.sha256, dict(conditions), status)
        output_dir = self.output_root / project_id / "runs" / run_id
        output_dir.mkdir(parents=True, exist_ok=True)
        analysis = {"metadata": imported.metadata.__dict__, "analysis": imported.analysis}
        (output_dir / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
        (output_dir / "manifest.json").write_text(json.dumps({
            "run_id": run_id, "project_id": project_id, "raw_data_sha256": imported.metadata.sha256,
            "status": status, "artifacts": ["analysis.json"], "origin_status": "PENDING",
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        self.store.save_analysis_artifact(run_id, "csv_analysis", analysis)
        return ExperimentRun(run_id, project_id, imported.metadata.sha256, status, output_dir)

    def prepare_origin(self, project_id: str, run_id: str, raw_data_path: Path | str):
        run = self.store.get_run(run_id)
        if run["project_id"] != project_id:
            raise ValueError("Run does not belong to this project.")
        imported = self.csv_importer.read(raw_data_path)
        if imported.metadata.sha256 != run["raw_data_sha256"]:
            raise ValueError("Selected data no longer matches the run raw-data hash.")
        output_dir = self.output_root / project_id / "runs" / run_id
        tables = prepare_origin_tables(imported, output_dir / "origin_input")
        result = self.origin_adapter.plot(output_dir, tables["curves"], tables["summary"], run_id, imported.metadata.sha256, tables.get("initial_discharge"))
        self.store.save_analysis_artifact(run_id, "origin", {"status": result.status, "reason": result.reason, "manifest": result.manifest_path.name})
        run_manifest_path = output_dir / "manifest.json"
        manifest = json.loads(run_manifest_path.read_text(encoding="utf-8"))
        manifest["origin_status"] = result.status
        manifest["origin_manifest"] = "origin/{}".format(result.manifest_path.name)
        artifacts = list(manifest.get("artifacts") or [])
        if "origin/origin_manifest.json" not in artifacts:
            artifacts.append("origin/origin_manifest.json")
        manifest["artifacts"] = artifacts
        run_manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return result

    @staticmethod
    def _is_current_web_research_cache(payload: dict | None) -> bool:
        """Reject pre-curation cache entries that cannot support the review workflow."""
        if not isinstance(payload, dict):
            return False
        online = payload.get("codex_web_research")
        return isinstance(online, dict) and "priority_sources" in online and "knowledge_digest" in online and "research_synthesis" in online and "commercial_batteries" in online

    def research_benchmarks(self, project_id: str, run_id: str, system_keywords: list[str]) -> dict:
        run = self.store.get_run(run_id)
        if run["project_id"] != project_id:
            raise ValueError("Run does not belong to this project.")
        output_dir = self.output_root / project_id / "runs" / run_id
        analysis_payload = json.loads((output_dir / "analysis.json").read_text(encoding="utf-8"))
        analysis = analysis_payload["analysis"]
        research_context = self._build_research_context(project_id, run["input_conditions"], analysis_payload)
        topic_context = " ".join(dict.fromkeys([
            str(research_context["project_name"]),
            str(research_context["material_system"]),
            *[str(term) for term in research_context["keywords"]],
            *[str(term) for term in system_keywords],
        ]))
        topics = build_benchmark_topics(topic_context, analysis)
        fingerprint = hashlib.sha256(json.dumps(topics, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        cached = self.store.get_search_cache(fingerprint)
        cache_usable = self._is_current_web_research_cache(cached)
        self._record_codex_activity(output_dir, "CODEX_WEB_SEARCH", "STARTED", "开始联网检索文献、标准和主流体系", {"topics": topics, "cache_hit": cache_usable, "stale_cache_discarded": cached is not None and not cache_usable})
        if cache_usable:
            result = dict(cached)
            result["cache_reused"] = True
        else:
            from .search import LiteratureSearchAdapter
            adapter = LiteratureSearchAdapter()
            api_records = []
            query_audit = []
            for topic in topics[:6]:
                search = adapter.search([topic], rows=5)
                query_audit.append({"query": search.query, "searched_at": search.searched_at, "status": search.status, "error": search.error, "record_count": len(search.records), "records": self._record_summaries(search.records, limit=8)})
                api_records.extend(search.records)
            codex = CodexResearchClient(str(self.project_root))
            online = codex.research_online(
                research_context,
                topics,
                api_records,
            )
            theory = None
            model = online.get("theoretical_model")
            if model:
                try:
                    theory = derive_theoretical_energy(model, analysis)
                except (KeyError, TypeError, ValueError) as error:
                    theory = {"status": "not_calculated", "reason": str(error), "model": model}
            result = {"fingerprint": fingerprint, "topics": topics, "query_audit": query_audit, "api_records": api_records, "codex_web_research": online, "literature_studies": online.get("literature_studies") or [], "theoretical_energy": theory, "cache_reused": False}
            self.store.save_search_cache(fingerprint, result)
        model = (result.get("codex_web_research") or {}).get("theoretical_model")
        if model:
            try:
                result["theoretical_energy"] = derive_theoretical_energy(model, analysis)
            except (TypeError, ValueError) as error:
                result["theoretical_energy"] = {"status": "not_calculated", "reason": str(error), "model": model}
        result.setdefault("literature_studies", (result.get("codex_web_research") or {}).get("literature_studies") or [])
        (output_dir / "benchmark_research.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        online = result.get("codex_web_research") or {}
        digest_preview = [{key: item.get(key) for key in ("title", "priority", "claim", "question", "finding", "how_to_borrow", "source_urls") if item.get(key)} for item in (online.get("knowledge_digest") or [])[:6]]
        priority_sources = [{key: item.get(key) for key in ("title", "url", "why_relevant") if item.get(key)} for item in (online.get("priority_sources") or [])[:8]]
        self._record_codex_activity(output_dir, "CODEX_WEB_SEARCH", "COMPLETED", "联网检索完成，结果已保存", {
            "topics": result.get("topics") or [],
            "query_audit": result.get("query_audit") or [],
            "api_record_count": len(result.get("api_records") or []),
            "api_records": self._record_summaries(result.get("api_records") or []),
            "codex_source_count": len(online.get("sources") or []),
            "priority_sources": priority_sources,
            "knowledge_digest": digest_preview,
            "mainstream_system_count": len(online.get("mainstream_systems") or []),
            "standard_count": len(online.get("standards") or []),
            "literature_study_count": len(online.get("literature_studies") or []),
            "theoretical_model_found": bool(online.get("theoretical_model")),
        })
        self._update_manifest(output_dir, artifact="benchmark_research.json", benchmark_status="CACHED" if result.get("cache_reused") else "RESEARCHED", theoretical_energy_status=(result.get("theoretical_energy") or {}).get("status"))
        return result

    def evaluate_with_codex(self, project_id: str, run_id: str, thread_id: str | None = None):
        run = self.store.get_run(run_id)
        if run["project_id"] != project_id:
            raise ValueError("Run does not belong to this project.")
        output_dir = self.output_root / project_id / "runs" / run_id
        analysis_path = output_dir / "analysis.json"
        origin_path = output_dir / "origin" / "origin_manifest.json"
        if not analysis_path.is_file() or not origin_path.is_file():
            raise ValueError("Run requires deterministic analysis and an Origin manifest before Codex assessment.")
        analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
        feature_packet = build_codex_feature_packet(analysis)
        (output_dir / "codex_input_manifest.json").write_text(json.dumps({"consumer": "CodexResearchClient.evaluate_project", "source_sha256": feature_packet.get("source_sha256"), "fields": sorted(feature_packet.keys()), "point_level_input_sent": False, "row_level_input_sent": False}, ensure_ascii=False, indent=2), encoding="utf-8")
        origin = json.loads(origin_path.read_text(encoding="utf-8"))
        benchmark_path = output_dir / "benchmark_research.json"
        benchmark = json.loads(benchmark_path.read_text(encoding="utf-8")) if benchmark_path.is_file() else {}
        approved_claims = self.store.list_approved_claims(project_id)
        self._record_codex_activity(output_dir, "CODEX_ASSESSMENT", "STARTED", "开始基于特征包、Origin 状态和批准证据评估课题", {
            "approved_claim_count": len(approved_claims),
            "feature_fields": sorted(feature_packet.keys()),
            "origin_status": origin.get("status"),
            "online_source_count": len((benchmark.get("codex_web_research") or {}).get("sources") or []),
        })
        client = CodexResearchClient(str(self.project_root))
        try:
            next_thread_id, guidance = client.evaluate_project(
                self._build_research_context(project_id, run["input_conditions"], analysis),
                feature_packet,
                origin,
                approved_claims,
                online_research=benchmark.get("codex_web_research") or {},
                theoretical_energy=benchmark.get("theoretical_energy") or {},
                thread_id=thread_id,
            )
        except Exception as error:
            self._record_codex_activity(output_dir, "CODEX_ASSESSMENT", "FAILED", "Codex 课题评估失败", {"error": str(error)})
            raise
        (output_dir / "guidance.json").write_text(json.dumps({"thread_id": next_thread_id, "basis": {"analysis": "analysis.json", "origin": "origin/origin_manifest.json", "benchmark_research": "benchmark_research.json", "approved_claim_count": len(approved_claims)}, "guidance": guidance}, ensure_ascii=False, indent=2), encoding="utf-8")
        self._record_codex_activity(output_dir, "CODEX_ASSESSMENT", "COMPLETED", "Codex 已生成课题判断和下一轮实验建议", {
            "assessment": str(guidance.get("assessment") or "")[:1200],
            "data_fact_count": len(guidance.get("data_facts") or []),
            "hypothesis_count": len(guidance.get("hypotheses") or []),
            "cannot_determine_count": len(guidance.get("cannot_determine") or []),
            "benchmark_comparison_count": len(guidance.get("benchmark_comparisons") or []),
            "next_experiment_count": len(guidance.get("next_experiments") or []),
        })
        self._update_manifest(output_dir, artifact="guidance.json", codex_input_manifest="codex_input_manifest.json", codex_assessment_status="COMPLETED")
        return next_thread_id, guidance

    def run_all(
        self,
        project_id: str,
        data_path: Path | str,
        conditions: dict,
        *,
        pdf_path: Path | str | None = None,
        keywords: list[str] | None = None,
        use_codex_candidates: bool = True,
        use_codex_assessment: bool = True,
        use_online_research: bool = True,
        progress=None,
    ) -> dict:
        """Run the single safe workflow, retaining partial products on any stage failure."""
        emit = progress or (lambda _stage, _message, _details: None)
        result: dict = {"project_id": project_id, "search_status": "SKIPPED", "document": None, "candidate_count": 0, "raw_candidate_count": 0, "candidate_rejections": [], "knowledge_review": None, "run": None, "origin": None, "guidance": None, "report": None, "errors": []}
        terms = list(keywords or [])
        benchmark: dict = {}
        pdf_thread_id: str | None = None
        search_audit: dict = {"status": "SKIPPED", "keywords": terms}
        pdf_audit: dict = {"status": "SKIPPED"}
        if terms:
            emit("SEARCH", "正在检索可追溯文献元数据…", {"keywords": terms})
            try:
                search = self.search_literature(project_id, terms)
                result["search_status"] = search.status
                search_audit = {"status": search.status, "query": search.query, "record_count": len(search.records), "records": self._record_summaries(search.records, limit=12), "error": search.error}
                emit("SEARCH", "检索完成：{}".format(search.status), search_audit)
            except Exception as error:
                result["search_status"] = "SEARCH_PARTIAL"
                search_audit = {"status": "SEARCH_PARTIAL", "keywords": terms, "error": str(error)}
                result["errors"].append("Search: {}".format(error))
                emit("SEARCH", "检索未完成，继续本地 PDF 流程。", search_audit)
        if pdf_path:
            emit("PDF", "正在校验并逐页读取本地 PDF…", {"file": Path(pdf_path).name})
            try:
                document = self.learn_local_pdf(project_id, pdf_path)
                result["document"] = document
                emit("PDF", "PDF 覆盖完成：{}/{} 页，{} 个证据片段。".format(len(document.coverage_manifest["text_pages"]), document.page_count, document.coverage_manifest["span_count"]), dict(document.coverage_manifest))
                if use_codex_candidates and self.was_new_source(document.source_id):
                    emit("CODEX_PDF", "Codex 正在从受限页码证据提炼候选知识…", {"source_id": document.source_id})
                    pdf_thread_id, claims, rejected = self.extract_pdf_candidates(project_id, document.source_id)
                    result["raw_candidate_count"] = len(claims)
                    result["candidate_rejections"] = rejected
                    pdf_audit = {"status": "COMPLETED", "source_id": document.source_id, "raw_candidate_count": len(claims), "rejected_count": len(rejected), "rejected": rejected}
                    emit("CODEX_PDF", "Codex 原始证据提取完成：{} 条已进入内部筛选，{} 条拒收。".format(len(claims), len(rejected)), pdf_audit)
                elif use_codex_candidates:
                    pdf_audit = {"status": "REUSED", "source_id": document.source_id}
                    emit("CODEX_PDF", "相同 PDF 哈希已复用，未重复调用 Codex。", pdf_audit)
            except Exception as error:
                pdf_audit = {"status": "FAILED", "error": str(error)}
                result["errors"].append("PDF: {}".format(error))
                emit("PDF", "PDF 学习失败，保留已完成阶段并继续数据分析。", {"status": "PDF_INCOMPLETE", "error": str(error)})
        emit("DATA", "正在确定性解析实验数据和异常…", {"file": Path(data_path).name})
        run = self.analyze_data(project_id, data_path, conditions)
        result["run"] = run
        analysis = json.loads((run.output_dir / "analysis.json").read_text(encoding="utf-8"))
        self._record_codex_activity(run.output_dir, "RUN", "STARTED", "本轮 Codex 可观测记录已启用", {"keywords": terms, "search": search_audit, "pdf": pdf_audit, "data_source_sha256": run.raw_data_sha256})
        if search_audit.get("status") != "SKIPPED":
            self._record_codex_activity(run.output_dir, "METADATA_SEARCH", search_audit.get("status", "UNKNOWN"), "题录元数据检索状态：{}".format(search_audit.get("status")), search_audit)
        if pdf_audit.get("status") != "SKIPPED":
            self._record_codex_activity(run.output_dir, "CODEX_PDF", pdf_audit.get("status", "UNKNOWN"), "本地 PDF 候选提取状态：{}".format(pdf_audit.get("status")), pdf_audit)
        emit("DATA", "数据分析完成：{} 行，{} 个候选容量段。".format(analysis["analysis"]["row_count"], len(analysis["analysis"]["segments"])), analysis["analysis"])
        if use_online_research:
            emit("BENCHMARK_RESEARCH", "正在按已检测性能检索主流体系、标准和理论能量依据…", {"metrics": analysis["analysis"].get("gcd_summary") or {}})
            try:
                benchmark = self.research_benchmarks(project_id, run.run_id, terms)
                emit("BENCHMARK_RESEARCH", "Codex 联网研究完成；检索知识已写入可复用缓存。", {"topics": benchmark.get("topics"), "cache_reused": benchmark.get("cache_reused"), "theoretical_energy": benchmark.get("theoretical_energy")})
            except Exception as error:
                self._record_codex_activity(run.output_dir, "CODEX_WEB_SEARCH", "FAILED", "联网检索失败", {"error": str(error), "topics": build_benchmark_topics(" ".join(terms), analysis["analysis"])})
                result["errors"].append("Benchmark research: {}".format(error))
                emit("BENCHMARK_RESEARCH", "主流体系联网研究未完成，继续 Origin 和本轮数据判断。", {"error": str(error)})
        if use_codex_candidates or use_online_research:
            emit("CODEX_KNOWLEDGE", "Codex 正在筛选关键文献并提炼少量待审批知识…", {"raw_candidate_count": result["raw_candidate_count"], "online_digest_count": len((benchmark.get("codex_web_research") or {}).get("knowledge_digest") or [])})
            try:
                review = self.curate_literature(
                    project_id,
                    run.run_id,
                    benchmark.get("codex_web_research") or {},
                    pdf_thread_id,
                    self._build_research_context(project_id, conditions, analysis),
                )
                result["knowledge_review"] = review
                result["candidate_count"] = len(review.get("claims") or [])
                emit("CODEX_KNOWLEDGE", "Codex 精选完成：{} 条待审批知识，原始候选不再展示。".format(result["candidate_count"]), {"status": review.get("status"), "research_gaps": review.get("research_gaps") or []})
            except Exception as error:
                result["errors"].append("Literature synthesis: {}".format(error))
                emit("CODEX_KNOWLEDGE", "Codex 精选未完成，原始候选仍保留在审计库但不进入正式结论。", {"error": str(error)})
        emit("ORIGIN", "正在调用 Origin 生成可编辑工程和正式图片…", {"run_id": run.run_id})
        origin = self.prepare_origin(project_id, run.run_id, data_path)
        result["origin"] = origin
        emit("ORIGIN", "Origin 状态：{}。".format(origin.status), {"status": origin.status, "reason": origin.reason})
        if use_codex_assessment:
            emit("CODEX_ASSESSMENT", "Codex 正在评估本轮数据和课题，不使用未批准文献作正式比较…", {"run_id": run.run_id})
            try:
                _thread_id, guidance = self.evaluate_with_codex(project_id, run.run_id)
                result["guidance"] = guidance
                emit("CODEX_ASSESSMENT", "Codex 课题评估完成：{}".format(guidance["assessment"][:100]), guidance)
            except Exception as error:
                result["errors"].append("Codex assessment: {}".format(error))
                emit("CODEX_ASSESSMENT", "Codex 评估未通过结构校验，报告保留确定性结果。", {"error": str(error)})
        self._update_manifest(run.output_dir, errors=result["errors"], completed_stages=["SEARCH", "PDF", "DATA", "BENCHMARK_RESEARCH", "CODEX_KNOWLEDGE", "ORIGIN", "CODEX_ASSESSMENT", "REPORT"])
        result["report"] = self.build_report(project_id, run.run_id)
        emit("REPORT", "图文报告已生成。", {"report": result["report"].name, "errors": result["errors"]})
        return result

    @staticmethod
    def _derive_literature_studies(claims: list) -> list[dict]:
        studies = []
        seen = set()
        for claim in claims:
            text = str(getattr(claim, "text", ""))
            lowered = text.casefold()
            if any(token in lowered for token in ("xanes", "hrtem", "selected-area electron diffraction", "pair distribution")):
                key = "structure_and_interface_characterization"
                if key not in seen:
                    studies.append({
                        "study": "固态电解质结构与界面表征",
                        "tests": ["SAED", "HRTEM", "PDF/rPDF", "Zr K-edge XANES"],
                        "question": "这些测试用于区分局域结构、非晶/纳米晶特征以及循环或环境处理后的局域化学变化。",
                        "finding": "当前已批准文献方法条目确认了这组表征被用于该类固态电解质研究；具体数值结果仍应回到原文图表核对。",
                        "how_to_borrow": "对 P₂O₅–LiTaCl₆ 体系优先设计循环前后和环境处理前后的 XPS/XANES；若需要局域结构证据，再补充 HRTEM/SAED 或 PDF 分析，并把状态与电化学容量段绑定。",
                        "source_urls": [], "source_ids": [getattr(claim, "source_id", "")], "evidence_status": "approved_local_pdf",
                    })
                    seen.add(key)
            if "dry-room" in lowered or "dew point" in lowered:
                key = "dry_room_stability"
                if key not in seen:
                    studies.append({
                        "study": "干燥空气/湿度稳定性",
                        "tests": ["受控露点暴露", "暴露前后电化学曲线", "界面/局域化学表征"],
                        "question": "环境暴露是否改变固态电解质、界面极化或后续电池性能。",
                        "finding": "已批准文献方法条目确认了受控露点暴露与复合正极测试设计；环境暴露后的具体性能变化应以原文结果页核对。",
                        "how_to_borrow": "为 LiTaCl₆ 设定露点、暴露时间、样品封装和对照组；比较暴露前后极化、平均放电电压、容量保持率，并用 XPS/XANES 定位界面变化。",
                        "source_urls": [], "source_ids": [getattr(claim, "source_id", "")], "evidence_status": "approved_local_pdf",
                    })
                    seen.add(key)
        return studies

    def build_report(self, project_id: str, run_id: str) -> Path:
        run = self.store.get_run(run_id)
        if run["project_id"] != project_id:
            raise ValueError("Run does not belong to this project.")
        claims = self.store.list_approved_claims(project_id)
        pending_curated = self.store.list_review_queue(project_id)
        project = next((item for item in self.store.list_projects() if item["project_id"] == project_id), None)
        if project is None:
            raise KeyError("Project does not exist.")
        output_dir = self.output_root / project_id / "runs" / run_id
        origin_status = "PENDING"
        origin_reason = None
        origin_manifest = output_dir / "origin" / "origin_manifest.json"
        if origin_manifest.is_file():
            try:
                origin_payload = json.loads(origin_manifest.read_text(encoding="utf-8"))
                origin_status = str(origin_payload.get("status") or "PLOT_BLOCKED")
                origin_reason = origin_payload.get("reason")
            except (OSError, json.JSONDecodeError):
                origin_status = "PLOT_BLOCKED"
                origin_reason = "Origin manifest is unreadable."
        status = "PLOT_BLOCKED" if origin_status == "PLOT_BLOCKED" else "REPORT_READY" if claims else "REPORT_READY_WITH_NO_COMPARABLE_PAPERS"
        summary = {
            "status": status,
            "project_id": project_id,
            "project_name": project["name"],
            "material_system": project["material_system"],
            "keywords": project["keywords"],
            "run_id": run_id,
            "raw_data_sha256": run["raw_data_sha256"],
            "conditions": run["input_conditions"],
            "origin_status": origin_status,
            "origin_reason": origin_reason,
            "codex_curated_pending_count": len(pending_curated),
            "limitations": ([] if claims else ["No approved literature claims; formal performance comparison is blocked."]) + (["Origin formal figures are blocked."] if origin_status == "PLOT_BLOCKED" else []),
        }
        guidance = None
        guidance_path = output_dir / "guidance.json"
        if guidance_path.is_file():
            try:
                guidance = (json.loads(guidance_path.read_text(encoding="utf-8")) or {}).get("guidance")
            except (OSError, json.JSONDecodeError):
                guidance = None
        analysis = {}
        analysis_path = output_dir / "analysis.json"
        if analysis_path.is_file():
            analysis = (json.loads(analysis_path.read_text(encoding="utf-8")) or {}).get("analysis") or {}
        benchmark = {}
        benchmark_path = output_dir / "benchmark_research.json"
        if benchmark_path.is_file():
            benchmark = json.loads(benchmark_path.read_text(encoding="utf-8")) or {}
        review_path = output_dir / "literature_review.json"
        if review_path.is_file():
            benchmark["codex_review"] = json.loads(review_path.read_text(encoding="utf-8")) or {}
        activity_path = output_dir / "codex_activity.json"
        if activity_path.is_file():
            benchmark["codex_activity"] = json.loads(activity_path.read_text(encoding="utf-8")) or []
        codex_failures = [
            {"stage": row.get("stage"), "message": row.get("message"), "error": (row.get("details") or {}).get("error")}
            for row in benchmark.get("codex_activity") or []
            if row.get("status") == "FAILED"
        ]
        if guidance is None and codex_failures:
            status = "CODEX_FAILED"
            summary["status"] = status
            summary["codex_failures"] = codex_failures
        if not benchmark.get("literature_studies"):
            benchmark["literature_studies"] = self._derive_literature_studies(claims)
        figures = []
        for name in ("charge_discharge.png", "cycling.png"):
            if (output_dir / "figures" / name).is_file():
                figures.append("figures/{}".format(name))
        target = output_dir / "research_decision_report.html"
        written = write_report(target, summary, claims, [], guidance=guidance, analysis=analysis, benchmark=benchmark, figures=figures)
        self._update_manifest(output_dir, artifact="research_decision_report.html", status=status, report_status=status)
        return written
