"""Single-window Tk interface for the four-stage Harness-v2 workflow."""
from __future__ import annotations

import json
from pathlib import Path
import queue
import threading
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, ttk


RESEARCH_STATE_LIST_FIELDS = (
    "confirmed_decisions",
    "user_corrections",
    "rejected_hypotheses",
    "open_questions",
)
ANALYSIS_TYPES = ("gcd", "cv", "eis", "gitt")
ANALYSIS_LABELS = {
    "gcd": "GCD 恒流充放电",
    "cv": "CV 循环伏安",
    "eis": "EIS 阻抗谱",
    "gitt": "GITT 间歇滴定",
}
DEFAULT_REPLICATE_METRICS = {
    "gcd": "gcd_summary.latest_complete_discharge_capacity_mAh_g",
    "cv": "cycles.0.peak_separation_V",
    "eis": "high_frequency_real_axis_intercept_candidate.z_real_ohm",
    "gitt": "pulses.0.instantaneous_voltage_change_V",
}


def normalize_analysis_type(value: str) -> str:
    method = str(value or "").strip().casefold()
    if method not in ANALYSIS_TYPES:
        raise ValueError("分析方法必须是 gcd、cv、eis 或 gitt。")
    return method


def analysis_condition_hint(method: str) -> str:
    hints = {
        "gcd": "GCD：可填写 active_material_mass_mg、temperature_C 等条件。",
        "cv": "CV：scan_rate 可选；缺少时不计算积分电荷。",
        "eis": "EIS：tail_fraction 可选，默认 0.3。",
        "gitt": "GITT：必须填写 current_threshold_A。",
    }
    return hints[normalize_analysis_type(method)]


def default_replicate_metric(method: str) -> str:
    return DEFAULT_REPLICATE_METRICS[normalize_analysis_type(method)]


def format_stage_statuses(stages) -> str:
    if not stages:
        return "暂无阶段记录。"
    return "；".join(
        "{}={}(第{}次)".format(row["stage"], row["status"], row["attempt"])
        for row in stages
    )


def parse_condition_value(value: str):
    text = str(value).strip()
    if not text:
        return ""
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return text
    if isinstance(parsed, (dict, list, int, float, bool)) or parsed is None:
        return parsed
    return text


def build_run_options(pdf_evidence: bool, online_research: bool, codex_assessment: bool) -> dict[str, bool]:
    """Map the three independent GUI switches to ``run_all`` keyword arguments."""
    return {
        "use_codex_candidates": bool(pdf_evidence),
        "use_online_research": bool(online_research),
        "use_codex_assessment": bool(codex_assessment),
    }


def build_send_scope_summary(
    pdf_evidence: bool,
    online_research: bool,
    codex_assessment: bool,
    *,
    has_pdf: bool,
) -> str:
    """Describe model/network scope without accepting or rendering file paths."""
    if pdf_evidence and has_pdf:
        pdf_scope = "开启；向 Codex 发送课题上下文和分页证据片段，不发送 PDF 文件。"
    elif pdf_evidence:
        pdf_scope = "开启；尚未选择 PDF，本轮不发送 PDF 证据。"
    else:
        pdf_scope = "关闭。"
    online_scope = (
        "开启；发送课题关键词和确定性指标，用于检索公开学术来源。"
        if online_research else "关闭。"
    )
    assessment_scope = (
        "开启；发送确定性摘要、Origin 状态和分级知识，不发送逐行原始数据。"
        if codex_assessment else "关闭。"
    )
    lines = [
        "本轮发送范围",
        "• PDF 证据提取：{}".format(pdf_scope),
        "• 联网研究：{}".format(online_scope),
        "• Codex 课题评估：{}".format(assessment_scope),
        "• 文件路径：不发送。",
    ]
    if not any((pdf_evidence, online_research, codex_assessment)):
        lines.append("• 三项均关闭，本轮不调用任何 Codex 路径。")
    return "\n".join(lines)


def parse_research_state_items(text: str) -> list:
    """Parse one item per line, retaining JSON objects used by rejected hypotheses."""
    values = []
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            value = line
        values.append(value)
    return values[-40:]


def format_research_state_items(values) -> str:
    """Render state items in a line-oriented form that round-trips JSON records."""
    lines = []
    for value in values or []:
        if isinstance(value, str):
            lines.append(value)
        else:
            lines.append(json.dumps(value, ensure_ascii=False, sort_keys=True))
    return "\n".join(lines)


def format_claim_review_details(claim, spans) -> str:
    """Build a complete, readable claim review record from domain objects."""
    conditions = dict(getattr(claim, "conditions", {}) or {})
    urls = [str(value) for value in conditions.get("source_urls") or [] if str(value).strip()]
    span_by_id = {getattr(span, "span_id", ""): span for span in spans or []}
    evidence_lines = []
    for span_id in getattr(claim, "evidence_span_ids", ()) or ():
        span = span_by_id.get(span_id)
        if span is None:
            evidence_lines.append("  - {}（本地 span 未找到）".format(span_id))
            continue
        page = getattr(span, "page_label", None) or str(getattr(span, "page_index", "?"))
        evidence_lines.append("  - {}｜页 {}｜{}".format(span_id, page, str(getattr(span, "text", "")).strip()))
    if not evidence_lines:
        evidence_lines.append("  （无本地证据 span；请核对列出的外部来源。）")
    sources = ["source_id: {}".format(getattr(claim, "source_id", ""))]
    sources.extend(urls)
    return "\n".join([
        "Claim：{}".format(getattr(claim, "text", "")),
        "状态：{}".format(getattr(claim, "status", "")),
        "条件：{}".format(json.dumps(conditions, ensure_ascii=False, indent=2, sort_keys=True)),
        "限制：{}".format("；".join(str(value) for value in (getattr(claim, "limitations", ()) or ())) or "无"),
        "来源：\n  {}".format("\n  ".join(sources)),
        "本地证据 span：\n{}".format("\n".join(evidence_lines)),
    ])


def format_review_audit(rows) -> str:
    """Render persisted review events for refresh-safe audit display."""
    lines = []
    for claim, event in rows:
        lines.append(
            "{}｜{} → {}｜审核人：{}｜理由：{}｜{}".format(
                getattr(claim, "claim_id", ""),
                getattr(event, "previous_status", ""),
                getattr(event, "new_status", ""),
                getattr(event, "reviewer", ""),
                getattr(event, "reason", ""),
                getattr(event, "reviewed_at", ""),
            )
        )
    return "\n".join(lines) if lines else "暂无审核审计。"


class HarnessApp:
    def __init__(self, root: tk.Tk, project_root: Path | str):
        from .workflow import ResearchWorkflow

        self.root = root
        self.project_root = Path(project_root)
        self.workflow = ResearchWorkflow(self.project_root / "knowledge" / "research.sqlite3", self.project_root / "outputs" / "research_cockpit")
        self.project_id: str | None = None
        self.source_id: str | None = None
        self.run_id: str | None = None
        self.thread_id: str | None = None
        self.name = tk.StringVar()
        self.material = tk.StringVar()
        self.keywords = tk.StringVar()
        self.analysis_type = tk.StringVar(value="gcd")
        self.conditions = tk.StringVar(value="temperature_C=60")
        self.active_material_mass_mg = tk.StringVar()
        self.pdf_path = tk.StringVar()
        self.data_path = tk.StringVar()
        self.use_pdf_evidence = tk.BooleanVar(value=True)
        self.use_online_research = tk.BooleanVar(value=True)
        self.use_codex_assessment = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value="填写课题、选择数据和可选 PDF 后，单击一次自动完成流程。")
        self._events: queue.Queue = queue.Queue()
        self._running = False
        self._cancel_event = threading.Event()
        self._last_report: Path | None = None
        self._mutating_buttons: list[ttk.Button] = []
        self._review_window = None
        self._state_window = None
        self._segment_window = None
        self._replicate_window = None
        self._run_rows: list[dict] = []
        self._build()
        self.refresh_projects()

    def _build(self) -> None:
        self.root.title("ElectrochemHarness v2｜可审计科研闭环")
        self.root.geometry("1180x880")
        outer = ttk.Frame(self.root, padding=14)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(14, weight=1)
        ttk.Label(outer, text="ElectrochemHarness v2", font=("Microsoft YaHei UI", 18, "bold")).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(outer, text="①课题/数据  ②检索/知识  ③确定性分析/Origin  ④报告/指导", foreground="#38566f").grid(row=1, column=0, columnspan=3, sticky="w", pady=(2, 12))
        self._field(outer, 2, "课题名称", self.name)
        self._field(outer, 3, "课题类型（材料体系）", self.material)
        self._field(outer, 4, "关键词（分号）", self.keywords)
        ttk.Label(outer, text="分析方法").grid(row=5, column=0, sticky="w", pady=3)
        self.analysis_methods = ttk.Combobox(
            outer,
            textvariable=self.analysis_type,
            values=ANALYSIS_TYPES,
            state="readonly",
        )
        self.analysis_methods.grid(row=5, column=1, sticky="ew", pady=3)
        self.analysis_methods.bind("<<ComboboxSelected>>", self._analysis_type_changed)
        self.analysis_hint = ttk.Label(outer, text=analysis_condition_hint("gcd"), foreground="#667582")
        self.analysis_hint.grid(row=5, column=2, sticky="w", padx=(6, 0))
        self._field(outer, 6, "实验条件（key=value；分隔）", self.conditions)
        self._field(outer, 7, "活性物质质量（mg，仅 GCD）", self.active_material_mass_mg)
        self._file_field(outer, 8, "本地 PDF（可选）", self.pdf_path, [("PDF", "*.pdf")])
        self._file_field(outer, 9, "实验数据", self.data_path, [("Data", "*.csv *.txt *.tsv *.dat")])

        scope = ttk.LabelFrame(outer, text="可选外部处理（彼此独立）", padding=(8, 4))
        scope.grid(row=10, column=0, columnspan=3, sticky="ew", pady=(8, 4))
        ttk.Checkbutton(scope, text="PDF 证据提取（Codex，仅发送分页证据片段）", variable=self.use_pdf_evidence).pack(side="left")
        ttk.Checkbutton(scope, text="联网研究", variable=self.use_online_research).pack(side="left", padx=16)
        ttk.Checkbutton(scope, text="Codex 课题评估", variable=self.use_codex_assessment).pack(side="left")

        controls = ttk.Frame(outer)
        controls.grid(row=11, column=0, columnspan=3, sticky="ew", pady=(4, 4))
        self.create_button = self._state_button(controls, "创建新课题", self.create_project)
        self.create_button.pack(side="left")
        self.open_button = self._state_button(controls, "打开选中课题", self.open_project)
        self.open_button.pack(side="left", padx=4)
        self.save_project_button = self._state_button(controls, "保存课题修改", self.save_project_changes)
        self.save_project_button.pack(side="left", padx=4)
        self.projects = ttk.Combobox(controls, width=36, state="readonly")
        self.projects.pack(side="left", padx=4)
        ttk.Button(controls, text="刷新课题", command=self.refresh_projects).pack(side="left", padx=4)
        self.review_entry_button = self._state_button(controls, "审核候选知识", self.open_review_queue)
        self.review_entry_button.pack(side="right")
        self.state_entry_button = self._state_button(controls, "编辑研究状态", self.open_research_state)
        self.state_entry_button.pack(side="right", padx=4)

        run_controls = ttk.Frame(outer)
        run_controls.grid(row=12, column=0, columnspan=3, sticky="ew", pady=(2, 4))
        ttk.Label(run_controls, text="运行记录").pack(side="left")
        self.runs = ttk.Combobox(run_controls, width=58, state="readonly")
        self.runs.pack(side="left", padx=4)
        self.runs.bind("<<ComboboxSelected>>", self._run_selected)
        ttk.Button(run_controls, text="刷新运行", command=self.refresh_runs).pack(side="left", padx=4)
        self.resume_button = self._state_button(run_controls, "恢复选中运行", self.resume_selected_run)
        self.resume_button.pack(side="left", padx=4)
        self.segment_button = self._state_button(run_controls, "审核 GCD 分段", self.open_segment_review)
        self.segment_button.pack(side="left", padx=4)
        self.replicate_button = self._state_button(run_controls, "重复统计", self.open_replicate_analysis)
        self.replicate_button.pack(side="left", padx=4)

        actions = ttk.Frame(outer)
        actions.grid(row=13, column=0, columnspan=3, sticky="ew")
        self.auto_button = self._state_button(actions, "自动执行课题全流程", self.run_all_automatically)
        self.auto_button.pack(side="left")
        self.cancel_button = ttk.Button(actions, text="请求取消", command=self.cancel_current_run, state="disabled")
        self.cancel_button.pack(side="left", padx=4)
        ttk.Button(actions, text="打开最近图文报告", command=self.open_latest_report).pack(side="left", padx=4)
        ttk.Button(actions, text="打开 Codex 工作记录", command=self.open_codex_activity).pack(side="left", padx=4)
        self.progress = ttk.Progressbar(actions, mode="determinate", maximum=9, length=250)
        self.progress.pack(side="right", padx=8)
        self.monitor = tk.Text(outer, height=10, wrap="word", state="disabled", padx=8, pady=8)
        self.monitor.grid(row=14, column=0, columnspan=3, sticky="nsew", pady=(8, 4))
        ttk.Label(outer, textvariable=self.status, foreground="#38566f").grid(row=15, column=0, columnspan=3, sticky="w")

    def _state_button(self, parent, text, command) -> ttk.Button:
        button = ttk.Button(parent, text=text, command=command)
        self._mutating_buttons.append(button)
        return button

    def _set_mutating_buttons_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        live_buttons = []
        for button in self._mutating_buttons:
            try:
                if button.winfo_exists():
                    button.configure(state=state)
                    live_buttons.append(button)
            except tk.TclError:
                continue
        self._mutating_buttons = live_buttons

    def _field(self, parent, row, label, variable):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=3)
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, columnspan=2, sticky="ew", pady=3)

    def _file_field(self, parent, row, label, variable, filetypes):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=3)
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky="ew", pady=3)
        ttk.Button(parent, text="选择", command=lambda: self._choose(variable, filetypes)).grid(row=row, column=2, padx=(6, 0))

    def _choose(self, variable, filetypes):
        path = filedialog.askopenfilename(parent=self.root, filetypes=filetypes)
        if path:
            variable.set(path)

    def _analysis_type_changed(self, _event=None):
        try:
            method = normalize_analysis_type(self.analysis_type.get())
        except ValueError:
            return
        self.analysis_hint.configure(text=analysis_condition_hint(method))
        self.status.set(analysis_condition_hint(method))

    def refresh_runs(self):
        if not self.project_id:
            self._run_rows = []
            self.runs["values"] = []
            self.runs.set("")
            return
        rows = self.workflow.store.list_runs(self.project_id)
        enriched = []
        labels = []
        for row in rows:
            output_dir = self.project_root / "outputs" / "research_cockpit" / self.project_id / "runs" / row["run_id"]
            manifest_path = output_dir / "manifest.json"
            manifest = {}
            if manifest_path.is_file():
                try:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) or {}
                except (OSError, json.JSONDecodeError):
                    manifest = {}
            item = dict(row)
            item["analysis_type"] = str(manifest.get("analysis_type") or "gcd").casefold()
            item["output_dir"] = output_dir
            enriched.append(item)
            labels.append("{} ｜ {} ｜ {}".format(row["status"], item["analysis_type"].upper(), row["run_id"]))
        self._run_rows = enriched
        self.runs["values"] = labels
        if self.run_id:
            index = next((i for i, row in enumerate(enriched) if row["run_id"] == self.run_id), -1)
            if index >= 0:
                self.runs.current(index)

    def _run_selected(self, _event=None):
        index = self.runs.current()
        if index < 0 or index >= len(self._run_rows):
            return
        row = self._run_rows[index]
        self.run_id = row["run_id"]
        self.analysis_type.set(row["analysis_type"])
        self._analysis_type_changed()
        stages = self.workflow.store.list_run_stages(self.run_id)
        self.status.set("运行 {}：{}".format(self.run_id, format_stage_statuses(stages)))

    def _selected_run(self) -> dict:
        index = self.runs.current()
        if index < 0 or index >= len(self._run_rows):
            raise ValueError("请先选择一条运行记录。")
        return self._run_rows[index]

    def create_project(self):
        try:
            self.project_id = self.workflow.create_project(self.name.get(), self.material.get(), self._keywords())
            self.status.set("已创建课题：{}".format(self.project_id))
            self.refresh_projects()
            self.refresh_runs()
        except Exception as error:
            messagebox.showerror("创建失败", str(error), parent=self.root)

    def refresh_projects(self):
        values = self.workflow.store.list_projects()
        self._project_rows = values
        self.projects["values"] = ["{} ｜ {}".format(item["project_id"], item["name"]) for item in values]

    def open_project(self):
        current = self.projects.current()
        if current < 0:
            messagebox.showwarning("未选择课题", "请从下拉框选择已有课题。", parent=self.root)
            return
        project = self._project_rows[current]
        self.project_id = project["project_id"]
        self.name.set(project["name"])
        self.material.set(project["material_system"])
        self.keywords.set("；".join(project["keywords"]))
        self.refresh_runs()
        self.status.set("已打开课题，可修改名称、课题类型和关键词后保存。")

    def save_project_changes(self):
        if not self.project_id:
            messagebox.showwarning("未打开课题", "请先打开需要修改的课题。", parent=self.root)
            return
        try:
            project = self.workflow.update_project(self.project_id, self.name.get(), self.material.get(), self._keywords())
            self.name.set(project["name"])
            self.material.set(project["material_system"])
            self.keywords.set("；".join(project["keywords"]))
            self.refresh_projects()
            self.status.set("课题修改已保存：{}。".format(project["name"]))
        except Exception as error:
            messagebox.showerror("保存课题修改失败", str(error), parent=self.root)

    def run_all_automatically(self):
        if self._running:
            return
        try:
            if not Path(self.data_path.get()).is_file():
                raise ValueError("请选择存在的实验数据。")
            if self.pdf_path.get() and not Path(self.pdf_path.get()).is_file():
                raise ValueError("所选 PDF 不存在。")
            data_path = self.data_path.get()
            pdf_path = self.pdf_path.get() or None
            keywords = self._keywords()
            conditions = self._conditions()
            method = normalize_analysis_type(self.analysis_type.get())
            if method == "gitt" and not str(conditions.get("current_threshold_A") or "").strip():
                raise ValueError("GITT 必须填写 current_threshold_A。")
            run_options = build_run_options(
                self.use_pdf_evidence.get(),
                self.use_online_research.get(),
                self.use_codex_assessment.get(),
            )
            scope_summary = build_send_scope_summary(
                run_options["use_codex_candidates"],
                run_options["use_online_research"],
                run_options["use_codex_assessment"],
                has_pdf=bool(pdf_path),
            )
            scope_summary += "\n• 分析方法：{}。".format(ANALYSIS_LABELS[method])
        except Exception as error:
            messagebox.showerror("无法启动自动流程", str(error), parent=self.root)
            return
        if not messagebox.askokcancel("确认本轮发送范围", scope_summary, icon="info", parent=self.root):
            return
        try:
            if self.project_id is None:
                self.project_id = self.workflow.create_project(self.name.get(), self.material.get(), keywords)
                self.refresh_projects()
            project_id = self.project_id
        except Exception as error:
            messagebox.showerror("无法启动自动流程", str(error), parent=self.root)
            return
        self._running = True
        self._cancel_event.clear()
        self.cancel_button.configure(state="normal")
        self.progress["value"] = 0
        self._set_mutating_buttons_enabled(False)
        self._write_monitor(scope_summary)
        self._write_monitor("自动流程已启动；关闭的可选阶段将被跳过。")

        def emit(stage, message, details):
            self._events.put(("progress", stage, message, details))

        def worker():
            try:
                result = self.workflow.run_all(
                    project_id,
                    data_path,
                    conditions,
                    analysis_type=method,
                    pdf_path=pdf_path,
                    keywords=keywords,
                    use_codex_candidates=run_options["use_codex_candidates"],
                    use_online_research=run_options["use_online_research"],
                    use_codex_assessment=run_options["use_codex_assessment"],
                    progress=emit,
                    cancel_requested=self._cancel_event.is_set,
                )
                self._events.put(("done", result))
            except Exception as error:
                self._events.put(("error", str(error)))

        threading.Thread(target=worker, name="Harness-v2-automatic-run", daemon=True).start()
        self.root.after(100, self._poll_automatic_events)

    def resume_selected_run(self):
        if self._running:
            return
        try:
            self._require_project()
            selected = self._selected_run()
            data_path = self.data_path.get()
            if not Path(data_path).is_file():
                raise ValueError("请选择与该运行哈希一致的实验数据。")
            pdf_path = self.pdf_path.get() or None
            if pdf_path and not Path(pdf_path).is_file():
                raise ValueError("所选 PDF 不存在。")
            run_options = build_run_options(
                self.use_pdf_evidence.get(),
                self.use_online_research.get(),
                self.use_codex_assessment.get(),
            )
            scope_summary = build_send_scope_summary(
                run_options["use_codex_candidates"],
                run_options["use_online_research"],
                run_options["use_codex_assessment"],
                has_pdf=bool(pdf_path),
            )
            scope_summary += "\n• 恢复运行：{}。".format(selected["run_id"])
            scope_summary += "\n• 分析方法和实验条件沿用原运行。"
        except Exception as error:
            messagebox.showerror("无法恢复运行", str(error), parent=self.root)
            return
        if not messagebox.askokcancel("确认恢复范围", scope_summary, icon="info", parent=self.root):
            return

        self._running = True
        self._cancel_event.clear()
        self.cancel_button.configure(state="normal")
        self.progress["value"] = 0
        self._set_mutating_buttons_enabled(False)
        self._write_monitor(scope_summary)

        def emit(stage, message, details):
            self._events.put(("progress", stage, message, details))

        def worker():
            try:
                result = self.workflow.resume_run(
                    self.project_id,
                    selected["run_id"],
                    data_path,
                    pdf_path=pdf_path,
                    keywords=self._keywords(),
                    use_codex_candidates=run_options["use_codex_candidates"],
                    use_online_research=run_options["use_online_research"],
                    use_codex_assessment=run_options["use_codex_assessment"],
                    progress=emit,
                    cancel_requested=self._cancel_event.is_set,
                )
                self._events.put(("done", result))
            except Exception as error:
                self._events.put(("error", str(error)))

        threading.Thread(target=worker, name="Harness-v2-resume-run", daemon=True).start()
        self.root.after(100, self._poll_automatic_events)

    def cancel_current_run(self):
        if not self._running:
            return
        self._cancel_event.set()
        self.cancel_button.configure(state="disabled")
        self.status.set("已请求取消；当前外部调用结束后停止。")
        self._write_monitor("取消请求已记录。正在执行的 Origin 或 Codex 调用不会被强行终止。")

    def _poll_automatic_events(self):
        finished = False
        stage_values = {"SEARCH": 1, "PDF": 2, "CODEX_PDF": 3, "DATA": 4, "BENCHMARK_RESEARCH": 5, "CODEX_KNOWLEDGE": 6, "ORIGIN": 7, "CODEX_ASSESSMENT": 8, "REPORT": 9}
        while True:
            try:
                event = self._events.get_nowait()
            except queue.Empty:
                break
            if event[0] == "progress":
                _, stage, message, details = event
                self.progress["value"] = max(self.progress["value"], stage_values.get(stage, 0))
                self.status.set("{}：{}".format(stage, message))
                self._write_monitor("[{}] {}\n{}".format(stage, message, json.dumps(details, ensure_ascii=False, indent=2)[:1800]))
            elif event[0] == "done":
                result = event[1]
                run = result.get("run")
                if run is not None:
                    self.run_id = run.run_id
                report_value = result.get("report")
                report_path = Path(report_value) if report_value else None
                self._last_report = report_path if report_path and report_path.is_file() else None
                self.source_id = result["document"].source_id if result.get("document") else self.source_id
                run_status = "UNKNOWN"
                stages = []
                if self.run_id:
                    try:
                        run_status = self.workflow.store.get_run(self.run_id)["status"]
                        stages = self.workflow.store.list_run_stages(self.run_id)
                    except (KeyError, ValueError):
                        pass
                report_name = self._last_report.name if self._last_report else "未生成"
                self.status.set(
                    "运行结束：{}；报告：{}；错误：{} 项。".format(
                        run_status, report_name, len(result.get("errors") or [])
                    )
                )
                self._write_monitor("阶段状态：{}".format(format_stage_statuses(stages)))
                if self._last_report and run_status != "CANCELLED":
                    webbrowser.open_new_tab(self._last_report.resolve().as_uri())
                self.refresh_runs()
                finished = True
            elif event[0] == "error":
                self.status.set("自动流程失败")
                self._write_monitor("自动流程失败：{}".format(event[1]))
                messagebox.showerror("自动流程失败", event[1], parent=self.root)
                finished = True
        if finished:
            self._running = False
            self._cancel_event.clear()
            self.cancel_button.configure(state="disabled")
            self._set_mutating_buttons_enabled(True)
        else:
            self.root.after(100, self._poll_automatic_events)

    def _write_monitor(self, text):
        self.monitor.configure(state="normal")
        self.monitor.insert("end", text + "\n\n")
        self.monitor.see("end")
        self.monitor.configure(state="disabled")

    def open_segment_review(self):
        if self._running:
            return
        try:
            self._require_project()
            selected = self._selected_run()
            self.run_id = selected["run_id"]
            if selected["analysis_type"] != "gcd":
                raise ValueError("分段审核只适用于 GCD 运行。")
            if not Path(self.data_path.get()).is_file():
                raise ValueError("请选择与运行哈希一致的 GCD 数据文件。")
        except Exception as error:
            messagebox.showwarning("无法审核分段", str(error), parent=self.root)
            return
        if self._segment_window is not None and self._segment_window.winfo_exists():
            self._segment_window.lift()
            return
        window = tk.Toplevel(self.root)
        self._segment_window = window
        window.title("审核 GCD 分段")
        window.geometry("980x620")
        window.transient(self.root)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(1, weight=1)
        ttk.Label(
            window,
            text="批准会固定充放电方向；驳回会排除该段。后续结果将失效并等待恢复运行。",
            padding=8,
        ).grid(row=0, column=0, sticky="ew")
        self.segment_tree = ttk.Treeview(
            window,
            columns=("direction", "confidence", "review", "capacity", "method"),
            show="tree headings",
        )
        self.segment_tree.heading("#0", text="分段")
        self.segment_tree.heading("direction", text="方向")
        self.segment_tree.heading("confidence", text="置信度")
        self.segment_tree.heading("review", text="审核状态")
        self.segment_tree.heading("capacity", text="容量 mAh/g")
        self.segment_tree.heading("method", text="依据")
        self.segment_tree.column("#0", width=120)
        self.segment_tree.column("direction", width=90)
        self.segment_tree.column("confidence", width=90)
        self.segment_tree.column("review", width=150)
        self.segment_tree.column("capacity", width=120)
        self.segment_tree.column("method", width=220)
        self.segment_tree.grid(row=1, column=0, sticky="nsew", padx=8)

        form = ttk.Frame(window, padding=8)
        form.grid(row=2, column=0, sticky="ew")
        ttk.Label(form, text="方向").grid(row=0, column=0)
        self.segment_direction = tk.StringVar(value="charge")
        ttk.Combobox(
            form,
            textvariable=self.segment_direction,
            values=("charge", "discharge"),
            state="readonly",
            width=12,
        ).grid(row=0, column=1, padx=4)
        ttk.Label(form, text="审核人").grid(row=0, column=2)
        self.segment_reviewer = tk.StringVar()
        ttk.Entry(form, textvariable=self.segment_reviewer, width=18).grid(row=0, column=3, padx=4)
        ttk.Label(form, text="理由").grid(row=0, column=4)
        self.segment_reason = tk.StringVar()
        ttk.Entry(form, textvariable=self.segment_reason).grid(row=0, column=5, padx=4, sticky="ew")
        form.columnconfigure(5, weight=1)
        self._state_button(form, "批准方向", lambda: self._submit_segment_review("approved")).grid(row=0, column=6, padx=4)
        self._state_button(form, "驳回分段", lambda: self._submit_segment_review("rejected")).grid(row=0, column=7, padx=4)
        self._refresh_segment_review()

    def _refresh_segment_review(self):
        if not self.run_id or self._segment_window is None or not self._segment_window.winfo_exists():
            return
        path = self.project_root / "outputs" / "research_cockpit" / self.project_id / "runs" / self.run_id / "analysis.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            self._segment_rows = list((payload.get("analysis") or {}).get("segments") or [])
        except (OSError, json.JSONDecodeError):
            self._segment_rows = []
        self.segment_tree.delete(*self.segment_tree.get_children())
        for row in self._segment_rows:
            self.segment_tree.insert(
                "",
                "end",
                iid=str(row.get("segment_id")),
                text=str(row.get("segment_id")),
                values=(
                    row.get("direction_candidate"),
                    row.get("confidence"),
                    row.get("review_status"),
                    row.get("specific_capacity_mAh_g"),
                    row.get("direction_inference_method") or row.get("segmentation_method"),
                ),
            )

    def _submit_segment_review(self, status: str):
        selected = self.segment_tree.selection()
        reviewer = self.segment_reviewer.get().strip()
        reason = self.segment_reason.get().strip()
        if not selected or not reviewer or not reason:
            messagebox.showwarning("审核信息不完整", "请选择分段，并填写审核人和理由。", parent=self._segment_window)
            return
        decision = {
            "segment_id": selected[0],
            "status": status,
            "reviewer": reviewer,
            "reason": reason,
        }
        if status == "approved":
            decision["direction"] = self.segment_direction.get()
        try:
            self.workflow.review_gcd_segments(
                self.project_id,
                self.run_id,
                self.data_path.get(),
                [decision],
            )
            self.segment_reason.set("")
            self._refresh_segment_review()
            self.refresh_runs()
            self.status.set("分段审核已保存；请恢复该运行以重算后续阶段。")
        except Exception as error:
            messagebox.showerror("分段审核失败", str(error), parent=self._segment_window)

    def open_review_queue(self):
        if self._running:
            return
        try:
            self._require_project()
        except Exception as error:
            messagebox.showwarning("未打开课题", str(error), parent=self.root)
            return
        if self._review_window is not None and self._review_window.winfo_exists():
            self._review_window.lift()
            return
        window = tk.Toplevel(self.root)
        self._review_window = window
        window.title("审核候选知识")
        window.geometry("940x720")
        window.transient(self.root)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(1, weight=2)
        window.rowconfigure(4, weight=1)
        ttk.Label(window, text="候选知识来自受控筛选。批准或驳回均会写入追加式审核审计。", padding=8).grid(row=0, column=0, sticky="ew")
        self.review_tree = ttk.Treeview(window, columns=("status", "claim"), show="headings", height=7)
        self.review_tree.heading("status", text="状态")
        self.review_tree.heading("claim", text="Claim 文本")
        self.review_tree.column("status", width=90, stretch=False)
        self.review_tree.column("claim", width=760)
        self.review_tree.grid(row=1, column=0, sticky="nsew", padx=8)
        self.review_tree.bind("<<TreeviewSelect>>", lambda _event: self._show_selected_review())
        self.review_details = tk.Text(window, height=13, wrap="word", state="disabled", padx=6, pady=6)
        self.review_details.grid(row=2, column=0, sticky="nsew", padx=8, pady=(6, 0))

        decision = ttk.Frame(window, padding=8)
        decision.grid(row=3, column=0, sticky="ew")
        ttk.Label(decision, text="Reviewer（必填）").grid(row=0, column=0, sticky="w")
        self.review_reviewer = tk.StringVar()
        ttk.Entry(decision, textvariable=self.review_reviewer, width=24).grid(row=0, column=1, sticky="ew", padx=(4, 12))
        ttk.Label(decision, text="Reason（必填）").grid(row=0, column=2, sticky="w")
        self.review_reason = tk.StringVar()
        ttk.Entry(decision, textvariable=self.review_reason).grid(row=0, column=3, sticky="ew", padx=4)
        decision.columnconfigure(3, weight=1)
        approve = self._state_button(decision, "批准选中项", lambda: self._review_selected("approved"))
        approve.grid(row=0, column=4, padx=4)
        reject = self._state_button(decision, "驳回选中项", lambda: self._review_selected("rejected"))
        reject.grid(row=0, column=5, padx=4)
        ttk.Button(decision, text="刷新", command=self._refresh_review_dialog).grid(row=0, column=6, padx=(8, 0))

        audit_frame = ttk.LabelFrame(window, text="已持久化审核审计", padding=6)
        audit_frame.grid(row=4, column=0, sticky="nsew", padx=8, pady=(0, 8))
        audit_frame.columnconfigure(0, weight=1)
        audit_frame.rowconfigure(0, weight=1)
        self.review_audit = tk.Text(audit_frame, height=7, wrap="word", state="disabled")
        self.review_audit.grid(row=0, column=0, sticky="nsew")
        self._refresh_review_dialog()

    def _refresh_review_dialog(self):
        if not self.project_id or self._review_window is None or not self._review_window.winfo_exists():
            return
        self._review_claims = self.workflow.store.list_review_queue(self.project_id)
        self.review_tree.delete(*self.review_tree.get_children())
        for claim in self._review_claims:
            self.review_tree.insert("", "end", iid=claim.claim_id, values=(claim.status, claim.text))
        audit_rows = []
        for claim in self.workflow.store.list_claims(self.project_id):
            for event in self.workflow.store.list_review_events(claim.claim_id):
                audit_rows.append((claim, event))
        audit_rows.sort(key=lambda row: getattr(row[1], "reviewed_at", ""), reverse=True)
        self._replace_text(self.review_audit, format_review_audit(audit_rows))
        if self._review_claims:
            first = self._review_claims[0].claim_id
            self.review_tree.selection_set(first)
            self.review_tree.focus(first)
            self._show_selected_review()
        else:
            self._replace_text(self.review_details, "当前没有待审核候选知识。")

    def _show_selected_review(self):
        selected = self.review_tree.selection()
        if not selected:
            return
        claim = next((item for item in self._review_claims if item.claim_id == selected[0]), None)
        if claim is None:
            return
        source_ids = {claim.source_id}
        for candidate_id in (claim.conditions or {}).get("candidate_claim_ids") or []:
            try:
                source_ids.add(self.workflow.store.get_claim(str(candidate_id)).source_id)
            except KeyError:
                continue
        spans = []
        for source_id in source_ids:
            spans.extend(self.workflow.store.list_source_spans(source_id))
        self._replace_text(self.review_details, format_claim_review_details(claim, spans))

    def _review_selected(self, status: str):
        selected = self.review_tree.selection()
        reviewer = self.review_reviewer.get().strip()
        reason = self.review_reason.get().strip()
        if not selected:
            messagebox.showwarning("未选择候选", "请选择一条候选知识。", parent=self._review_window)
            return
        if not reviewer or not reason:
            messagebox.showwarning("审核信息不完整", "Reviewer 和 reason 均为必填项。", parent=self._review_window)
            return
        try:
            reviewed = self.workflow.store.review_claim(selected[0], status, reviewer, reason)
            self.status.set("候选知识已{}，审核事件已持久化。".format("批准" if status == "approved" else "驳回"))
            self._write_monitor("审核 {}：{}（reviewer={}）".format(reviewed.claim_id, status, reviewer))
            self.review_reason.set("")
            self._refresh_review_dialog()
        except Exception as error:
            messagebox.showerror("审核失败", str(error), parent=self._review_window)

    @staticmethod
    def _replace_text(widget, text: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def open_research_state(self):
        if self._running:
            return
        try:
            self._require_project()
            state = self.workflow.store.get_research_state(self.project_id)
        except Exception as error:
            messagebox.showwarning("无法打开研究状态", str(error), parent=self.root)
            return
        if self._state_window is not None and self._state_window.winfo_exists():
            self._state_window.lift()
            return
        window = tk.Toplevel(self.root)
        self._state_window = window
        window.title("编辑研究状态")
        window.geometry("820x760")
        window.transient(self.root)
        window.columnconfigure(1, weight=1)
        ttk.Label(window, text="仅保存研究人员明确输入；此入口不调用模型，也不批准候选知识。", padding=8).grid(row=0, column=0, columnspan=2, sticky="ew")
        labels = {
            "confirmed_decisions": "已确认决策",
            "user_corrections": "用户纠正",
            "rejected_hypotheses": "已拒绝假设",
            "open_questions": "开放问题",
        }
        self._state_editors = {}
        for row, field in enumerate(RESEARCH_STATE_LIST_FIELDS, start=1):
            ttk.Label(window, text=labels[field], padding=(8, 4)).grid(row=row, column=0, sticky="nw")
            editor = tk.Text(window, height=5, wrap="word")
            editor.grid(row=row, column=1, sticky="nsew", padx=(0, 8), pady=3)
            editor.insert("1.0", format_research_state_items(state.get(field) or []))
            self._state_editors[field] = editor
            window.rowconfigure(row, weight=1)
        next_row = 1 + len(RESEARCH_STATE_LIST_FIELDS)
        ttk.Label(window, text="下一意图", padding=(8, 4)).grid(row=next_row, column=0, sticky="nw")
        self._next_intent_editor = tk.Text(window, height=4, wrap="word")
        self._next_intent_editor.grid(row=next_row, column=1, sticky="nsew", padx=(0, 8), pady=3)
        self._next_intent_editor.insert("1.0", state.get("next_intent") or "")
        buttons = ttk.Frame(window, padding=8)
        buttons.grid(row=next_row + 1, column=0, columnspan=2, sticky="e")
        save = self._state_button(buttons, "保存研究状态", self._save_research_state)
        save.pack(side="right")
        ttk.Button(buttons, text="关闭", command=window.destroy).pack(side="right", padx=6)

    def _save_research_state(self):
        if not self.project_id:
            return
        fields = {
            field: parse_research_state_items(editor.get("1.0", "end"))
            for field, editor in self._state_editors.items()
        }
        fields["next_intent"] = self._next_intent_editor.get("1.0", "end").strip()
        try:
            state = self.workflow.store.update_research_state(self.project_id, **fields)
            self.status.set("研究状态已保存（版本 {}）；未调用模型。".format(state.get("row_version")))
            self._write_monitor("人工研究状态已保存：版本 {}。".format(state.get("row_version")))
        except Exception as error:
            messagebox.showerror("保存研究状态失败", str(error), parent=self._state_window)

    def open_replicate_analysis(self):
        if self._running:
            return
        try:
            self._require_project()
            self.refresh_runs()
            if len(self._run_rows) < 2:
                raise ValueError("至少需要两次运行。")
        except Exception as error:
            messagebox.showwarning("无法进行重复统计", str(error), parent=self.root)
            return
        if self._replicate_window is not None and self._replicate_window.winfo_exists():
            self._replicate_window.lift()
            return
        window = tk.Toplevel(self.root)
        self._replicate_window = window
        window.title("重复实验统计")
        window.geometry("900x650")
        window.transient(self.root)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(1, weight=1)
        ttk.Label(
            window,
            text="选择同方法运行。只计算同名同单位指标的描述统计。",
            padding=8,
        ).grid(row=0, column=0, sticky="ew")
        self.replicate_runs = tk.Listbox(window, selectmode="extended", exportselection=False)
        self.replicate_runs.grid(row=1, column=0, sticky="nsew", padx=8)
        self._replicate_rows = list(self._run_rows)
        for row in self._replicate_rows:
            self.replicate_runs.insert(
                "end",
                "{} ｜ {} ｜ {}".format(row["status"], row["analysis_type"].upper(), row["run_id"]),
            )
        form = ttk.Frame(window, padding=8)
        form.grid(row=2, column=0, sticky="ew")
        ttk.Label(form, text="指标路径").grid(row=0, column=0)
        method = self.analysis_type.get() if self.analysis_type.get() in ANALYSIS_TYPES else "gcd"
        self.replicate_metric = tk.StringVar(value=default_replicate_metric(method))
        ttk.Entry(form, textvariable=self.replicate_metric).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Label(form, text="单位（可选）").grid(row=0, column=2)
        self.replicate_unit = tk.StringVar()
        ttk.Entry(form, textvariable=self.replicate_unit, width=14).grid(row=0, column=3, padx=4)
        form.columnconfigure(1, weight=1)
        self._state_button(form, "生成统计报告", self._run_replicate_analysis).grid(row=0, column=4, padx=4)
        self.replicate_output = tk.Text(window, height=12, wrap="word", state="disabled")
        self.replicate_output.grid(row=3, column=0, sticky="nsew", padx=8, pady=(0, 8))

    def _run_replicate_analysis(self):
        indexes = list(self.replicate_runs.curselection())
        if len(indexes) < 2:
            messagebox.showwarning("样本不足", "请选择至少两次运行。", parent=self._replicate_window)
            return
        run_ids = [self._replicate_rows[index]["run_id"] for index in indexes]
        metric = self.replicate_metric.get().strip()
        unit = self.replicate_unit.get().strip() or None
        try:
            envelope = self.workflow.summarize_runs(self.project_id, run_ids, metric, unit=unit)
            self._replace_text(self.replicate_output, json.dumps(envelope, ensure_ascii=False, indent=2))
            report_name = (envelope.get("metadata") or {}).get("report")
            if report_name:
                report = self.project_root / "outputs" / "research_cockpit" / self.project_id / "replicates" / report_name
                if report.is_file():
                    webbrowser.open_new_tab(report.resolve().as_uri())
            self.status.set("重复统计已生成；不包含显著性或因果结论。")
        except Exception as error:
            messagebox.showerror("重复统计失败", str(error), parent=self._replicate_window)

    def open_latest_report(self):
        if self._last_report and self._last_report.is_file():
            webbrowser.open_new_tab(self._last_report.resolve().as_uri())
            return
        if self.project_id:
            runs_root = self.project_root / "outputs" / "research_cockpit" / self.project_id / "runs"
            reports = sorted(runs_root.glob("*/research_decision_report.html"), key=lambda item: item.stat().st_mtime, reverse=True) if runs_root.is_dir() else []
            if reports:
                self._last_report = reports[0]
                webbrowser.open_new_tab(reports[0].resolve().as_uri())
                return
        messagebox.showwarning("没有报告", "当前课题还没有可打开的图文报告。", parent=self.root)

    def open_codex_activity(self):
        if self.run_id and self.project_id:
            activity = self.project_root / "outputs" / "research_cockpit" / self.project_id / "runs" / self.run_id / "codex_activity.json"
            if activity.is_file():
                webbrowser.open_new_tab(activity.resolve().as_uri())
                return
        messagebox.showwarning("没有 Codex 记录", "当前课题没有可打开的 Codex 工作记录。请重新运行自动流程。", parent=self.root)

    def analyze_and_plot(self):
        try:
            self._require_project()
            if not Path(self.data_path.get()).is_file():
                raise ValueError("请选择存在的实验数据。")
            run = self.workflow.analyze_data(
                self.project_id,
                self.data_path.get(),
                self._conditions(),
                normalize_analysis_type(self.analysis_type.get()),
            )
            self.run_id = run.run_id
            plot = self.workflow.prepare_origin(self.project_id, run.run_id, self.data_path.get())
            self.status.set("数据状态：{}；Origin：{}。".format(run.status, plot.status))
        except Exception as error:
            messagebox.showerror("数据或 Origin 失败", str(error), parent=self.root)

    def evaluate_and_report(self):
        try:
            self._require_project()
            if not self.run_id:
                raise ValueError("请先完成阶段③的数据分析和 Origin 作图。")
            self.status.set("Codex 正在基于本轮确定性数据、Origin 状态和已批准证据评估课题…")
            self.root.update_idletasks()
            self.thread_id, guidance = self.workflow.evaluate_with_codex(self.project_id, self.run_id, self.thread_id)
            target = self.workflow.build_report(self.project_id, self.run_id)
            self.status.set("Codex 评估已保存：{}；报告：{}".format(guidance["assessment"][:80], target.name))
        except Exception as error:
            messagebox.showerror("Codex 评估或报告失败", str(error), parent=self.root)

    def _keywords(self):
        return [item.strip() for item in self.keywords.get().replace("；", ";").split(";") if item.strip()]

    def _conditions(self):
        result = {}
        for item in self.conditions.get().replace("；", ";").split(";"):
            if not item.strip():
                continue
            if "=" not in item:
                raise ValueError("实验条件必须采用 key=value。")
            key, value = item.split("=", 1)
            key = key.strip()
            if not key:
                raise ValueError("实验条件名称不能为空。")
            result[key] = parse_condition_value(value)
        mass_text = self.active_material_mass_mg.get().strip()
        if mass_text:
            try:
                mass_mg = float(mass_text)
            except ValueError as error:
                raise ValueError("活性物质质量必须是正数，单位为 mg。") from error
            if mass_mg <= 0:
                raise ValueError("活性物质质量必须大于 0 mg。")
            result["active_material_mass_mg"] = mass_mg
        return result

    def _require_project(self):
        if not self.project_id:
            raise ValueError("请先创建或打开课题。")


def main(project_root: Path | str) -> None:
    root = tk.Tk()
    HarnessApp(root, project_root)
    root.mainloop()
