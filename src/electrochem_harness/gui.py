"""Local Tkinter interface for the electrochemical workflow."""

import locale
import os
from pathlib import Path
import queue
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


UNKNOWN_VALUES = {"", "待填", "未知", "unknown", "n/a", "na", "???"}
METADATA_FIELDS = (
    ("battery_system", "电池体系", "例如：锂硫电池 / lithium-sulfur battery"),
    ("active_material", "活性物质", "例如：S/C复合正极、LiFePO4"),
    ("cell_type", "电池类型", "例如：半电池、全电池、对称电池"),
    ("counter_electrode", "对电极/另一电极", "例如：Li、Na、NMC811"),
    ("test_current", "测试电流/倍率", "例如：100 mA g-1、0.1 C"),
    ("temperature", "测试温度", "例如：25 C、60 C"),
    ("normalization_basis", "质量归一化口径", "例如：硫质量、正极活性物质质量"),
)
CLI_FIELD_FLAGS = {
    "battery_system": "-BatterySystem",
    "active_material": "-ActiveMaterial",
    "cell_type": "-CellType",
    "counter_electrode": "-CounterElectrode",
    "test_current": "-TestCurrent",
    "temperature": "-Temperature",
    "normalization_basis": "-NormalizationBasis",
}
SUPPORTED_EXTENSIONS = {".csv", ".txt", ".tsv", ".dat"}


def _missing(value):
    return str(value or "").strip().casefold() in UNKNOWN_VALUES


def validate_form(values):
    """Return user-facing validation errors without touching the filesystem."""
    errors = []
    source_text = str(values.get("input_file", "")).strip()
    if not source_text or not Path(source_text).is_file():
        errors.append("请选择存在的蓝电输入文件。")
    elif Path(source_text).suffix.lower() not in SUPPORTED_EXTENSIONS:
        errors.append("输入文件必须是 CSV、TXT、TSV 或 DAT 文本导出。")
    if not str(values.get("output_dir", "")).strip():
        errors.append("请选择输出目录。")
    if values.get("search_literature"):
        for name, label, _ in METADATA_FIELDS:
            if _missing(values.get(name)):
                errors.append("启用文献检索时必须填写：{}。".format(label))
    try:
        maximum = int(values.get("max_literature", 50))
        if maximum < 1 or maximum > 200:
            raise ValueError
    except (TypeError, ValueError):
        errors.append("候选 DOI 数量必须是 1–200 的整数。")
    origin_exe = str(values.get("origin_exe", "")).strip()
    if values.get("use_origin") and origin_exe and not Path(origin_exe).is_file():
        errors.append("指定的 Origin64.exe 不存在；可清空该项让程序自动查找。")
    return errors


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


class ElectrochemApp:
    def __init__(self, root, project_root):
        self.root = root
        self.project_root = Path(project_root).resolve()
        self.process = None
        self.events = queue.Queue()
        self.busy = False
        self.task_kind = None
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
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(100, self._poll_events)

    def _configure_window(self):
        self.root.title("ElectrochemHarness v0.3.0 — 电化学数据分析")
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
            text="本地读取蓝电文本数据；原始文件不会上传。只有实验检索条件会发送到 Crossref。",
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
        controls.columnconfigure(4, weight=1)
        self.check_button = ttk.Button(controls, text="检查环境", command=self.check_environment)
        self.check_button.grid(row=0, column=0, padx=(0, 6))
        self.run_button = ttk.Button(controls, text="开始分析", command=self.run_analysis)
        self.run_button.grid(row=0, column=1, padx=6)
        self.cancel_button = ttk.Button(controls, text="取消任务", command=self.cancel_task, state="disabled")
        self.cancel_button.grid(row=0, column=2, padx=6)
        self.open_button = ttk.Button(controls, text="打开结果目录", command=self.open_output)
        self.open_button.grid(row=0, column=3, padx=6)
        self.progress = ttk.Progressbar(controls, mode="indeterminate", length=180)
        self.progress.grid(row=0, column=4, sticky="e", padx=(12, 8))
        ttk.Label(controls, textvariable=self.status).grid(row=0, column=5, sticky="e")

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

    def open_output(self):
        target = self.variables["output_dir"].get().strip()
        if not target or not Path(target).is_dir():
            messagebox.showwarning("目录不存在", "分析结果目录尚未生成。")
            return
        os.startfile(str(Path(target).resolve()))

    def _on_close(self):
        if self.busy and not messagebox.askyesno("退出", "任务仍在运行。是否终止任务并退出？"):
            return
        if self.busy:
            self._terminate_process()
        self.root.destroy()


def smoke_test(project_root):
    root = tk.Tk()
    root.withdraw()
    ElectrochemApp(root, project_root)
    root.update_idletasks()
    root.destroy()


def main(project_root):
    root = tk.Tk()
    ElectrochemApp(root, project_root)
    root.mainloop()
