"""Six-step wizard controller for the production GUI (Phase 5 / B2).

This module holds every decision the interface needs and none of the drawing:
which step is active, whether the user may advance, which approvals are still
valid, what happens on cancel or retry, and what the results screen should show.

Keeping that logic out of Tk has two payoffs:

* every rule below is covered by headless tests, so a layout change cannot
  silently weaken the approval gate;
* the Tk layer becomes a thin renderer, which is what makes the six-step flow
  reviewable by someone who does not read Python.

Step model::

    1 数据与实验条件 -> 2 预检查与阻断问题 -> 3 分析计划
    -> 4 三档独立批准 -> 5 受控执行 -> 6 结果、证据与审计

The wizard never executes anything itself. It only tells
:class:`electrochem_harness.gui_phase1.Phase1GuiController` what to prepare,
approve, run, cancel, or retry.
"""

from dataclasses import dataclass
from enum import Enum
import math
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence, Tuple

from .gui_phase1 import Phase1GuiController, Phase1Preparation
from .production_registry import LEGACY_NETWORK_ARTIFACTS, NETWORK_ARTIFACTS, ORIGIN_ARTIFACTS
from .workflow import ApprovalRequired


class WizardStep(str, Enum):
    DATA = "data"
    PREFLIGHT = "preflight"
    PLAN = "plan"
    APPROVAL = "approval"
    EXECUTE = "execute"
    RESULTS = "results"


class WizardError(RuntimeError):
    """Raised when the wizard is asked to leave the six-step order."""


STEP_TITLES = {
    WizardStep.DATA: "1. 数据与实验条件",
    WizardStep.PREFLIGHT: "2. 预检查与阻断问题",
    WizardStep.PLAN: "3. 分析计划",
    WizardStep.APPROVAL: "4. 独立批准",
    WizardStep.EXECUTE: "5. 受控执行",
    WizardStep.RESULTS: "6. 知识审核、结论与课题对话",
}

_NEXT_STEP = {
    WizardStep.DATA: WizardStep.PREFLIGHT,
    WizardStep.PREFLIGHT: WizardStep.PLAN,
    WizardStep.PLAN: WizardStep.APPROVAL,
    WizardStep.APPROVAL: WizardStep.EXECUTE,
    WizardStep.EXECUTE: WizardStep.RESULTS,
}

SCOPE_LABELS = {
    "local_analysis": "本地分析与报告",
    "network_access": "联网文献检索",
    "formal_output": "正式输出（写入产物文件）",
}

UNKNOWN_VALUES = {"", "待填", "未知", "unknown", "n/a", "na", "???"}

METADATA_FIELDS = (
    ("battery_system", "电池体系", "例如：锂硫电池 / lithium-sulfur battery"),
    ("active_material", "活性物质", "例如：S/C复合正极、LiFePO4"),
    ("cell_type", "电池类型", "例如：半电池、全电池、对称电池"),
    ("counter_electrode", "对电极/另一电极", "例如：Li、Na、NMC811"),
    ("test_current", "测试电流", "mA"),
    ("temperature", "测试温度", "°C"),
)

SUPPORTED_EXTENSIONS = {".csv", ".txt", ".tsv", ".dat"}


def _missing(value: Any) -> bool:
    return str(value or "").strip().casefold() in UNKNOWN_VALUES


def validate_form(values: Mapping[str, Any]) -> Tuple[str, ...]:
    """Shared, display-free form validation.

    It lives here rather than in the Tk module so the headless evaluation path
    and the GUI enforce exactly the same rules; previously only the dialog
    checked the form, so a scripted run could plan a literature search with
    every search field blank.
    """

    errors = []
    source_text = str(values.get("input_file", "")).strip()
    if not source_text or not Path(source_text).is_file():
        errors.append("请选择存在的蓝电输入文件。")
    elif Path(source_text).suffix.lower() not in SUPPORTED_EXTENSIONS:
        errors.append("输入文件必须是 CSV、TXT、TSV 或 DAT 文本导出。")
    if not str(values.get("output_dir", "")).strip():
        errors.append("请选择输出目录。")
    if values.get("search_literature"):
        for name, label, _hint in METADATA_FIELDS:
            if _missing(values.get(name)):
                errors.append("完整研究闭环必须填写：{}。".format(label))
        if values.get("unified_research"):
            for name, label in (
                ("research_domain", "研究领域"),
                ("research_background", "课题背景"),
                ("research_question", "本轮科学问题"),
            ):
                if _missing(values.get(name)):
                    errors.append("完整研究闭环必须填写：{}。".format(label))
            fulltext_dir = str(values.get("local_fulltext_dir", "")).strip()
            if fulltext_dir and not Path(fulltext_dir).is_dir():
                errors.append("本地论文原文目录不存在。")
    for name, label, unit in (
        ("test_current", "测试电流", "mA"),
        ("temperature", "测试温度", "°C"),
    ):
        value = str(values.get(name, "")).strip()
        if value and not _missing(value):
            try:
                number = float(value)
                if not math.isfinite(number):
                    raise ValueError
                if name == "test_current" and number <= 0:
                    raise ValueError
                if name == "temperature" and number <= -273.15:
                    raise ValueError
            except (TypeError, ValueError):
                errors.append("{}只填写数值，单位固定为{}。".format(label, unit))
    try:
        maximum = int(values.get("max_literature", 5 if values.get("unified_research") else 50))
        upper = 5 if values.get("unified_research") else 200
        if maximum < 1 or maximum > upper:
            raise ValueError
    except (TypeError, ValueError):
        errors.append(
            "每轮学习论文数量必须是 1–5 的整数。"
            if values.get("unified_research")
            else "候选 DOI 数量必须是 1–200 的整数。"
        )
    origin_exe = str(values.get("origin_exe", "")).strip()
    if values.get("use_origin") and origin_exe and not Path(origin_exe).is_file():
        errors.append("指定的 Origin64.exe 不存在；可清空该项让程序自动查找。")
    plot_mode = str(values.get("origin_plot_mode", "both") or "both").strip().casefold()
    if values.get("use_origin") and plot_mode not in {"curve", "cycling", "both"}:
        errors.append("请选择充放电曲线图、循环库仑效率图或两张都画。")
    return tuple(errors)


@dataclass(frozen=True)
class PreflightView:
    """What step 2 shows, split by severity so the user knows what blocks."""

    blocking: Tuple[Mapping[str, Any], ...]
    warnings: Tuple[Mapping[str, Any], ...]
    summary: Mapping[str, Any]

    @property
    def blocked(self) -> bool:
        return bool(self.blocking)

    def to_dict(self) -> Mapping[str, Any]:
        return {
            "blocking": [dict(item) for item in self.blocking],
            "warnings": [dict(item) for item in self.warnings],
            "summary": dict(self.summary),
            "blocked": self.blocked,
        }


@dataclass(frozen=True)
class ResultEntry:
    """One reviewable item on the results screen."""

    name: str
    path: Optional[Path]
    required: bool = True

    @property
    def available(self) -> bool:
        return self.path is not None and Path(self.path).is_file()

    def to_dict(self) -> Mapping[str, Any]:
        return {
            "name": self.name,
            "path": None if self.path is None else str(self.path),
            "required": self.required,
            "available": self.available,
        }


@dataclass(frozen=True)
class ResultView:
    """Grouped results; missing optional groups are shown as 'not enabled'."""

    report: Tuple[ResultEntry, ...]
    evidence: Tuple[ResultEntry, ...]
    origin: Tuple[ResultEntry, ...]
    audit: Tuple[ResultEntry, ...]
    degradations: Tuple[str, ...] = ()
    state: Optional[str] = None

    def all_entries(self) -> Tuple[ResultEntry, ...]:
        return self.report + self.evidence + self.origin + self.audit

    def to_dict(self) -> Mapping[str, Any]:
        return {
            "report": [item.to_dict() for item in self.report],
            "evidence": [item.to_dict() for item in self.evidence],
            "origin": [item.to_dict() for item in self.origin],
            "audit": [item.to_dict() for item in self.audit],
            "degradations": list(self.degradations),
            "state": self.state,
        }


class SixStepWizard:
    """Drive the six steps while delegating all work to the harness controller."""

    def __init__(
        self,
        project_root: Path,
        *,
        origin_launcher: Optional[Callable[..., Any]] = None,
        progress_callback: Optional[Callable[[str, str, Mapping], None]] = None,
    ):
        self.project_root = Path(project_root)
        self._controller = Phase1GuiController(
            self.project_root,
            origin_launcher=origin_launcher,
            progress_callback=progress_callback,
        )
        self._step = WizardStep.DATA
        self._values: Optional[Mapping[str, Any]] = None
        self._scopes: Tuple[str, ...] = ()
        self._approved = False
        self._prepared: Optional[Phase1Preparation] = None
        self._results: Optional[ResultView] = None
        self._history = []

    # -- read-only view state -------------------------------------------------

    @property
    def step(self) -> WizardStep:
        return self._step

    @property
    def title(self) -> str:
        return STEP_TITLES[self._step]

    @property
    def controller(self) -> Phase1GuiController:
        return self._controller

    @property
    def prepared(self) -> Optional[Phase1Preparation]:
        return self._prepared

    @property
    def scopes(self) -> Tuple[str, ...]:
        return self._scopes

    @property
    def results(self) -> Optional[ResultView]:
        return self._results

    @property
    def history(self) -> Tuple[str, ...]:
        return tuple(self._history)

    @property
    def required_scopes(self) -> Tuple[str, ...]:
        """Local analysis and formal output are mandatory; network is optional."""

        required = ["local_analysis", "formal_output"]
        if self._prepared is not None and self._prepared.plan is not None:
            if self._prepared.plan.network_enabled:
                required.append("network_access")
        return tuple(required)

    @property
    def can_start(self) -> bool:
        """Execution is reachable only with a recorded, complete approval.

        Selecting scopes is not approving: ``can_start`` stays false until
        :meth:`approve` has persisted a decision bound to the current plan hash.
        """

        if self._step is not WizardStep.APPROVAL or not self._approved:
            return False
        return set(self.required_scopes).issubset(set(self._scopes))

    # -- step 1 ---------------------------------------------------------------

    def edit_form(self, values: Mapping[str, Any]) -> None:
        """Record form values and invalidate any prepared plan and approval."""

        self._values = dict(values)
        self._prepared = None
        self._results = None
        self._scopes = ()
        self._approved = False
        self._step = WizardStep.DATA
        self._note("form_edited")

    # -- step 2 ---------------------------------------------------------------

    def run_preflight(self) -> PreflightView:
        if self._values is None:
            raise WizardError("请先填写第 1 步的数据与实验条件。")
        errors = validate_form(self._values)
        if errors:
            raise WizardError("；".join(errors))
        try:
            prepared = self._controller.prepare(self._values)
        except ValueError as error:
            raise WizardError(str(error)) from error

        self._prepared = prepared
        self._step = WizardStep.PREFLIGHT
        self._note("preflight_blocked" if prepared.blocked else "preflight_passed")

        blocking = tuple(item for item in prepared.issues if item.get("blocking"))
        warnings = tuple(item for item in prepared.issues if not item.get("blocking"))
        return PreflightView(blocking, warnings, prepared.summary)

    # -- step 3 ---------------------------------------------------------------

    def review_plan(self) -> Mapping[str, Any]:
        """Return a step-3 summary; blocked runs cannot advance."""

        if self._prepared is None:
            raise WizardError("请先完成第 2 步的预检查。")
        if self._prepared.blocked or self._prepared.plan is None:
            raise WizardError("存在阻断问题，修正数据后重新预检查。")
        self._step = WizardStep.PLAN
        self._note("plan_reviewed")
        plan = self._prepared.plan
        return {
            "plan_id": plan.plan_id,
            "plan_hash": plan.plan_hash,
            "input_sha256": plan.input_identity["sha256"],
            "tools": list(plan.tools),
            "network_enabled": plan.network_enabled,
            "network_fields": dict(plan.network_fields),
            "origin_enabled": plan.origin_enabled,
            "expected_artifacts": list(plan.expected_artifacts),
            "limitations": list(plan.limitations),
            "risks": list(plan.risks),
        }

    # -- step 4 ---------------------------------------------------------------

    def request_approval(self) -> Mapping[str, Any]:
        """Move to step 4 and describe what each scope authorises."""

        if self._step is not WizardStep.PLAN:
            raise WizardError("请先在第 3 步查看分析计划。")
        self._step = WizardStep.APPROVAL
        self._note("approval_requested")
        plan = self._prepared.plan
        available = ["local_analysis", "formal_output"]
        if plan.network_enabled:
            available.insert(1, "network_access")
        return {
            "required": list(self.required_scopes),
            "available": [
                {"scope": name, "label": SCOPE_LABELS[name]} for name in available
            ],
            "network_fields": dict(plan.network_fields),
        }

    def set_scopes(self, scopes: Sequence[str]) -> None:
        if self._step is not WizardStep.APPROVAL:
            raise WizardError("只有第 4 步可以调整批准范围。")
        unknown = sorted(set(scopes) - set(SCOPE_LABELS))
        if unknown:
            raise WizardError("未知批准范围：{}".format("、".join(unknown)))
        self._scopes = tuple(sorted(set(scopes)))
        self._note("scopes_updated")

    def approve(self, scopes: Optional[Sequence[str]] = None) -> None:
        if self._step is not WizardStep.APPROVAL:
            raise WizardError("只有第 4 步可以批准。")
        if scopes is not None:
            self.set_scopes(scopes)
        missing = sorted(set(self.required_scopes) - set(self._scopes))
        if missing:
            raise ApprovalRequired(
                "批准范围不足：{}".format("、".join(missing))
            )
        self._controller.approve(self._scopes)
        self._approved = True
        self._note("approved")

    def approve_and_start(self, scopes: Optional[Sequence[str]] = None) -> str:
        """Approve the current plan and execute it in one user action."""

        self.approve(scopes)
        return self.start()

    # -- step 5 ---------------------------------------------------------------

    def start(self) -> str:
        if not self.can_start:
            raise ApprovalRequired("未获得完整批准，不能开始执行。")
        self._step = WizardStep.EXECUTE
        self._note("execution_started")
        result = self._controller.execute()
        self._results = self._collect_results(result)
        self._step = WizardStep.RESULTS
        self._note("execution_finished:{}".format(result.state.value))
        return result.state.value

    def cancel(self, reason: str = "用户取消") -> None:
        self._controller.cancel(reason)
        self._note("cancel_requested")

    def retry(self) -> str:
        """Re-run the whole plan as a fresh, separately audited run.

        A failed run is never resurrected: its registry is sealed, its event
        chain already has a terminal event, and rewriting either would destroy
        the audit trail. Retrying therefore prepares a new run from the same
        form values, re-grants the same scopes against the same plan hash, and
        records the retry in the new run's own event log.
        """

        if self._results is None:
            raise WizardError("只有完成过一次执行后才能重试。")
        previous = self._controller.controlled_run
        previous_run_dir = None if previous is None else previous.run_dir
        if self._values is None:
            raise WizardError("原始表单已丢失，无法重试。")

        try:
            prepared = self._controller.prepare(self._values)
        except ValueError as error:
            raise WizardError(str(error)) from error
        self._prepared = prepared
        if prepared.blocked:
            self._step = WizardStep.PREFLIGHT
            self._note("retry_blocked")
            return "blocked"

        self._step = WizardStep.APPROVAL
        self._controller.approve(self._scopes)
        self._approved = True
        if previous_run_dir is not None and self._controller.controlled_run is not None:
            self._controller.controlled_run.audit.append_event(
                "retry_requested",
                self._controller.controlled_run.state.value,
                {"previous_run_dir": str(previous_run_dir), "scopes": list(self._scopes)},
            )
        result = self._controller.execute()
        self._results = self._collect_results(result)
        self._step = WizardStep.RESULTS
        self._note("retried:{}".format(result.state.value))
        return result.state.value

    def back_to_form(self) -> None:
        """Return to step 1 while keeping the last values, invalidating approval."""

        if self._values is None:
            raise WizardError("还没有可编辑的表单内容。")
        self.edit_form(self._values)

    # -- step 6 ---------------------------------------------------------------

    def _collect_results(self, result) -> ResultView:
        artifacts = Path(result.run_dir) / "artifacts"
        run_dir = Path(result.run_dir)

        plan = None if self._prepared is None else self._prepared.plan
        network_enabled = bool(plan is not None and plan.network_enabled)
        origin_enabled = bool(plan is not None and plan.origin_enabled)

        def entry(name, required=True):
            return ResultEntry(name, artifacts / name, required=required)

        report = [
            entry(name)
            for name in (
                "关键结论.txt",
                "关键参数报告.md",
                "关键参数.csv",
                "完整分析.json",
                "科学计算标准.json",
                "Origin_充放电曲线数据.csv",
                "origin_job.json",
            )
        ]
        if plan is not None and plan.experiment_metadata.get("unified_research"):
            report.extend((entry("研究结论与指导.txt"), entry("研究分析报告.html")))
        network_artifacts = (
            NETWORK_ARTIFACTS
            if plan is not None and plan.experiment_metadata.get("unified_research")
            else LEGACY_NETWORK_ARTIFACTS
        )
        evidence = [entry(name, network_enabled) for name in network_artifacts]
        expected = set(() if plan is None else plan.expected_artifacts)
        origin = [entry(name, origin_enabled and name in expected) for name in ORIGIN_ARTIFACTS]
        audit = [
            ResultEntry(name, run_dir / name)
            for name in (
                "plan.json",
                "preflight.json",
                "approval.json",
                "events.jsonl",
                "run_record.json",
            )
        ]
        return ResultView(
            report=tuple(report),
            evidence=tuple(evidence),
            origin=tuple(origin),
            audit=tuple(audit),
            degradations=tuple(
                "{}: {}".format(item.tool_id, item.reason) for item in result.degradations
            ),
            state=result.state.value,
        )

    def _note(self, event: str) -> None:
        self._history.append("{}:{}".format(self._step.value, event))
