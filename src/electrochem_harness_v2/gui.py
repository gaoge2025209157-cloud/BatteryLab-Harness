"""Single-window Tk interface for the four-stage Harness-v2 workflow."""
from __future__ import annotations

import json
from pathlib import Path
import queue
import threading
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, ttk

from .workflow import ResearchWorkflow


class HarnessApp:
    def __init__(self, root: tk.Tk, project_root: Path | str):
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
        self.conditions = tk.StringVar(value="temperature_C=60")
        self.active_material_mass_mg = tk.StringVar()
        self.pdf_path = tk.StringVar()
        self.data_path = tk.StringVar()
        self.use_codex = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value="填写课题、选择数据和可选 PDF 后，单击一次自动完成流程。")
        self._events: queue.Queue = queue.Queue()
        self._running = False
        self._last_report: Path | None = None
        self._build()
        self.refresh_projects()

    def _build(self) -> None:
        self.root.title("ElectrochemHarness v2｜可审计科研闭环")
        self.root.geometry("1020x720")
        outer = ttk.Frame(self.root, padding=14)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(11, weight=1)
        ttk.Label(outer, text="ElectrochemHarness v2", font=("Microsoft YaHei UI", 18, "bold")).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(outer, text="①课题/数据  ②检索/知识  ③确定性分析/Origin  ④报告/指导", foreground="#38566f").grid(row=1, column=0, columnspan=3, sticky="w", pady=(2, 12))
        self._field(outer, 2, "课题名称", self.name)
        self._field(outer, 3, "课题类型（材料体系）", self.material)
        self._field(outer, 4, "关键词（分号）", self.keywords)
        self._field(outer, 5, "实验条件（key=value；分隔）", self.conditions)
        self._field(outer, 6, "活性物质质量（mg）", self.active_material_mass_mg)
        self._file_field(outer, 7, "本地 PDF（可选）", self.pdf_path, [("PDF", "*.pdf")])
        self._file_field(outer, 8, "实验数据", self.data_path, [("Data", "*.csv *.txt *.tsv *.dat")])
        controls = ttk.Frame(outer)
        controls.grid(row=9, column=0, columnspan=3, sticky="ew", pady=(8, 4))
        ttk.Button(controls, text="创建新课题", command=self.create_project).pack(side="left")
        ttk.Button(controls, text="打开选中课题", command=self.open_project).pack(side="left", padx=4)
        ttk.Button(controls, text="保存课题修改", command=self.save_project_changes).pack(side="left", padx=4)
        self.projects = ttk.Combobox(controls, width=42, state="readonly")
        self.projects.pack(side="left", padx=4)
        ttk.Button(controls, text="刷新课题", command=self.refresh_projects).pack(side="left", padx=4)
        ttk.Checkbutton(controls, text="允许 Codex 接收最小 PDF 证据片段", variable=self.use_codex).pack(side="right")
        actions = ttk.Frame(outer)
        actions.grid(row=10, column=0, columnspan=3, sticky="ew")
        self.auto_button = ttk.Button(actions, text="自动执行课题全流程", command=self.run_all_automatically)
        self.auto_button.pack(side="left")
        ttk.Button(actions, text="打开最近图文报告", command=self.open_latest_report).pack(side="left", padx=4)
        ttk.Button(actions, text="打开 Codex 工作记录", command=self.open_codex_activity).pack(side="left", padx=4)
        self.progress = ttk.Progressbar(actions, mode="determinate", maximum=9, length=250)
        self.progress.pack(side="right", padx=8)
        self.monitor = tk.Text(outer, height=10, wrap="word", state="disabled", padx=8, pady=8)
        self.monitor.grid(row=11, column=0, columnspan=3, sticky="nsew", pady=(8, 4))
        ttk.Label(outer, textvariable=self.status, foreground="#38566f").grid(row=12, column=0, columnspan=3, sticky="w")

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

    def create_project(self):
        try:
            self.project_id = self.workflow.create_project(self.name.get(), self.material.get(), self._keywords())
            self.status.set("已创建课题：{}".format(self.project_id))
            self.refresh_projects()
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
            if self.project_id is None:
                self.project_id = self.workflow.create_project(self.name.get(), self.material.get(), self._keywords())
                self.refresh_projects()
            project_id = self.project_id
            data_path = self.data_path.get()
            pdf_path = self.pdf_path.get() or None
            keywords = self._keywords()
            conditions = self._conditions()
            use_codex = bool(self.use_codex.get())
        except Exception as error:
            messagebox.showerror("无法启动自动流程", str(error), parent=self.root)
            return
        self._running = True
        self.progress["value"] = 0
        self.auto_button.configure(state="disabled")
        self._write_monitor("自动流程已启动。将依次执行检索、PDF 学习、Codex 候选、数据分析、主流基准研究、Codex 精选、Origin、Codex 评估和报告；Codex 检索主题、来源和判断会同步写入监视区与本轮记录。")

        def emit(stage, message, details):
            self._events.put(("progress", stage, message, details))

        def worker():
            try:
                result = self.workflow.run_all(
                    project_id, data_path, conditions, pdf_path=pdf_path, keywords=keywords,
                    use_codex_candidates=use_codex, use_codex_assessment=True,
                    progress=emit,
                )
                self._events.put(("done", result))
            except Exception as error:
                self._events.put(("error", str(error)))

        threading.Thread(target=worker, name="Harness-v2-automatic-run", daemon=True).start()
        self.root.after(100, self._poll_automatic_events)

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
                self.run_id = result["run"].run_id
                self._last_report = Path(result["report"])
                self.source_id = result["document"].source_id if result.get("document") else self.source_id
                self.status.set("自动流程结束：{}；错误/部分完成：{} 项。".format(result["report"].name, len(result["errors"])))
                self._write_monitor("自动流程完成。报告：{}".format(result["report"]))
                webbrowser.open_new_tab(self._last_report.resolve().as_uri())
                finished = True
            elif event[0] == "error":
                self.status.set("自动流程失败")
                self._write_monitor("自动流程失败：{}".format(event[1]))
                messagebox.showerror("自动流程失败", event[1], parent=self.root)
                finished = True
        if finished:
            self._running = False
            self.auto_button.configure(state="normal")
        else:
            self.root.after(100, self._poll_automatic_events)

    def _write_monitor(self, text):
        self.monitor.configure(state="normal")
        self.monitor.insert("end", text + "\n\n")
        self.monitor.see("end")
        self.monitor.configure(state="disabled")

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
            run = self.workflow.analyze_data(self.project_id, self.data_path.get(), self._conditions())
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
            result[key.strip()] = value.strip()
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
