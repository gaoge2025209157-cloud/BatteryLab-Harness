"""Single, staged orchestration for the Harness-v2 research workflow."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from .analysis_dispatch import analyze_experiment, build_analysis_feature_packet, summarize_analysis_replicates
from .benchmarks import build_benchmark_topics
from .cache_policy import CachePolicy, DEFAULT_CACHE_TTL_SECONDS, fingerprint
from .codex_client import ADAPTER_VERSION, PROMPT_VERSIONS, CodexResearchClient, codex_model_identity
from .context_builder import ContextBuilder, ContextBuildResult, stable_hash
from .csv_importer import GcdCsvImporter
from .gcd_metrics import analyze_gcd_metrics
from .origin_adapter import OriginAdapter, OriginPlotResult
from .origin_data import prepare_origin_tables
from .pdf_reader import LocalPdfReader
from .report import write_report
from .search import SEARCH_ADAPTER_VERSION
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
        config: dict = {}
        config_path = self.project_root / "config.json"
        if config_path.is_file():
            try:
                config = json.loads(config_path.read_text(encoding="utf-8")) or {}
            except json.JSONDecodeError as error:
                raise ValueError("config.json is not valid JSON.") from error
            origin_executable = config.get("origin_executable")
        context_config = dict(config.get("context_management") or {})
        self.config = config
        self.cache_policy = CachePolicy(
            ttl_seconds=int(context_config.get("search_cache_ttl_seconds", DEFAULT_CACHE_TTL_SECONDS))
        )
        allowed_context_keys = {
            "max_input_tokens", "reserved_output_tokens", "max_approved_claims",
            "max_candidate_claims", "max_metadata_records",
        }
        self.context_builder = ContextBuilder(**{
            key: value for key, value in context_config.items() if key in allowed_context_keys
        })
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

    def _invocation_recorder(self, project_id: str, stage: str, run_id: str | None = None):
        """Return a recorder that appends to SQLite and a unique audit file."""
        if run_id:
            base = self.output_root / project_id / "runs" / run_id
        else:
            base = self.output_root / project_id
        directory = base / "codex_invocations"

        def record(payload: dict) -> None:
            stored = dict(payload)
            stored["project_id"] = project_id
            stored["run_id"] = run_id
            stored["stage"] = stage
            invocation_id = self.store.save_codex_invocation(project_id, run_id, stage, stored)
            directory.mkdir(parents=True, exist_ok=True)
            relative = "codex_invocations/{}.json".format(invocation_id)
            path = directory / "{}.json".format(invocation_id)
            with path.open("x", encoding="utf-8") as stream:
                json.dump(stored, stream, ensure_ascii=False, sort_keys=True, indent=2)
            if run_id and (base / "manifest.json").is_file():
                self._update_manifest(base, artifact=relative)

        return record

    @staticmethod
    def _record_summaries(records: list[dict], limit: int = 20) -> list[dict]:
        summaries = []
        for row in records[:limit]:
            summaries.append({
                key: row.get(key) for key in ("title", "source", "source_level", "doi", "url", "openalex_id") if row.get(key)
            })
        return summaries

    def _context_task(self, project_id: str, stage: str, run_id: str | None = None, source_id: str | None = None) -> dict:
        state = self.store.get_research_state(project_id)
        goals = {
            "pdf_candidate_extraction": "从本地PDF的受限证据片段中提取可追溯候选知识，不形成已批准结论。",
            "online_research": "围绕当前确定性数据特征和课题问题检索相关学术来源，明确证据边界。",
            "literature_synthesis": "从本地与联网候选证据中筛选少量高价值知识，提交研究人员审核。",
            "codex_assessment": "结合确定性数据、已批准知识和明确标注的候选证据，形成竞争解释与下一轮判别实验。",
        }
        criteria = {
            "pdf_candidate_extraction": ["每项候选知识引用有效证据片段", "候选知识保持candidate状态", "不编造PDF外信息"],
            "online_research": ["来源可追溯", "检索围绕当前数据现象", "明确摘要或网页线索的候选属性"],
            "literature_synthesis": ["最多保留六项高价值候选", "说明研究问题、测试、发现和借鉴方式", "所有结果等待人工审核"],
            "codex_assessment": ["区分数据事实、批准知识和候选解释", "每项假设包含支持、反对与反证实验", "下一轮实验改变一个变量并说明预期证据"],
        }
        suffix = source_id or run_id or project_id
        safe_suffix = "".join(char if char.isalnum() or char in "._-" else "-" for char in str(suffix))
        return {
            "task_id": "{}-{}".format(stage, safe_suffix),
            "stage": stage,
            "goal": goals.get(stage, "为当前课题构建受控、可追溯的模型上下文。"),
            "success_criteria": criteria.get(stage, ["上下文可追溯", "输出符合科学边界"]),
            "current_question": state.get("next_intent") or "；".join(str(value) for value in state.get("open_questions") or []),
            "open_questions": list(state.get("open_questions") or []),
        }

    def _persist_context(self, project_id: str, stage: str, result: ContextBuildResult, run_id: str | None = None) -> tuple[Path, Path]:
        if run_id:
            base = self.output_root / project_id / "runs" / run_id
            directory = base / "contexts"
        else:
            base = None
            directory = self.output_root / project_id / "contexts"
        directory.mkdir(parents=True, exist_ok=True)
        bundle_path = directory / "{}.bundle.json".format(stage)
        manifest_path = directory / "{}.manifest.json".format(stage)
        bundle_json = json.dumps(dict(result.bundle), ensure_ascii=False, sort_keys=True, indent=2)
        manifest_json = json.dumps(dict(result.manifest), ensure_ascii=False, sort_keys=True, indent=2)
        # Compatibility pointers retain their historical names. Every build also
        # gets unique, create-only files so rebuilding a stage cannot erase audit history.
        bundle_path.write_text(bundle_json, encoding="utf-8")
        manifest_path.write_text(manifest_json, encoding="utf-8")
        record_id = str(result.manifest.get("record_id") or "")
        if not record_id:
            raise ValueError("Context manifest requires an immutable record_id.")
        versions = directory / "versions"
        versions.mkdir(parents=True, exist_ok=True)
        version_bundle = versions / "{}.bundle.json".format(record_id)
        version_manifest = versions / "{}.manifest.json".format(record_id)
        with version_bundle.open("x", encoding="utf-8") as stream:
            stream.write(bundle_json)
        with version_manifest.open("x", encoding="utf-8") as stream:
            stream.write(manifest_json)
        self.store.save_context_record(project_id, run_id, stage, dict(result.manifest))
        if base is not None:
            bundle_ref = "contexts/{}.bundle.json".format(stage)
            manifest_ref = "contexts/{}.manifest.json".format(stage)
            version_bundle_ref = "contexts/versions/{}.bundle.json".format(record_id)
            version_manifest_ref = "contexts/versions/{}.manifest.json".format(record_id)
            self._update_manifest(base, artifact=bundle_ref)
            self._update_manifest(base, artifact=manifest_ref)
            self._update_manifest(base, artifact=version_bundle_ref)
            self._update_manifest(base, artifact=version_manifest_ref, **{
                "{}_context_hash".format(stage): result.context_hash,
                "{}_context_tokens_estimated".format(stage): result.estimated_input_tokens,
                "{}_context_record_id".format(stage): record_id,
            })
        return bundle_path, manifest_path

    def _build_managed_context(
        self,
        project_id: str,
        stage: str,
        *,
        run_id: str | None = None,
        source_id: str | None = None,
        conditions: dict | None = None,
        analysis: dict | None = None,
        candidate_metadata: list[dict] | None = None,
        online_research: dict | None = None,
        origin_status: dict | None = None,
        theoretical_energy: dict | None = None,
    ) -> ContextBuildResult:
        project_context = self._build_research_context(project_id, conditions, analysis)
        result = self.context_builder.build(
            stage=stage,
            task=self._context_task(project_id, stage, run_id=run_id, source_id=source_id),
            project_context=project_context,
            claims=self.store.list_claims(project_id),
            research_memory=self.store.get_research_state(project_id),
            candidate_metadata=candidate_metadata or [],
            online_research=online_research or {},
            origin_status=origin_status or {},
            theoretical_energy=theoretical_energy or {},
            permissions={
                "network_access": stage == "online_research",
                "raw_data_access": False,
                "write_original_data": False,
                "approve_knowledge": False,
                "control_equipment": False,
            },
            model_identity=codex_model_identity(stage),
            run_id=run_id,
        )
        self._persist_context(project_id, stage, result, run_id=run_id)
        return result

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
            context["deterministic_features"] = build_analysis_feature_packet(analysis)
        return context

    def search_literature(self, project_id: str, keywords: list[str]):
        from .search import LiteratureSearchAdapter
        result = LiteratureSearchAdapter().search(keywords)
        target = self.output_root / project_id / "searches"
        target.mkdir(parents=True, exist_ok=True)
        (target / "literature_search.json").write_text(json.dumps({
            "query": result.query,
            "searched_at": result.searched_at,
            "status": result.status,
            "error": result.error,
            "source_status": result.source_status,
            "records": result.records,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        return result

    def extract_pdf_candidates(self, project_id: str, source_id: str, thread_id: str | None = None):
        spans = self.store.list_source_spans(source_id)
        managed_context = self._build_managed_context(
            project_id,
            "pdf_candidate_extraction",
            source_id=source_id,
        )
        client = CodexResearchClient(
            str(self.project_root),
            invocation_recorder=self._invocation_recorder(project_id, "pdf_candidate_extraction"),
        )
        returned_thread_id, claims, rejected = client.extract_candidates(
            managed_context.bundle,
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
        conditions = None
        analysis_payload = None
        context_run_id = run_id
        if run_id:
            try:
                run = self.store.get_run(run_id)
            except KeyError:
                context_run_id = None
            else:
                conditions = run["input_conditions"]
                analysis_path = self.output_root / project_id / "runs" / run_id / "analysis.json"
                if analysis_path.is_file():
                    analysis_payload = json.loads(analysis_path.read_text(encoding="utf-8"))
        managed_context = self._build_managed_context(
            project_id,
            "literature_synthesis",
            run_id=context_run_id,
            conditions=conditions,
            analysis=analysis_payload,
            online_research=online,
        )
        client = CodexResearchClient(
            str(self.project_root),
            invocation_recorder=self._invocation_recorder(project_id, "literature_synthesis", context_run_id),
        )
        try:
            returned_thread_id, digest, claims, rejected = client.synthesize_literature(
                managed_context.bundle,
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

    @staticmethod
    def _source_sha256(source: Any) -> str:
        if isinstance(source, (str, Path)):
            return hashlib.sha256(Path(source).read_bytes()).hexdigest()
        encoded = json.dumps(source, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def analyze_data(
        self,
        project_id: str,
        path: Any,
        conditions: dict,
        analysis_type: str = "gcd",
        *,
        _run_id: str | None = None,
    ) -> ExperimentRun:
        """Run deterministic method dispatch and persist the common analysis envelope."""
        method = str(analysis_type or "gcd").strip().casefold()
        analysis = analyze_experiment(method, path, conditions)
        raw_hash = str((analysis.get("metadata") or {}).get("sha256") or self._source_sha256(path))
        analysis.setdefault("metadata", {})["sha256"] = raw_hash
        approved = self.store.list_approved_claims(project_id)
        legacy_status = "DATA_ANALYZED" if approved else "NEEDS_REVIEW"
        run_id = _run_id or self.store.create_run(project_id, raw_hash, dict(conditions), legacy_status)
        if _run_id:
            run = self.store.get_run(run_id)
            if run["project_id"] != project_id or run["raw_data_sha256"] != raw_hash:
                raise ValueError("Selected data no longer matches the run raw-data hash.")
        output_dir = self.output_root / project_id / "runs" / run_id
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
        manifest_path = output_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
        manifest.update({
            "run_id": run_id,
            "project_id": project_id,
            "raw_data_sha256": raw_hash,
            "analysis_type": method,
            "status": manifest.get("status", legacy_status),
            "origin_status": manifest.get("origin_status", "PENDING"),
        })
        artifacts = list(manifest.get("artifacts") or [])
        if "analysis.json" not in artifacts:
            artifacts.append("analysis.json")
        manifest["artifacts"] = artifacts
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        self.store.save_analysis_artifact(run_id, "{}_analysis".format(method), analysis)
        return ExperimentRun(run_id, project_id, raw_hash, legacy_status, output_dir)

    def prepare_origin(self, project_id: str, run_id: str, raw_data_path: Path | str):
        run = self.store.get_run(run_id)
        if run["project_id"] != project_id:
            raise ValueError("Run does not belong to this project.")
        output_dir = self.output_root / project_id / "runs" / run_id
        analysis_path = output_dir / "analysis.json"
        envelope = json.loads(analysis_path.read_text(encoding="utf-8")) if analysis_path.is_file() else {}
        method = str(envelope.get("analysis_type") or "gcd").casefold()
        if method != "gcd":
            origin_dir = output_dir / "origin"
            origin_dir.mkdir(parents=True, exist_ok=True)
            manifest_path = origin_dir / "origin_manifest.json"
            payload = {
                "run_id": run_id,
                "raw_data_sha256": run["raw_data_sha256"],
                "analysis_type": method,
                "status": "PLOT_NOT_AVAILABLE_FOR_METHOD",
                "reason": "The legacy Origin engine is available only for GCD analysis.",
                "figures": [],
            }
            manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            result = OriginPlotResult(
                "PLOT_NOT_AVAILABLE_FOR_METHOD", manifest_path,
                origin_dir / "electrochemistry.opju", tuple(), payload["reason"],
            )
        else:
            imported = self.csv_importer.read(raw_data_path, conditions=run["input_conditions"])
            if imported.metadata.sha256 != run["raw_data_sha256"]:
                raise ValueError("Selected data no longer matches the run raw-data hash.")
            persisted = envelope.get("analysis") if isinstance(envelope.get("analysis"), dict) else None
            if persisted and persisted.get("segments"):
                imported = replace(imported, analysis=dict(persisted))
            tables = prepare_origin_tables(imported, output_dir / "origin_input")
            result = self.origin_adapter.plot(
                output_dir, tables["curves"], tables["summary"], run_id,
                imported.metadata.sha256, tables.get("initial_discharge"),
            )
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
        analysis_type = str(analysis_payload.get("analysis_type") or "gcd").casefold()
        research_context = self._build_research_context(project_id, run["input_conditions"], analysis_payload)
        topic_context = " ".join(dict.fromkeys([
            str(research_context["project_name"]),
            str(research_context["material_system"]),
            *[str(term) for term in research_context["keywords"]],
            *[str(term) for term in system_keywords],
        ]))
        topics = build_benchmark_topics(topic_context, analysis, analysis_type)
        cache_key = fingerprint({"benchmark_topics": topics})
        prompt_version = PROMPT_VERSIONS.get("online_research", "unknown")
        adapter_version = {
            "codex_adapter": ADAPTER_VERSION,
            "search_adapter": SEARCH_ADAPTER_VERSION,
        }
        model_identity = codex_model_identity("online_research")
        context_identity = stable_hash({
            "research_context": research_context,
            "knowledge": [claim.to_dict() for claim in self.store.list_claims(project_id)],
            "research_memory": self.store.get_research_state(project_id),
            "context_policy": {
                "max_input_tokens": self.context_builder.max_input_tokens,
                "reserved_output_tokens": self.context_builder.reserved_output_tokens,
                "max_approved_claims": self.context_builder.max_approved_claims,
                "max_candidate_claims": self.context_builder.max_candidate_claims,
                "max_metadata_records": self.context_builder.max_metadata_records,
            },
        })
        cached_entry = self.store.get_search_cache(cache_key)
        cache_status = self.cache_policy.classify(
            cached_entry,
            prompt=prompt_version,
            adapter=adapter_version,
            model=model_identity,
            context=context_identity,
            topic=topics,
        )
        cache_usable = cache_status == "fresh" and self._is_current_web_research_cache(cached_entry.get("payload"))
        if cache_status == "fresh" and not cache_usable:
            cache_status = "incompatible"
        self._record_codex_activity(output_dir, "CODEX_WEB_SEARCH", "STARTED", "开始联网检索文献、标准和主流体系", {
            "topics": topics,
            "cache_status": cache_status,
            "cache_hit": cache_usable,
            "cache_expired": cache_status == "stale",
            "cache_incompatible": cache_status == "incompatible",
        })
        if cache_usable:
            result = dict(cached_entry["payload"])
            result["cache_reused"] = True
        else:
            from .search import LiteratureSearchAdapter
            adapter = LiteratureSearchAdapter()
            api_records = []
            query_audit = []
            for topic in topics[:6]:
                search = adapter.search([topic], rows=5)
                query_audit.append({
                    "query": search.query,
                    "searched_at": search.searched_at,
                    "status": search.status,
                    "error": search.error,
                    "source_status": dict(getattr(search, "source_status", {}) or {}),
                    "record_count": len(search.records),
                    "records": self._record_summaries(search.records, limit=8),
                })
                api_records.extend(search.records)
            managed_context = self._build_managed_context(
                project_id,
                "online_research",
                run_id=run_id,
                conditions=run["input_conditions"],
                analysis=analysis_payload,
                candidate_metadata=api_records,
            )
            codex = CodexResearchClient(
                str(self.project_root),
                invocation_recorder=self._invocation_recorder(project_id, "online_research", run_id),
            )
            online = codex.research_online(
                managed_context.bundle,
                topics,
                api_records,
            )
            theory = None
            model = online.get("theoretical_model")
            if analysis_type == "gcd" and model:
                try:
                    theory = derive_theoretical_energy(model, analysis)
                except (KeyError, TypeError, ValueError) as error:
                    theory = {"status": "not_calculated", "reason": str(error), "model": model}
            result = {"fingerprint": cache_key, "topics": topics, "query_audit": query_audit, "api_records": api_records, "codex_web_research": online, "literature_studies": online.get("literature_studies") or [], "theoretical_energy": theory, "cache_reused": False, "cache_status": cache_status}
            cache_entry = self.cache_policy.create(
                result,
                prompt=prompt_version,
                adapter=adapter_version,
                model=model_identity,
                context=context_identity,
                topic=topics,
            )
            self.store.save_search_cache(cache_key, cache_entry)
        model = (result.get("codex_web_research") or {}).get("theoretical_model")
        if analysis_type == "gcd" and model:
            try:
                result["theoretical_energy"] = derive_theoretical_energy(model, analysis)
            except (TypeError, ValueError) as error:
                result["theoretical_energy"] = {"status": "not_calculated", "reason": str(error), "model": model}
        elif analysis_type != "gcd":
            result["theoretical_energy"] = None
        result["cache_status"] = cache_status
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
        feature_packet = build_analysis_feature_packet(analysis)
        origin = json.loads(origin_path.read_text(encoding="utf-8"))
        benchmark_path = output_dir / "benchmark_research.json"
        benchmark = json.loads(benchmark_path.read_text(encoding="utf-8")) if benchmark_path.is_file() else {}
        approved_claims = self.store.list_approved_claims(project_id)
        managed_context = self._build_managed_context(
            project_id,
            "codex_assessment",
            run_id=run_id,
            conditions=run["input_conditions"],
            analysis=analysis,
            online_research=benchmark.get("codex_web_research") or {},
            origin_status=origin,
            theoretical_energy=benchmark.get("theoretical_energy") or {},
        )
        (output_dir / "codex_input_manifest.json").write_text(json.dumps({
            "consumer": "CodexResearchClient.evaluate_project",
            "managed_context": "contexts/codex_assessment.bundle.json",
            "context_manifest": "contexts/codex_assessment.manifest.json",
            "context_hash": managed_context.context_hash,
            "source_sha256": feature_packet.get("source_sha256"),
            "fields": sorted(managed_context.bundle.keys()),
            "point_level_input_sent": False,
            "row_level_input_sent": False,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        self._record_codex_activity(output_dir, "CODEX_ASSESSMENT", "STARTED", "开始基于受控上下文、Origin状态和分级证据评估课题", {
            "approved_claim_count": len(approved_claims),
            "context_hash": managed_context.context_hash,
            "context_tokens_estimated": managed_context.estimated_input_tokens,
            "origin_status": origin.get("status"),
            "online_source_count": len((benchmark.get("codex_web_research") or {}).get("sources") or []),
        })
        client = CodexResearchClient(
            str(self.project_root),
            invocation_recorder=self._invocation_recorder(project_id, "codex_assessment", run_id),
        )
        try:
            next_thread_id, guidance = client.evaluate_project(
                managed_context.bundle,
                feature_packet,
                origin,
                approved_claims,
                online_research=benchmark.get("codex_web_research") or {},
                theoretical_energy=benchmark.get("theoretical_energy") or {},
                thread_id=thread_id,
            )
        except Exception as error:
            self._record_codex_activity(output_dir, "CODEX_ASSESSMENT", "FAILED", "Codex课题评估失败", {"error": str(error), "context_hash": managed_context.context_hash})
            raise
        research_state = self.store.record_guidance_state(project_id, run_id, guidance)
        (output_dir / "guidance.json").write_text(json.dumps({
            "thread_id": next_thread_id,
            "basis": {
                "analysis": "analysis.json",
                "origin": "origin/origin_manifest.json",
                "benchmark_research": "benchmark_research.json",
                "managed_context": "contexts/codex_assessment.bundle.json",
                "context_manifest": "contexts/codex_assessment.manifest.json",
                "context_hash": managed_context.context_hash,
                "approved_claim_count": len(approved_claims),
            },
            "research_state_version": research_state.get("row_version"),
            "guidance": guidance,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        self._record_codex_activity(output_dir, "CODEX_ASSESSMENT", "COMPLETED", "Codex已生成课题判断和下一轮实验建议", {
            "assessment": str(guidance.get("assessment") or "")[:1200],
            "data_fact_count": len(guidance.get("data_facts") or []),
            "hypothesis_count": len(guidance.get("hypotheses") or []),
            "cannot_determine_count": len(guidance.get("cannot_determine") or []),
            "benchmark_comparison_count": len(guidance.get("benchmark_comparisons") or []),
            "next_experiment_count": len(guidance.get("next_experiments") or []),
            "context_hash": managed_context.context_hash,
        })
        self._update_manifest(
            output_dir,
            artifact="guidance.json",
            codex_input_manifest="codex_input_manifest.json",
            codex_context_manifest="contexts/codex_assessment.manifest.json",
            codex_context_hash=managed_context.context_hash,
            research_state_version=research_state.get("row_version"),
            codex_assessment_status="COMPLETED",
        )
        return next_thread_id, guidance

    def _run_all_legacy(
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
        if terms and use_online_research:
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
        self._update_manifest(run.output_dir, errors=result["errors"])
        result["report"] = self.build_report(project_id, run.run_id)
        emit("REPORT", "图文报告已生成。", {"report": result["report"].name, "errors": result["errors"]})
        return result

    def _sync_stage_manifest(self, output_dir: Path, run_id: str) -> None:
        stages = self.store.list_run_stages(run_id)
        statuses = {row["stage"]: row["status"] for row in stages}
        self._update_manifest(
            output_dir,
            stage_statuses=statuses,
            completed_stages=[row["stage"] for row in stages if row["status"] == "COMPLETED"],
        )

    @staticmethod
    def _stage_artifacts_exist(output_dir: Path, stage: dict) -> bool:
        paths = list(stage.get("artifact_paths") or [])
        return all((output_dir / path).is_file() for path in paths)

    def _start_stage(self, run_id: str, output_dir: Path, stage: str, recoverable: dict | None = None) -> bool:
        """Start a stage, or return False when a completed stage is safely reusable."""
        try:
            current = self.store.get_run_stage(run_id, stage)
        except KeyError:
            current = None
        if current and current["status"] == "RUNNING":
            self.store.finish_run_stage(run_id, stage, "PARTIAL", "Interrupted before a terminal stage status was recorded.")
            current = self.store.get_run_stage(run_id, stage)
        if current and current["status"] == "COMPLETED" and self._stage_artifacts_exist(output_dir, current):
            self._sync_stage_manifest(output_dir, run_id)
            return False
        self.store.start_run_stage(run_id, stage, recoverable)
        self._sync_stage_manifest(output_dir, run_id)
        return True

    def _finish_stage(
        self,
        run_id: str,
        output_dir: Path,
        stage: str,
        status: str,
        *,
        error: str | None = None,
        artifacts: list[str] | None = None,
        recoverable: dict | None = None,
    ) -> dict:
        try:
            current = self.store.get_run_stage(run_id, stage)
        except KeyError:
            self.store.start_run_stage(run_id, stage, recoverable)
        else:
            if current["status"] != "RUNNING":
                self.store.start_run_stage(run_id, stage, recoverable)
        row = self.store.finish_run_stage(
            run_id, stage, status, error=error, artifact_paths=artifacts, recoverable_input=recoverable,
        )
        self._sync_stage_manifest(output_dir, run_id)
        return row

    def _skip_stage(self, run_id: str, output_dir: Path, stage: str, reason: str) -> dict | None:
        if not self._start_stage(run_id, output_dir, stage):
            return None
        return self._finish_stage(run_id, output_dir, stage, "SKIPPED", error=reason)

    def _cancel_remaining(self, run_id: str, output_dir: Path, stages: list[str], reason: str) -> None:
        for stage in stages:
            try:
                current = self.store.get_run_stage(run_id, stage)
            except KeyError:
                current = None
            if current and current["status"] == "COMPLETED" and self._stage_artifacts_exist(output_dir, current):
                continue
            self._finish_stage(run_id, output_dir, stage, "CANCELLED", error=reason)
        self.store.update_run_status(run_id, "CANCELLED")
        self._update_manifest(output_dir, status="CANCELLED")

    def review_gcd_segments(
        self,
        project_id: str,
        run_id: str,
        data_path: Path | str,
        decisions: list[Mapping[str, Any]],
    ) -> dict:
        """Apply append-only human segment decisions and recompute GCD cycles."""
        run = self.store.get_run(run_id)
        if run["project_id"] != project_id:
            raise ValueError("Run does not belong to this project.")
        imported = self.csv_importer.read(data_path, conditions=run["input_conditions"])
        if imported.metadata.sha256 != run["raw_data_sha256"]:
            raise ValueError("Selected data no longer matches the run raw-data hash.")
        output_dir = self.output_root / project_id / "runs" / run_id
        analysis_path = output_dir / "analysis.json"
        envelope = json.loads(analysis_path.read_text(encoding="utf-8"))
        if str(envelope.get("analysis_type") or "gcd").casefold() != "gcd":
            raise ValueError("Segment review is available only for GCD analysis.")
        native = dict(envelope.get("analysis") or {})
        segments = [dict(row) for row in native.get("segments") or []]
        by_id = {str(row.get("segment_id")): row for row in segments}
        audit_path = output_dir / "segment_review.json"
        existing = json.loads(audit_path.read_text(encoding="utf-8")) if audit_path.is_file() else {"events": []}
        events = list(existing.get("events") or [])
        before_hash = stable_hash(segments)
        for item in decisions:
            if not isinstance(item, Mapping):
                raise TypeError("Each segment decision must be a mapping.")
            required = ("segment_id", "reviewer", "reason")
            if any(not str(item.get(key) or "").strip() for key in required):
                raise ValueError("Each decision requires segment_id, reviewer, and reason.")
            status = str(item.get("status") or item.get("decision") or "").strip().casefold()
            if status not in {"approved", "rejected"}:
                raise ValueError("Each decision status must be approved or rejected.")
            segment_id = str(item["segment_id"]).strip()
            if segment_id not in by_id:
                raise ValueError("Unknown segment_id: {}".format(segment_id))
            row = by_id[segment_id]
            previous = {
                "review_status": row.get("review_status"),
                "direction_candidate": row.get("direction_candidate"),
                "origin_eligible": row.get("origin_eligible"),
            }
            if status == "approved":
                direction = str(item.get("direction") or "").strip().casefold()
                if direction not in {"charge", "discharge"}:
                    raise ValueError("Approved decisions require direction=charge or discharge.")
                row["direction_candidate"] = direction
                row["review_status"] = "reviewed"
                row["origin_eligible"] = True
                row["human_reviewed"] = True
            else:
                direction = None
                row["original_direction_candidate"] = row.get("direction_candidate")
                row["direction_candidate"] = "rejected"
                row["review_status"] = "rejected"
                row["origin_eligible"] = False
                row["human_reviewed"] = True
            events.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "segment_id": segment_id,
                "status": status,
                "direction": direction,
                "reviewer": str(item["reviewer"]).strip(),
                "reason": str(item["reason"]).strip(),
                "previous": previous,
            })
        time_info = ((native.get("unit_normalization") or {}).get("time") or {})
        recalculated = analyze_gcd_metrics(
            imported.points,
            segments,
            active_material_mass_mg=run["input_conditions"].get("active_material_mass_mg"),
            time_reliable=bool(time_info.get("explicit")),
        )
        native["segments"] = recalculated["segments"]
        native["cycles"] = recalculated["cycles"]
        native["gcd_summary"] = recalculated["summary"]
        native["warnings"] = list(dict.fromkeys([*(native.get("warnings") or []), *(recalculated.get("warnings") or [])]))
        envelope["analysis"] = native
        envelope["quality_flags"] = list(native.get("warnings") or [])
        analysis_path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8")
        audit = {
            "schema_version": "1.0",
            "project_id": project_id,
            "run_id": run_id,
            "raw_data_sha256": run["raw_data_sha256"],
            "before_segments_hash": before_hash,
            "reviewed_segments_hash": stable_hash(native["segments"]),
            "events": events,
        }
        audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
        self.store.save_analysis_artifact(run_id, "segment_review", audit)
        self._update_manifest(output_dir, artifact="segment_review.json", segment_review_hash=audit["reviewed_segments_hash"])
        invalidated = []
        for stage in (
            "BENCHMARK_RESEARCH",
            "CODEX_KNOWLEDGE",
            "ORIGIN",
            "CODEX_ASSESSMENT",
            "REPORT",
        ):
            try:
                current = self.store.get_run_stage(run_id, stage)
            except KeyError:
                continue
            if current["status"] == "RUNNING":
                self.store.finish_run_stage(
                    run_id,
                    stage,
                    "PARTIAL",
                    "Human segment review changed deterministic GCD results.",
                )
            else:
                self.store.start_run_stage(
                    run_id,
                    stage,
                    {"invalidated_by": "segment_review"},
                )
                self.store.finish_run_stage(
                    run_id,
                    stage,
                    "PARTIAL",
                    "Human segment review changed deterministic GCD results.",
                )
            invalidated.append(stage)
        if invalidated:
            self.store.update_run_status(run_id, "PARTIAL")
            self._sync_stage_manifest(output_dir, run_id)
            self._update_manifest(
                output_dir,
                status="PARTIAL",
                invalidated_stages=invalidated,
            )
        return envelope

    def summarize_runs(
        self,
        project_id: str,
        run_ids: list[str],
        metric: str,
        unit: str | None = None,
    ) -> dict:
        """Persist descriptive same-project replicate statistics in a report envelope."""
        if len(run_ids) < 2:
            raise ValueError("At least two run_ids are required.")
        if len(set(run_ids)) != len(run_ids):
            raise ValueError("run_ids must identify distinct runs.")
        analyses = []
        identities = []
        analysis_types: set[str] = set()
        for run_id in run_ids:
            run = self.store.get_run(run_id)
            if run["project_id"] != project_id:
                raise ValueError("All runs must belong to the requested project.")
            path = self.output_root / project_id / "runs" / run_id / "analysis.json"
            if not path.is_file():
                raise ValueError("Run {} has no analysis.json artifact.".format(run_id))
            payload = json.loads(path.read_text(encoding="utf-8"))
            analyses.append(payload)
            analysis_types.add(str(payload.get("analysis_type") or "gcd").casefold())
            identities.append({
                "run_id": run_id,
                "raw_data_sha256": run["raw_data_sha256"],
                "analysis_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            })
        if len(analysis_types) != 1:
            raise ValueError("Replicate runs must use the same analysis_type.")
        summary = summarize_analysis_replicates(analyses, metric, unit=unit)
        replicate_hash = stable_hash({"project_id": project_id, "runs": identities, "metric": metric, "unit": unit})
        envelope = {
            "schema_version": "1.0",
            "analysis_type": "replicates",
            "metadata": {
                "project_id": project_id,
                "run_ids": list(run_ids),
                "metric": metric,
                "unit": summary.get("unit"),
                "replicate_hash": replicate_hash,
            },
            "analysis": summary,
            "limitations": list(summary.get("limitations") or []),
            "quality_flags": list(summary.get("quality_flags") or []),
        }
        target_dir = self.output_root / project_id / "replicates"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / "replicate-{}.json".format(replicate_hash)
        project = next(
            (item for item in self.store.list_projects() if item["project_id"] == project_id),
            None,
        )
        if project is None:
            raise KeyError("Project does not exist.")
        report_target = target_dir / "replicate-{}.html".format(replicate_hash)
        write_report(
            report_target,
            {
                "status": "REPORT_READY",
                "project_id": project_id,
                "project_name": project["name"],
                "material_system": project["material_system"],
                "keywords": project["keywords"],
                "conditions": {},
            },
            [],
            [],
            analysis=envelope,
        )
        envelope["metadata"]["report"] = report_target.name
        target.write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8")
        return envelope

    def run_all(
        self,
        project_id: str,
        data_path: Any,
        conditions: dict,
        *,
        analysis_type: str = "gcd",
        pdf_path: Path | str | None = None,
        keywords: list[str] | None = None,
        use_codex_candidates: bool = True,
        use_codex_assessment: bool = True,
        use_online_research: bool = True,
        progress=None,
        cancel_requested: Callable[[], bool] | None = None,
        _resume_run_id: str | None = None,
    ) -> dict:
        """Run or resume the staged workflow with durable, truthful stage states."""
        emit = progress or (lambda _stage, _message, _details: None)
        cancelled = cancel_requested or (lambda: False)
        method = str(analysis_type or "gcd").strip().casefold()
        raw_hash = self._source_sha256(data_path)
        if _resume_run_id:
            stored_run = self.store.get_run(_resume_run_id)
            if stored_run["project_id"] != project_id:
                raise ValueError("Run does not belong to this project.")
            if stored_run["raw_data_sha256"] != raw_hash:
                raise ValueError("Selected data no longer matches the run raw-data hash.")
            run_id = _resume_run_id
            self.store.update_run_status(run_id, "RUNNING")
        else:
            run_id = self.store.create_run(project_id, raw_hash, dict(conditions), "RUNNING")
        output_dir = self.output_root / project_id / "runs" / run_id
        output_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = output_dir / "manifest.json"
        if not manifest_path.is_file():
            manifest_path.write_text(json.dumps({
                "run_id": run_id, "project_id": project_id, "raw_data_sha256": raw_hash,
                "analysis_type": method, "status": "RUNNING", "artifacts": [], "origin_status": "PENDING",
                "stage_statuses": {}, "completed_stages": [],
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            self._update_manifest(output_dir, status="RUNNING", analysis_type=method)
        stages = [
            "SEARCH", "PDF", "CODEX_PDF", "DATA", "BENCHMARK_RESEARCH",
            "CODEX_KNOWLEDGE", "ORIGIN", "CODEX_ASSESSMENT", "REPORT",
        ]
        result: dict[str, Any] = {
            "project_id": project_id, "search_status": "SKIPPED", "document": None,
            "candidate_count": 0, "raw_candidate_count": 0, "candidate_rejections": [],
            "knowledge_review": None, "run": None, "origin": None, "guidance": None,
            "report": None, "errors": [],
        }
        result["run"] = ExperimentRun(run_id, project_id, raw_hash, "RUNNING", output_dir)
        terms = list(keywords or [])
        benchmark: dict = {}
        pdf_thread_id: str | None = None
        document = None
        search_audit: dict = {"status": "SKIPPED", "keywords": terms}
        pdf_audit: dict = {"status": "SKIPPED"}

        def stop_if_cancelled(index: int) -> bool:
            if not cancelled():
                return False
            self._cancel_remaining(run_id, output_dir, stages[index:], "Cancellation requested by user.")
            return True

        if stop_if_cancelled(0):
            return result
        if terms and use_online_research:
            if self._start_stage(run_id, output_dir, "SEARCH", {"keywords": terms}):
                emit("SEARCH", "正在检索可追溯文献元数据…", {"keywords": terms})
                try:
                    search = self.search_literature(project_id, terms)
                    records = list(getattr(search, "records", []) or [])
                    result["search_status"] = str(getattr(search, "status", "LITERATURE_SEARCHED"))
                    search_audit = {
                        "status": result["search_status"], "query": getattr(search, "query", " ".join(terms)),
                        "record_count": len(records), "records": self._record_summaries(records, limit=12),
                        "error": getattr(search, "error", None),
                        "source_status": dict(getattr(search, "source_status", {}) or {}),
                    }
                    stage_status = "PARTIAL" if result["search_status"] == "SEARCH_PARTIAL" else "COMPLETED"
                    self._finish_stage(run_id, output_dir, "SEARCH", stage_status, error=search_audit.get("error"))
                except Exception as error:
                    result["search_status"] = "SEARCH_PARTIAL"
                    search_audit = {"status": "SEARCH_PARTIAL", "keywords": terms, "error": str(error)}
                    result["errors"].append("Search: {}".format(error))
                    self._finish_stage(run_id, output_dir, "SEARCH", "FAILED", error=str(error))
        else:
            self._skip_stage(run_id, output_dir, "SEARCH", "Online search disabled or no keywords supplied.")

        if stop_if_cancelled(1):
            return result
        if pdf_path:
            if self._start_stage(run_id, output_dir, "PDF", {"source_name": Path(pdf_path).name}):
                emit("PDF", "正在校验并逐页读取本地 PDF…", {"file": Path(pdf_path).name})
                try:
                    document = self.learn_local_pdf(project_id, pdf_path)
                    result["document"] = document
                    pdf_audit = {"status": "COMPLETED", "source_id": document.source_id}
                    self._finish_stage(run_id, output_dir, "PDF", "COMPLETED")
                except Exception as error:
                    pdf_audit = {"status": "FAILED", "error": str(error)}
                    result["errors"].append("PDF: {}".format(error))
                    self._finish_stage(run_id, output_dir, "PDF", "FAILED", error=str(error))
            elif result["document"] is None:
                try:
                    document = self.learn_local_pdf(project_id, pdf_path)
                    result["document"] = document
                except Exception:
                    document = None
        else:
            self._skip_stage(run_id, output_dir, "PDF", "No PDF supplied.")

        if stop_if_cancelled(2):
            return result
        if document is not None and use_codex_candidates and self.was_new_source(document.source_id):
            if self._start_stage(run_id, output_dir, "CODEX_PDF", {"source_id": document.source_id}):
                try:
                    pdf_thread_id, claims, rejected = self.extract_pdf_candidates(project_id, document.source_id)
                    result["raw_candidate_count"] = len(claims)
                    result["candidate_rejections"] = rejected
                    pdf_audit.update({"codex_status": "COMPLETED", "raw_candidate_count": len(claims), "rejected_count": len(rejected)})
                    self._finish_stage(run_id, output_dir, "CODEX_PDF", "COMPLETED")
                except Exception as error:
                    result["errors"].append("Codex PDF: {}".format(error))
                    self._finish_stage(run_id, output_dir, "CODEX_PDF", "FAILED", error=str(error))
        else:
            reason = "Codex PDF extraction disabled, PDF unavailable, or source hash already processed."
            self._skip_stage(run_id, output_dir, "CODEX_PDF", reason)

        if stop_if_cancelled(3):
            return result
        run: ExperimentRun
        if self._start_stage(run_id, output_dir, "DATA", {"source_name": Path(data_path).name if isinstance(data_path, (str, Path)) else "structured-input", "analysis_type": method}):
            emit("DATA", "正在执行确定性实验分析…", {"analysis_type": method})
            try:
                run = self.analyze_data(project_id, data_path, conditions, method, _run_id=run_id)
                self._finish_stage(run_id, output_dir, "DATA", "COMPLETED", artifacts=["analysis.json"])
            except Exception as error:
                result["errors"].append("Data: {}".format(error))
                self._finish_stage(run_id, output_dir, "DATA", "FAILED", error=str(error))
                for remaining in stages[4:]:
                    self._skip_stage(run_id, output_dir, remaining, "Core data analysis failed.")
                self.store.update_run_status(run_id, "FAILED")
                self._update_manifest(output_dir, status="FAILED", errors=result["errors"])
                return result
        else:
            legacy_status = "DATA_ANALYZED" if self.store.list_approved_claims(project_id) else "NEEDS_REVIEW"
            run = ExperimentRun(run_id, project_id, raw_hash, legacy_status, output_dir)
        result["run"] = run
        analysis_envelope = json.loads((output_dir / "analysis.json").read_text(encoding="utf-8"))
        self._record_codex_activity(output_dir, "RUN", "STARTED", "本轮 Codex 可观测记录已启用", {
            "keywords": terms, "search": search_audit, "pdf": pdf_audit,
            "data_source_sha256": raw_hash, "analysis_type": method,
        })

        if stop_if_cancelled(4):
            return result
        if use_online_research:
            if self._start_stage(run_id, output_dir, "BENCHMARK_RESEARCH", {"keywords": terms, "analysis_type": method}):
                emit("BENCHMARK_RESEARCH", "正在执行方法匹配的基准文献研究…", {"analysis_type": method})
                try:
                    benchmark = self.research_benchmarks(project_id, run_id, terms)
                    self._finish_stage(run_id, output_dir, "BENCHMARK_RESEARCH", "COMPLETED", artifacts=["benchmark_research.json"])
                except Exception as error:
                    result["errors"].append("Benchmark research: {}".format(error))
                    self._record_codex_activity(output_dir, "CODEX_WEB_SEARCH", "FAILED", "联网检索失败", {
                        "error": str(error), "topics": build_benchmark_topics(" ".join(terms), analysis_envelope["analysis"], method),
                    })
                    self._finish_stage(run_id, output_dir, "BENCHMARK_RESEARCH", "FAILED", error=str(error))
            else:
                benchmark_path = output_dir / "benchmark_research.json"
                benchmark = json.loads(benchmark_path.read_text(encoding="utf-8")) if benchmark_path.is_file() else {}
        else:
            self._skip_stage(run_id, output_dir, "BENCHMARK_RESEARCH", "Online benchmark research disabled.")

        if stop_if_cancelled(5):
            return result
        if use_codex_candidates or use_online_research:
            if self._start_stage(run_id, output_dir, "CODEX_KNOWLEDGE"):
                emit("CODEX_KNOWLEDGE", "Codex 正在筛选待审批知识…", {})
                try:
                    review = self.curate_literature(project_id, run_id, benchmark.get("codex_web_research") or {}, pdf_thread_id)
                    result["knowledge_review"] = review
                    result["candidate_count"] = len(review.get("claims") or [])
                    stage_status = "SKIPPED" if review.get("status") == "NO_REVIEW_ITEMS" else "COMPLETED"
                    artifacts = ["literature_review.json"] if (output_dir / "literature_review.json").is_file() else []
                    self._finish_stage(run_id, output_dir, "CODEX_KNOWLEDGE", stage_status, artifacts=artifacts)
                except Exception as error:
                    result["errors"].append("Literature synthesis: {}".format(error))
                    self._finish_stage(run_id, output_dir, "CODEX_KNOWLEDGE", "FAILED", error=str(error))
        else:
            self._skip_stage(run_id, output_dir, "CODEX_KNOWLEDGE", "Codex knowledge curation disabled.")

        if stop_if_cancelled(6):
            return result
        if self._start_stage(run_id, output_dir, "ORIGIN", {"analysis_type": method}):
            emit("ORIGIN", "正在处理方法对应的 Origin 阶段…", {"analysis_type": method, "run_id": run_id})
            try:
                origin = self.prepare_origin(project_id, run_id, data_path)
                result["origin"] = origin
                origin_stage = "SKIPPED" if origin.status == "PLOT_NOT_AVAILABLE_FOR_METHOD" else "PARTIAL" if origin.status == "PLOT_BLOCKED" else "COMPLETED"
                self._finish_stage(run_id, output_dir, "ORIGIN", origin_stage, error=origin.reason, artifacts=["origin/origin_manifest.json"])
            except Exception as error:
                result["errors"].append("Origin: {}".format(error))
                self._finish_stage(run_id, output_dir, "ORIGIN", "FAILED", error=str(error))
        else:
            origin_path = output_dir / "origin" / "origin_manifest.json"
            if origin_path.is_file():
                payload = json.loads(origin_path.read_text(encoding="utf-8"))
                result["origin"] = OriginPlotResult(payload.get("status"), origin_path, output_dir / "origin" / "electrochemistry.opju", tuple(), payload.get("reason"))

        if stop_if_cancelled(7):
            return result
        if use_codex_assessment:
            if self._start_stage(run_id, output_dir, "CODEX_ASSESSMENT"):
                emit("CODEX_ASSESSMENT", "Codex 正在执行受控评估…", {"run_id": run_id})
                try:
                    _thread_id, guidance = self.evaluate_with_codex(project_id, run_id)
                    result["guidance"] = guidance
                    self._finish_stage(run_id, output_dir, "CODEX_ASSESSMENT", "COMPLETED", artifacts=["guidance.json"])
                except Exception as error:
                    result["errors"].append("Codex assessment: {}".format(error))
                    self._finish_stage(run_id, output_dir, "CODEX_ASSESSMENT", "FAILED", error=str(error))
        else:
            self._skip_stage(run_id, output_dir, "CODEX_ASSESSMENT", "Codex assessment disabled.")

        if stop_if_cancelled(8):
            return result
        if self._start_stage(run_id, output_dir, "REPORT"):
            emit("REPORT", "正在生成图文报告…", {"run_id": run_id})
            try:
                result["report"] = self.build_report(project_id, run_id)
                self._finish_stage(run_id, output_dir, "REPORT", "COMPLETED", artifacts=["research_decision_report.html"])
            except Exception as error:
                result["errors"].append("Report: {}".format(error))
                self._finish_stage(run_id, output_dir, "REPORT", "FAILED", error=str(error))
        else:
            report_path = output_dir / "research_decision_report.html"
            result["report"] = report_path if report_path.is_file() else None

        if cancelled():
            self.store.update_run_status(run_id, "CANCELLED")
            self._update_manifest(output_dir, status="CANCELLED")
            return result

        statuses = {row["stage"]: row["status"] for row in self.store.list_run_stages(run_id)}
        if any(value == "CANCELLED" for value in statuses.values()):
            final_status = "CANCELLED"
        elif statuses.get("DATA") == "FAILED":
            final_status = "FAILED"
        elif any(value in {"FAILED", "PARTIAL"} for value in statuses.values()):
            final_status = "PARTIAL"
        else:
            final_status = "COMPLETED"
        self.store.update_run_status(run_id, final_status)
        self._update_manifest(output_dir, status=final_status, errors=result["errors"], stage_statuses=statuses)
        return result

    def resume_run(
        self,
        project_id: str,
        run_id: str,
        data_path: Any,
        conditions: dict | None = None,
        **kwargs: Any,
    ) -> dict:
        """Resume a run after validating caller-supplied source data by hash."""
        run = self.store.get_run(run_id)
        if run["project_id"] != project_id:
            raise ValueError("Run does not belong to this project.")
        if self._source_sha256(data_path) != run["raw_data_sha256"]:
            raise ValueError("Selected data no longer matches the run raw-data hash.")
        manifest_path = self.output_root / project_id / "runs" / run_id / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
        stored_conditions = dict(run["input_conditions"])
        if conditions is not None and dict(conditions) != stored_conditions:
            raise ValueError("A resumed run must use its original experiment conditions; create a new run for changed conditions.")
        stored_method = str(manifest.get("analysis_type") or "gcd").strip().casefold()
        requested_method = str(kwargs.get("analysis_type") or stored_method).strip().casefold()
        if requested_method != stored_method:
            raise ValueError("A resumed run must use its original analysis_type; create a new run for another method.")
        kwargs["analysis_type"] = stored_method
        return self.run_all(
            project_id, data_path, stored_conditions,
            _resume_run_id=run_id, **kwargs,
        )

    @staticmethod
    def _derive_literature_studies(claims: list) -> list[dict]:
        """Expose only researcher-approved, source-linked study details.

        This fallback never invents material names, tests, or recommendations.
        It renders fields already stored with an approved curated claim.
        """
        studies = []
        for claim in claims:
            conditions = dict(getattr(claim, "conditions", {}) or {})
            tests = [str(value).strip() for value in conditions.get("tests") or [] if str(value).strip()]
            question = str(conditions.get("question") or "").strip()
            finding = str(conditions.get("finding") or "").strip()
            how_to_borrow = str(conditions.get("how_to_borrow") or "").strip()
            if not tests or not question or not finding or not how_to_borrow:
                continue
            studies.append({
                "study": str(conditions.get("title") or getattr(claim, "text", "已批准文献方法")).strip(),
                "tests": tests,
                "question": question,
                "finding": finding,
                "how_to_borrow": how_to_borrow,
                "source_urls": [
                    str(value).strip()
                    for value in conditions.get("source_urls") or []
                    if str(value).strip()
                ],
                "source_ids": [str(getattr(claim, "source_id", ""))],
                "evidence_status": "approved",
            })
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
            analysis = json.loads(analysis_path.read_text(encoding="utf-8")) or {}
        benchmark = {}
        benchmark_path = output_dir / "benchmark_research.json"
        if benchmark_path.is_file():
            benchmark = json.loads(benchmark_path.read_text(encoding="utf-8")) or {}
        context_manifest_path = output_dir / "contexts" / "codex_assessment.manifest.json"
        if context_manifest_path.is_file():
            try:
                benchmark["context_manifest"] = json.loads(context_manifest_path.read_text(encoding="utf-8")) or {}
            except (OSError, json.JSONDecodeError):
                benchmark["context_manifest"] = {"status": "unreadable"}
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
