"""GUI-facing adapter for the Phase 1 controlled Harness workflow.

This module keeps Tk concerns out of the safety core.  It performs a real LAND
preflight and real local report generation, while optional external adapters
remain independently authorized and degradable.
"""

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
from .models import AnalysisPlan, ApprovalRecord
from .planning import build_analysis_plan
from .production_registry import ToolchainInputs, build_production_registry
from .tool_registry import CancellationToken
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
    """Prepare, approve and execute one GUI-owned controlled analysis.

    ``origin_launcher`` is injectable so tests (and CI machines without Origin)
    can exercise both the success and the degradation path without starting a
    real Origin instance.
    """

    def __init__(self, project_root: Path, *, origin_launcher=None):
        self.project_root = Path(project_root).resolve()
        self.origin_launcher = origin_launcher
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
            source,
            values,
            analysis_payload,
            self.project_root,
            origin_launcher=self.origin_launcher,
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
            # 四列模式解析成功但数值检查失败时，必须给出可操作的原因，
            # 否则"时间倒退"会被误报成"格式无法识别"，用户不知道该改什么。
            translated = _translate_raw_failure(raw_error, curve_error)
            if translated is not None:
                return {"mode": "unknown", "rows": 0}, None, (translated,)
            message = "无法识别为三列容量曲线或四列原始数据：{}；{}".format(
                curve_error, raw_error
            )
            issue = {"code": "unrecognized_land_format", "message": message, "blocking": True}
            return {"mode": "unknown", "rows": 0}, None, (issue,)
        issues = []
        # 四列模式没有内建的质检，这里补上"某圈缺放电段"的提示：
        # 否则末圈不完整会被算成放电容量 0 而没有任何说明。
        for item in metrics:
            if item.charge_capacity_mAh > 0 and item.discharge_capacity_mAh == 0:
                issues.append(
                    {
                        "code": "incomplete_cycle",
                        "message": "第 {} 圈只有充电段、没有放电段；该圈的库仑效率与容量保持率不可用。".format(
                            item.cycle
                        ),
                        "blocking": False,
                    }
                )
        summary = {
            "mode": "raw_current_curve",
            "rows": len(imported.points),
            "cycles": len(metrics),
            "encoding": imported.encoding,
            "columns": imported.detected_columns,
        }
        payload = {"mode": "raw_current_curve", "imported": imported, "metrics": metrics}
        return summary, payload, tuple(issues)

    # 三列比容量曲线：直接使用导出的比容量，不做电流积分
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


def _translate_raw_failure(raw_error: Exception, curve_error: Exception):
    """Map a numeric failure on parsed four-column data to a blocking quality issue."""

    text = str(raw_error).lower()
    if "time_s must increase" in text:
        return {
            "code": "non_monotonic_time",
            "message": "时间列不是严格递增（存在倒退或重复），无法对电流做积分；请检查导出或排序后重试。",
            "blocking": True,
        }
    if "non-finite" in text:
        return {
            "code": "non_finite_value",
            "message": "存在 NaN 或无穷大数值，无法计算容量；请检查原始导出。",
            "blocking": True,
        }
    return None


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
    origin_launcher=None,
):
    """Backward-compatible wrapper around the Phase 5 production registry.

    Kept so existing callers and tests keep one import path while the declared
    registry lives in :mod:`electrochem_harness.production_registry`.
    """

    return build_production_registry(
        ToolchainInputs(
            source=Path(source),
            values=values,
            analysis_payload=analysis_payload,
            project_root=Path(project_root),
            knowledge_markdown=Path(project_root) / "knowledge" / "literature_knowledge.md",
            origin_launcher=origin_launcher,
            origin_exe=str(values.get("origin_exe", "")).strip(),
        )
    )
