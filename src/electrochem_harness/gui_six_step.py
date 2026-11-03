"""Six-step Tk interface for the production workflow (Phase 5 / B2).

This module is deliberately thin: every rule about which step is allowed lives
in :class:`electrochem_harness.gui_controller.SixStepWizard`, which is covered by
headless tests.  Here we only draw, and we never compute anything.

The dialog replaces the old "start analysis" button, which shelled out to
``run_sci_origin.ps1`` and gave the user no plan, no approval and no way back
after a failure.
"""

import json
import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from .gui import METADATA_FIELDS, validate_form
from .gui_controller import STEP_TITLES, SixStepWizard, WizardError, WizardStep
from .knowledge_assistant import ResearchKnowledgeStore, knowledge_candidate_key
from .research_profiles import PROFILE_FIELDS, ResearchProfileStore, suggested_profile_name
from .research_report import create_research_html_report
from .research_workflow import (
    append_dialogue,
    ask_research_question,
    finalize_research_guidance,
    provider_from_environment,
)
from .workflow import ApprovalRequired

_STEP_ORDER = (
    WizardStep.DATA,
    WizardStep.PREFLIGHT,
    WizardStep.PLAN,
    WizardStep.APPROVAL,
    WizardStep.EXECUTE,
    WizardStep.RESULTS,
)

def _short_digest(value: str) -> str:
    """表格里只显示前 12 位；完整值放到下方可复制的输入框。

    12 位足够人工比对，也给产物名留出空间——产物名被截断比哈希短几位更影响阅读。
    """

    return "" if not value else value[:12] + "…"


_CHIP_LABELS = {
    WizardStep.DATA: "1 课题与数据",
    WizardStep.PREFLIGHT: "2 自动预检",
    WizardStep.PLAN: "3 研究计划",
    WizardStep.APPROVAL: "4 一键授权",
    WizardStep.EXECUTE: "5 自动执行",
    WizardStep.RESULTS: "6 报告与对话",
}

_SCOPE_HINTS = {
    "local_analysis": "解析数据、计算指标、生成报告与绘图 CSV。",
    "network_access": "发送批准的研究领域、科学问题和实验体系用于学术检索；尝试读取可访问原文并交由本地模型学习。",
    "formal_output": "把报告、CSV、JSON 等产物写入输出目录。",
}


class SixStepDialog(tk.Toplevel):
    """One window, six steps, no hidden work."""

    def __init__(self, parent, project_root, values=None, *, origin_launcher=None, on_complete=None):
        super().__init__(parent)
        self.project_root = Path(project_root).resolve()
        self.on_complete = on_complete
        self.events = queue.Queue()
        self.busy = False
        self.learning_reasoning = None
        self.learning_audit = None
        self.paper_records = []
        self.knowledge_statuses = {}
        self.final_guidance_path = None
        self.dialogue_history = []
        self.dialogue_busy = False
        self.wizard = SixStepWizard(
            self.project_root,
            origin_launcher=origin_launcher,
            progress_callback=lambda stage, message, details: self.events.put(
                ("research_progress", (stage, message, details))
            ),
        )
        self.scope_vars = {}
        self._blocked = False
        self._closed = False
        self._poll_id = None
        self._dirty = False
        self._loading = True
        self.profile_store = ResearchProfileStore(
            self.project_root / "knowledge" / "research_profiles.json"
        )

        self.title("自动研究工作台：数据 → 自主调研 → 分析 → 报告 → 对话")
        self.transient(parent)

        self._init_variables(values or {})
        self._configure_style()
        self._build()
        self._show_step(WizardStep.DATA)
        for variable in self.variables.values():
            variable.trace_add("write", self._on_form_changed)
        self._loading = False
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

    def _on_form_changed(self, *_):
        """计划一旦生成就不可变；改表单必须重新预检查，否则批准绑定的是旧计划。"""

        if self._loading or self.wizard.step is WizardStep.DATA:
            return
        if self._dirty:
            return
        self._dirty = True
        self.status.set("参数已改变：请回到第 1 步重新预检查，当前计划与批准已失效")
        self._refresh_footer(self.wizard.step)

    # -- construction ---------------------------------------------------------

    def _init_variables(self, values):
        saved = self.profile_store.active()
        merged = dict(saved)
        for key, value in dict(values).items():
            if key in PROFILE_FIELDS and value in (None, "") and key in merged:
                continue
            merged[key] = value
        profile_name = self.profile_store.active_name() or suggested_profile_name(merged)
        self.variables = {
            "profile_name": tk.StringVar(value=profile_name),
            "input_file": tk.StringVar(value=str(merged.get("input_file", ""))),
            "output_dir": tk.StringVar(value=str(merged.get("output_dir", ""))),
            "origin_exe": tk.StringVar(value=str(merged.get("origin_exe", ""))),
            "search_literature": tk.BooleanVar(value=bool(merged.get("search_literature", True))),
            "unified_research": tk.BooleanVar(value=bool(merged.get("unified_research", False))),
            "use_origin": tk.BooleanVar(value=bool(merged.get("use_origin", True))),
            "origin_plot_mode": tk.StringVar(value=str(merged.get("origin_plot_mode", "both") or "both")),
            "max_literature": tk.IntVar(value=5),
            "research_domain": tk.StringVar(value=str(merged.get("research_domain", "卤化物固态电解质"))),
            "research_background": tk.StringVar(value=str(merged.get("research_background", ""))),
            "research_question": tk.StringVar(value=str(merged.get("research_question", ""))),
            "local_fulltext_dir": tk.StringVar(value=str(merged.get("local_fulltext_dir", ""))),
            "literature_year_from": tk.IntVar(value=int(merged.get("literature_year_from", 2018) or 2018)),
        }
        for name, _, _ in METADATA_FIELDS:
            self.variables[name] = tk.StringVar(value=str(merged.get(name, "")))

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
        # Tk 默认行高不随 DPI 缩放，中文会被上下裁切，这里显式给足
        style.configure("Treeview", rowheight=30, font=("Microsoft YaHei UI", 9))
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 9, "bold"))

    def _build(self):
        outer = ttk.Frame(self, padding=14)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)

        header = ttk.Frame(outer)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="自动研究、分析与课题指导", style="Title.TLabel").grid(row=0, column=0, sticky="w")
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

        # 状态单独占一行：挤在按钮行里会被窗口边缘截断。
        self.status = tk.StringVar(value="请确认数据与实验条件")
        ttk.Label(
            outer, textvariable=self.status, style="Hint.TLabel", anchor="w"
        ).grid(row=3, column=0, sticky="ew", pady=(10, 0))

        footer = ttk.Frame(outer)
        footer.grid(row=4, column=0, sticky="ew", pady=(6, 0))
        footer.columnconfigure(2, weight=1)
        self.back_button = ttk.Button(footer, text="上一步", command=self.go_back, state="disabled")
        self.back_button.grid(row=0, column=0, padx=(0, 6))
        self.next_button = ttk.Button(footer, text="下一步", command=self._next_action)
        self.next_button.grid(row=0, column=1, padx=(0, 6))
        self.approve_button = ttk.Button(
            footer, text="批准并开始执行", command=self.approve_and_run, state="disabled"
        )
        self.cancel_button = ttk.Button(footer, text="取消执行", command=self.cancel_run, state="disabled")
        self.cancel_button.grid(row=0, column=3, padx=6)
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
            text="选择数据后单击一次即可：系统自动预检、调研、学习、分析、绘图并生成图文报告。课题与测试参数会保存为可复用配置。",
            style="Hint.TLabel",
            wraplength=900,
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))

        profiles = ttk.LabelFrame(page, text="课题配置（自动保存，可随时切换）", padding=8)
        profiles.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        profiles.columnconfigure(1, weight=1)
        ttk.Label(profiles, text="当前配置").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.profile_combo = ttk.Combobox(
            profiles,
            textvariable=self.variables["profile_name"],
            values=self.profile_store.names(),
            state="normal",
        )
        self.profile_combo.grid(row=0, column=1, sticky="ew")
        self.profile_combo.bind("<<ComboboxSelected>>", self._load_selected_profile)
        ttk.Button(profiles, text="载入", command=self._load_selected_profile).grid(row=0, column=2, padx=(6, 0))
        ttk.Button(profiles, text="另存为…", command=self._save_profile_as).grid(row=0, column=3, padx=(6, 0))
        ttk.Label(
            profiles,
            text="以后通常只需更换数据文件。修改下方体系、参数或课题信息后，开始运行时会自动更新当前配置。",
            style="Hint.TLabel",
            wraplength=860,
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(6, 0))

        paths = ttk.LabelFrame(page, text="数据与输出", padding=8)
        paths.grid(row=2, column=0, sticky="ew")
        paths.columnconfigure(1, weight=1)
        self._path_row(paths, 0, "蓝电文件", "input_file", self._choose_input)
        self._path_row(paths, 1, "输出目录", "output_dir", self._choose_output)

        metadata = ttk.LabelFrame(page, text="实验条件（启用文献检索时必填）", padding=8)
        metadata.grid(row=3, column=0, sticky="ew", pady=(4, 0))
        for block, chunk in enumerate((METADATA_FIELDS[:4], METADATA_FIELDS[4:])):
            column = ttk.Frame(metadata)
            column.grid(row=0, column=block, sticky="nsew", padx=(0, 18) if block == 0 else 0)
            column.columnconfigure(1, weight=1)
            for row, (name, label, hint) in enumerate(chunk):
                ttk.Label(column, text=label).grid(
                    row=row, column=0, sticky="w", padx=(0, 8), pady=3
                )
                ttk.Entry(column, textvariable=self.variables[name]).grid(
                    row=row, column=1, sticky="ew", pady=3
                )
                ttk.Label(column, text=hint, style="Hint.TLabel").grid(
                    row=row, column=2, sticky="w", padx=(6, 0), pady=3
                )
        ttk.Label(
            metadata,
            text="这些字段只在启用联网检索时发送给 Crossref；留空则无法进入联网阶段。",
            style="Hint.TLabel",
            wraplength=880,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))

        research = ttk.LabelFrame(page, text="研究课题与原文（用于自动检索、学习和最终指导）", padding=8)
        research.grid(row=4, column=0, sticky="ew", pady=(6, 0))
        research.columnconfigure(1, weight=1)
        for row, (name, label, hint) in enumerate((
            ("research_domain", "研究领域", "例如：卤化物固态电解质正极界面"),
            ("research_background", "课题背景", "说明材料体系、已有工作、目标和当前困难"),
            ("research_question", "本轮科学问题", "例如：容量衰减是否与界面反应和接触损失有关"),
        )):
            ttk.Label(research, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=3)
            ttk.Entry(research, textvariable=self.variables[name]).grid(row=row, column=1, sticky="ew", pady=3)
            ttk.Label(research, text=hint, style="Hint.TLabel").grid(row=row, column=2, sticky="w", padx=(6, 0), pady=3)
        ttk.Label(research, text="论文原文目录").grid(row=3, column=0, sticky="w", padx=(0, 8), pady=3)
        ttk.Entry(research, textvariable=self.variables["local_fulltext_dir"]).grid(row=3, column=1, sticky="ew", pady=3)
        ttk.Button(research, text="浏览…", command=self._choose_fulltext_dir).grid(row=3, column=2, sticky="w", padx=(6, 0), pady=3)
        ttk.Label(research, text="起始年份").grid(row=4, column=0, sticky="w", pady=3)
        tk.Spinbox(research, from_=1900, to=2100, width=8, textvariable=self.variables["literature_year_from"]).grid(row=4, column=1, sticky="w", pady=3)
        ttk.Label(
            research,
            text="系统自动展示5篇真实题录，复用本地全文，并让Qwen渐进学习最相关且尚未学习的论文。人工复核移到报告之后，不再阻断分析与课题指导。",
            style="Hint.TLabel",
            wraplength=880,
        ).grid(row=5, column=0, columnspan=3, sticky="w", pady=(6, 0))

        options = ttk.LabelFrame(page, text="绘图选项", padding=8)
        options.grid(row=5, column=0, sticky="ew", pady=(6, 0))
        options.columnconfigure(3, weight=1)
        ttk.Label(
            options,
            text="数据分析 → 自主调研 → 原文学习 → 联合判断 → 图文报告 → 课题对话自动连续执行。单击开始即授权本次本地分析、联网题录检索和结果写入。",
            style="Hint.TLabel",
            wraplength=880,
        ).grid(row=0, column=0, columnspan=4, sticky="w")
        ttk.Checkbutton(
            options, text="调用 Origin 生成工程和图片", variable=self.variables["use_origin"]
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Entry(options, textvariable=self.variables["origin_exe"]).grid(
            row=1, column=2, columnspan=1, sticky="ew", padx=(0, 6), pady=(8, 0)
        )
        ttk.Button(options, text="浏览…", command=self._choose_origin).grid(
            row=1, column=3, sticky="w", pady=(8, 0)
        )
        self.origin_plot_choice = ttk.LabelFrame(options, text="Origin绘图内容（请人工确认）", padding=6)
        self.origin_plot_choice.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        for column, (value, label) in enumerate((
            ("curve", "只画充放电曲线图"),
            ("cycling", "只画循环容量/库仑效率图"),
            ("both", "两张都画"),
        )):
            ttk.Radiobutton(
                self.origin_plot_choice,
                text=label,
                value=value,
                variable=self.variables["origin_plot_mode"],
            ).grid(row=0, column=column, sticky="w", padx=(0, 18))
        ttk.Label(
            options,
            text="Origin64.exe 留空则自动查找 2021–2026b；缺失或失败时只降级绘图，报告与绘图 CSV 保留。",
            style="Hint.TLabel",
            wraplength=880,
        ).grid(row=3, column=0, columnspan=4, sticky="w", pady=(6, 0))
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

    def _choose_fulltext_dir(self):
        path = filedialog.askdirectory(title="选择本轮可读取的论文原文目录")
        if path:
            self.variables["local_fulltext_dir"].set(path)

    def _choose_origin(self):
        path = filedialog.askopenfilename(
            title="选择 Origin64.exe", filetypes=[("Origin", "Origin64.exe"), ("所有文件", "*.*")]
        )
        if path:
            self.variables["origin_exe"].set(path)

    def _refresh_profile_choices(self):
        self.profile_combo.configure(values=self.profile_store.names())

    def _load_selected_profile(self, event=None):
        name = self.variables["profile_name"].get().strip()
        saved = self.profile_store.get(name)
        if not saved:
            if event is not None:
                messagebox.showinfo("配置不存在", "请输入新名称后点击“另存为”，或从列表选择已有配置。", parent=self)
            return
        self._loading = True
        try:
            for field, value in saved.items():
                variable = self.variables.get(field)
                if variable is not None:
                    variable.set(value)
            self.profile_store.set_active(name)
        finally:
            self._loading = False
        self.status.set("已载入课题配置：{}；通常只需更换数据文件".format(name))

    def _save_profile_as(self):
        initial = self.variables["profile_name"].get().strip() or suggested_profile_name(self._values())
        name = simpledialog.askstring("保存课题配置", "配置名称：", initialvalue=initial, parent=self)
        if not name:
            return
        saved_name = self.profile_store.save(name, self._values())
        self.variables["profile_name"].set(saved_name)
        self._refresh_profile_choices()
        self.status.set("已保存课题配置：{}".format(saved_name))

    def _auto_save_profile(self):
        name = self.variables["profile_name"].get().strip() or suggested_profile_name(self._values())
        saved_name = self.profile_store.save(name, self._values())
        self._loading = True
        try:
            self.variables["profile_name"].set(saved_name)
        finally:
            self._loading = False
        self._refresh_profile_choices()
        return saved_name

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
            variable = tk.BooleanVar(value=False)
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
                text="联网检索会使用以下批准字段：\n{}\n用于Crossref/OpenAlex检索并尝试访问出版商HTML；不发送原始数据、文件路径、样品编号、账号或Cookie。原文证据交由本地Qwen处理。".format(
                    "\n".join(rows)
                )
            )
        else:
            self.network_note.configure(text="本次未启用联网检索，不会有任何数据离开本机。")

    def _refresh_approve_button(self):
        if self._dirty:
            self.approve_button.configure(state="disabled")
            self.status.set("参数已改变：请回到第 1 步重新预检查，当前计划与批准已失效")
            return
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
        page.rowconfigure(4, weight=1)
        ttk.Label(page, text="第 5 步：按批准计划完成数据分析、原文检索、Qwen学习和知识写入。", style="Hint.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.execute_state = ttk.Label(page, text="等待开始", style="Title.TLabel")
        self.execute_state.grid(row=1, column=0, sticky="w", pady=(6, 8))
        self.research_progress_tree = ttk.Treeview(
            page, columns=("state", "detail"), show="tree headings", height=7
        )
        self.research_progress_tree.heading("#0", text="研究阶段")
        self.research_progress_tree.heading("state", text="状态")
        self.research_progress_tree.heading("detail", text="实时信息")
        self.research_progress_tree.column("#0", width=180, anchor="w")
        self.research_progress_tree.column("state", width=80, anchor="center")
        self.research_progress_tree.column("detail", width=620, anchor="w")
        self.research_progress_tree.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        self.paper_tree = ttk.Treeview(
            page,
            columns=("journal", "year", "doi", "status"),
            show="tree headings",
            height=5,
        )
        self.paper_tree.heading("#0", text="本轮5篇文献")
        self.paper_tree.heading("journal", text="期刊")
        self.paper_tree.heading("year", text="年份")
        self.paper_tree.heading("doi", text="DOI")
        self.paper_tree.heading("status", text="PDF / 学习状态")
        self.paper_tree.column("#0", width=340, anchor="w")
        self.paper_tree.column("journal", width=180, anchor="w")
        self.paper_tree.column("year", width=58, anchor="center")
        self.paper_tree.column("doi", width=170, anchor="w")
        self.paper_tree.column("status", width=190, anchor="w")
        self.paper_tree.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        self.research_stage_nodes = {}
        for stage, label in (
            ("plan", "生成学术检索计划"),
            ("search", "筛选高水平高相关论文"),
            ("fulltext", "读取并核对论文原文"),
            ("evidence", "整理数据与文献证据"),
            ("llm", "本地Qwen学习与推理"),
            ("knowledge", "写入候选知识库"),
            ("done", "完成并等待人工审核"),
        ):
            self.research_stage_nodes[stage] = self.research_progress_tree.insert(
                "", "end", text=label, values=("等待", "")
            )
        self.execute_text = tk.Text(
            page,
            wrap="word",
            state="disabled",
            font=("Consolas", 9),
            padx=8,
            pady=8,
            width=1,
            height=8,
        )
        scroll = ttk.Scrollbar(page, orient="vertical", command=self.execute_text.yview)
        self.execute_text.configure(yscrollcommand=scroll.set)
        self.execute_text.grid(row=4, column=0, sticky="nsew")
        scroll.grid(row=4, column=1, sticky="ns")
        return page

    # -- step 6 ---------------------------------------------------------------

    def _build_results_page(self):
        page = ttk.Frame(self.inner)
        page.columnconfigure(0, weight=1)
        # 表格固定行数、不参与纵向拉伸：否则它会把下面的降级提示和操作按钮挤出视野。
        self.results_headline = ttk.Label(page, text="", style="Title.TLabel", wraplength=940)
        self.results_headline.grid(row=0, column=0, sticky="w", pady=(0, 8))
        summary_box = ttk.LabelFrame(page, text="数据结论、文献依据与研究指导", padding=6)
        summary_box.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        summary_box.columnconfigure(0, weight=1)
        self.result_summary = tk.Text(
            summary_box,
            wrap="word",
            state="disabled",
            font=("Microsoft YaHei UI", 10),
            height=16,
            padx=8,
            pady=6,
        )
        summary_scroll = ttk.Scrollbar(summary_box, orient="vertical", command=self.result_summary.yview)
        self.result_summary.configure(yscrollcommand=summary_scroll.set)
        self.result_summary.grid(row=0, column=0, sticky="ew")
        summary_scroll.grid(row=0, column=1, sticky="ns")

        review_box = ttk.LabelFrame(page, text="原文学习知识（自动使用为候选解释，复核为可选）", padding=6)
        review_box.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        review_box.columnconfigure(0, weight=1)
        self.result_paper_tree = ttk.Treeview(
            review_box,
            columns=("journal", "year", "doi", "status"),
            show="tree headings",
            height=5,
        )
        self.result_paper_tree.heading("#0", text="本轮检索文献")
        self.result_paper_tree.heading("journal", text="期刊")
        self.result_paper_tree.heading("year", text="年份")
        self.result_paper_tree.heading("doi", text="DOI")
        self.result_paper_tree.heading("status", text="PDF / 学习状态")
        self.result_paper_tree.column("#0", width=350, anchor="w")
        self.result_paper_tree.column("journal", width=170, anchor="w")
        self.result_paper_tree.column("year", width=55, anchor="center")
        self.result_paper_tree.column("doi", width=165, anchor="w")
        self.result_paper_tree.column("status", width=190, anchor="w")
        self.result_paper_tree.grid(row=0, column=0, columnspan=5, sticky="ew", pady=(0, 8))
        self.result_paper_tree.bind("<Double-1>", self._open_selected_paper)
        self.knowledge_tree = ttk.Treeview(
            review_box,
            columns=("status", "confidence", "sources"),
            show="tree headings",
            height=6,
        )
        self.knowledge_tree.heading("#0", text="候选知识")
        self.knowledge_tree.heading("status", text="人工状态")
        self.knowledge_tree.heading("confidence", text="模型置信度")
        self.knowledge_tree.heading("sources", text="原文来源")
        self.knowledge_tree.column("#0", width=500, anchor="w")
        self.knowledge_tree.column("status", width=90, anchor="center")
        self.knowledge_tree.column("confidence", width=90, anchor="center")
        self.knowledge_tree.column("sources", width=180, anchor="w")
        self.knowledge_tree.grid(row=1, column=0, columnspan=5, sticky="ew")
        review_scroll = ttk.Scrollbar(review_box, orient="vertical", command=self.knowledge_tree.yview)
        self.knowledge_tree.configure(yscrollcommand=review_scroll.set)
        review_scroll.grid(row=1, column=5, sticky="ns")
        ttk.Label(review_box, text="审核备注").grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.review_note = tk.StringVar()
        ttk.Entry(review_box, textvariable=self.review_note).grid(row=2, column=1, sticky="ew", padx=6, pady=(6, 0))
        review_box.columnconfigure(1, weight=1)
        self.approve_knowledge_button = ttk.Button(review_box, text="批准选中", command=lambda: self._review_selected_knowledge("approved"), state="disabled")
        self.approve_knowledge_button.grid(row=2, column=2, padx=3, pady=(6, 0))
        self.reject_knowledge_button = ttk.Button(review_box, text="拒绝选中", command=lambda: self._review_selected_knowledge("rejected"), state="disabled")
        self.reject_knowledge_button.grid(row=2, column=3, padx=3, pady=(6, 0))
        self.finalize_guidance_button = ttk.Button(review_box, text="按复核结果刷新报告", command=self._finalize_guidance, state="disabled")
        self.finalize_guidance_button.grid(row=2, column=4, padx=(8, 0), pady=(6, 0))
        paper_actions = ttk.Frame(review_box)
        paper_actions.grid(row=3, column=0, columnspan=5, sticky="w", pady=(8, 0))
        ttk.Button(
            paper_actions,
            text="在浏览器打开需下载文献",
            command=self._open_restricted_papers,
        ).grid(row=0, column=0)
        ttk.Button(
            paper_actions,
            text="选择已下载PDF目录",
            command=self._choose_downloaded_pdf_folder,
        ).grid(row=0, column=1, padx=(6, 0))

        self.results_tree = ttk.Treeview(
            page, columns=("state", "sha256", "path"), show="tree headings", height=12
        )
        self.results_tree.heading("#0", text="产物")
        self.results_tree.heading("state", text="状态")
        self.results_tree.heading("sha256", text="SHA-256")
        self.results_tree.heading("path", text="路径")
        self.results_tree.column("#0", width=268, anchor="w")
        self.results_tree.column("state", width=76, anchor="center")
        # 12 位十六进制加省略号约需 110px。
        self.results_tree.column("sha256", width=132, anchor="w")
        self.results_tree.column("path", width=235, anchor="w")
        self.results_tree.bind("<Double-1>", self._open_selected_artifact)
        self.results_tree.bind("<<TreeviewSelect>>", self._show_selected_hash)
        scroll = ttk.Scrollbar(page, orient="vertical", command=self.results_tree.yview)
        self.results_tree.configure(yscrollcommand=scroll.set)
        self.results_tree.grid(row=3, column=0, sticky="nsew")
        scroll.grid(row=3, column=1, sticky="ns")

        self.degradation_label = ttk.Label(page, text="", style="Hint.TLabel", wraplength=940)
        self.degradation_label.grid(row=4, column=0, sticky="w", pady=(8, 0))

        # 表格里只放前 16 位；完整值在这里给出，可选中复制，用于对外核对。
        hash_row = ttk.Frame(page)
        hash_row.grid(row=5, column=0, sticky="ew", pady=(6, 0))
        hash_row.columnconfigure(1, weight=1)
        ttk.Label(hash_row, text="选中项完整哈希", style="Hint.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )
        self.full_hash = tk.StringVar(value="（选中上方任意一行）")
        self.full_hash_entry = ttk.Entry(
            hash_row, textvariable=self.full_hash, state="readonly"
        )
        self.full_hash_entry.grid(row=0, column=1, sticky="ew")

        actions = ttk.Frame(page)
        actions.grid(row=6, column=0, sticky="ew", pady=(10, 0))
        self.open_report_button = ttk.Button(actions, text="打开图文报告", command=self.open_html_report, state="disabled")
        self.open_report_button.grid(row=0, column=0)
        ttk.Button(actions, text="打开输出目录", command=self.open_run_artifacts).grid(row=0, column=1, padx=6)
        ttk.Button(actions, text="打开审计目录", command=self.open_run_directory).grid(
            row=0, column=2, padx=6
        )
        self.retry_button = ttk.Button(actions, text="重跑（新 run，保留原记录）", command=self.retry_run)
        self.retry_button.grid(row=0, column=3, padx=6)
        ttk.Button(actions, text="返回修改配置", command=self.back_to_form).grid(row=0, column=4, padx=6)

        dialogue_box = ttk.LabelFrame(page, text="课题对话（自动报告生成后即可使用）", padding=6)
        dialogue_box.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        dialogue_box.columnconfigure(0, weight=1)
        self.dialogue_text = tk.Text(dialogue_box, wrap="word", state="disabled", height=8, font=("Microsoft YaHei UI", 9), padx=8, pady=6)
        self.dialogue_text.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.dialogue_input = tk.Text(dialogue_box, wrap="word", height=3, font=("Microsoft YaHei UI", 9))
        self.dialogue_input.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        self.dialogue_send_button = ttk.Button(dialogue_box, text="发送并获得课题指导", command=self._send_dialogue, state="disabled")
        self.dialogue_send_button.grid(row=1, column=1, sticky="e", padx=(6, 0), pady=(6, 0))
        return page

    def _display_path(self, path):
        """Show paths relative to the run directory; absolute temp paths are noisy."""

        if path is None:
            return ""
        candidate = Path(path)
        run_dir = self._run_dir()
        if run_dir is not None:
            try:
                return str(candidate.relative_to(run_dir))
            except ValueError:
                pass
        return candidate.name

    def _recorded_hashes(self):
        """Read the SHA-256 values recorded when the run was validated.

        读 run_record.json 而不是现场重新计算：记录里存的是本次运行实际校验过的
        内容。如果磁盘上的文件之后被改动，两者不一致本身就是需要看到的信息。
        """

        run_dir = self._run_dir()
        if run_dir is None:
            return {}
        try:
            payload = json.loads(
                (run_dir / "run_record.json").read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            return {}
        hashes = {}
        for item in payload.get("artifacts") or ():
            if isinstance(item, dict) and item.get("path") and item.get("sha256"):
                hashes[str(item["path"])] = str(item["sha256"])
        return hashes

    def _show_selected_hash(self, event=None):
        """Put the full digest of the selected row into the copyable field."""

        selection = self.results_tree.selection()
        if not selection:
            return
        item = selection[0]
        name = self.results_tree.item(item, "text").strip()
        digest = getattr(self, "_hashes", {}).get(name, "")
        self.full_hash.set(digest or "（该产物没有登记哈希）")

    def _open_selected_artifact(self, event=None):
        selection = self.results_tree.selection()
        if not selection:
            return
        values = self.results_tree.item(selection[0], "values")
        # 列顺序：状态 / SHA-256 / 路径
        if len(values) < 3 or not values[2]:
            return
        run_dir = self._run_dir()
        if run_dir is None:
            return
        target = Path(run_dir) / values[2]
        if target.is_file():
            self._open(target)
        else:
            messagebox.showinfo("尚未生成", "该产物在本次运行中没有生成。", parent=self)

    def _render_papers(self, papers):
        self.paper_records = [dict(item) for item in (papers or [])]
        self._paper_by_iid = {}
        for tree in (self.paper_tree, self.result_paper_tree):
            for child in tree.get_children():
                tree.delete(child)
            for index, paper in enumerate(self.paper_records):
                iid = "paper-{}".format(index)
                self._paper_by_iid[iid] = paper
                tree.insert(
                    "",
                    "end",
                    iid=iid,
                    text=str(paper.get("title") or "未命名文献"),
                    values=(
                        paper.get("journal") or "",
                        paper.get("year") or "",
                        paper.get("doi") or "",
                        paper.get("status") or "",
                    ),
                )

    def _open_selected_paper(self, event=None):
        selection = self.result_paper_tree.selection()
        if not selection:
            return
        paper = getattr(self, "_paper_by_iid", {}).get(selection[0], {})
        local_file = str(paper.get("local_file") or "").strip()
        if local_file:
            target = self.project_root / "knowledge" / "paper_library" / "pdfs" / local_file
            if target.is_file():
                self._open(target)
                return
        url = str(paper.get("landing_url") or "").strip()
        if url:
            import webbrowser

            webbrowser.open(url)
            return
        messagebox.showinfo("没有可打开的原文", "该论文尚无本地PDF或DOI页面。", parent=self)

    def _open_restricted_papers(self):
        import webbrowser

        opened = 0
        for paper in self.paper_records:
            if paper.get("learned"):
                continue
            url = str(paper.get("landing_url") or "").strip()
            if url and webbrowser.open(url):
                opened += 1
        if not opened:
            messagebox.showinfo("没有待下载文献", "当前没有可在浏览器中打开的受限文献。", parent=self)
        else:
            self.status.set("已在默认浏览器打开{}篇文献；请使用校园网合法下载PDF".format(opened))

    def _choose_downloaded_pdf_folder(self):
        selected = filedialog.askdirectory(parent=self, title="选择保存论文PDF的目录")
        if not selected:
            return
        self.variables["local_fulltext_dir"].set(selected)
        self.back_to_form()
        self.status.set("已填入PDF目录；重新预检查并批准后，系统将优先读取这些原文")

    @staticmethod
    def _learning_summary_text(reasoning):
        lines = ["文献原文学习摘要", str(reasoning.get("summary") or "")]
        findings = list(reasoning.get("article_core_findings") or [])
        if findings:
            lines.extend(["", "逐篇核心发现"])
            for item in findings:
                lines.append(
                    "{}：{}（方法：{}；依据：{}；限制：{}）".format(
                        item.get("source_id") or "来源待核对",
                        item.get("core_finding") or "",
                        item.get("method") or "未注明",
                        item.get("evidence_location") or "正文",
                        item.get("limitations") or "未注明",
                    )
                )
        background = list(reasoning.get("research_background") or [])
        if background:
            lines.extend(["", "领域背景知识"])
            for item in background:
                lines.append("{}（来源：{}；边界：{}）".format(
                    item.get("claim") or "", "、".join(item.get("source_ids") or []),
                    item.get("limitations") or "待核对",
                ))
        foundations = list(reasoning.get("electrochemistry_foundations") or [])
        if foundations:
            lines.extend(["", "电化学专业知识"])
            for item in foundations:
                lines.append(
                    "{}：{}；来源：{}；边界：{}".format(
                        item.get("concept") or "概念", item.get("explanation") or "",
                        "、".join(item.get("source_ids") or []), item.get("boundaries") or "待核对",
                    )
                )
        figures = list(reasoning.get("key_figures_tables") or [])
        if figures:
            lines.extend(["", "与本实验相关的图表参数"])
            for item in figures:
                lines.append("{} {}：{} {}；条件：{}；逻辑：{}".format(
                    item.get("source_id") or "来源待核对", item.get("location") or "",
                    item.get("parameter") or "参数", "{} {}".format(item.get("value") or "", item.get("unit") or "").strip(),
                    item.get("conditions") or "待核对", item.get("scientific_logic") or "待核对",
                ))
        assessments = list(reasoning.get("data_value_assessment") or [])
        if assessments:
            lines.extend(["", "文献学习后的数据判断"])
            for item in assessments:
                lines.append("{}；价值：{}；依据：{}；置信度：{}；限制：{}".format(
                    item.get("finding") or "", item.get("value") or "", item.get("evidence") or "",
                    item.get("confidence") or "", item.get("limitations") or "",
                ))
        unknowns = list(reasoning.get("cannot_determine") or [])
        if unknowns:
            lines.extend(["", "当前仍不能判断"])
            lines.extend(str(item) for item in unknowns)
        experiments = list(reasoning.get("missing_experiments") or [])
        characterizations = list(reasoning.get("missing_characterization") or [])
        if experiments or characterizations:
            lines.extend(["", "下一轮建议（已自动进入报告；知识复核可提升依据等级）"])
            for item in experiments:
                lines.append("实验：{}；变量/对照：{}；支持或反证：{}".format(
                    item.get("experiment") or "", item.get("variables") or "", item.get("expected_evidence") or "",
                ))
            for item in characterizations:
                lines.append("表征：{}；取样：{}；支持或反证：{}".format(
                    item.get("characterization") or "", item.get("sampling") or "", item.get("expected_evidence") or "",
                ))
        if reasoning.get("knowledge_candidates"):
            lines.extend(["", "下方知识已从原文自动提炼并用于候选解释；人工复核为可选，复核后可刷新报告并提升依据等级。"])
        else:
            lines.extend(["", "本轮仅完成文献检索，没有原文学习结果或知识候选。"])
        return "\n".join(line for line in lines if line is not None)

    def _render_results(self):
        results = self.wizard.results
        if results is None:
            return
        summary_path = None
        for entry in results.report:
            if entry.name == "关键结论.txt" and entry.available:
                summary_path = Path(entry.path)
                break
        if summary_path is None:
            summary_text = "本次运行没有生成确定性结论，请查看失败或降级记录。"
        else:
            try:
                summary_text = summary_path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as error:
                summary_text = "关键结论读取失败：{}".format(error)
        artifacts = self._run_dir() / "artifacts" if self._run_dir() is not None else None
        learning_path = None if artifacts is None else artifacts / "文献学习结果.json"
        audit_path = None if artifacts is None else artifacts / "文献学习审计.json"
        paper_manifest_path = None if artifacts is None else artifacts / "文献清单.json"
        self.learning_reasoning = None
        self.learning_audit = None
        if paper_manifest_path is not None and paper_manifest_path.is_file():
            try:
                paper_manifest = json.loads(paper_manifest_path.read_text(encoding="utf-8"))
                self._render_papers(paper_manifest.get("papers", []))
            except (OSError, json.JSONDecodeError):
                pass
        if learning_path is not None and learning_path.is_file():
            try:
                self.learning_reasoning = json.loads(learning_path.read_text(encoding="utf-8"))
                summary_text += "\n\n" + self._learning_summary_text(self.learning_reasoning)
            except (OSError, json.JSONDecodeError) as error:
                summary_text += "\n\n文献学习结果读取失败：{}".format(error)
        else:
            summary_text += "\n\n原文学习阶段未完成。系统仍已生成确定性数据报告；文献支持和机理解释会明确标记为证据不足。"
        if audit_path is not None and audit_path.is_file():
            try:
                self.learning_audit = json.loads(audit_path.read_text(encoding="utf-8"))
                if self.learning_audit.get("selected_papers"):
                    self._render_papers(self.learning_audit["selected_papers"])
            except (OSError, json.JSONDecodeError):
                self.learning_audit = None
        guidance_path = None if artifacts is None else artifacts / "研究结论与指导.txt"
        if guidance_path is not None and guidance_path.is_file():
            try:
                summary_text = guidance_path.read_text(encoding="utf-8")
                self.final_guidance_path = guidance_path
                self.dialogue_send_button.configure(state="normal")
            except (OSError, UnicodeError):
                pass
        self._populate_knowledge_review()
        self.result_summary.configure(state="normal")
        self.result_summary.delete("1.0", "end")
        self.result_summary.insert("1.0", summary_text)
        self.result_summary.configure(state="disabled")
        for item in self.results_tree.get_children():
            self.results_tree.delete(item)
        self._hashes = self._recorded_hashes()
        groups = (
            ("报告与数值", results.report),
            ("原文学习与知识审计", results.evidence),
            ("Origin 产物（可选）", results.origin),
            ("审计记录", results.audit),
        )
        for title, entries in groups:
            parent = self.results_tree.insert(
                "", "end", text=title, values=("", "", ""), open=True
            )
            for entry in entries:
                if entry.available:
                    state = "已生成"
                elif entry.required:
                    state = "缺失"
                else:
                    state = "未启用"
                digest = self._hashes.get(entry.name, "")
                if digest:
                    sha_cell = _short_digest(digest)
                elif entry.available:
                    # 文件存在但没有登记哈希，说明它没进入校验环节；
                    # 留白会让人以为是界面漏显示，所以明确标注。
                    sha_cell = "未登记"
                else:
                    sha_cell = ""
                self.results_tree.insert(
                    parent,
                    "end",
                    text="  " + entry.name,
                    values=(
                        state,
                        sha_cell,
                        self._display_path(entry.path),
                    ),
                )
        self.full_hash.set("（选中上方任意一行查看完整哈希）")

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

    def _populate_knowledge_review(self):
        for item in self.knowledge_tree.get_children():
            self.knowledge_tree.delete(item)
        self.knowledge_statuses = {}
        reasoning = self.learning_reasoning or {}
        persisted_reviews = {}
        if self.learning_audit:
            try:
                persisted_reviews = ResearchKnowledgeStore(
                    self.project_root / "knowledge" / "research_knowledge.md"
                ).candidate_reviews_for_entry(self.learning_audit["knowledge_entry_key"])
            except Exception:
                persisted_reviews = {}
        for item in reasoning.get("knowledge_candidates", []):
            candidate_id = knowledge_candidate_key(item)
            status, _note = persisted_reviews.get(candidate_id, ("candidate", ""))
            self.knowledge_statuses[candidate_id] = status
            self.knowledge_tree.insert(
                "",
                "end",
                iid=candidate_id,
                text=str(item.get("claim", "")),
                values=(status, item.get("confidence", ""), "、".join(item.get("source_ids", []))),
            )
        enabled = "normal" if self.knowledge_tree.get_children() and self.learning_audit else "disabled"
        self.approve_knowledge_button.configure(state=enabled)
        self.reject_knowledge_button.configure(state=enabled)
        self._refresh_finalize_guidance()
        run_dir = self._run_dir()
        existing = None if run_dir is None else run_dir / "artifacts" / "研究结论与指导.txt"
        if existing is not None and existing.is_file():
            self.final_guidance_path = existing
            self.dialogue_send_button.configure(state="normal")
            html_report = existing.with_name("研究分析报告.html")
            self.open_report_button.configure(state="normal" if html_report.is_file() else "disabled")

    def _review_selected_knowledge(self, status):
        selected = self.knowledge_tree.selection()
        if not selected:
            messagebox.showinfo("请选择知识", "请先选择一条候选知识。", parent=self)
            return
        candidate_id = selected[0]
        note = self.review_note.get().strip()
        if status == "approved" and not note:
            messagebox.showinfo("需要审核依据", "批准知识时请填写已核对的正文位置、图号或理由。", parent=self)
            return
        try:
            store = ResearchKnowledgeStore(self.project_root / "knowledge" / "research_knowledge.md")
            store.set_candidate_status(
                self.learning_audit["knowledge_entry_key"],
                candidate_id,
                status,
                note,
            )
        except Exception as error:
            messagebox.showerror("知识审核失败", str(error), parent=self)
            return
        self.knowledge_statuses[candidate_id] = status
        values = list(self.knowledge_tree.item(candidate_id, "values"))
        values[0] = status
        self.knowledge_tree.item(candidate_id, values=values)
        self.review_note.set("")
        self._refresh_finalize_guidance()

    def _refresh_finalize_guidance(self):
        if self.learning_reasoning is None:
            self.finalize_guidance_button.configure(state="disabled")
            return
        pending = [status for status in self.knowledge_statuses.values() if status == "candidate"]
        self.finalize_guidance_button.configure(state="normal")
        if pending:
            self.status.set("自动报告已生成；可选复核{}条知识并刷新报告".format(len(pending)))

    def _finalize_guidance(self):
        run_dir = self._run_dir()
        if run_dir is None or self.learning_reasoning is None:
            return
        artifacts = run_dir / "artifacts"
        try:
            path = finalize_research_guidance(
                deterministic_conclusion=artifacts / "关键结论.txt",
                reasoning=self.learning_reasoning,
                status_by_id=self.knowledge_statuses,
                values=self._values(),
                target=artifacts / "研究结论与指导.txt",
                require_review=False,
            )
        except Exception as error:
            messagebox.showerror("不能生成最终结论", str(error), parent=self)
            return
        self.final_guidance_path = path
        text = path.read_text(encoding="utf-8")
        self.result_summary.configure(state="normal")
        self.result_summary.delete("1.0", "end")
        self.result_summary.insert("1.0", text)
        self.result_summary.configure(state="disabled")
        self._refresh_html_report()
        self.open_report_button.configure(state="normal")
        self.dialogue_send_button.configure(state="normal")
        self.status.set("报告已按当前复核状态刷新，可以继续课题对话")
        if self.on_complete is not None:
            try:
                self.on_complete(run_dir)
            except Exception:
                pass

    def _refresh_html_report(self):
        run_dir = self._run_dir()
        if run_dir is None:
            return None
        artifacts = run_dir / "artifacts"
        deterministic = artifacts / "关键结论.txt"
        guidance = artifacts / "研究结论与指导.txt"
        if not deterministic.is_file() or not guidance.is_file():
            return None
        images = sorted(
            path for path in artifacts.iterdir()
            if path.suffix.casefold() in {".png", ".jpg", ".jpeg", ".gif", ".svg"}
        )
        return create_research_html_report(
            artifacts / "研究分析报告.html",
            values=self._values(),
            deterministic_text=deterministic.read_text(encoding="utf-8"),
            guidance_text=guidance.read_text(encoding="utf-8"),
            reasoning=self.learning_reasoning or {},
            status_by_id=self.knowledge_statuses,
            papers=self.paper_records,
            image_paths=images,
        )

    def _append_dialogue_view(self, role, text):
        self.dialogue_text.configure(state="normal")
        self.dialogue_text.insert("end", "{}\n{}\n\n".format(role, text))
        self.dialogue_text.see("end")
        self.dialogue_text.configure(state="disabled")

    def _send_dialogue(self):
        if self.dialogue_busy or self.final_guidance_path is None:
            return
        message = self.dialogue_input.get("1.0", "end").strip()
        if not message:
            messagebox.showinfo("请输入课题信息", "请说明你的整体课题、当前困难或希望讨论的问题。", parent=self)
            return
        self.dialogue_input.delete("1.0", "end")
        self._append_dialogue_view("你", message)
        self.dialogue_history.append({"role": "user", "content": message})
        append_dialogue(self._run_dir() / "artifacts" / "课题对话.jsonl", self.dialogue_history[-1])
        self.dialogue_busy = True
        self.dialogue_send_button.configure(state="disabled")
        self.status.set("本地大模型正在结合数据、原文和已批准知识回答…")
        values = self._values()
        guidance = self.final_guidance_path.read_text(encoding="utf-8")
        history = list(self.dialogue_history)
        statuses = dict(self.knowledge_statuses)
        threading.Thread(
            target=self._dialogue_worker,
            args=(values, guidance, history, message, statuses),
            daemon=True,
        ).start()

    def _dialogue_worker(self, values, guidance, history, message, statuses):
        try:
            answer = ask_research_question(
                provider=provider_from_environment(),
                values=values,
                guidance_text=guidance,
                reasoning=self.learning_reasoning or {},
                history=history,
                user_message=message,
                status_by_id=statuses,
            )
            self.events.put(("dialogue_done", answer))
        except Exception as error:
            self.events.put(("dialogue_error", "{}: {}".format(type(error).__name__, error)))

    def _finish_dialogue(self, answer):
        lines = [answer.get("answer", "")]
        for field, label in (
            ("basis", "依据"),
            ("uncertainties", "不确定性"),
            ("next_actions", "下一步"),
            ("questions_for_user", "还需要了解"),
        ):
            values = answer.get(field, [])
            if values:
                lines.append("{}：{}".format(label, "；".join(values)))
        rendered = "\n".join(lines)
        self._append_dialogue_view("研究助手", rendered)
        record = {"role": "assistant", "content": rendered, "model": answer.get("model"), "total_tokens": answer.get("total_tokens", 0)}
        self.dialogue_history.append(record)
        append_dialogue(self._run_dir() / "artifacts" / "课题对话.jsonl", record)
        self.dialogue_busy = False
        self.dialogue_send_button.configure(state="normal")
        self.status.set("可以继续补充课题信息或追问")

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
            self.next_button.configure(text="开始自动调研与分析", state=busy_state)
            self.cancel_button.configure(state="disabled")
        elif step is WizardStep.PREFLIGHT:
            self.back_button.configure(state=busy_state)
            self.next_button.configure(
                text="下一步：查看计划",
                state="disabled" if self._blocked or self.busy else "normal",
            )
            self.cancel_button.configure(state="disabled")
        elif step is WizardStep.PLAN:
            self.back_button.configure(state=busy_state)
            # 计划页必须能继续走到第 4 步：这里曾经被误设成 disabled，用户会卡死。
            self.next_button.configure(
                text="下一步：确认批准范围",
                state="disabled" if self.busy or self._dirty else "normal",
            )
            self.cancel_button.configure(state="disabled")
        elif step is WizardStep.APPROVAL:
            self.back_button.configure(state=busy_state)
            self.next_button.grid_remove()
            self.approve_button.grid(row=0, column=1, padx=(0, 6))
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

    def start_automated_research(self):
        """Use one explicit click to prepare, authorise and run the full workflow."""

        self.variables["search_literature"].set(True)
        self.variables["unified_research"].set(True)
        self.variables["max_literature"].set(5)
        errors = self._local_errors()
        if errors:
            messagebox.showerror("请完善必要信息", "\n".join("• " + item for item in errors), parent=self)
            return
        profile_name = self._auto_save_profile()
        try:
            self.wizard.edit_form(self._values())
            preflight = self.wizard.run_preflight()
            self._blocked = preflight.blocked
            self._render_preflight(preflight)
            if preflight.blocked:
                self._show_step(WizardStep.PREFLIGHT)
                self.status.set("数据预检发现阻断问题，请修正后重试")
                return
            self.wizard.review_plan()
            self.wizard.request_approval()
            self.wizard.approve(self.wizard.required_scopes)
        except (WizardError, ApprovalRequired, ValueError) as error:
            messagebox.showerror("无法开始自动研究", str(error), parent=self)
            return
        self._dirty = False
        self.status.set("已使用配置“{}”，正在自动调研与分析".format(profile_name))
        self._start_execution()

    def _next_action(self):
        if self.wizard.step is WizardStep.DATA:
            self.start_automated_research()
        else:
            self.go_next()

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
        return {
            name: variable.get()
            for name, variable in self.variables.items()
            if name != "profile_name"
        }

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
        self._dirty = False
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
        tool_labels = {
            "parse_land_text": "解析实验数据",
            "quality_check": "检查数据质量",
            "calculate_cycle_metrics": "计算确定性电化学指标",
            "search_literature_metadata": "根据实验与课题信息筛选最多5篇高质量论文、读取原文并由本地大模型学习",
            "build_scientific_report": "生成确定性报告并准备人工知识审核",
            "build_origin_project": "按已选内容生成Origin图",
        }
        lines.extend(
            "  {}. {}".format(index, tool_labels.get(tool, tool))
            for index, tool in enumerate(plan["tools"], 1)
        )
        lines.append("")
        lines.append("预期产物：")
        lines.extend("  - {}".format(name) for name in plan["expected_artifacts"])
        lines.append("")
        lines.append("联网：{}".format("是" if plan["network_enabled"] else "否"))
        if plan["network_enabled"]:
            lines.append("  发送字段：{}".format("、".join(plan["network_fields"]) or "（未填写）"))
        if plan["origin_enabled"]:
            mode = str(self.variables["origin_plot_mode"].get())
            labels = {
                "curve": "只画充放电曲线图",
                "cycling": "只画循环容量/库仑效率图",
                "both": "两张都画",
            }
            lines.append("Origin：是（{}）".format(labels.get(mode, mode)))
        else:
            lines.append("Origin：否")
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
        self._reset_research_progress()
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

    def _reset_research_progress(self):
        self._render_papers([])
        for node in self.research_stage_nodes.values():
            self.research_progress_tree.item(node, values=("等待", ""))

    def _on_research_progress(self, stage, message, details):
        order = ("plan", "search", "fulltext", "evidence", "llm", "knowledge", "done")
        if stage not in order:
            return
        current = order.index(stage)
        for previous in order[:current]:
            node = self.research_stage_nodes.get(previous)
            if node is not None:
                old = self.research_progress_tree.item(node, "values")
                self.research_progress_tree.item(node, values=("完成", old[1] if len(old) > 1 else ""))
        if (details or {}).get("papers") is not None:
            self._render_papers((details or {}).get("papers"))
        detail_text = "；".join(
            "{}={}".format(key, value)
            for key, value in sorted((details or {}).items())
            if key != "papers"
        )
        node = self.research_stage_nodes.get(stage)
        state = "完成" if stage == "done" or "完成" in message or "通过" in message else "进行中"
        if node is not None:
            self.research_progress_tree.item(node, values=(state, "{}{}".format(message, "；" + detail_text if detail_text else "")))
            self.research_progress_tree.see(node)
        if stage == "done":
            for item in self.research_stage_nodes.values():
                values = self.research_progress_tree.item(item, "values")
                self.research_progress_tree.item(item, values=("完成", values[1] if len(values) > 1 else ""))
        label = {
            "plan": "检索计划",
            "search": "论文筛选",
            "fulltext": "原文读取",
            "evidence": "证据整理",
            "llm": "Qwen学习",
            "knowledge": "知识写入",
            "done": "完成",
        }[stage]
        self.execute_state.configure(text="{}：{}".format(label, message))
        self._append_execute("[{}] {}{}\n".format(label, message, "；" + detail_text if detail_text else ""))
        self.status.set(message)

    def cancel_run(self):
        if not self.busy:
            return
        self.wizard.cancel("用户在界面点击取消")
        self.status.set("已请求取消；当前工具会在检查点退出")

    def retry_run(self):
        self.busy = True
        self._reset_research_progress()
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
        self._dirty = False
        self._show_step(WizardStep.DATA)
        self.status.set("已回到第 1 步，原批准已失效")

    def _poll_events(self):
        if self._closed:
            return
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "research_progress":
                    stage, message, details = payload
                    self._on_research_progress(stage, message, details)
                elif kind == "done":
                    self._on_execution_done(payload)
                elif kind == "error":
                    self._on_execution_failed(payload)
                elif kind == "dialogue_done":
                    self._finish_dialogue(payload)
                elif kind == "dialogue_error":
                    self.dialogue_busy = False
                    self.dialogue_send_button.configure(state="normal")
                    self.status.set("课题对话失败")
                    messagebox.showerror("课题对话失败", payload, parent=self)
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
                if item.startswith("search_literature_metadata:"):
                    for stage, node in self.research_stage_nodes.items():
                        values = self.research_progress_tree.item(node, "values")
                        if not values or values[0] in {"等待", "进行中"}:
                            self.research_progress_tree.item(node, values=("未完成", "文献学习降级，详情见下方日志"))
        self._render_results()
        html_report = self._refresh_html_report()
        self.open_report_button.configure(state="normal" if html_report and html_report.is_file() else "disabled")
        self._show_step(WizardStep.RESULTS)
        self.status.set("自动研究完成：图文报告已生成，可继续课题对话；知识复核为可选")
        if self.on_complete is not None:
            try:
                self.on_complete(self._run_dir())
            except Exception:
                pass

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

    def open_html_report(self):
        run_dir = self._run_dir()
        report = None if run_dir is None else run_dir / "artifacts" / "研究分析报告.html"
        if report is None or not report.is_file():
            messagebox.showinfo("报告尚未生成", "请先完成一次自动调研与分析。", parent=self)
            return
        self._open(report)

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
        if self.busy or self.dialogue_busy:
            if not messagebox.askyesno("仍在执行", "分析或课题对话尚未结束，确定关闭窗口吗？", parent=self):
                return
            if self.busy:
                self.wizard.cancel("用户关闭窗口")
        self.destroy()
