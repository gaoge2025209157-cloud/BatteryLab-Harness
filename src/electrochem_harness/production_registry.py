"""Declared production tool registry for the controlled Harness (Phase 5 / B1).

Every capability is registered as an individual deterministic tool with an
explicit declaration of its network need, write scope, timeout, retry budget and
failure policy. Nothing here is a black box: the GUI never shells out to an
analysis script, and the only external process is Origin, launched from inside
its own tool by :mod:`electrochem_harness.origin_adapter`.

Declaration rules enforced by tests:

* a tool that reads the network must declare ``requires_network=True``;
* a tool that writes deliverables must declare ``writes_output=True``;
* the two optional stages (literature, Origin) must degrade instead of failing
  the whole run, because local results are always worth keeping;
* every accepted argument must be a safe lower-case identifier.
"""

import csv
import json
from dataclasses import dataclass
from .knowledge_assistant import NoReadableFulltextError, ResearchKnowledgeStore

from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Tuple

from .literature import ResearchProfile, search_crossref
from .markdown_knowledge import MarkdownLiteratureKnowledgeStore
from .origin_adapter import (
    DEFAULT_TIMEOUT_SECONDS,
    OriginError,
    OriginJob,
    OriginStatus,
    launch_origin,
)
from .research_report import create_research_html_report
from .research_workflow import finalize_research_guidance, run_integrated_learning
from .sci_report import create_scientific_bundle, render_readable_summary
from .scientific_standard import (
    scientific_standard_identity,
    scientific_standard_manifest,
)
from .tool_registry import FailurePolicy, ToolOutcome, ToolRegistry, ToolSpec


RESEARCH_FIELDS = (
    "battery_system",
    "active_material",
    "cell_type",
    "counter_electrode",
    "test_current",
    "temperature",
    "normalization_basis",
)

TOOL_ORDER = (
    "parse_land_text",
    "quality_check",
    "calculate_cycle_metrics",
    "search_literature_metadata",
    "build_scientific_report",
    "build_origin_project",
)

NETWORK_ARTIFACTS = ("文献清单.json", "文献学习结果.json", "文献学习审计.json")
LEGACY_NETWORK_ARTIFACTS = ("文献证据.json", "文献比较.csv")
ORIGIN_ARTIFACTS = (
    "电化学分析.opju",
    "充放电曲线.png",
    "循环性能.png",
    "origin_status.json",
)


@dataclass(frozen=True)
class ToolchainInputs:
    """Everything a production tool needs, resolved once per run."""

    source: Path
    values: Mapping[str, Any]
    analysis_payload: Any
    project_root: Path
    knowledge_markdown: Path
    origin_launcher: Optional[Callable[..., OriginStatus]] = None
    origin_exe: str = ""
    origin_timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    progress_callback: Optional[Callable[[str, str, Mapping], None]] = None

    @property
    def profile(self) -> ResearchProfile:
        values = {
            key: str(self.values.get(key, "")).strip()
            for key in RESEARCH_FIELDS
            if key not in {"test_current", "temperature", "normalization_basis"}
        }
        current = str(self.values.get("test_current", "")).strip()
        temperature = str(self.values.get("temperature", "")).strip()
        try:
            values["test_current"] = "{:g} mA".format(float(current))
        except (TypeError, ValueError):
            values["test_current"] = current
        try:
            values["temperature"] = "{:g} °C".format(float(temperature))
        except (TypeError, ValueError):
            values["temperature"] = temperature
        values["normalization_basis"] = (
            "未归一化容量（mAh）"
            if self.is_raw_current_curve
            else "仪器文件导出的比容量口径（质量分母需由设备方法记录核验）"
        )
        return ResearchProfile(**values)

    @property
    def max_literature(self) -> int:
        try:
            requested = int(self.values.get("max_literature", 5))
        except (TypeError, ValueError):
            requested = 5
        return max(1, min(requested, 5))

    @property
    def is_raw_current_curve(self) -> bool:
        return (
            isinstance(self.analysis_payload, dict)
            and self.analysis_payload.get("mode") == "raw_current_curve"
        )


def tool_declarations() -> Tuple[Mapping[str, Any], ...]:
    """Return the static, reviewable declaration of every production tool."""

    return (
        {
            "tool_id": "parse_land_text",
            "purpose": "把蓝电文本导出解析为统一的逐点数据",
            "requires_network": False,
            "writes_output": False,
            "failure_policy": "fail",
            "timeout_seconds": 120,
            "max_retries": 0,
            "artifacts": (),
        },
        {
            "tool_id": "quality_check",
            "purpose": "报告字段、时间、循环和数值质量问题",
            "requires_network": False,
            "writes_output": False,
            "failure_policy": "fail",
            "timeout_seconds": 60,
            "max_retries": 0,
            "artifacts": (),
        },
        {
            "tool_id": "calculate_cycle_metrics",
            "purpose": "按冻结口径计算容量、效率、保持率和电压指标",
            "requires_network": False,
            "writes_output": False,
            "failure_policy": "fail",
            "timeout_seconds": 300,
            "max_retries": 0,
            "artifacts": (),
        },
        {
            "tool_id": "search_literature_metadata",
            "purpose": "依据实验与课题信息筛选最多5篇高质量论文、读取原文并由本地大模型生成知识候选",
            "requires_network": True,
            "writes_output": True,
            "failure_policy": "degrade",
            "timeout_seconds": 600,
            "max_retries": 1,
            "artifacts": NETWORK_ARTIFACTS,
        },
        {
            "tool_id": "build_scientific_report",
            "purpose": "生成关键参数报告、汇总表和绘图输入",
            "requires_network": False,
            "writes_output": True,
            "failure_policy": "fail",
            "timeout_seconds": 180,
            "max_retries": 0,
            "artifacts": ("关键结论.txt", "关键参数报告.md", "关键参数.csv", "完整分析.json"),
        },
        {
            "tool_id": "build_origin_project",
            "purpose": "在 Origin 2021-2026b 中生成工程和 SCI 风格图",
            "requires_network": False,
            "writes_output": True,
            "failure_policy": "degrade",
            "timeout_seconds": 180,
            "max_retries": 0,
            "artifacts": ORIGIN_ARTIFACTS,
        },
    )


def build_production_registry(inputs: ToolchainInputs) -> ToolRegistry:
    """Build and seal the production registry for exactly one controlled run."""

    registry = ToolRegistry()
    profile = inputs.profile

    def parse_tool(context):
        context.checkpoint()
        if inputs.is_raw_current_curve:
            imported = inputs.analysis_payload["imported"]
            return {
                "mode": "raw_current_curve",
                "rows": len(imported.points),
                "metadata": imported.metadata(),
            }
        return {
            "mode": "specific_capacity_curve",
            "rows": inputs.analysis_payload["report"]["source_rows"],
            "metadata": inputs.analysis_payload["import_metadata"],
        }

    def quality_tool(context):
        context.checkpoint()
        if inputs.is_raw_current_curve:
            return {"issues": []}
        return {"issues": list(inputs.analysis_payload["report"].get("quality_issues", ()))}

    def metrics_tool(context):
        context.checkpoint()
        if inputs.is_raw_current_curve:
            cycles = [item.to_dict() for item in inputs.analysis_payload["metrics"]]
        else:
            cycles = list(inputs.analysis_payload["report"].get("cycles", ()))
        return {"scientific_standard": scientific_standard_identity(), "cycles": cycles}

    def literature_tool(context):
        context.checkpoint()
        if not inputs.values.get("unified_research"):
            result = search_crossref(profile, max_results=inputs.max_literature)
            evidence = context.output_dir / "文献证据.json"
            comparison = context.output_dir / "文献比较.csv"
            evidence.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            with comparison.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["match_level", "year", "journal", "title", "doi"])
                for item in result.get("records", ()):
                    writer.writerow([item.get(name) for name in ("match_level", "year", "journal", "title", "doi")])
            return ToolOutcome(
                value={"verified_count": result.get("verified_count", 0), "write_policy": "discovery_only"},
                artifacts=(evidence, comparison),
            )
        analysis_evidence = context.output_dir / "分析证据.json"
        analysis_evidence.write_text(
            json.dumps(
                {
                    "experiment_context": profile.to_dict(),
                    "research_domain": inputs.values.get("research_domain", ""),
                    "research_background": inputs.values.get("research_background", ""),
                    "research_question": inputs.values.get("research_question", ""),
                    "deterministic_metrics": context.shared.get("calculate_cycle_metrics", {}),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        paper_manifest_path = context.output_dir / "文献清单.json"

        def learning_progress(stage, message, details):
            if inputs.progress_callback is not None:
                inputs.progress_callback(stage, message, details)
            papers = (details or {}).get("papers")
            if papers is not None:
                temporary = paper_manifest_path.with_suffix(".json.tmp")
                temporary.write_text(
                    json.dumps(
                        {
                            "stage": stage,
                            "message": message,
                            "selected_count": len(papers),
                            "papers": list(papers),
                        },
                        ensure_ascii=False,
                        indent=2,
                    ) + "\n",
                    encoding="utf-8",
                )
                temporary.replace(paper_manifest_path)

        try:
            learning = run_integrated_learning(
                inputs.values,
                data_file=analysis_evidence,
                project_root=inputs.project_root,
                progress_callback=learning_progress,
            )
        except NoReadableFulltextError as error:
            papers = list(error.papers)
            search_only_reasoning = {
                "summary": "已完成天津大学图书馆、Web of Science、Wiley及公开题录检索；本轮未取得可读取原文，因此未调用Qwen、未生成文献知识。",
                "recommended_search_terms": [],
                "article_core_findings": [],
                "research_background": [],
                "electrochemistry_foundations": [],
                "key_figures_tables": [],
                "learning_delta": [],
                "data_value_assessment": [],
                "missing_experiments": [],
                "missing_characterization": [],
                "cannot_determine": ["没有原文和人工核对，不能形成文献支持的机理判断。"],
                "knowledge_candidates": [],
            }
            result_path = context.output_dir / "文献学习结果.json"
            audit_path = context.output_dir / "文献学习审计.json"
            paper_manifest_path.write_text(
                json.dumps(
                    {"stage": "search_only", "message": str(error), "selected_count": len(papers), "papers": papers},
                    ensure_ascii=False,
                    indent=2,
                ) + "\n",
                encoding="utf-8",
            )
            result_path.write_text(json.dumps(search_only_reasoning, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            audit_path.write_text(
                json.dumps(
                    {
                        "status": "search_only",
                        "knowledge_entry_key": "",
                        "metadata_count": len(papers),
                        "document_count": 0,
                        "selected_papers": papers,
                        "model_called": False,
                        "reason": str(error),
                    },
                    ensure_ascii=False,
                    indent=2,
                ) + "\n",
                encoding="utf-8",
            )
            learning_progress(
                "done",
                "已显示5篇检索结果；本轮没有可读原文，未调用Qwen",
                {"papers": papers, "document_count": 0},
            )
            return ToolOutcome(
                value={"status": "search_only", "metadata_count": len(papers), "document_count": 0, "model": "not_called"},
                artifacts=(paper_manifest_path, result_path, audit_path),
            )
        if not paper_manifest_path.is_file():
            paper_manifest_path.write_text(
                json.dumps(
                    {
                        "stage": "done",
                        "message": "文献学习完成",
                        "selected_count": len(getattr(learning, "selected_papers", ())),
                        "papers": list(getattr(learning, "selected_papers", ())),
                    },
                    ensure_ascii=False,
                    indent=2,
                ) + "\n",
                encoding="utf-8",
            )
        result_path = context.output_dir / "文献学习结果.json"
        audit_path = context.output_dir / "文献学习审计.json"
        result_path.write_text(
            json.dumps(dict(learning.reasoning), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        audit_path.write_text(
            json.dumps(
                {
                    "learning_run_id": learning.run_id,
                    "learning_run_dir": learning.run_dir.name,
                    "knowledge_entry_key": learning.knowledge_entry_key,
                    "knowledge_path": "knowledge/research_knowledge.md",
                    "plan_hash": learning.plan_hash,
                    "evidence_hash": learning.evidence_hash,
                    "context_hash": learning.context_hash,
                    "context_tokens_estimated": learning.context_tokens_estimated,
                    "model": learning.model,
                    "total_tokens": learning.total_tokens,
                    "cache_hit": learning.cache_hit,
                    "metadata_count": learning.metadata_count,
                    "available_document_count": getattr(learning, "available_document_count", learning.document_count),
                    "document_count": learning.document_count,
                    "model_document_limit": getattr(learning, "model_document_limit", learning.document_count),
                    "selected_papers": list(getattr(learning, "selected_papers", ())),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        context.checkpoint()
        return ToolOutcome(
            value={
                "learning_run_id": learning.run_id,
                "knowledge_entry_key": learning.knowledge_entry_key,
                "metadata_count": learning.metadata_count,
                "available_document_count": getattr(learning, "available_document_count", learning.document_count),
                "document_count": learning.document_count,
                "model_document_limit": getattr(learning, "model_document_limit", learning.document_count),
                "model": learning.model,
            },
            artifacts=(paper_manifest_path, result_path, audit_path),
        )

    def report_tool(context):
        context.checkpoint()
        if inputs.is_raw_current_curve:
            artifacts = _write_raw_bundle(
                context.output_dir, inputs.source, inputs.analysis_payload, profile
            )
        else:
            paths = create_scientific_bundle(
                inputs.source,
                context.output_dir,
                material=profile.active_material,
                cell_configuration=profile.cell_description,
                rate=profile.test_current,
                temperature=profile.temperature,
                research_profile=profile,
                search_literature=False,
                literature_knowledge_path=None,
                literature_markdown_path=inputs.knowledge_markdown,
                origin_plot_mode=str(inputs.values.get("origin_plot_mode", "both") or "both"),
            )
            artifacts = tuple(
                path
                for name, path in paths.items()
                if name != "knowledge_markdown" and Path(path).is_file()
            )
        report = context.output_dir / "关键参数报告.md"
        literature_result = None
        if not inputs.is_raw_current_curve:
            conclusion = context.output_dir / "关键结论.txt"
            conclusion.write_text(
                render_readable_summary(inputs.analysis_payload, profile, literature_result),
                encoding="utf-8",
            )
            if conclusion not in artifacts:
                artifacts = tuple(artifacts) + (conclusion,)

        if inputs.values.get("unified_research"):
            conclusion = context.output_dir / "关键结论.txt"
            learning_path = context.output_dir / "文献学习结果.json"
            audit_path = context.output_dir / "文献学习审计.json"
            manifest_path = context.output_dir / "文献清单.json"
            reasoning = json.loads(learning_path.read_text(encoding="utf-8")) if learning_path.is_file() else {}
            learning_audit = json.loads(audit_path.read_text(encoding="utf-8")) if audit_path.is_file() else {}
            papers_payload = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
            statuses = {}
            entry_key = str(learning_audit.get("knowledge_entry_key") or "")
            if entry_key:
                reviews = ResearchKnowledgeStore(
                    inputs.project_root / "knowledge" / "research_knowledge.md"
                ).candidate_reviews_for_entry(entry_key)
                statuses = {candidate_id: status for candidate_id, (status, _note) in reviews.items()}
            guidance = finalize_research_guidance(
                deterministic_conclusion=conclusion,
                reasoning=reasoning,
                status_by_id=statuses,
                values=inputs.values,
                target=context.output_dir / "研究结论与指导.txt",
                require_review=False,
            )
            html_report = create_research_html_report(
                context.output_dir / "研究分析报告.html",
                values=inputs.values,
                deterministic_text=conclusion.read_text(encoding="utf-8"),
                guidance_text=guidance.read_text(encoding="utf-8"),
                reasoning=reasoning,
                status_by_id=statuses,
                papers=papers_payload.get("papers", []),
                image_paths=(),
            )
            artifacts = tuple(artifacts) + (guidance, html_report)
        if "search_literature_metadata" in context.shared:
            with report.open("a", encoding="utf-8") as handle:
                if inputs.values.get("unified_research"):
                    handle.write(
                        "\n## 受控文献学习记录\n\n"
                        "已依据本次实验与课题信息筛选高质量论文、读取可核验原文并生成自动研究指导。原文学习知识保留复核状态，详情见 `研究分析报告.html`、`文献学习结果.json` 和 `文献学习审计.json`。\n"
                    )
                else:
                    handle.write(
                        "\n## Phase 1文献执行记录\n\n"
                        "已在独立联网授权范围内完成文献元数据检索，详情见 `文献证据.json`。\n"
                    )
        # 只回传文件名：核心结果哈希必须与 run 目录无关，否则同输入两次运行
        # 会得到不同的哈希，可复现性检查就失效了（见 E-12）。
        return ToolOutcome(value={"report": report.name}, artifacts=tuple(artifacts))

    def origin_tool(context):
        context.checkpoint()
        job_path = context.output_dir / "origin_job.json"
        if not job_path.is_file():
            raise OriginError(
                "本次运行没有生成 origin_job.json，Origin 阶段已跳过；"
                "报告与绘图 CSV 均已保留。"
            )
        try:
            job_payload = json.loads(job_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise OriginError("origin_job.json 无法读取：{}".format(error)) from error
        if not job_payload.get("status_path"):
            raise OriginError(
                "该数据模式只生成绘图 CSV，尚未生成可执行的 Origin 作业；"
                "报告与绘图 CSV 均已保留。"
            )
        try:
            job = OriginJob.from_dict(job_payload)
        except OriginError as error:
            raise OriginError("origin_job.json 无法读取：{}".format(error)) from error

        launcher = inputs.origin_launcher or launch_origin
        status = launcher(
            job_path,
            inputs.project_root,
            explicit_exe=inputs.origin_exe or None,
            timeout_seconds=inputs.origin_timeout_seconds,
            checkpoint=context.checkpoint,
        )
        artifacts = job.expected_outputs()
        return ToolOutcome(
            value={
                "origin_release": status.origin_release,
                "originpro_version": status.originpro_version,
                # 同上：不要回传绝对路径，保持核心结果哈希可复现
                "project": (
                    None if not status.project else Path(status.project).name
                ),
                "compatibility_warnings": list(status.warnings),
            },
            artifacts=artifacts,
            warnings=tuple(
                "Origin: {}".format(item) for item in status.warnings
            ),
        )

    registry.register(
        ToolSpec("parse_land_text", parse_tool, timeout_seconds=120)
    )
    registry.register(
        ToolSpec("quality_check", quality_tool, timeout_seconds=60)
    )
    registry.register(
        ToolSpec(
            "calculate_cycle_metrics",
            metrics_tool,
            writes_output=False,
            timeout_seconds=300,
            failure_policy=FailurePolicy.FAIL,
        )
    )
    registry.register(
        ToolSpec(
            "search_literature_metadata",
            literature_tool,
            requires_network=True,
            writes_output=True,
            failure_policy=FailurePolicy.DEGRADE,
            timeout_seconds=600,
            max_retries=1,
            allowed_arguments=("max_results",),
        )
    )
    registry.register(
        ToolSpec(
            "build_scientific_report",
            report_tool,
            writes_output=True,
            timeout_seconds=180,
        )
    )
    registry.register(
        ToolSpec(
            "build_origin_project",
            origin_tool,
            writes_output=True,
            failure_policy=FailurePolicy.DEGRADE,
            timeout_seconds=180,
            allowed_arguments=("origin_exe",),
        )
    )
    registry.seal()
    return registry


def _write_raw_bundle(
    target: Path,
    source: Path,
    payload: Mapping[str, Any],
    profile: ResearchProfile,
):
    target.mkdir(parents=True, exist_ok=True)
    metrics = [item.to_dict() for item in payload["metrics"]]
    report = target / "关键参数报告.md"
    report.write_text(
        "# Phase 1受控分析报告\n\n"
        "- 输入：{}\n"
        "- 模式：四列时间/电流/电压积分\n"
        "- 循环数：{}\n"
        "- 科学标准：{}（SHA-256 `{}`）\n"
        "- 统计边界：单个电池只能作为探索性结果，不能证明重复性。\n\n"
        "> 本报告用于演示计划、批准、白名单、验证和审计链。\n".format(
            source.name,
            len(metrics),
            scientific_standard_identity()["version"],
            scientific_standard_identity()["sha256"],
        ),
        encoding="utf-8",
    )
    conclusion = target / "关键结论.txt"
    complete_metrics = [
        item for item in metrics
        if item.get("charge_capacity_mAh", 0) > 0 and item.get("discharge_capacity_mAh", 0) > 0
    ]
    conclusion_lines = [
        "数据质量与范围",
        "有效完整循环：{} 圈；总循环记录：{} 圈。".format(len(complete_metrics), len(metrics)),
        "计算口径：容量与能量由时间、电流和电压积分得到；当前未提供可审计质量和体积。",
        "",
        "关键指标全景",
    ]
    if complete_metrics:
        first, last = complete_metrics[0], complete_metrics[-1]
        ces = [item["coulombic_efficiency"] for item in complete_metrics if item.get("coulombic_efficiency") is not None]
        retentions = [item["capacity_retention"] for item in complete_metrics if item.get("capacity_retention") is not None]
        gaps = [item["voltage_gap_V"] for item in complete_metrics if item.get("voltage_gap_V") is not None]
        conclusion_lines.extend([
            "放电容量：首个 {:.4g}，末个 {:.4g} mAh；变化 {:+.4g} mAh。".format(
                first["discharge_capacity_mAh"], last["discharge_capacity_mAh"],
                last["discharge_capacity_mAh"] - first["discharge_capacity_mAh"],
            ),
            "充电容量：首个 {:.4g}，末个 {:.4g} mAh。".format(
                first["charge_capacity_mAh"], last["charge_capacity_mAh"]
            ),
            "放电能量：首个 {:.4g}，末个 {:.4g} mWh；变化 {:+.4g} mWh。".format(
                first["discharge_energy_mWh"], last["discharge_energy_mWh"],
                last["discharge_energy_mWh"] - first["discharge_energy_mWh"],
            ),
            "平均放电电压：首个 {}，末个 {} V。".format(
                "—" if first.get("average_discharge_voltage_V") is None else "{:.3f}".format(first["average_discharge_voltage_V"]),
                "—" if last.get("average_discharge_voltage_V") is None else "{:.3f}".format(last["average_discharge_voltage_V"]),
            ),
            "平均充电电压：首个 {}，末个 {} V。".format(
                "—" if first.get("average_charge_voltage_V") is None else "{:.3f}".format(first["average_charge_voltage_V"]),
                "—" if last.get("average_charge_voltage_V") is None else "{:.3f}".format(last["average_charge_voltage_V"]),
            ),
        ])
        if ces:
            conclusion_lines.append("库仑效率：首个 {:.2%}，末个 {:.2%}，平均 {:.2%}，范围 {:.2%}–{:.2%}。".format(
                ces[0], ces[-1], sum(ces) / len(ces), min(ces), max(ces)
            ))
        if retentions:
            conclusion_lines.append("末个完整循环容量保持率：{:.2%}。".format(retentions[-1]))
        if gaps:
            conclusion_lines.append("平均充放电电压差：首个 {:.3f}，末个 {:.3f} V；变化 {:+.3f} V。".format(
                gaps[0], gaps[-1], gaps[-1] - gaps[0]
            ))
        energy_efficiency = [
            item["discharge_energy_mWh"] / item["charge_energy_mWh"]
            for item in complete_metrics if item.get("charge_energy_mWh", 0) > 0
        ]
        if energy_efficiency:
            conclusion_lines.append("能量效率：首个 {:.2%}，末个 {:.2%}。".format(energy_efficiency[0], energy_efficiency[-1]))
        conclusion_lines.append("能量密度限制：当前只能报告单电池绝对能量mWh；缺少可审计质量或体积，不能计算质量比能量或体积能量密度。")

        conclusion_lines.extend(["", "趋势与异常"])
        if len(complete_metrics) >= 2:
            cycle_span = max(1, int(last["cycle"]) - int(first["cycle"]))
            slope = (last["discharge_capacity_mAh"] - first["discharge_capacity_mAh"]) / cycle_span
            conclusion_lines.append("放电容量平均变化率：{:+.4g} mAh/圈。".format(slope))
            if gaps:
                conclusion_lines.append("极化表征量{}：平均电压差由 {:.3f} 变为 {:.3f} V。".format(
                    "增大" if gaps[-1] > gaps[0] else "未增大", gaps[0], gaps[-1]
                ))
        else:
            conclusion_lines.append("只有一个完整循环，不能判断长期变化率和稳定性。")

        conclusion_lines.extend([
            "",
            "数据支持的判断",
            "可以直接支持：按Q=∫|I|dt与E=∫|VI|dt得到的绝对容量、绝对能量、效率、保持率和平均电压趋势。",
            "不能直接支持：比容量、质量/体积能量密度、阻抗、扩散系数、界面成分或唯一衰减机理。",
            "",
            "候选解释与判别依据",
        ])
        drop = last["discharge_capacity_mAh"] < first["discharge_capacity_mAh"] * 0.95
        gap_growth = len(gaps) >= 2 and gaps[-1] - gaps[0] > 0.05
        if drop and gap_growth:
            conclusion_lines.append("候选解释A：动力学、界面接触或传输限制可能加剧。支持依据：容量下降且平均电压差增大；缺失证据：分阶段EIS。判别实验：固定SOC、温度和静置时间测EIS；阻抗同步增长则支持，不增长则削弱。")
        elif drop:
            conclusion_lines.append("候选解释A：活性库存损失、接触退化、结构变化或副反应均可能造成容量下降。判别实验：分阶段EIS结合循环前后结构与界面表征，不能仅凭曲线选定唯一原因。")
        else:
            conclusion_lines.append("当前区间未见超过5%的容量下降，但测试长度不足以证明长期稳定；需延长循环并增加平行电池。")
    else:
        conclusion_lines.extend([
            "没有同时包含充电和放电的完整循环，容量保持、效率趋势、电压趋势和能量比较暂不成立。",
            "",
            "趋势与异常",
            "先修复循环缺失或分段问题，再进行科学解释。",
            "",
            "数据支持的判断",
            "当前只能说明数据流程不完整，不能评价循环性能。",
            "",
            "候选解释与判别依据",
            "无法建立候选解释；应先取得完整循环。",
        ])
    conclusion_lines.extend([
        "参考文献：原始电流数据的确定性计算不依赖文献；文献支持的机理解释只在原文学习并逐条批准后进入最终指导。",
        "",
        "下一轮实验决策",
        "1. 数据复核：从设备软件抽查一个完整循环，独立核对容量、能量、电压和循环边界。",
        "2. 重复性：完成至少3个同条件独立电池，比较散点、均值、标准差和失效样本。",
        "3. 判别实验：在首圈、稳定期和衰减后测EIS，并以循环前后结构、界面和形貌表征区分候选原因。",
        "4. 单变量：每轮只改变一个关键变量，预先写明支持结果和反证结果后再执行。",
    ])
    conclusion.write_text("\n".join(conclusion_lines) + "\n", encoding="utf-8")
    summary = target / "关键参数.csv"
    fields = list(metrics[0]) if metrics else ["cycle"]
    with summary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(metrics)
    complete = target / "完整分析.json"
    complete.write_text(
        json.dumps(
            {
                "experiment_context": profile.to_dict(),
                "scientific_standard": scientific_standard_identity(),
                "metrics": metrics,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    standard = target / "科学计算标准.json"
    standard.write_text(
        json.dumps(
            {
                "identity": scientific_standard_identity(),
                "manifest": scientific_standard_manifest(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    curves = target / "Origin_充放电曲线数据.csv"
    with curves.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["cycle", "time_s", "current_mA", "voltage_V"])
        for point in payload["imported"].points:
            writer.writerow([point.cycle, point.time_s, point.current_mA, point.voltage_V])
    job = target / "origin_job.json"
    job.write_text(
        json.dumps(
            {"curves_csv": str(curves), "status": "raw_current_curve"},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return report, conclusion, summary, complete, standard, curves, job
