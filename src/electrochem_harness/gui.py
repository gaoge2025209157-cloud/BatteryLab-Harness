"""Local Tkinter interface for the electrochemical workflow."""

import locale
import os
from pathlib import Path
import queue
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .approval import ApprovalError
from .gui_controller import (
    METADATA_FIELDS,
    SUPPORTED_EXTENSIONS,
    UNKNOWN_VALUES,
    validate_form,
)
from .gui_phase1 import Phase1GuiController, format_plan
from .workflow import ApprovalRequired


CLI_FIELD_FLAGS = {
    "battery_system": "-BatterySystem",
    "active_material": "-ActiveMaterial",
    "cell_type": "-CellType",
    "counter_electrode": "-CounterElectrode",
    "test_current": "-TestCurrent",
    "temperature": "-Temperature",
    "normalization_basis": "-NormalizationBasis",
}


def _missing(value):
    """True when a metadata field counts as unanswered (shares the wizard's set)."""

    return str(value or "").strip().casefold() in UNKNOWN_VALUES


def build_workflow_command(project_root, values):
    """Build a subprocess argument list; never concatenate a shell command."""
    root = Path(project_root).resolve()
    command = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(root / "run_sci_origin.ps1"),
        "-InputFile",
        str(values["input_file"]),
        "-OutputDir",
        str(values["output_dir"]),
        "-MaxLiterature",
        str(int(values.get("max_literature", 50))),
    ]
    if values.get("search_literature"):
        command.append("-SearchLiterature")
    if not values.get("use_origin"):
        command.append("-SkipOrigin")
    origin_exe = str(values.get("origin_exe", "")).strip()
    if values.get("use_origin") and origin_exe:
        command.extend(["-OriginExe", origin_exe])
    for name, _, _ in METADATA_FIELDS:
        value = str(values.get(name, "")).strip()
        if value and not _missing(value):
            command.extend([CLI_FIELD_FLAGS[name], value])
    return command


class Phase1Dialog:
    """Six-step Phase 1 demonstration without replacing the legacy runner."""

    def __init__(self, parent, project_root, values):
        self.parent = parent
        self.values = dict(values)
        self.controller = Phase1GuiController(project_root)
        self.events = queue.Queue()
        self.busy = False
        self.window = tk.Toplevel(parent)
        self.window.title("Phase 1受控Harness演示")
        self.window.geometry("900x720")
        self.window.minsize(760, 580)
        self.status = tk.StringVar(value="请先生成分析计划")
        self.scope_local = tk.BooleanVar(value=False)
        self.scope_network = tk.BooleanVar(value=False)
        self.scope_output = tk.BooleanVar(value=False)
        self._build()
        self.window.protocol("WM_DELETE_WINDOW", self._close)
        self.window.after(100, self._poll_events)

    def _build(self):
        outer = ttk.Frame(self.window, padding=12)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)

        ttk.Label(
            outer,
            text="Phase 1：预检查 → 计划 → 批准 → 执行 → 验证 → 审计",
            style="Title.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            outer,
            text="本窗口使用当前主界面参数。Origin尚未接入独立白名单适配器时会显式降级，不影响本地报告。",
            style="Hint.TLabel",
            wraplength=820,
        ).grid(row=1, column=0, sticky="w", pady=(3, 8))

        plan_box = ttk.LabelFrame(outer, text="分析计划与状态", padding=8)
        plan_box.grid(row=2, column=0, sticky="nsew")
        plan_box.columnconfigure(0, weight=1)
        plan_box.rowconfigure(0, weight=1)
        self.plan_text = tk.Text(plan_box, wrap="word", state="disabled", font=("Consolas", 9))
        scroll = ttk.Scrollbar(plan_box, orient="vertical", command=self.plan_text.yview)
        self.plan_text.configure(yscrollcommand=scroll.set)
        self.plan_text.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")

        approval = ttk.LabelFrame(outer, text="人工批准范围", padding=8)
        approval.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        ttk.Checkbutton(approval, text="批准本地分析", variable=self.scope_local).grid(row=0, column=0, padx=(0, 16), sticky="w")
        self.network_check = ttk.Checkbutton(approval, text="批准联网检索", variable=self.scope_network)
        self.network_check.grid(row=0, column=1, padx=(0, 16), sticky="w")
        ttk.Checkbutton(approval, text="批准正式输出", variable=self.scope_output).grid(row=0, column=2, sticky="w")

        controls = ttk.Frame(outer)
        controls.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        self.prepare_button = ttk.Button(controls, text="1. 生成计划", command=self.generate_plan)
        self.prepare_button.grid(row=0, column=0, padx=(0, 6))
        self.approve_button = ttk.Button(controls, text="2. 批准计划", command=self.grant_approval, state="disabled")
        self.approve_button.grid(row=0, column=1, padx=6)
        self.execute_button = ttk.Button(controls, text="3. 受控执行", command=self.execute, state="disabled")
        self.execute_button.grid(row=0, column=2, padx=6)
        self.cancel_button = ttk.Button(controls, text="取消", command=self.cancel, state="disabled")
        self.cancel_button.grid(row=0, column=3, padx=6)
        self.audit_button = ttk.Button(controls, text="打开审计目录", command=self.open_audit, state="disabled")
        self.audit_button.grid(row=0, column=4, padx=6)
        controls.columnconfigure(5, weight=1)
        ttk.Label(controls, textvariable=self.status).grid(row=0, column=5, sticky="e")

    def _replace_plan_text(self, text):
        self.plan_text.configure(state="normal")
        self.plan_text.delete("1.0", "end")
        self.plan_text.insert("1.0", text)
        self.plan_text.configure(state="disabled")

    def generate_plan(self):
        if self.busy:
            return
        try:
            prepared = self.controller.prepare(self.values)
        except Exception as error:
            messagebox.showerror("无法生成计划", "{}: {}".format(type(error).__name__, error), parent=self.window)
            return
        self._replace_plan_text(format_plan(prepared))
        self.scope_local.set(False)
        self.scope_network.set(False)
        self.scope_output.set(False)
        if prepared.blocked:
            self.status.set("BLOCKED：请修正输入")
            self.approve_button.configure(state="disabled")
            self.execute_button.configure(state="disabled")
            self.audit_button.configure(state="disabled")
            return
        self.status.set("AWAITING_APPROVAL")
        self.approve_button.configure(state="normal")
        self.execute_button.configure(state="disabled")
        self.audit_button.configure(state="normal")
        if prepared.plan.network_enabled:
            self.network_check.configure(state="normal")
        else:
            self.network_check.configure(state="disabled")

    def grant_approval(self):
        scopes = []
        if self.scope_local.get():
            scopes.append("local_analysis")
        if self.scope_network.get():
            scopes.append("network_access")
        if self.scope_output.get():
            scopes.append("formal_output")
        try:
            record = self.controller.approve(scopes)
        except (ApprovalError, ApprovalRequired, ValueError) as error:
            messagebox.showerror("批准无效", str(error), parent=self.window)
            return
        self.status.set("已批准：{}".format(", ".join(record.scopes)))
        self.execute_button.configure(state="normal")
        self.approve_button.configure(state="disabled")

    def execute(self):
        if self.busy:
            return
        try:
            if self.controller.approval is None:
                raise ApprovalRequired("必须先批准当前计划。")
        except ApprovalRequired as error:
            messagebox.showerror("不能执行", str(error), parent=self.window)
            return
        self.busy = True
        self.status.set("RUNNING")
        self.prepare_button.configure(state="disabled")
        self.execute_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        threading.Thread(target=self._execute_worker, daemon=True).start()

    def _execute_worker(self):
        try:
            self.events.put(("done", self.controller.execute()))
        except Exception as error:
            self.events.put(("error", "{}: {}".format(type(error).__name__, error)))

    def _poll_events(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                self.busy = False
                self.prepare_button.configure(state="normal")
                self.cancel_button.configure(state="disabled")
                if kind == "error":
                    self.status.set("FAILED")
                    messagebox.showerror("受控执行失败", value, parent=self.window)
                    continue
                result = value
                self.status.set(result.state.value.upper())
                self.audit_button.configure(state="normal")
                details = format_plan(self.controller.preparation)
                details += "\n\n最终状态：{}\n运行目录：{}".format(result.state.value, result.run_dir)
                if result.degradations:
                    details += "\n降级：\n" + "\n".join(
                        "- {}: {}".format(item.tool_id, item.reason) for item in result.degradations
                    )
                if result.validation is not None:
                    details += "\n验证：{}；核心结果哈希：{}".format(
                        "通过" if result.validation.valid else "失败",
                        result.validation.core_results_hash,
                    )
                self._replace_plan_text(details)
        except queue.Empty:
            pass
        if self.window.winfo_exists():
            self.window.after(100, self._poll_events)

    def notify_form_changed(self, values):
        self.values = dict(values)
        if self.controller.invalidate_if_changed(self.values):
            self.execute_button.configure(state="disabled")
            self.approve_button.configure(state="disabled")
            self.status.set("计划已改变：旧批准失效，请重新生成")

    def cancel(self):
        if not self.busy:
            return
        self.controller.cancel()
        self.status.set("已请求取消，等待工具检查点")

    def open_audit(self):
        prepared = self.controller.preparation
        if prepared is None or prepared.run_dir is None or not prepared.run_dir.is_dir():
            messagebox.showwarning("审计目录不存在", "请先生成分析计划。", parent=self.window)
            return
        os.startfile(str(prepared.run_dir.resolve()))

    def _close(self):
        if self.busy:
            self.controller.cancel("关闭Phase 1演示窗口")
        self.window.destroy()


class ElectrochemApp:
    def __init__(self, root, project_root):
        self.root = root
        self.project_root = Path(project_root).resolve()
        self.process = None
        self.events = queue.Queue()
        self.busy = False
        self.task_kind = None
        self.phase1_dialog = None
        self.variables = {
            "input_file": tk.StringVar(),
            "output_dir": tk.StringVar(),
            "origin_exe": tk.StringVar(),
            "search_literature": tk.BooleanVar(value=True),
            "use_origin": tk.BooleanVar(value=True),
            "max_literature": tk.IntVar(value=50),
        }
        for name, _, _ in METADATA_FIELDS:
            self.variables[name] = tk.StringVar()
        self.status = tk.StringVar(value="就绪")
        self._configure_window()
        self._build_widgets()
        for variable in self.variables.values():
            variable.trace_add("write", self._notify_phase1_form_changed)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.bind("<Destroy>", self._on_root_destroy, add="+")
        self.poll_id = self.root.after(100, self._poll_events)

    def _configure_window(self):
        self.root.title("ElectrochemHarness v0.6.0-rc1 — 电化学数据分析")
        self.root.geometry("980x820")
        self.root.minsize(820, 680)
        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 16, "bold"))
        style.configure("Hint.TLabel", foreground="#555555")

    def _build_widgets(self):
        outer = ttk.Frame(self.root, padding=14)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(3, weight=1)

        ttk.Label(outer, text="电化学智能实验 Harness", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            outer,
            text="本地读取蓝电文本数据；原始文件不会上传。推荐使用「六步受控分析」：先看计划、再批准、失败可重跑。",
            style="Hint.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 10))

        form = ttk.Frame(outer)
        form.grid(row=2, column=0, sticky="nsew")
        form.columnconfigure(0, weight=1)
        form.columnconfigure(1, weight=1)

        data_box = ttk.LabelFrame(form, text="1. 数据与输出", padding=10)
        data_box.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        data_box.columnconfigure(1, weight=1)
        self._path_row(data_box, 0, "蓝电文件", "input_file", self._choose_input)
        self._path_row(data_box, 1, "输出目录", "output_dir", self._choose_output)

        metadata_box = ttk.LabelFrame(form, text="2. 实验条件", padding=10)
        metadata_box.grid(row=1, column=0, sticky="nsew", padx=(0, 4), pady=(0, 8))
        metadata_box.columnconfigure(1, weight=1)
        for row, (name, label, hint) in enumerate(METADATA_FIELDS):
            ttk.Label(metadata_box, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=3)
            entry = ttk.Entry(metadata_box, textvariable=self.variables[name])
            entry.grid(row=row, column=1, sticky="ew", pady=3)
            entry.insert(0, "")
            ttk.Label(metadata_box, text=hint, style="Hint.TLabel").grid(row=row, column=2, sticky="w", padx=(8, 0), pady=3)

        options_box = ttk.LabelFrame(form, text="3. 分析选项", padding=10)
        options_box.grid(row=1, column=1, sticky="nsew", padx=(4, 0), pady=(0, 8))
        options_box.columnconfigure(1, weight=1)
        ttk.Checkbutton(
            options_box,
            text="联网检索并核验文献 DOI",
            variable=self.variables["search_literature"],
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=3)
        ttk.Label(options_box, text="最多核验 DOI").grid(row=1, column=0, sticky="w", pady=3)
        tk.Spinbox(
            options_box,
            from_=1,
            to=200,
            width=8,
            textvariable=self.variables["max_literature"],
        ).grid(row=1, column=1, sticky="w", pady=3)
        ttk.Checkbutton(
            options_box,
            text="调用 Origin 生成工程和图片",
            variable=self.variables["use_origin"],
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(10, 3))
        ttk.Label(options_box, text="Origin64.exe（可留空自动查找）").grid(row=3, column=0, columnspan=3, sticky="w")
        origin_row = ttk.Frame(options_box)
        origin_row.grid(row=4, column=0, columnspan=3, sticky="ew", pady=3)
        origin_row.columnconfigure(0, weight=1)
        ttk.Entry(origin_row, textvariable=self.variables["origin_exe"]).grid(row=0, column=0, sticky="ew")
        ttk.Button(origin_row, text="浏览…", command=self._choose_origin).grid(row=0, column=1, padx=(6, 0))
        ttk.Label(
            options_box,
            text="没有 Origin 时取消勾选；报告、文献证据和绘图 CSV 仍会生成。",
            style="Hint.TLabel",
            wraplength=330,
        ).grid(row=5, column=0, columnspan=3, sticky="w", pady=(8, 0))

        log_box = ttk.LabelFrame(outer, text="运行日志", padding=8)
        log_box.grid(row=3, column=0, sticky="nsew")
        log_box.columnconfigure(0, weight=1)
        log_box.rowconfigure(0, weight=1)
        self.log = tk.Text(log_box, height=12, wrap="word", state="disabled", font=("Consolas", 9))
        scroll = ttk.Scrollbar(log_box, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        self.log.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")

        controls = ttk.Frame(outer)
        controls.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        controls.columnconfigure(7, weight=1)
        self.six_step_button = ttk.Button(
            controls, text="六步受控分析", command=self.open_six_step
        )
        self.six_step_button.grid(row=0, column=0, padx=(0, 6))
        self.check_button = ttk.Button(controls, text="检查环境", command=self.check_environment)
        self.check_button.grid(row=0, column=1, padx=6)
        self.run_button = ttk.Button(controls, text="开始分析", command=self.run_analysis)
        self.run_button.grid(row=0, column=2, padx=6)
        self.phase1_button = ttk.Button(controls, text="Phase 1受控演示", command=self.open_phase1_demo)
        self.phase1_button.grid(row=0, column=3, padx=6)
        self.cancel_button = ttk.Button(controls, text="取消任务", command=self.cancel_task, state="disabled")
        self.cancel_button.grid(row=0, column=4, padx=6)
        self.open_button = ttk.Button(controls, text="打开结果目录", command=self.open_output)
        self.open_button.grid(row=0, column=5, padx=6)
        self.knowledge_button = ttk.Button(
            controls, text="编辑文献知识库", command=self.open_knowledge
        )
        self.knowledge_button.grid(row=0, column=6, padx=6)
        self.progress = ttk.Progressbar(controls, mode="indeterminate", length=120)
        self.progress.grid(row=0, column=7, sticky="e", padx=(12, 8))
        ttk.Label(controls, textvariable=self.status).grid(row=0, column=8, sticky="e")

    def _path_row(self, parent, row, label, variable, callback):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(parent, textvariable=self.variables[variable]).grid(row=row, column=1, sticky="ew", pady=4)
        ttk.Button(parent, text="浏览…", command=callback).grid(row=row, column=2, padx=(6, 0), pady=4)

    def _choose_input(self):
        selected = filedialog.askopenfilename(
            title="选择蓝电文本导出",
            filetypes=[
                ("蓝电文本数据", "*.csv *.txt *.tsv *.dat"),
                ("CSV", "*.csv"),
                ("所有文件", "*.*"),
            ],
        )
        if selected:
            self.variables["input_file"].set(selected)
            if not self.variables["output_dir"].get().strip():
                source = Path(selected)
                self.variables["output_dir"].set(str(source.parent / (source.stem + "_SCI")))

    def _choose_output(self):
        selected = filedialog.askdirectory(title="选择分析结果目录")
        if selected:
            self.variables["output_dir"].set(selected)

    def _choose_origin(self):
        selected = filedialog.askopenfilename(
            title="选择 Origin64.exe",
            filetypes=[("Origin executable", "Origin64.exe"), ("Executable", "*.exe")],
        )
        if selected:
            self.variables["origin_exe"].set(selected)

    def _values(self):
        values = {name: variable.get() for name, variable in self.variables.items()}
        return values

    def _append_log(self, message):
        self.log.configure(state="normal")
        self.log.insert("end", message.rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _set_busy(self, busy, label=""):
        self.busy = busy
        self.run_button.configure(state="disabled" if busy else "normal")
        self.check_button.configure(state="disabled" if busy else "normal")
        self.cancel_button.configure(state="normal" if busy else "disabled")
        if busy:
            self.progress.start(12)
            self.status.set(label or "运行中")
        else:
            self.progress.stop()

    def _start_command(self, command, kind):
        if self.busy:
            return
        self.task_kind = kind
        self._append_log("\n> " + subprocess.list2cmdline(command))
        self._set_busy(True, "环境检查中" if kind == "check" else "分析中")
        threading.Thread(target=self._worker, args=(command,), daemon=True).start()

    def _worker(self, command):
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            self.process = subprocess.Popen(
                command,
                cwd=str(self.project_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding=locale.getpreferredencoding(False),
                errors="replace",
                creationflags=flags,
            )
            if self.process.stdout:
                for line in self.process.stdout:
                    self.events.put(("line", line.rstrip()))
            code = self.process.wait()
            self.events.put(("done", code))
        except Exception as error:
            self.events.put(("error", "{}: {}".format(type(error).__name__, error)))
        finally:
            self.process = None

    def _poll_events(self):
        try:
            while True:
                event, value = self.events.get_nowait()
                if event == "line":
                    self._append_log(value)
                elif event == "done":
                    self._finish(int(value))
                elif event == "error":
                    self._append_log("ERROR: " + value)
                    self._set_busy(False)
                    self.status.set("运行失败")
                    messagebox.showerror("运行失败", value)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_events)

    def _finish(self, exit_code):
        self._set_busy(False)
        if exit_code == 0:
            self.status.set("检查完成" if self.task_kind == "check" else "分析完成")
            self._append_log("任务完成。")
            if self.task_kind == "analysis":
                messagebox.showinfo("分析完成", "报告和图形输出已生成。")
        else:
            self.status.set("任务失败")
            self._append_log("任务失败，退出码：{}".format(exit_code))
            messagebox.showerror("任务失败", "请查看运行日志。退出码：{}".format(exit_code))

    def check_environment(self):
        command = [
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(self.project_root / "check_environment.ps1"),
        ]
        origin = self.variables["origin_exe"].get().strip()
        if origin:
            command.extend(["-OriginExe", origin])
        if self.variables["use_origin"].get():
            command.append("-RequireOrigin")
        self._start_command(command, "check")

    def run_analysis(self):
        values = self._values()
        errors = validate_form(values)
        if errors:
            messagebox.showerror("请完善输入", "\n".join("• " + error for error in errors))
            return
        command = build_workflow_command(self.project_root, values)
        self._start_command(command, "analysis")

    def open_six_step(self):
        """Open the production six-step flow with the current form values."""

        from .gui_six_step import SixStepDialog

        dialog = getattr(self, "six_step_dialog", None)
        if dialog is not None and getattr(dialog, "winfo_exists", lambda: 0)():
            dialog.lift()
            dialog.focus_force()
            return
        self.six_step_dialog = SixStepDialog(self.root, self.project_root, self._values())

    def open_phase1_demo(self):
        dialog = self.phase1_dialog
        if dialog is not None and getattr(dialog, "window", None) is not None:
            try:
                if dialog.window.winfo_exists():
                    dialog.window.lift()
                    dialog.window.focus_force()
                    return
            except tk.TclError:
                pass
        self.phase1_dialog = Phase1Dialog(self.root, self.project_root, self._values())

    def _notify_phase1_form_changed(self, *_):
        dialog = self.phase1_dialog
        if dialog is None:
            return
        try:
            if dialog.window.winfo_exists():
                dialog.notify_form_changed(self._values())
        except (AttributeError, tk.TclError):
            self.phase1_dialog = None

    def _terminate_process(self):
        process = self.process
        if process is None or process.poll() is not None:
            return
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=False,
            )
            self._append_log("已请求终止当前任务。")
        except Exception as error:
            self._append_log("取消失败：{}".format(error))

    def cancel_task(self):
        process = self.process
        if process is None or process.poll() is not None:
            return
        if not messagebox.askyesno("取消任务", "确定终止当前任务吗？部分输出文件可能已生成。"):
            return
        self._terminate_process()

    def open_knowledge(self):
        from .markdown_knowledge import MarkdownLiteratureKnowledgeStore

        target = MarkdownLiteratureKnowledgeStore(
            self.project_root / "knowledge" / "literature_knowledge.md"
        ).ensure_exists()
        os.startfile(str(target.resolve()))

    def open_output(self):
        target = self.variables["output_dir"].get().strip()
        if not target or not Path(target).is_dir():
            messagebox.showwarning("目录不存在", "分析结果目录尚未生成。")
            return
        os.startfile(str(Path(target).resolve()))

    def _on_root_destroy(self, event=None):
        if event is None or event.widget is self.root:
            self._cancel_polling()

    def _cancel_polling(self):
        poll_id = getattr(self, "poll_id", None)
        if poll_id is not None:
            try:
                self.root.after_cancel(poll_id)
            except tk.TclError:
                pass
            self.poll_id = None

    def _on_close(self):
        if self.busy and not messagebox.askyesno("退出", "任务仍在运行。是否终止任务并退出？"):
            return
        if self.busy:
            self._terminate_process()
        self.root.destroy()


def smoke_test(project_root):
    root = tk.Tk()
    root.withdraw()
    app = ElectrochemApp(root, project_root)
    root.update_idletasks()
    app._cancel_polling()
    root.destroy()


def main(project_root):
    root = tk.Tk()
    ElectrochemApp(root, project_root)
    root.mainloop()
