"""GUI-facing adapter for the Phase 1 controlled Harness workflow.

This module keeps Tk concerns out of the safety core.  It performs a real LAND
preflight and real local report generation, while optional external adapters
remain independently authorized and degradable.
"""

import csv
import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Tuple

from .analysis import analyze_cycles
from .approval import create_approval
from .controlled_run import ControlledAnalysisRun, ControlledRunResult
from .land import load_land_export
from .land_curve import analyze_land_capacity_curve
from .literature import ResearchProfile, search_crossref
from .models import AnalysisPlan, ApprovalRecord
from .planning import build_analysis_plan
from .sci_report import create_scientific_bundle
from .scientific_standard import scientific_standard_identity, scientific_standard_manifest
from .tool_registry import (
    CancellationToken,
    FailurePolicy,
    ToolOutcome,
    ToolRegistry,
    ToolSpec,
)
from .validation import hash_file
from .workflow import ApprovalRequired, WorkflowState


@dataclass(frozen=True)
class Phase1Preparation:
    state: WorkflowState
    blocked: bool
    issues: Tuple[Mapping[str, Any], ...]
    summary: Mapping[str, Any]
    plan: Optional[AnalysisPlan]
    run_dir: Optional[Path]


class Phase1GuiController:
    """Prepare, approve and execute one GUI-owned controlled analysis."""

    def __init__(self, project_root: Path):
        self.project_root = Path(project_root).resolve()
        self.preparation: Optional[Phase1Preparation] = None
        self.controlled_run: Optional[ControlledAnalysisRun] = None
        self.approval: Optional[ApprovalRecord] = None
        self.cancellation = CancellationToken()
        self.approval_invalidated = False
        self._fingerprint = ""

    def prepare(self, values: Mapping[str, Any]) -> Phase1Preparation:
        source = Path(str(values.get("input_file", ""))).resolve()
        output = Path(str(values.get("output_dir", ""))).resolve()
        if not source.is_file():
            raise ValueError("请选择存在的蓝电输入文件。")
        if not str(values.get("output_dir", "")).strip():
            raise ValueError("请选择输出目录。")

        summary, analysis_payload, issues = _preflight(source)
        self._fingerprint = _form_fingerprint(values, source)
        self.approval = None
        self.approval_invalidated = False
        self.cancellation = CancellationToken()

        if any(bool(issue.get("blocking")) for issue in issues):
            self.controlled_run = None
            self.preparation = Phase1Preparation(
                WorkflowState.BLOCKED,
                True,
                tuple(issues),
                summary,
                None,
                None,
            )
            return self.preparation

        metadata = _metadata(values)
        metadata["output_dir"] = str(output)
        network = bool(values.get("search_literature"))
        origin = bool(values.get("use_origin"))
        plan = build_analysis_plan(
            input_identity={
                "display_path": str(source),
                "sha256": hash_file(source),
                "size_bytes": source.stat().st_size,
            },
            experiment_metadata=metadata,
            preflight_issues=issues,
            network_enabled=network,
            network_fields=(
                {key: metadata[key] for key in _RESEARCH_FIELDS}
                if network
                else None
            ),
            origin_enabled=origin,
            limitations=("Phase 1 GUI演示版仅用于验证受控执行与审计链。",),
        )
        run_id = "run-{}".format(uuid.uuid4().hex)
        registry = _production_demo_registry(
            source, values, analysis_payload, self.project_root
        )
        controlled = ControlledAnalysisRun(
            plan,
            registry,
            output / "runs",
            run_id=run_id,
        )
        self.controlled_run = controlled
        self.preparation = Phase1Preparation(
            controlled.state,
            False,
            tuple(issues),
            summary,
            plan,
            controlled.run_dir,
        )
        return self.preparation

    def approve(self, scopes=None) -> ApprovalRecord:
        if self.controlled_run is None or self.preparation is None or self.preparation.blocked:
            raise ApprovalRequired("阻断状态或尚未生成计划，不能批准执行。")
        if self.approval_invalidated:
            raise ApprovalRequired("表单已经改变，请重新生成并审核分析计划。")
        if scopes is None:
            selected_scopes = ["local_analysis", "formal_output"]
            if self.controlled_run.plan.network_enabled:
                selected_scopes.append("network_access")
        else:
            selected_scopes = list(scopes)
        record = create_approval(
            self.controlled_run.plan.plan_hash,
            scopes=selected_scopes,
            source="gui",
        )
        self.controlled_run.grant(record)
        self.approval = record
        return record

    def execute(self) -> ControlledRunResult:
        if self.controlled_run is None:
            raise ApprovalRequired("尚未生成可执行的分析计划。")
        if self.approval_invalidated:
            raise ApprovalRequired("表单已经改变，旧批准已失效。")
        return self.controlled_run.execute(cancellation=self.cancellation)

    def cancel(self, reason: str = "用户从GUI取消任务") -> None:
        self.cancellation.cancel(reason)

    def invalidate_if_changed(self, values: Mapping[str, Any]) -> bool:
        if self.preparation is None:
            return False
        source = Path(str(values.get("input_file", ""))).resolve()
        changed = _form_fingerprint(values, source) != self._fingerprint
        if changed and self.approval is not None:
            self.approval_invalidated = True
        return changed


_RESEARCH_FIELDS = (
    "battery_system",
    "active_material",
    "cell_type",
    "counter_electrode",
    "test_current",
    "temperature",
    "normalization_basis",
)


def format_plan(prepared: Phase1Preparation) -> str:
    """Return a compact user-reviewable plan for the Tk dialog."""

    lines = ["状态：{}".format(prepared.state.value)]
    if prepared.blocked:
        lines.append("\n阻断问题：")
        for issue in prepared.issues:
            lines.append("- [{}] {}".format(issue.get("code"), issue.get("message")))
        return "\n".join(lines)
    plan = prepared.plan
    lines.extend(
        [
            "计划哈希：{}".format(plan.plan_hash),
            "输入SHA-256：{}".format(plan.input_identity["sha256"]),
            "数据模式：{}".format(prepared.summary.get("mode", "unknown")),
            "数据点：{}".format(prepared.summary.get("rows", "unknown")),
            "\n工具顺序：",
        ]
    )
    lines.extend("{}. {}".format(index, tool) for index, tool in enumerate(plan.tools, 1))
    lines.append("\n联网：{}".format("是" if plan.network_enabled else "否"))
    if plan.network_enabled:
        lines.append("联网字段：{}".format(", ".join(plan.network_fields)))
    lines.append("Origin：{}".format("是（本演示版将显式降级）" if plan.origin_enabled else "否"))
    lines.append("\n预期产物：")
    lines.extend("- {}".format(name) for name in plan.expected_artifacts)
    if plan.limitations:
        lines.append("\n限制：")
        lines.extend("- {}".format(item) for item in plan.limitations)
    return "\n".join(lines)


def _preflight(source: Path):
    try:
        payload = analyze_land_capacity_curve(source)
    except (OSError, UnicodeError, ValueError) as curve_error:
        try:
            imported = load_land_export(source)
            metrics = analyze_cycles(imported.points)
        except (OSError, UnicodeError, ValueError) as raw_error:
            message = "无法识别为三列容量曲线或四列原始数据：{}；{}".format(
                curve_error, raw_error
            )
            issue = {"code": "unrecognized_land_format", "message": message, "blocking": True}
            return {"mode": "unknown", "rows": 0}, None, (issue,)
        issues = []
        summary = {
            "mode": "raw_current_curve",
            "rows": len(imported.points),
            "cycles": len(metrics),
            "encoding": imported.encoding,
            "columns": imported.detected_columns,
        }
        payload = {"mode": "raw_current_curve", "imported": imported, "metrics": metrics}
        return summary, payload, tuple(issues)

    report = payload.get("report", {})
    issues = tuple(report.get("quality_issues", ()))
    summary = {
        "mode": payload.get("import_metadata", {}).get("mode", "specific_capacity_curve"),
        "rows": report.get("source_rows", 0),
        "cycles": len(report.get("cycles", ())),
        "encoding": payload.get("import_metadata", {}).get("encoding", "unknown"),
        "columns": payload.get("import_metadata", {}).get("detected_columns", {}),
    }
    return summary, payload, issues


def _metadata(values: Mapping[str, Any]):
    return {key: str(values.get(key, "")).strip() for key in _RESEARCH_FIELDS}


def _form_fingerprint(values: Mapping[str, Any], source: Path) -> str:
    payload = {
        "input_file": str(source),
        "input_sha256": hash_file(source) if source.is_file() else "missing",
        "output_dir": str(values.get("output_dir", "")).strip(),
        "metadata": _metadata(values),
        "search_literature": bool(values.get("search_literature")),
        "use_origin": bool(values.get("use_origin")),
        "max_literature": int(values.get("max_literature", 50)),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _production_demo_registry(
    source: Path,
    values: Mapping[str, Any],
    analysis_payload: Any,
    project_root: Path,
):
    registry = ToolRegistry()
    profile = ResearchProfile(**_metadata(values))
    knowledge_markdown = Path(project_root) / "knowledge" / "literature_knowledge.md"

    def parse_tool(context):
        context.checkpoint()
        if isinstance(analysis_payload, dict) and analysis_payload.get("mode") == "raw_current_curve":
            imported = analysis_payload["imported"]
            return {"mode": "raw_current_curve", "rows": len(imported.points), "metadata": imported.metadata()}
        return {
            "mode": "specific_capacity_curve",
            "rows": analysis_payload["report"]["source_rows"],
            "metadata": analysis_payload["import_metadata"],
        }

    def quality_tool(context):
        if isinstance(analysis_payload, dict) and analysis_payload.get("mode") == "raw_current_curve":
            return {"issues": []}
        return {"issues": list(analysis_payload["report"].get("quality_issues", ())) }

    def metrics_tool(context):
        if isinstance(analysis_payload, dict) and analysis_payload.get("mode") == "raw_current_curve":
            cycles = [item.to_dict() for item in analysis_payload["metrics"]]
        else:
            cycles = list(analysis_payload["report"].get("cycles", ()))
        return {"scientific_standard": scientific_standard_identity(), "cycles": cycles}

    def literature_tool(context):
        from .markdown_knowledge import MarkdownLiteratureKnowledgeStore

        result = search_crossref(profile, max_results=max(1, min(int(values.get("max_literature", 50)), 200)))
        knowledge_update = MarkdownLiteratureKnowledgeStore(
            knowledge_markdown
        ).update_from_search(profile, result)
        evidence = context.output_dir / "文献证据.json"
        comparison = context.output_dir / "文献比较.csv"
        evidence.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        with comparison.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["match_level", "year", "journal", "title", "doi"])
            for item in result.get("records", ()):
                writer.writerow([item.get(name) for name in ("match_level", "year", "journal", "title", "doi")])
        return ToolOutcome(
            value={
                "verified_count": result.get("verified_count", 0),
                "knowledge_update": knowledge_update,
            },
            artifacts=(evidence, comparison),
        )

    def report_tool(context):
        if isinstance(analysis_payload, dict) and analysis_payload.get("mode") == "raw_current_curve":
            artifacts = _write_raw_bundle(context.output_dir, source, analysis_payload, profile)
        else:
            paths = create_scientific_bundle(
                source,
                context.output_dir,
                material=profile.active_material,
                cell_configuration=profile.cell_description,
                rate=profile.test_current,
                temperature=profile.temperature,
                research_profile=profile,
                search_literature=False,
                literature_knowledge_path=None,
                literature_markdown_path=knowledge_markdown,
            )
            artifacts = tuple(
                path
                for name, path in paths.items()
                if name != "knowledge_markdown" and Path(path).is_file()
            )
        report = context.output_dir / "关键参数报告.md"
        if "search_literature_metadata" in context.shared:
            with report.open("a", encoding="utf-8") as handle:
                handle.write("\n## Phase 1文献执行记录\n\n已在独立联网授权范围内完成文献元数据检索，详情见 `文献证据.json`。\n")
        return ToolOutcome(value={"report": str(report)}, artifacts=tuple(artifacts))

    def origin_tool(context):
        raise RuntimeError("Phase 1 GUI演示版尚未接入独立Origin适配器；本地报告和绘图CSV已保留。")

    registry.register(ToolSpec("parse_land_text", parse_tool))
    registry.register(ToolSpec("quality_check", quality_tool))
    registry.register(ToolSpec("calculate_cycle_metrics", metrics_tool))
    registry.register(
        ToolSpec(
            "search_literature_metadata",
            literature_tool,
            requires_network=True,
            writes_output=True,
            failure_policy=FailurePolicy.DEGRADE,
            timeout_seconds=120,
        )
    )
    registry.register(ToolSpec("build_scientific_report", report_tool, writes_output=True, timeout_seconds=120))
    registry.register(
        ToolSpec(
            "build_origin_project",
            origin_tool,
            writes_output=True,
            failure_policy=FailurePolicy.DEGRADE,
        )
    )
    registry.seal()
    return registry


def _write_raw_bundle(target: Path, source: Path, payload: Mapping[str, Any], profile: ResearchProfile):
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
        json.dumps({"curves_csv": str(curves), "status": "phase1_demo"}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report, summary, complete, standard, curves, job
