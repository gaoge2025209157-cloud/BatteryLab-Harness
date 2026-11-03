"""Tkinter window for guided academic search and LLM-assisted knowledge drafts."""

import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .academic_search import (
    AcademicSearchRequest,
    build_advanced_search_plan,
    open_guided_search_pages,
    parse_concept_groups,
)
from .knowledge_assistant import (
    KnowledgeAssistantRequest,
    ResearchKnowledgeStore,
    knowledge_candidate_key,
    run_knowledge_assistant,
)
from .llm_provider import LLMConfig, OpenAICompatibleProvider


DATABASE_LABELS = (
    ("crossref", "Crossref（自动元数据）"),
    ("openalex", "OpenAlex（自动元数据/摘要）"),
    ("web_of_science", "Web of Science Advanced Search（浏览器）"),
    ("scopus", "Scopus Advanced Search（浏览器）"),
    ("cnki", "中国知网高级检索（浏览器）"),
    ("google_scholar", "Google Scholar（浏览器）"),
)


def _split_items(value: str):
    return tuple(
        item.strip()
        for raw in str(value or "").replace("；", ";").replace("，", ",").split(";")
        for item in raw.split(",")
        if item.strip()
    )


def _optional_int(value: str):
    value = str(value or "").strip()
    return int(value) if value else None


class KnowledgeAssistantDialog(tk.Toplevel):
    def __init__(self, parent, project_root, initial_data_file=""):
        super().__init__(parent)
        self.project_root = Path(project_root).resolve()
        self.plan = None
        self.result = None
        self.busy = False
        self.events = queue.Queue()
        self.poll_id = None
        self.title("LLM文献知识助手")
        self.geometry("1080x820")
        self.minsize(900, 700)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._init_variables(initial_data_file)
        self._build()
        self.poll_id = self.after(120, self._poll_events)

    def _init_variables(self, initial_data_file):
        current_year = "2026"
        self.variables = {
            "domain": tk.StringVar(value="卤化物固态电解质"),
            "exact_phrases": tk.StringVar(),
            "exclusions": tk.StringVar(),
            "year_from": tk.StringVar(value="2018"),
            "year_to": tk.StringVar(value=current_year),
            "max_results": tk.IntVar(value=5),
            "max_documents": tk.IntVar(value=5),
            "local_fulltext_dir": tk.StringVar(),
            "data_file": tk.StringVar(value=str(initial_data_file or "")),
            "auto_fetch_publisher_html": tk.BooleanVar(value=False),
            "llm_base_url": tk.StringVar(value=os.environ.get("ELECTROCHEM_LLM_BASE_URL", "")),
            "llm_model": tk.StringVar(value=os.environ.get("ELECTROCHEM_LLM_MODEL", "")),
            "api_key_env": tk.StringVar(value="ELECTROCHEM_LLM_API_KEY"),
            "max_tokens": tk.IntVar(value=5000),
            "max_evidence_chars": tk.IntVar(value=50000),
        }
        self.database_vars = {
            name: tk.BooleanVar(value=name in {"crossref", "openalex", "web_of_science", "scopus", "cnki"})
            for name, _ in DATABASE_LABELS
        }
        self.status = tk.StringVar(value="请先填写领域、科学问题和关键词组")

    def _build(self):
        outer = ttk.Frame(self, padding=12)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=1)

        ttk.Label(outer, text="LLM文献知识助手", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            outer,
            text="领域与问题 → 最多5篇高水平高相关论文 → 原文读取 → 背景/专业基础 → 参数逻辑 → 学习增量 → 人工批准",
            style="Hint.TLabel",
        ).grid(row=0, column=0, sticky="e")

        canvas = tk.Canvas(outer, highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        body = ttk.Frame(canvas)
        window_id = canvas.create_window((0, 0), window=body, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        scrollbar.grid(row=1, column=1, sticky="ns", pady=(10, 0))
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        body.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window_id, width=event.width))

        scope = ttk.LabelFrame(body, text="1. 要积累什么知识", padding=10)
        scope.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        scope.columnconfigure(1, weight=1)
        ttk.Label(scope, text="研究领域").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=3)
        ttk.Entry(scope, textvariable=self.variables["domain"]).grid(row=0, column=1, sticky="ew", pady=3)
        ttk.Label(scope, text="科学问题").grid(row=1, column=0, sticky="nw", padx=(0, 8), pady=3)
        self.question_text = tk.Text(scope, height=3, wrap="word")
        self.question_text.grid(row=1, column=1, sticky="ew", pady=3)
        ttk.Label(scope, text="关键词组").grid(row=2, column=0, sticky="nw", padx=(0, 8), pady=3)
        self.concepts_text = tk.Text(scope, height=4, wrap="word")
        self.concepts_text.grid(row=2, column=1, sticky="ew", pady=3)
        self.concepts_text.insert(
            "1.0",
            "halide solid electrolyte | chloride electrolyte\ninterface stability | interfacial reaction",
        )
        ttk.Label(
            scope,
            text="每行/分号表示AND概念组，组内用 | 表示OR同义词。例：halide electrolyte | chloride electrolyte",
            style="Hint.TLabel",
        ).grid(row=3, column=1, sticky="w")
        ttk.Label(scope, text="精确短语").grid(row=4, column=0, sticky="w", padx=(0, 8), pady=3)
        ttk.Entry(scope, textvariable=self.variables["exact_phrases"]).grid(row=4, column=1, sticky="ew", pady=3)
        ttk.Label(scope, text="排除词").grid(row=5, column=0, sticky="w", padx=(0, 8), pady=3)
        ttk.Entry(scope, textvariable=self.variables["exclusions"]).grid(row=5, column=1, sticky="ew", pady=3)

        search_box = ttk.LabelFrame(body, text="2. 数据库与高级检索", padding=10)
        search_box.grid(row=1, column=0, sticky="nsew", padx=(0, 4), pady=(0, 8))
        for row, (name, label) in enumerate(DATABASE_LABELS):
            ttk.Checkbutton(search_box, text=label, variable=self.database_vars[name]).grid(row=row, column=0, columnspan=4, sticky="w", pady=2)
        ttk.Label(search_box, text="年份").grid(row=6, column=0, sticky="w", pady=(8, 3))
        ttk.Entry(search_box, textvariable=self.variables["year_from"], width=8).grid(row=6, column=1, sticky="w", pady=(8, 3))
        ttk.Label(search_box, text="至").grid(row=6, column=2, sticky="w", pady=(8, 3))
        ttk.Entry(search_box, textvariable=self.variables["year_to"], width=8).grid(row=6, column=3, sticky="w", pady=(8, 3))
        ttk.Label(search_box, text="本轮学习论文上限").grid(row=7, column=0, sticky="w", pady=3)
        tk.Spinbox(search_box, from_=1, to=5, textvariable=self.variables["max_results"], width=8).grid(row=7, column=1, sticky="w", pady=3)
        ttk.Button(search_box, text="生成高级检索式", command=self.generate_search_plan).grid(row=8, column=0, columnspan=2, sticky="ew", pady=(10, 3), padx=(0, 3))
        ttk.Button(search_box, text="打开校园网数据库", command=self.open_database_pages).grid(row=8, column=2, columnspan=2, sticky="ew", pady=(10, 3), padx=(3, 0))

        evidence = ttk.LabelFrame(body, text="3. 全文与我的数据", padding=10)
        evidence.grid(row=1, column=1, sticky="nsew", padx=(4, 0), pady=(0, 8))
        evidence.columnconfigure(1, weight=1)
        ttk.Label(evidence, text="本地全文目录").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=3)
        ttk.Entry(evidence, textvariable=self.variables["local_fulltext_dir"]).grid(row=0, column=1, sticky="ew", pady=3)
        ttk.Button(evidence, text="浏览…", command=self._choose_fulltext_dir).grid(row=0, column=2, padx=(6, 0), pady=3)
        ttk.Label(evidence, text="数据/报告文件").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=3)
        ttk.Entry(evidence, textvariable=self.variables["data_file"]).grid(row=1, column=1, sticky="ew", pady=3)
        ttk.Button(evidence, text="浏览…", command=self._choose_data_file).grid(row=1, column=2, padx=(6, 0), pady=3)
        ttk.Checkbutton(
            evidence,
            text="尝试通过当前校园网直接读取DOI出版商HTML（不使用浏览器Cookie）",
            variable=self.variables["auto_fetch_publisher_html"],
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(8, 3))
        ttk.Label(evidence, text="最多原文（≤5）").grid(row=3, column=0, sticky="w", pady=3)
        tk.Spinbox(evidence, from_=1, to=5, textvariable=self.variables["max_documents"], width=8).grid(row=3, column=1, sticky="w", pady=3)
        ttk.Label(
            evidence,
            text="只学习与高水平高相关候选匹配的原文。摘要不写库；PDF需可提取文本并含DOI或可匹配题名。",
            style="Hint.TLabel",
            wraplength=430,
        ).grid(row=4, column=0, columnspan=3, sticky="w", pady=(8, 0))

        llm = ttk.LabelFrame(body, text="4. 大模型接口（密钥只读环境变量）", padding=10)
        llm.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        llm.columnconfigure(1, weight=1)
        ttk.Label(llm, text="OpenAI兼容Base URL").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=3)
        ttk.Entry(llm, textvariable=self.variables["llm_base_url"]).grid(row=0, column=1, sticky="ew", pady=3)
        ttk.Label(llm, text="模型ID").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=3)
        ttk.Entry(llm, textvariable=self.variables["llm_model"]).grid(row=1, column=1, sticky="ew", pady=3)
        ttk.Label(llm, text="API Key环境变量").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=3)
        ttk.Entry(llm, textvariable=self.variables["api_key_env"]).grid(row=2, column=1, sticky="ew", pady=3)
        ttk.Label(llm, text="最大输出Token").grid(row=0, column=2, sticky="w", padx=(14, 6), pady=3)
        tk.Spinbox(llm, from_=256, to=32000, increment=256, textvariable=self.variables["max_tokens"], width=9).grid(row=0, column=3, sticky="w", pady=3)
        ttk.Label(llm, text="证据包字符上限").grid(row=1, column=2, sticky="w", padx=(14, 6), pady=3)
        tk.Spinbox(llm, from_=5000, to=150000, increment=5000, textvariable=self.variables["max_evidence_chars"], width=9).grid(row=1, column=3, sticky="w", pady=3)
        ttk.Label(
            llm,
            text="远程接口必须HTTPS；本地Ollama等可使用 http://127.0.0.1。CC-SWITCH 使用 http://127.0.0.1:15721/v1 时会自动切换 Responses 协议，真实上游密钥仍由 CC-SWITCH 保管。",
            style="Hint.TLabel",
        ).grid(row=3, column=0, columnspan=4, sticky="w", pady=(6, 0))

        output = ttk.LabelFrame(body, text="5. 实时研究工作台", padding=8)
        output.grid(row=3, column=0, columnspan=2, sticky="nsew")
        output.columnconfigure(0, weight=1)
        output.rowconfigure(0, weight=1)
        self.conclusion_notebook = ttk.Notebook(output)
        self.conclusion_notebook.grid(row=0, column=0, sticky="nsew")

        progress_page = ttk.Frame(self.conclusion_notebook, padding=6)
        progress_page.columnconfigure(0, weight=1)
        progress_page.rowconfigure(0, weight=1)
        self.progress_tree = ttk.Treeview(
            progress_page, columns=("state", "detail"), show="tree headings", height=10
        )
        self.progress_tree.heading("#0", text="阶段")
        self.progress_tree.heading("state", text="状态")
        self.progress_tree.heading("detail", text="实时信息")
        self.progress_tree.column("#0", width=150, anchor="w")
        self.progress_tree.column("state", width=80, anchor="center")
        self.progress_tree.column("detail", width=650, anchor="w")
        self.progress_tree.grid(row=0, column=0, sticky="nsew")
        progress_scroll = ttk.Scrollbar(progress_page, orient="vertical", command=self.progress_tree.yview)
        self.progress_tree.configure(yscrollcommand=progress_scroll.set)
        progress_scroll.grid(row=0, column=1, sticky="ns")
        self.conclusion_notebook.add(progress_page, text="实时过程")
        self.progress_nodes = {}
        for stage, label in (
            ("plan", "检索计划"),
            ("search", "文献检索"),
            ("fulltext", "全文与图表"),
            ("evidence", "证据包"),
            ("llm", "大模型整理"),
            ("knowledge", "本地知识库"),
            ("done", "完成"),
        ):
            self.progress_nodes[stage] = self.progress_tree.insert(
                "", "end", text=label, values=("等待", "")
            )

        summary_page = ttk.Frame(self.conclusion_notebook, padding=6)
        summary_page.columnconfigure(0, weight=1)
        summary_page.rowconfigure(0, weight=1)
        self.output_text = tk.Text(summary_page, height=15, wrap="word", state="disabled", font=("Microsoft YaHei UI", 10), padx=10, pady=8)
        output_scroll = ttk.Scrollbar(summary_page, orient="vertical", command=self.output_text.yview)
        self.output_text.configure(yscrollcommand=output_scroll.set)
        self.output_text.grid(row=0, column=0, sticky="nsew")
        output_scroll.grid(row=0, column=1, sticky="ns")
        self.conclusion_notebook.add(summary_page, text="结论总览")

        value_page = ttk.Frame(self.conclusion_notebook, padding=6)
        value_page.columnconfigure(0, weight=1)
        value_page.rowconfigure(0, weight=1)
        self.data_value_text = tk.Text(value_page, height=15, wrap="word", state="disabled", font=("Microsoft YaHei UI", 10), padx=10, pady=8)
        self.data_value_text.grid(row=0, column=0, sticky="nsew")
        self.conclusion_notebook.add(value_page, text="数据价值")

        next_page = ttk.Frame(self.conclusion_notebook, padding=6)
        next_page.columnconfigure(0, weight=1)
        next_page.rowconfigure(0, weight=1)
        self.next_work_text = tk.Text(next_page, height=15, wrap="word", state="disabled", font=("Microsoft YaHei UI", 10), padx=10, pady=8)
        self.next_work_text.grid(row=0, column=0, sticky="nsew")
        self.conclusion_notebook.add(next_page, text="补充实验与表征")

        review_page = ttk.Frame(self.conclusion_notebook, padding=6)
        review_page.columnconfigure(0, weight=1)
        review_page.rowconfigure(0, weight=1)
        self.knowledge_tree = ttk.Treeview(
            review_page, columns=("status", "confidence", "sources"), show="tree headings", height=9
        )
        self.knowledge_tree.heading("#0", text="候选知识")
        self.knowledge_tree.heading("status", text="状态")
        self.knowledge_tree.heading("confidence", text="置信度")
        self.knowledge_tree.heading("sources", text="来源")
        self.knowledge_tree.column("#0", width=610, anchor="w")
        self.knowledge_tree.column("status", width=90, anchor="center")
        self.knowledge_tree.column("confidence", width=90, anchor="center")
        self.knowledge_tree.column("sources", width=180, anchor="w")
        self.knowledge_tree.grid(row=0, column=0, sticky="nsew")
        review_scroll = ttk.Scrollbar(review_page, orient="vertical", command=self.knowledge_tree.yview)
        self.knowledge_tree.configure(yscrollcommand=review_scroll.set)
        review_scroll.grid(row=0, column=1, sticky="ns")
        review_actions = ttk.Frame(review_page)
        review_actions.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        ttk.Label(review_actions, text="人工备注").grid(row=0, column=0, padx=(0, 6))
        self.review_note = tk.StringVar()
        ttk.Entry(review_actions, textvariable=self.review_note).grid(row=0, column=1, sticky="ew")
        review_actions.columnconfigure(1, weight=1)
        self.approve_candidate_button = ttk.Button(
            review_actions, text="批准选中知识", command=self.approve_selected_candidate, state="disabled"
        )
        self.approve_candidate_button.grid(row=0, column=2, padx=6)
        self.reject_candidate_button = ttk.Button(
            review_actions, text="拒绝选中知识", command=self.reject_selected_candidate, state="disabled"
        )
        self.reject_candidate_button.grid(row=0, column=3)
        self.conclusion_notebook.add(review_page, text="知识审核")

        controls = ttk.Frame(outer)
        controls.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self.run_button = ttk.Button(controls, text="批准并运行知识助手", command=self.run_assistant)
        self.run_button.grid(row=0, column=0, padx=(0, 6))
        self.open_knowledge_button = ttk.Button(controls, text="打开研究知识库", command=self.open_knowledge)
        self.open_knowledge_button.grid(row=0, column=1, padx=6)
        self.open_run_button = ttk.Button(controls, text="打开本次运行目录", command=self.open_run_dir, state="disabled")
        self.open_run_button.grid(row=0, column=2, padx=6)
        controls.columnconfigure(3, weight=1)
        self.progress = ttk.Progressbar(controls, mode="indeterminate", length=150)
        self.progress.grid(row=0, column=3, sticky="e", padx=(8, 8))
        ttk.Label(controls, textvariable=self.status).grid(row=0, column=4, sticky="e")

    def _request(self):
        databases = tuple(name for name, variable in self.database_vars.items() if variable.get())
        search = AcademicSearchRequest(
            domain=self.variables["domain"].get(),
            research_question=self.question_text.get("1.0", "end").strip(),
            concept_groups=parse_concept_groups(self.concepts_text.get("1.0", "end")),
            exact_phrases=_split_items(self.variables["exact_phrases"].get()),
            exclusions=_split_items(self.variables["exclusions"].get()),
            year_from=_optional_int(self.variables["year_from"].get()),
            year_to=_optional_int(self.variables["year_to"].get()),
            databases=databases,
            max_results=int(self.variables["max_results"].get()),
        )
        local_dir = self.variables["local_fulltext_dir"].get().strip()
        data_file = self.variables["data_file"].get().strip()
        if local_dir and not Path(local_dir).is_dir():
            raise ValueError("本地全文目录不存在。")
        if data_file and not Path(data_file).is_file():
            raise ValueError("数据/报告文件不存在。")
        return KnowledgeAssistantRequest(
            search=search,
            local_fulltext_dir=local_dir,
            data_file=data_file,
            auto_fetch_publisher_html=bool(self.variables["auto_fetch_publisher_html"].get()),
            max_documents=int(self.variables["max_documents"].get()),
            max_evidence_chars=int(self.variables["max_evidence_chars"].get()),
        )

    def _replace_output(self, text):
        self._set_text(self.output_text, text)

    @staticmethod
    def _set_text(widget, text):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", str(text))
        widget.configure(state="disabled")

    def _reset_progress(self):
        for node in self.progress_nodes.values():
            self.progress_tree.item(node, values=("等待", ""))
        self.conclusion_notebook.select(0)

    def _update_progress(self, stage, message, details=None):
        node = self.progress_nodes.get(stage)
        if node is None:
            return
        suffix = ""
        if details:
            suffix = "；".join("{}={}".format(key, value) for key, value in details.items())
        self.progress_tree.item(node, values=("完成" if stage == "done" else "进行中", "{}{}".format(message, "；" + suffix if suffix else "")))
        self.progress_tree.see(node)

    @staticmethod
    def _format_objects(title, items, fields):
        lines = [title, ""]
        if not items:
            return "\n".join(lines + ["暂无可核验内容。"])
        for index, item in enumerate(items, 1):
            lines.append("{}. {}".format(index, item.get(fields[0][0], "")))
            for key, label in fields[1:]:
                value = item.get(key, "")
                if isinstance(value, list):
                    value = "、".join(value)
                if value:
                    lines.append("   {}：{}".format(label, value))
            lines.append("")
        return "\n".join(lines).rstrip()

    def _render_reasoning(self, result):
        reasoning = result.reasoning
        summary_sections = [
            "综合结论\n\n{}".format(reasoning.get("summary", "")),
            self._format_objects(
                "逐篇文章核心内容",
                reasoning.get("article_core_findings", []),
                (("core_finding", "核心发现"), ("source_id", "来源"), ("research_question", "研究问题"), ("method", "方法"), ("evidence_location", "正文位置"), ("limitations", "限制")),
            ),
            self._format_objects(
                "领域背景知识",
                reasoning.get("research_background", []),
                (("claim", "背景"), ("source_ids", "来源"), ("evidence_level", "证据等级"), ("limitations", "限制")),
            ),
            self._format_objects(
                "电化学专业基础知识",
                reasoning.get("electrochemistry_foundations", []),
                (("concept", "概念"), ("explanation", "原理"), ("source_ids", "来源"), ("evidence_level", "证据等级"), ("boundaries", "适用边界")),
            ),
            self._format_objects(
                "与本实验体系相关的参数和科学逻辑",
                reasoning.get("key_figures_tables", []),
                (("parameter", "参数"), ("source_id", "来源"), ("location", "位置"), ("value", "数值"), ("unit", "单位"), ("conditions", "条件"), ("scientific_logic", "科学逻辑"), ("relevance_to_experiment", "与本实验关系")),
            ),
            self._format_objects(
                "本轮新增认识与知识演进",
                reasoning.get("learning_delta", []),
                (("new_understanding", "新增认识"), ("relationship_to_prior", "与既有批准知识关系"), ("source_ids", "来源"), ("unresolved_question", "未解决问题")),
            ),
        ]
        self._replace_output("\n\n".join(summary_sections))

        value_text = self._format_objects(
            "当前数据的研究价值",
            reasoning.get("data_value_assessment", []),
            (("finding", "发现"), ("value", "价值"), ("evidence", "证据"), ("confidence", "置信度"), ("limitations", "限制")),
        )
        cannot = reasoning.get("cannot_determine", [])
        if cannot:
            value_text += "\n\n当前不能判断\n\n" + "\n".join("• " + item for item in cannot)
        self._set_text(self.data_value_text, value_text)

        experiment_text = self._format_objects(
            "需要补充的实验",
            reasoning.get("missing_experiments", []),
            (("experiment", "实验"), ("question", "回答问题"), ("variables", "变量"), ("expected_evidence", "预期证据"), ("priority", "优先级")),
        )
        characterization_text = self._format_objects(
            "需要补充的表征",
            reasoning.get("missing_characterization", []),
            (("characterization", "表征"), ("question", "回答问题"), ("sampling", "取样"), ("expected_evidence", "预期证据"), ("priority", "优先级")),
        )
        self._set_text(self.next_work_text, experiment_text + "\n\n" + characterization_text)

        for node in self.knowledge_tree.get_children():
            self.knowledge_tree.delete(node)
        for item in reasoning.get("knowledge_candidates", []):
            candidate_id = knowledge_candidate_key(item)
            self.knowledge_tree.insert(
                "", "end", iid=candidate_id, text=item.get("claim", ""),
                values=("candidate", item.get("confidence", ""), "、".join(item.get("source_ids", []))),
            )
        enabled = "normal" if self.knowledge_tree.get_children() else "disabled"
        self.approve_candidate_button.configure(state=enabled)
        self.reject_candidate_button.configure(state=enabled)
        self.conclusion_notebook.select(1)

    def _set_selected_candidate_status(self, status):
        if self.result is None:
            messagebox.showwarning("尚无候选知识", "请先完成一次知识助手运行。", parent=self)
            return
        selected = self.knowledge_tree.selection()
        if not selected:
            messagebox.showinfo("请选择知识", "请先在审核列表中选择一条候选知识。", parent=self)
            return
        candidate_id = selected[0]
        try:
            ResearchKnowledgeStore(self.result.knowledge_path).set_candidate_status(
                self.result.knowledge_entry_key,
                candidate_id,
                status,
                self.review_note.get(),
            )
        except Exception as error:
            messagebox.showerror("审核写入失败", str(error), parent=self)
            return
        values = list(self.knowledge_tree.item(candidate_id, "values"))
        values[0] = status
        self.knowledge_tree.item(candidate_id, values=values)
        self.status.set("已{}选中知识并写入本地Markdown".format("批准" if status == "approved" else "拒绝"))

    def approve_selected_candidate(self):
        self._set_selected_candidate_status("approved")

    def reject_selected_candidate(self):
        self._set_selected_candidate_status("rejected")

    def generate_search_plan(self):
        try:
            request = self._request()
            self.plan = build_advanced_search_plan(request.search)
        except Exception as error:
            messagebox.showerror("检索条件无效", str(error), parent=self)
            return None
        lines = [
            "计划哈希：{}".format(self.plan.plan_hash),
            "领域：{}".format(request.search.domain),
            "问题：{}".format(request.search.research_question),
            "",
            "高级检索式：",
        ]
        for database, query in self.plan.database_queries.items():
            lines.extend(["", "[{}]".format(database), query])
        lines.extend(
            [
                "",
                "访问边界：Crossref/OpenAlex由程序检索；授权数据库在你的浏览器中打开，使用校园IP/已登录会话。",
                "程序不会读取校园账号、密码、Cookie，也不会绕过验证码或批量抓取受限全文。",
            ]
        )
        self._replace_output("\n".join(lines))
        self.status.set("高级检索计划已生成")
        return self.plan

    def open_database_pages(self):
        plan = self.plan or self.generate_search_plan()
        if plan is None:
            return
        opened = open_guided_search_pages(plan)
        if opened:
            self.status.set("已打开：{}".format(", ".join(opened)))
        else:
            messagebox.showinfo("没有浏览器数据库", "当前只选择了自动元数据接口。", parent=self)

    def run_assistant(self):
        if self.busy:
            return
        try:
            request = self._request()
            config = LLMConfig(
                base_url=self.variables["llm_base_url"].get(),
                model=self.variables["llm_model"].get(),
                api_key_env=self.variables["api_key_env"].get(),
                max_tokens=int(self.variables["max_tokens"].get()),
                max_input_chars=int(self.variables["max_evidence_chars"].get()) + 15000,
            )
            plan = build_advanced_search_plan(request.search)
        except Exception as error:
            messagebox.showerror("不能启动", str(error), parent=self)
            return
        preview = (
            "即将执行：\n"
            "1. 使用Crossref/OpenAlex建立候选池，并按研究问题相关性和可审计期刊优先名单筛选；\n"
            "2. 只读取最多 {} 篇与候选DOI/题名匹配的原文；无法取得原文时停止，不写入摘要知识；\n"
            "3. 模型依次学习逐篇核心、领域背景、电化学基础、体系参数逻辑及相对既有批准知识的新增认识；\n"
            "4. 结合当前数据指出价值、限制、缺失实验和表征；\n"
            "5. 结果写入本地candidate审核队列，不自动批准。\n\n"
            "不会发送API密钥或浏览器Cookie。远程模型只接收受限原文证据包；本地Qwen在本机处理。是否批准本次联网与模型调用？"
        ).format(request.max_documents, config.model)
        if not messagebox.askyesno("批准知识助手计划", preview, parent=self):
            return
        self.plan = plan
        self.busy = True
        self._reset_progress()
        self._update_progress("plan", "计划已批准，准备开始检索")
        self.run_button.configure(state="disabled")
        self.progress.start(12)
        self.status.set("检索、阅读并调用大模型中…")
        self._replace_output("计划已批准。正在检索元数据、提取全文证据并构造受限证据包……")
        threading.Thread(target=self._worker, args=(request, config), daemon=True).start()

    def _worker(self, request, config):
        try:
            provider = OpenAICompatibleProvider(config)
            result = run_knowledge_assistant(
                request,
                provider,
                run_root=self.project_root / "knowledge" / "runs",
                knowledge_path=self.project_root / "knowledge" / "research_knowledge.md",
                progress_callback=lambda stage, message, details: self.events.put(
                    ("progress", (stage, message, details))
                ),
            )
            self.events.put(("done", result))
        except Exception as error:
            self.events.put(("error", "{}: {}".format(type(error).__name__, error)))

    def _poll_events(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "progress":
                    stage, message, details = value
                    self._update_progress(stage, message, details)
                    self.status.set(message)
                    continue
                self.busy = False
                self.progress.stop()
                self.run_button.configure(state="normal")
                if kind == "error":
                    self.status.set("知识助手失败")
                    self._replace_output(value)
                    self.conclusion_notebook.select(1)
                    messagebox.showerror("知识助手失败", value, parent=self)
                    continue
                self.result = value
                self.open_run_button.configure(state="normal")
                self.status.set("完成：候选知识可在“知识审核”中逐条批准")
                self._render_reasoning(value)
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.poll_id = self.after(120, self._poll_events)

    def _choose_fulltext_dir(self):
        selected = filedialog.askdirectory(title="选择已下载的论文全文目录", parent=self)
        if selected:
            self.variables["local_fulltext_dir"].set(selected)

    def _choose_data_file(self):
        selected = filedialog.askopenfilename(
            title="选择本次数据摘要或报告",
            parent=self,
            filetypes=[
                ("分析数据/报告", "*.json *.csv *.tsv *.md *.txt"),
                ("所有文件", "*.*"),
            ],
        )
        if selected:
            self.variables["data_file"].set(selected)

    def open_knowledge(self):
        target = self.project_root / "knowledge" / "research_knowledge.md"
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(ResearchKnowledgeStore(target)._default(), encoding="utf-8")
        os.startfile(str(target.resolve()))

    def open_run_dir(self):
        if self.result is None or not self.result.run_dir.is_dir():
            messagebox.showwarning("运行目录不存在", "请先完成一次知识助手运行。", parent=self)
            return
        os.startfile(str(self.result.run_dir.resolve()))

    def _on_close(self):
        if self.busy:
            messagebox.showwarning("任务仍在运行", "知识助手正在访问网络或模型，请等待完成后关闭。", parent=self)
            return
        if self.poll_id is not None:
            try:
                self.after_cancel(self.poll_id)
            except tk.TclError:
                pass
            self.poll_id = None
        self.destroy()


# Imported late to avoid exposing the store in the GUI module namespace before use.
from .knowledge_assistant import ResearchKnowledgeStore
