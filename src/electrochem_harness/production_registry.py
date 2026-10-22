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
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Tuple

from .literature import ResearchProfile, search_crossref
from .markdown_knowledge import MarkdownLiteratureKnowledgeStore
from .origin_adapter import (
    DEFAULT_TIMEOUT_SECONDS,
    OriginError,
    OriginStatus,
    launch_origin,
)
from .sci_report import create_scientific_bundle
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

NETWORK_ARTIFACTS = ("文献证据.json", "文献比较.csv")
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

    @property
    def profile(self) -> ResearchProfile:
        return ResearchProfile(
            **{
                key: str(self.values.get(key, "")).strip()
                for key in RESEARCH_FIELDS
            }
        )

    @property
    def max_literature(self) -> int:
        try:
            requested = int(self.values.get("max_literature", 50))
        except (TypeError, ValueError):
            requested = 50
        return max(1, min(requested, 200))

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
            "purpose": "在独立联网授权下核验 DOI 并筛选可比文献",
            "requires_network": True,
            "writes_output": True,
            "failure_policy": "degrade",
            "timeout_seconds": 120,
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
            "artifacts": ("关键参数报告.md", "关键参数.csv", "完整分析.json"),
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
        result = search_crossref(profile, max_results=inputs.max_literature)
        context.checkpoint()
        knowledge_update = MarkdownLiteratureKnowledgeStore(
            inputs.knowledge_markdown
        ).update_from_search(profile, result)
        evidence = context.output_dir / "文献证据.json"
        comparison = context.output_dir / "文献比较.csv"
        evidence.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        with comparison.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["match_level", "year", "journal", "title", "doi"])
            for item in result.get("records", ()):
                writer.writerow(
                    [item.get(name) for name in ("match_level", "year", "journal", "title", "doi")]
                )
        return ToolOutcome(
            value={
                "verified_count": result.get("verified_count", 0),
                "knowledge_update": knowledge_update,
            },
            artifacts=(evidence, comparison),
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
            )
            artifacts = tuple(
                path
                for name, path in paths.items()
                if name != "knowledge_markdown" and Path(path).is_file()
            )
        report = context.output_dir / "关键参数报告.md"
        if "search_literature_metadata" in context.shared:
            with report.open("a", encoding="utf-8") as handle:
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

        launcher = inputs.origin_launcher or launch_origin
        status = launcher(
            job_path,
            inputs.project_root,
            explicit_exe=inputs.origin_exe or None,
            timeout_seconds=inputs.origin_timeout_seconds,
            checkpoint=context.checkpoint,
        )
        artifacts = tuple(
            Path(job_payload[key])
            for key in ("project_path", "curve_png", "cycling_png", "status_path")
            if job_payload.get(key)
        )
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
            timeout_seconds=120,
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
    return report, summary, complete, standard, curves, job
