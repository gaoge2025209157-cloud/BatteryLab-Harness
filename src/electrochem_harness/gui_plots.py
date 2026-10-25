"""Tk dialog for the literature-aligned electrochemical plot catalog."""

import os
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .electrochemical_plots import PLOT_SPECS, PlotDataError, create_electrochemical_plot


class ElectrochemicalPlotDialog(tk.Toplevel):
    def __init__(self, parent, project_root, initial_plot_type="rate_capability"):
        super().__init__(parent)
        self.project_root = Path(project_root).resolve()
        self.plot_ids = tuple(PLOT_SPECS)
        if initial_plot_type not in PLOT_SPECS:
            initial_plot_type = self.plot_ids[0]
        self.label_to_id = {spec.label: key for key, spec in PLOT_SPECS.items()}
        self.plot_type = tk.StringVar(value=PLOT_SPECS[initial_plot_type].label)
        self.input_file = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.status = tk.StringVar(value="请选择图型和数据文件")
        self.title("常规电化学性能图谱")
        self.geometry("820x560")
        self.minsize(720, 500)
        self.transient(parent)
        self._build()
        self._update_spec()

    def _build(self):
        outer = ttk.Frame(self, padding=16)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(5, weight=1)

        ttk.Label(outer, text="常规电化学性能图谱", style="Title.TLabel").grid(
            row=0, column=0, columnspan=3, sticky="w"
        )
        ttk.Label(
            outer,
            text="从CSV/TXT/TSV/DAT读取数据，自动识别常见中英文列名和单位，输出Nature风格可编辑SVG及绘图审计JSON。",
            style="Hint.TLabel",
            wraplength=770,
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(3, 12))

        ttk.Label(outer, text="图型").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=4)
        chooser = ttk.Combobox(
            outer,
            textvariable=self.plot_type,
            values=[spec.label for spec in PLOT_SPECS.values()],
            state="readonly",
        )
        chooser.grid(row=2, column=1, columnspan=2, sticky="ew", pady=4)
        chooser.bind("<<ComboboxSelected>>", lambda _event: self._update_spec())

        ttk.Label(outer, text="数据文件").grid(row=3, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(outer, textvariable=self.input_file).grid(row=3, column=1, sticky="ew", pady=4)
        ttk.Button(outer, text="浏览…", command=self._choose_input).grid(row=3, column=2, padx=(6, 0), pady=4)

        ttk.Label(outer, text="输出目录").grid(row=4, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(outer, textvariable=self.output_dir).grid(row=4, column=1, sticky="ew", pady=4)
        ttk.Button(outer, text="浏览…", command=self._choose_output).grid(row=4, column=2, padx=(6, 0), pady=4)

        info = ttk.LabelFrame(outer, text="该图需要什么数据、能回答什么", padding=10)
        info.grid(row=5, column=0, columnspan=3, sticky="nsew", pady=(10, 0))
        info.columnconfigure(0, weight=1)
        info.rowconfigure(0, weight=1)
        self.spec_text = tk.Text(
            info,
            wrap="word",
            state="disabled",
            font=("Microsoft YaHei UI", 10),
            padx=8,
            pady=8,
            height=14,
        )
        self.spec_text.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(info, orient="vertical", command=self.spec_text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.spec_text.configure(yscrollcommand=scroll.set)

        controls = ttk.Frame(outer)
        controls.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        ttk.Button(controls, text="生成图像", command=self.create_plot, style="Accent.TButton").grid(row=0, column=0)
        ttk.Button(controls, text="关闭", command=self.destroy).grid(row=0, column=1, padx=8)
        controls.columnconfigure(2, weight=1)
        ttk.Label(controls, textvariable=self.status, style="Hint.TLabel").grid(row=0, column=3, sticky="e")

    def _selected_id(self):
        return self.label_to_id[self.plot_type.get()]

    def _update_spec(self):
        spec = PLOT_SPECS[self._selected_id()]
        body = (
            "标准列名\n"
            + "、".join(spec.required_columns)
            + "\n\n科学问题\n"
            + spec.scientific_question
            + "\n\n解释边界\n"
            + spec.limitations
            + "\n\n方法依据 DOI\n"
            + "\n".join(spec.reference_dois)
            + "\n\n单位规则\n"
            + "程序根据表头自动换算A→mA、mV→V、min/h→s、kΩ→Ω、K→°C和mS/cm→S/cm；原始表头与换算结果写入审计JSON。"
        )
        self.spec_text.configure(state="normal")
        self.spec_text.delete("1.0", "end")
        self.spec_text.insert("1.0", body)
        self.spec_text.configure(state="disabled")

    def _choose_input(self):
        selected = filedialog.askopenfilename(
            title="选择电化学绘图数据",
            filetypes=[("文本数据", "*.csv *.txt *.tsv *.dat"), ("所有文件", "*.*")],
        )
        if selected:
            self.input_file.set(selected)
            if not self.output_dir.get().strip():
                self.output_dir.set(str(Path(selected).parent / (Path(selected).stem + "_plots")))

    def _choose_output(self):
        selected = filedialog.askdirectory(title="选择图像输出目录")
        if selected:
            self.output_dir.set(selected)

    def create_plot(self):
        source = Path(self.input_file.get().strip())
        output = self.output_dir.get().strip()
        if not source.is_file():
            messagebox.showerror("缺少数据", "请选择存在的数据文件。", parent=self)
            return
        if not output:
            messagebox.showerror("缺少输出目录", "请选择输出目录。", parent=self)
            return
        try:
            result = create_electrochemical_plot(self._selected_id(), source, Path(output))
        except (OSError, UnicodeError, PlotDataError, ValueError) as error:
            messagebox.showerror("无法生成图像", str(error), parent=self)
            return
        self.status.set("已生成：{}个绘图点".format(result.point_count))
        messagebox.showinfo(
            "图像已生成",
            "SVG：{}\n审计记录：{}".format(result.svg_path, result.audit_path),
            parent=self,
        )
        if os.name == "nt":
            os.startfile(str(result.svg_path))
