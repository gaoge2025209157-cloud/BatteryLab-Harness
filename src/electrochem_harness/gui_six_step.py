"""Six-step Tk interface for the production workflow (Phase 5 / B2).

This module is deliberately thin: every rule about which step is allowed lives
in :class:`electrochem_harness.gui_controller.SixStepWizard`, which is covered by
headless tests.  Here we only draw, and we never compute anything.

The dialog replaces the old "start analysis" button, which shelled out to
``run_sci_origin.ps1`` and gave the user no plan, no approval and no way back
after a failure.
"""

import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .gui import METADATA_FIELDS, validate_form
from .gui_controller import STEP_TITLES, SixStepWizard, WizardError, WizardStep
from .workflow import ApprovalRequired

_STEP_ORDER = (
    WizardStep.DATA,
    WizardStep.PREFLIGHT,
    WizardStep.PLAN,
    WizardStep.APPROVAL,
    WizardStep.EXECUTE,
    WizardStep.RESULTS,
)

_CHIP_LABELS = {
    WizardStep.DATA: "1 数据",
    WizardStep.PREFLIGHT: "2 预检",
    WizardStep.PLAN: "3 计划",
    WizardStep.APPROVAL: "4 批准",
    WizardStep.EXECUTE: "5 执行",
    WizardStep.RESULTS: "6 结果",
}

_SCOPE_HINTS = {
    "local_analysis": "解析数据、计算指标、生成报告与绘图 CSV。",
    "network_access": "把电池体系、活性物质、电池类型、电流、温度、归一化口径发给 Crossref 核验 DOI。",
    "formal_output": "把报告、CSV、JSON 等产物写入输出目录。",
}


class SixStepDialog(tk.Toplevel):
    """One window, six steps, no hidden work."""

    def __init__(self, parent, project_root, values=None, *, origin_launcher=None):
        super().__init__(parent)
        self.project_root = Path(project_root).resolve()
        self.events = queue.Queue()
        self.busy = False
        self.wizard = SixStepWizard(self.project_root, origin_launcher=origin_launcher)
        self.scope_vars = {}
        self._blocked = False
        self._closed = False
        self._poll_id = None

        self.title("受控分析：预检查 → 计划 → 批准 → 执行 → 验证 → 结果")
        self.transient(parent)

        self._init_variables(values or {})
        self._configure_style()
        self._build()
        self._show_step(WizardStep.DATA)
        # 几何必须在窗口构建完成、transient 生效之后再设置，否则 Windows
        # 会把窗口级联到父窗口右下角并超出屏幕。
        self._fit_to_screen()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _fit_to_screen(self):
        """Size the wizard to the available screen and centre it.

        A fixed 1020x760 window is taller than a 768-pixel laptop screen once the
        title bar and taskbar are counted, which clips the footer buttons.
        """

        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        # 两种极端都要照顾：小屏（1366x768）不能让底部按钮掉出屏幕，
        # 大屏也不要拉成整屏宽。
        width = min(1040, max(840, screen_w - 60), screen_w - 16)
        height = min(820, max(500, screen_h - 120), screen_h - 60)
        left = max(0, (screen_w - width) // 2)
        top = max(0, (screen_h - height) // 6)
        self.geometry("{}x{}+{}+{}".format(width, height, left, top))
        self.minsize(min(840, width), min(500, height))

    # -- construction ---------------------------------------------------------

    def _init_variables(self, values):
        self.variables = {
            "input_file": tk.StringVar(value=str(values.get("input_file", ""))),
            "output_dir": tk.StringVar(value=str(values.get("output_dir", ""))),
            "origin_exe": tk.StringVar(value=str(values.get("origin_exe", ""))),
            "search_literature": tk.BooleanVar(value=bool(values.get("search_literature", True))),
            "use_origin": tk.BooleanVar(value=bool(values.get("use_origin", True))),
            "max_literature": tk.IntVar(value=int(values.get("max_literature", 50) or 50)),
        }
        for name, _, _ in METADATA_FIELDS:
            self.variables[name] = tk.StringVar(value=str(values.get(name, "")))

    def _configure_style(self):
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("StepActive.TLabel", foreground="#0b5394", font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("StepDone.TLabel", foreground="#2e6b2e", font=("Microsoft YaHei UI", 10))
        style.configure("StepIdle.TLabel", foreground="#888888", font=("Microsoft YaHei UI", 10))
        style.configure("Hint.TLabel", foreground="#555555")
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 15, "bold"))
        style.configure("Blocking.TLabel", foreground="#a10000", font=("Microsoft YaHei UI", 10, "bold"))

    def _build(self):
        outer = ttk.Frame(self, padding=14)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)

        header = ttk.Frame(outer)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="受控分析", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        self.step_label = ttk.Label(header, text="", style="Hint.TLabel")
        self.step_label.configure(text="第 1 / 6 步")
        self.step_label.grid(row=0, column=1, sticky="e")

        self.step_bar = ttk.Frame(outer)
        self.step_bar.grid(row=1, column=0, sticky="ew", pady=(4, 8))
        self.step_chips = {}
        for index, step in enumerate(_STEP_ORDER):
            chip = ttk.Label(self.step_bar, text=_CHIP_LABELS[step], style="StepIdle.TLabel")
            chip.grid(row=0, column=index, sticky="w", padx=(0, 18))
            self.step_chips[step] = chip

        # 内容区可滚动：小屏（1366x768）上第 1 步也不会把底部按钮顶出屏幕。
        self.body = ttk.Frame(outer)
        self.body.grid(row=2, column=0, sticky="nsew")
        self.body.columnconfigure(0, weight=1)
        self.body.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self.body, highlightthickness=0, borderwidth=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vbar = ttk.Scrollbar(self.body, orient="vertical", command=self.canvas.yview)
        self.vbar.grid(row=0, column=1, sticky="ns")
        self.canvas.configure(yscrollcommand=self.vbar.set)
        self.inner = ttk.Frame(self.canvas)
        self.inner.columnconfigure(0, weight=1)
        self._inner_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

        self.pages = {
            WizardStep.DATA: self._build_data_page(),
            WizardStep.PREFLIGHT: self._build_preflight_page(),
            WizardStep.PLAN: self._build_plan_page(),
            WizardStep.APPROVAL: self._build_approval_page(),
            WizardStep.EXECUTE: self._build_execute_page(),
            WizardStep.RESULTS: self._build_results_page(),
        }
        for page in self.pages.values():
            page.grid(row=0, column=0, sticky="nsew")

        footer = ttk.Frame(outer)
        footer.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        footer.columnconfigure(3, weight=1)
        self.back_button = ttk.Button(footer, text="上一步", command=self.go_back, state="disabled")
        self.back_button.grid(row=0, column=0, padx=(0, 6))
        self.next_button = ttk.Button(footer, text="下一步", command=self.go_next)
        self.next_button.grid(row=0, column=1, padx=6)
        self.approve_button = ttk.Button(
            footer, text="批准并开始执行", command=self.approve_and_run, state="disabled"
        )
        self.cancel_button = ttk.Button(footer, text="取消执行", command=self.cancel_run, state="disabled")
        self.cancel_button.grid(row=0, column=2, padx=6)
        self.status = tk.StringVar(value="请确认数据与实验条件")
        ttk.Label(footer, textvariable=self.status, style="Hint.TLabel").grid(row=0, column=3, sticky="e", padx=8)
        ttk.Button(footer, text="关闭", command=self._on_close).grid(row=0, column=4, padx=(6, 0))

    def _on_inner_configure(self, event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.canvas.itemconfigure(self._inner_id, width=event.width)

    def _on_mousewheel(self, event):
        if not self.winfo_exists():
            return
        try:
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        except tk.TclError:
            pass

    # -- step 1 ---------------------------------------------------------------

    def _build_data_page(self):
        page = ttk.Frame(self.inner)
        page.columnconfigure(0, weight=1)
        ttk.Label(
            page,
            text="第 1 步：选择蓝电导出文件与输出目录，填写实验条件。原始文件只在本机读取。",
            style="Hint.TLabel",
            wraplength=900,
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))

        paths = ttk.LabelFrame(page, text="数据与输出", padding=8)
        paths.grid(row=1, column=0, sticky="ew")
        paths.columnconfigure(1, weight=1)
        self._path_row(paths, 0, "蓝电文件", "input_file", self._choose_input)
        self._path_row(paths, 1, "输出目录", "output_dir", self._choose_output)

        metadata = ttk.LabelFrame(page, text="实验条件（启用文献检索时必填）", padding=8)
        metadata.grid(row=2, column=0, sticky="ew", pady=(4, 0))
        for block, chunk in enumerate((METADATA_FIELDS[:4], METADATA_FIELDS[4:])):
            column = ttk.Frame(metadata)
            column.grid(row=0, column=block, sticky="nsew", padx=(0, 18) if block == 0 else 0)
            column.columnconfigure(1, weight=1)
            for row, (name, label, _hint) in enumerate(chunk):
                ttk.Label(column, text=label).grid(
                    row=row, column=0, sticky="w", padx=(0, 8), pady=3
                )
                ttk.Entry(column, textvariable=self.variables[name]).grid(
                    row=row, column=1, sticky="ew", pady=3
                )
        ttk.Label(
            metadata,
            text="这些字段只在启用联网检索时发送给 Crossref；留空则无法进入联网阶段。",
            style="Hint.TLabel",
            wraplength=880,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))

        options = ttk.LabelFrame(page, text="可选阶段", padding=8)
        options.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        options.columnconfigure(3, weight=1)
        ttk.Checkbutton(
            options, text="联网检索并核验文献 DOI", variable=self.variables["search_literature"]
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(options, text="最多核验 DOI").grid(row=0, column=1, sticky="e", padx=(16, 4))
        tk.Spinbox(
            options, from_=1, to=200, width=6, textvariable=self.variables["max_literature"]
        ).grid(row=0, column=2, sticky="w")
        ttk.Checkbutton(
            options, text="调用 Origin 生成工程和图片", variable=self.variables["use_origin"]
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Entry(options, textvariable=self.variables["origin_exe"]).grid(
            row=1, column=2, columnspan=1, sticky="ew", padx=(0, 6), pady=(8, 0)
        )
        ttk.Button(options, text="浏览…", command=self._choose_origin).grid(
            row=1, column=3, sticky="w", pady=(8, 0)
        )
        ttk.Label(
            options,
            text="Origin64.exe 留空则自动查找 2021–2026b；缺失或失败时只降级绘图，报告与绘图 CSV 保留。",
            style="Hint.TLabel",
            wraplength=880,
        ).grid(row=2, column=0, columnspan=4, sticky="w", pady=(6, 0))
        return page

    def _path_row(self, parent, row, label, name, callback):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(parent, textvariable=self.variables[name]).grid(row=row, column=1, sticky="ew", pady=4)
        ttk.Button(parent, text="浏览…", command=callback).grid(row=row, column=2, padx=(6, 0), pady=4)

    def _choose_input(self):
        path = filedialog.askopenfilename(
            title="选择蓝电导出文件",
            filetypes=[("蓝电文本导出", "*.csv *.txt *.tsv *.dat"), ("所有文件", "*.*")],
        )
        if path:
            self.variables["input_file"].set(path)
            if not self.variables["output_dir"].get().strip():
                self.variables["output_dir"].set(str(Path(path).with_name(Path(path).stem + "_SCI")))

    def _choose_output(self):
        path = filedialog.askdirectory(title="选择输出目录")
        if path:
            self.variables["output_dir"].set(path)

    def _choose_origin(self):
        path = filedialog.askopenfilename(
            title="选择 Origin64.exe", filetypes=[("Origin", "Origin64.exe"), ("所有文件", "*.*")]
        )
        if path:
            self.variables["origin_exe"].set(path)

    # -- step 2 ---------------------------------------------------------------

    def _build_preflight_page(self):
        page = ttk.Frame(self.inner)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)
        self.preflight_headline = ttk.Label(page, text="", style="Hint.TLabel", wraplength=940)
        self.preflight_headline.grid(row=0, column=0, sticky="w", pady=(0, 8))

        self.preflight_text = tk.Text(
            page,
            wrap="word",
            state="disabled",
            font=("Microsoft YaHei UI", 9),
            padx=8,
            pady=8,
            width=1,
            height=12,
        )
        scroll = ttk.Scrollbar(page, orient="vertical", command=self.preflight_text.yview)
        self.preflight_text.configure(yscrollcommand=scroll.set)
        self.preflight_text.grid(row=1, column=0, sticky="nsew")
        scroll.grid(row=1, column=1, sticky="ns")
        self.preflight_text.tag_configure("blocking", foreground="#a10000")
        self.preflight_text.tag_configure("warning", foreground="#8a5a00")
        self.preflight_text.tag_configure("ok", foreground="#2e6b2e")
        return page

    # -- step 3 ---------------------------------------------------------------

    def _build_plan_page(self):
        page = ttk.Frame(self.inner)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)
        ttk.Label(
            page,
            text="第 3 步：这份计划会被哈希绑定。任何参数变化都会让计划与批准一起失效。",
            style="Hint.TLabel",
            wraplength=940,
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.plan_text = tk.Text(
            page,
            wrap="word",
            state="disabled",
            font=("Consolas", 9),
            padx=8,
            pady=8,
            width=1,
            height=12,
        )
        scroll = ttk.Scrollbar(page, orient="vertical", command=self.plan_text.yview)
        self.plan_text.configure(yscrollcommand=scroll.set)
        self.plan_text.grid(row=1, column=0, sticky="nsew")
        scroll.grid(row=1, column=1, sticky="ns")
        return page

    # -- step 4 ---------------------------------------------------------------

    def _build_approval_page(self):
        page = ttk.Frame(self.inner)
        page.columnconfigure(0, weight=1)
        ttk.Label(
            page,
            text="第 4 步：逐项批准。勾选表示你同意该范围内的操作，勾选本身不等于已批准。",
            style="Hint.TLabel",
            wraplength=940,
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))

        self.scope_box = ttk.LabelFrame(page, text="批准范围（本次计划的全部范围都需要批准）", padding=12)
        self.scope_box.grid(row=1, column=0, sticky="ew")
        self.scope_box.columnconfigure(0, weight=1)

        self.network_note = ttk.Label(page, text="", style="Hint.TLabel", wraplength=940)
        self.network_note.grid(row=2, column=0, sticky="w", pady=(8, 0))

        return page

    def _render_scopes(self, approval):
        for child in self.scope_box.winfo_children():
            child.destroy()
        self.scope_vars = {}
        required = set(approval["required"])
        for row, item in enumerate(approval["available"]):
            scope = item["scope"]
            variable = tk.BooleanVar(value=scope in required)
            self.scope_vars[scope] = variable
            label = item["label"]
            ttk.Checkbutton(
                self.scope_box,
                text=label,
                variable=variable,
                command=self._refresh_approve_button,
            ).grid(row=row * 2, column=0, sticky="w", pady=(4, 0))
            ttk.Label(
                self.scope_box, text=_SCOPE_HINTS.get(scope, ""), style="Hint.TLabel", wraplength=900
            ).grid(row=row * 2 + 1, column=0, sticky="w", padx=(22, 0))

        fields = approval.get("network_fields") or {}
        pairs = [
            "{}={}".format(key, value) for key, value in sorted(fields.items()) if value
        ]
        if pairs:
            rows = ["、".join(pairs[index : index + 2]) for index in range(0, len(pairs), 2)]
            self.network_note.configure(
                text="联网时只会把这些字段发给 Crossref：\n{}\n不含文件名、路径、样品编号或原始数据。".format(
                    "\n".join(rows)
                )
            )
        else:
            self.network_note.configure(text="本次未启用联网检索，不会有任何数据离开本机。")

    def _refresh_approve_button(self):
        required = set(self.wizard.required_scopes)
        selected = {scope for scope, var in self.scope_vars.items() if var.get()}
        missing = required - selected
        self.approve_button.configure(state="disabled" if missing else "normal")
        if missing:
            self.status.set("还缺必选范围：{}".format("、".join(sorted(missing))))
        else:
            self.status.set("范围已齐，可以批准并执行")

    # -- step 5 ---------------------------------------------------------------

    def _build_execute_page(self):
        page = ttk.Frame(self.inner)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(2, weight=1)
        ttk.Label(page, text="第 5 步：按批准的计划逐个执行白名单工具。", style="Hint.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.execute_state = ttk.Label(page, text="等待开始", style="Title.TLabel")
        self.execute_state.grid(row=1, column=0, sticky="w", pady=(6, 10))
        self.execute_text = tk.Text(
            page,
            wrap="word",
            state="disabled",
            font=("Consolas", 9),
            padx=8,
            pady=8,
            width=1,
            height=12,
        )
        scroll = ttk.Scrollbar(page, orient="vertical", command=self.execute_text.yview)
        self.execute_text.configure(yscrollcommand=scroll.set)
        self.execute_text.grid(row=2, column=0, sticky="nsew")
        scroll.grid(row=2, column=1, sticky="ns")
        return page

    # -- step 6 ---------------------------------------------------------------

    def _build_results_page(self):
        page = ttk.Frame(self.inner)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)
        self.results_headline = ttk.Label(page, text="", style="Title.TLabel", wraplength=940)
        self.results_headline.grid(row=0, column=0, sticky="w", pady=(0, 8))

        self.results_tree = ttk.Treeview(
            page, columns=("state", "path"), show="tree headings", height=8
        )
        self.results_tree.heading("#0", text="产物")
        self.results_tree.heading("state", text="状态")
        self.results_tree.heading("path", text="路径")
        self.results_tree.column("#0", width=260, anchor="w")
        self.results_tree.column("state", width=90, anchor="center")
        self.results_tree.column("path", width=620, anchor="w")
        scroll = ttk.Scrollbar(page, orient="vertical", command=self.results_tree.yview)
        self.results_tree.configure(yscrollcommand=scroll.set)
        self.results_tree.grid(row=1, column=0, sticky="nsew")
        scroll.grid(row=1, column=1, sticky="ns")

        self.degradation_label = ttk.Label(page, text="", style="Hint.TLabel", wraplength=940)
        self.degradation_label.grid(row=2, column=0, sticky="w", pady=(8, 0))

        actions = ttk.Frame(page)
        actions.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        ttk.Button(actions, text="打开输出目录", command=self.open_run_artifacts).grid(row=0, column=0)
        ttk.Button(actions, text="打开审计目录", command=self.open_run_directory).grid(
            row=0, column=1, padx=6
        )
        self.retry_button = ttk.Button(actions, text="重跑（新 run，保留原记录）", command=self.retry_run)
        self.retry_button.grid(row=0, column=2, padx=6)
        ttk.Button(actions, text="返回第 1 步修改", command=self.back_to_form).grid(row=0, column=3, padx=6)
        return page

    def _render_results(self):
        results = self.wizard.results
        if results is None:
            return
        for item in self.results_tree.get_children():
            self.results_tree.delete(item)
        groups = (
            ("报告与数值", results.report),
            ("文献证据（可选）", results.evidence),
            ("Origin 产物（可选）", results.origin),
            ("审计记录", results.audit),
        )
        for title, entries in groups:
            parent = self.results_tree.insert("", "end", text=title, values=("", ""), open=True)
            for entry in entries:
                if entry.available:
                    state = "已生成"
                elif entry.required:
                    state = "缺失"
                else:
                    state = "未启用"
                self.results_tree.insert(
                    parent,
                    "end",
                    text="  " + entry.name,
                    values=(state, "" if entry.path is None else str(entry.path)),
                )

        endings = {
            "completed": "全部校验通过",
            "completed_with_warnings": "完成，但有降级或警告",
            "failed": "执行失败",
            "cancelled": "已取消",
        }
        self.results_headline.configure(
            text="第 6 步：{}（状态 {}）".format(endings.get(results.state, results.state), results.state)
        )
        if results.degradations:
            self.degradation_label.configure(
                text="降级记录：\n" + "\n".join("• " + item for item in results.degradations)
            )
        else:
            self.degradation_label.configure(text="没有降级：所有登记阶段均按计划完成。")

    # -- navigation -----------------------------------------------------------

    def _show_step(self, step):
        self.pages[step].tkraise()
        self.step_label.configure(
            text="第 {} / 6 步".format(_STEP_ORDER.index(step) + 1)
        )
        current_index = _STEP_ORDER.index(step)
        for index, candidate in enumerate(_STEP_ORDER):
            chip = self.step_chips[candidate]
            if index == current_index:
                chip.configure(style="StepActive.TLabel")
            elif index < current_index:
                chip.configure(style="StepDone.TLabel")
            else:
                chip.configure(style="StepIdle.TLabel")
        self._refresh_footer(step)

    def _refresh_footer(self, step):
        busy_state = "disabled" if self.busy else "normal"
        # 批准动作固定在页脚，避免落在滚动区外看不见。
        self.approve_button.grid_remove()
        self.next_button.grid()
        if step is WizardStep.DATA:
            self.back_button.configure(state="disabled")
            self.next_button.configure(text="下一步：预检查", state=busy_state)
            self.cancel_button.configure(state="disabled")
        elif step is WizardStep.PREFLIGHT:
            self.back_button.configure(state=busy_state)
            blocked = bool(getattr(self, "_blocked", False))
            self.next_button.configure(
                text="下一步：查看计划", state="disabled" if blocked or self.busy else "normal"
            )
            self.cancel_button.configure(state="disabled")
        elif step is WizardStep.PLAN:
            self.back_button.configure(state=busy_state)
            self.next_button.configure(text="下一步", state="disabled")
            self.cancel_button.configure(state="disabled")
        elif step is WizardStep.APPROVAL:
            self.back_button.configure(state=busy_state)
            self.next_button.grid_remove()
            self.approve_button.grid(row=0, column=1, padx=6)
            self.cancel_button.configure(state="disabled")
            self._refresh_approve_button()
        elif step is WizardStep.EXECUTE:
            self.back_button.configure(state="disabled")
            self.next_button.configure(text="执行中…", state="disabled")
            self.cancel_button.configure(state="normal")
        else:
            self.back_button.configure(state="disabled")
            self.next_button.configure(text="已结束", state="disabled")
            self.cancel_button.configure(state="disabled")

    def go_next(self):
        step = self.wizard.step
        if step is WizardStep.DATA:
            self._enter_preflight()
        elif step is WizardStep.PREFLIGHT:
            self._enter_plan()
        elif step is WizardStep.PLAN:
            self._enter_approval()

    def go_back(self):
        step = self.wizard.step
        if step is WizardStep.PREFLIGHT:
            self._show_step(WizardStep.DATA)
            self.wizard.edit_form(self._values())
            self.status.set("已回到第 1 步；重新预检查会生成新计划")
        elif step is WizardStep.PLAN:
            self._enter_preflight()
        elif step is WizardStep.APPROVAL:
            self._enter_plan()

    # -- transitions ----------------------------------------------------------

    def _values(self):
        return {name: variable.get() for name, variable in self.variables.items()}

    def _enter_preflight(self):
        errors = self._local_errors()
        if errors:
            messagebox.showerror("请完善输入", "\n".join("• " + item for item in errors), parent=self)
            return
        try:
            self.wizard.edit_form(self._values())
            view = self.wizard.run_preflight()
        except WizardError as error:
            messagebox.showerror("预检查失败", str(error), parent=self)
            return
        self._blocked = view.blocked
        self._render_preflight(view)
        self._show_step(WizardStep.PREFLIGHT)
        self.status.set("存在阻断问题，请修正后重新检查" if view.blocked else "预检查通过")

    def _local_errors(self):
        """Reuse the shared form validator so dialog and legacy path agree."""

        return validate_form(self._values())

    def _render_preflight(self, view):
        self.preflight_text.configure(state="normal")
        self.preflight_text.delete("1.0", "end")
        if view.blocked:
            self.preflight_headline.configure(
                text="预检查未通过：以下问题必须修正，分析不能继续。", style="Blocking.TLabel"
            )
            for issue in view.blocking:
                self.preflight_text.insert(
                    "end", "[阻断] {}：{}\n".format(issue.get("code"), issue.get("message")), "blocking"
                )
        else:
            self.preflight_headline.configure(text="预检查通过，可以进入计划确认。", style="Hint.TLabel")
            self.preflight_text.insert("end", "未发现阻断问题。\n", "ok")
        if view.warnings:
            self.preflight_text.insert("end", "\n以下为非阻断问题，结论需要保留相应限制：\n", "warning")
            for issue in view.warnings:
                self.preflight_text.insert(
                    "end", "[提醒] {}：{}\n".format(issue.get("code"), issue.get("message")), "warning"
                )
        summary = view.summary or {}
        self.preflight_text.insert("end", "\n数据概况：\n")
        self.preflight_text.insert("end", "  识别模式：{}\n".format(summary.get("mode", "unknown")))
        self.preflight_text.insert("end", "  数据行数：{}\n".format(summary.get("rows", "unknown")))
        self.preflight_text.insert("end", "  循环数：{}\n".format(summary.get("cycles", "unknown")))
        self.preflight_text.insert("end", "  编码：{}\n".format(summary.get("encoding", "unknown")))
        self.preflight_text.configure(state="disabled")

    def _enter_plan(self):
        try:
            plan = self.wizard.review_plan()
        except WizardError as error:
            messagebox.showerror("无法查看计划", str(error), parent=self)
            return
        self.plan_text.configure(state="normal")
        self.plan_text.delete("1.0", "end")
        lines = [
            "计划哈希：{}".format(plan["plan_hash"]),
            "输入 SHA-256：{}".format(plan["input_sha256"]),
            "",
            "将按顺序调用以下工具：",
        ]
        lines.extend("  {}. {}".format(index, tool) for index, tool in enumerate(plan["tools"], 1))
        lines.append("")
        lines.append("预期产物：")
        lines.extend("  - {}".format(name) for name in plan["expected_artifacts"])
        lines.append("")
        lines.append("联网：{}".format("是" if plan["network_enabled"] else "否"))
        if plan["network_enabled"]:
            lines.append("  发送字段：{}".format("、".join(plan["network_fields"]) or "（未填写）"))
        lines.append("Origin：{}".format("是" if plan["origin_enabled"] else "否"))
        if plan["limitations"]:
            lines.append("")
            lines.append("限制：")
            lines.extend("  - {}".format(item) for item in plan["limitations"])
        if plan["risks"]:
            lines.append("")
            lines.append("风险与降级：")
            lines.extend("  - {}".format(item) for item in plan["risks"])
        self.plan_text.insert("1.0", "\n".join(lines))
        self.plan_text.configure(state="disabled")
        self._show_step(WizardStep.PLAN)
        self.status.set("请核对工具顺序、联网字段与预期产物")

    def _enter_approval(self):
        try:
            approval = self.wizard.request_approval()
        except WizardError as error:
            messagebox.showerror("无法进入批准", str(error), parent=self)
            return
        self._render_scopes(approval)
        self._show_step(WizardStep.APPROVAL)
        self._refresh_approve_button()

    def approve_and_run(self):
        selected = [scope for scope, var in self.scope_vars.items() if var.get()]
        try:
            self.wizard.approve(selected)
        except (ApprovalRequired, WizardError) as error:
            messagebox.showerror("批准未生效", str(error), parent=self)
            return
        self._start_execution()

    def _start_execution(self):
        self.busy = True
        self._poll_id = self.after(100, self._poll_events)
        self._show_step(WizardStep.EXECUTE)
        self.execute_state.configure(text="执行中，请稍候…")
        self._append_execute("开始执行：按计划逐个调用白名单工具。\n")
        self.status.set("执行中")
        threading.Thread(target=self._execute_worker, daemon=True).start()

    def _execute_worker(self):
        try:
            state = self.wizard.start()
            self.events.put(("done", state))
        except Exception as error:  # noqa: BLE001 - surfaced to the user verbatim
            self.events.put(("error", "{}: {}".format(type(error).__name__, error)))

    def _append_execute(self, text):
        self.execute_text.configure(state="normal")
        self.execute_text.insert("end", text)
        self.execute_text.see("end")
        self.execute_text.configure(state="disabled")

    def cancel_run(self):
        if not self.busy:
            return
        self.wizard.cancel("用户在界面点击取消")
        self.status.set("已请求取消；当前工具会在检查点退出")

    def retry_run(self):
        self.busy = True
        self._poll_id = self.after(100, self._poll_events)
        self.execute_state.configure(text="重跑中（新 run，原记录保留）…")
        self._append_execute("\n发起重跑：新 run 目录，approval 与 plan 复用，原记录不改写。\n")
        threading.Thread(target=self._retry_worker, daemon=True).start()

    def _retry_worker(self):
        try:
            state = self.wizard.retry()
            self.events.put(("done", state))
        except Exception as error:  # noqa: BLE001
            self.events.put(("error", "{}: {}".format(type(error).__name__, error)))

    def back_to_form(self):
        self.wizard.back_to_form()
        self._blocked = False
        self._show_step(WizardStep.DATA)
        self.status.set("已回到第 1 步，原批准已失效")

    def _poll_events(self):
        if self._closed:
            return
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "done":
                    self._on_execution_done(payload)
                elif kind == "error":
                    self._on_execution_failed(payload)
        except queue.Empty:
            pass
        if not self._closed:
            self._poll_id = self.after(100, self._poll_events)

    def _on_execution_done(self, state):
        self.busy = False
        self.execute_state.configure(text="执行结束：{}".format(state))
        self._append_execute("执行结束，状态：{}\n".format(state))
        results = self.wizard.results
        if results and results.degradations:
            self._append_execute("\n降级记录：\n")
            for item in results.degradations:
                self._append_execute("  • {}\n".format(item))
        self._render_results()
        self._show_step(WizardStep.RESULTS)
        self.status.set("完成，请查看产物与审计记录")

    def _on_execution_failed(self, message):
        self.busy = False
        self.execute_state.configure(text="执行失败")
        self._append_execute("\n失败：{}\n".format(message))
        self._show_step(WizardStep.RESULTS)
        self._render_results()
        self.status.set("执行失败，可重跑或返回第 1 步")
        messagebox.showerror("执行失败", message, parent=self)

    # -- opening paths --------------------------------------------------------

    def _run_dir(self):
        controlled = self.wizard.controller.controlled_run
        return None if controlled is None else Path(controlled.run_dir)

    def open_run_artifacts(self):
        run_dir = self._run_dir()
        if run_dir is None or not (run_dir / "artifacts").is_dir():
            messagebox.showinfo("还没有产物", "请先完成一次执行。", parent=self)
            return
        self._open(run_dir / "artifacts")

    def open_run_directory(self):
        run_dir = self._run_dir()
        if run_dir is None or not run_dir.is_dir():
            messagebox.showinfo("还没有审计记录", "请先完成一次执行。", parent=self)
            return
        self._open(run_dir)

    def _open(self, path):
        try:
            if os.name == "nt":
                os.startfile(str(path))  # noqa: S606 - local UI action
            else:  # pragma: no cover - Windows is the supported platform
                messagebox.showinfo("请手动打开", str(path), parent=self)
        except OSError as error:
            messagebox.showerror("无法打开", str(error), parent=self)

    def destroy(self):
        """Cancel the polling timer before Tk deletes the callback command."""

        self._closed = True
        if self._poll_id is not None:
            try:
                self.after_cancel(self._poll_id)
            except tk.TclError:
                pass
            self._poll_id = None
        super().destroy()

    def _on_close(self):
        if self.busy:
            if not messagebox.askyesno("仍在执行", "任务尚未结束，确定关闭窗口吗？", parent=self):
                return
            self.wizard.cancel("用户关闭窗口")
        self.destroy()
