"""Interactive manual acceptance centre for ElectrochemHarness."""

import os
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, Mapping, Optional

from .acceptance import ACCEPTANCE_ITEMS, STATUS_LABELS, AcceptanceStore


class AcceptanceDialog(tk.Toplevel):
    """Show one auditable checklist item at a time without running hidden work."""

    def __init__(self, parent, project_root, action_handlers=None):
        super().__init__(parent)
        self.project_root = Path(project_root).resolve()
        self.action_handlers: Mapping[str, Callable[[], None]] = action_handlers or {}
        self.items = {item.item_id: item for item in ACCEPTANCE_ITEMS}
        self.store = AcceptanceStore(
            self.project_root / "outputs" / "manual_acceptance" / "acceptance_state.json"
        )
        self.selected_item_id: Optional[str] = None
        self.title("ElectrochemHarness 知识点与数据流程核对")
        self.transient(parent)
        self.geometry("1180x760")
        self.minsize(940, 620)
        self._configure_style()
        self._build()
        self._populate_tree()
        first = ACCEPTANCE_ITEMS[0].item_id
        self.tree.selection_set(first)
        self.tree.focus(first)
        self._show_item(first)

    def _configure_style(self):
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("AcceptanceTitle.TLabel", font=("Microsoft YaHei UI", 15, "bold"))
        style.configure("AcceptanceItem.TLabel", font=("Microsoft YaHei UI", 12, "bold"))
        style.configure("AcceptanceHint.TLabel", foreground="#556273")
        style.configure("Treeview", rowheight=28, font=("Microsoft YaHei UI", 9))
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 9, "bold"))

    def _build(self):
        outer = ttk.Frame(self, padding=14)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)

        header = ttk.Frame(outer)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="知识点与数据流程核对", style="AcceptanceTitle.TLabel").grid(row=0, column=0, sticky="w")
        self.summary_var = tk.StringVar()
        ttk.Label(header, textvariable=self.summary_var, style="AcceptanceHint.TLabel").grid(row=0, column=1, sticky="e")
        ttk.Label(
            outer,
            text="直接核对本轮读到的原文知识点和数据分析结果。这里不包含角色签字、发布门、Git或安装检查。",
            style="AcceptanceHint.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(3, 10))

        pane = ttk.PanedWindow(outer, orient="horizontal")
        pane.grid(row=2, column=0, sticky="nsew")

        list_frame = ttk.LabelFrame(pane, text="验收清单", padding=6)
        pane.add(list_frame, weight=1)
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            list_frame,
            columns=("review_object", "status"),
            show="tree headings",
            selectmode="browse",
        )
        self.tree.heading("#0", text="编号与核对项")
        self.tree.heading("review_object", text="核对对象")
        self.tree.heading("status", text="状态")
        self.tree.column("#0", width=300, anchor="w")
        self.tree.column("review_object", width=250, anchor="w")
        self.tree.column("status", width=88, anchor="center")
        self.tree.grid(row=0, column=0, sticky="nsew")
        list_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=list_scroll.set)
        list_scroll.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        detail = ttk.LabelFrame(pane, text="核对内容", padding=12)
        pane.add(detail, weight=2)
        detail.columnconfigure(0, weight=1)
        detail.rowconfigure(3, weight=1)
        self.item_title = tk.StringVar()
        self.item_meta = tk.StringVar()
        ttk.Label(detail, textvariable=self.item_title, style="AcceptanceItem.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(detail, textvariable=self.item_meta, style="AcceptanceHint.TLabel").grid(row=1, column=0, sticky="w", pady=(2, 10))

        instructions = ttk.Notebook(detail)
        instructions.grid(row=2, column=0, sticky="nsew")
        detail.rowconfigure(2, weight=1)
        self.operation_text = self._text_page(instructions, "实际核对")
        self.expected_text = self._text_page(instructions, "确认要点")

        evidence = ttk.LabelFrame(detail, text="证据与备注", padding=6)
        evidence.grid(row=3, column=0, sticky="nsew", pady=(10, 0))
        evidence.columnconfigure(0, weight=1)
        evidence.rowconfigure(0, weight=1)
        self.note_text = tk.Text(evidence, height=6, wrap="word", font=("Microsoft YaHei UI", 9), padx=8, pady=6)
        self.note_text.grid(row=0, column=0, sticky="nsew")
        ttk.Label(
            evidence,
            text="建议记录数据编号、运行目录、主要数值、截图名称、异常和复核人；不要粘贴密码或Token。",
            style="AcceptanceHint.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(5, 0))

        actions = ttk.Frame(outer)
        actions.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        self.open_action_button = ttk.Button(actions, text="打开对应功能", command=self._open_action)
        self.open_action_button.grid(row=0, column=0, padx=(0, 6))
        ttk.Button(actions, text="确认无误", command=lambda: self._set_status("passed")).grid(row=0, column=1, padx=3)
        ttk.Button(actions, text="标记有误", command=lambda: self._set_status("failed")).grid(row=0, column=2, padx=3)
        ttk.Button(actions, text="缺少材料", command=lambda: self._set_status("blocked")).grid(row=0, column=3, padx=3)
        ttk.Button(actions, text="稍后核对", command=lambda: self._set_status("pending")).grid(row=0, column=4, padx=3)
        ttk.Button(actions, text="仅保存备注", command=self._save_note).grid(row=0, column=5, padx=3)
        actions.columnconfigure(6, weight=1)
        ttk.Button(actions, text="导出验收报告", command=self._export_report).grid(row=0, column=7, padx=3)
        ttk.Button(actions, text="全部重置", command=self._reset_all).grid(row=0, column=8, padx=3)
        ttk.Button(actions, text="关闭", command=self.destroy).grid(row=0, column=9, padx=(6, 0))

    def _text_page(self, notebook, label):
        page = ttk.Frame(notebook, padding=6)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(0, weight=1)
        widget = tk.Text(
            page, wrap="word", state="disabled", height=8,
            font=("Microsoft YaHei UI", 10), padx=10, pady=8,
        )
        widget.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(page, orient="vertical", command=widget.yview)
        widget.configure(yscrollcommand=scroll.set)
        scroll.grid(row=0, column=1, sticky="ns")
        notebook.add(page, text=label)
        return widget

    @staticmethod
    def _replace_text(widget, text):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def _populate_tree(self):
        for node in self.tree.get_children():
            self.tree.delete(node)
        group_nodes = {}
        for item in ACCEPTANCE_ITEMS:
            group_id = "group:" + item.group
            if item.group not in group_nodes:
                group_nodes[item.group] = group_id
                self.tree.insert("", "end", iid=group_id, text=item.group, open=True, values=("", ""))
            record = self.store.record(item.item_id)
            self.tree.insert(
                group_id, "end", iid=item.item_id,
                text="{}  {}".format(item.item_id, item.title),
                values=(item.review_object, STATUS_LABELS[record["status"]]),
            )
        self._refresh_summary()

    def _refresh_summary(self):
        counts = self.store.summary()
        self.summary_var.set(
            "共{}项｜已确认{}｜有误{}｜缺少材料{}｜待核对{}".format(
                counts["total"], counts["passed"], counts["failed"],
                counts["blocked"], counts["pending"],
            )
        )

    def _on_select(self, event=None):
        selected = self.tree.selection()
        if not selected or selected[0] not in self.items:
            return
        if self.selected_item_id and self.selected_item_id != selected[0]:
            self._persist_note(self.selected_item_id)
        self._show_item(selected[0])

    def _show_item(self, item_id):
        self.selected_item_id = item_id
        item = self.items[item_id]
        record = self.store.record(item_id)
        self.item_title.set("{}  {}".format(item.item_id, item.title))
        self.item_meta.set("分组：{}　核对对象：{}　当前状态：{}".format(item.group, item.review_object, STATUS_LABELS[record["status"]]))
        self._replace_text(self.operation_text, item.operation)
        self._replace_text(self.expected_text, item.expected)
        self.note_text.delete("1.0", "end")
        self.note_text.insert("1.0", record["note"])
        self.open_action_button.configure(
            state="normal" if item.action_key in self.action_handlers else "disabled"
        )

    def _note(self):
        return self.note_text.get("1.0", "end").strip()

    def _persist_note(self, item_id):
        record = self.store.record(item_id)
        note = self._note()
        if note != record["note"]:
            self.store.mark(item_id, record["status"], note)

    def _save_note(self):
        if not self.selected_item_id:
            return
        record = self.store.record(self.selected_item_id)
        self.store.mark(self.selected_item_id, record["status"], self._note())
        self._refresh_summary()
        self.item_meta.set(self.item_meta.get().split("　当前状态：", 1)[0] + "　当前状态：" + STATUS_LABELS[record["status"]])

    def _set_status(self, status):
        if not self.selected_item_id:
            return
        self.store.mark(self.selected_item_id, status, self._note())
        self.tree.set(self.selected_item_id, "status", STATUS_LABELS[status])
        self._refresh_summary()
        self._show_item(self.selected_item_id)

    def _open_action(self):
        if not self.selected_item_id:
            return
        item = self.items[self.selected_item_id]
        handler = self.action_handlers.get(item.action_key or "")
        if handler is not None:
            handler()

    def _export_report(self):
        if self.selected_item_id:
            self._persist_note(self.selected_item_id)
        target = self.store.export_markdown()
        messagebox.showinfo("核对记录已导出", "记录已保存到：\n{}".format(target), parent=self)
        if os.name == "nt":
            os.startfile(str(target.resolve()))

    def _reset_all(self):
        if not messagebox.askyesno("全部重置", "确定清除全部验收状态和备注吗？", parent=self):
            return
        self.store.reset_all()
        self._populate_tree()
        if self.selected_item_id:
            self._show_item(self.selected_item_id)


def install_acceptance_center(app, parent):
    """Install one acceptance entry in the existing navigation panel."""

    ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=10)

    def open_dialog():
        dialog = getattr(app, "acceptance_dialog", None)
        if dialog is not None:
            try:
                if dialog.winfo_exists():
                    dialog.lift()
                    dialog.focus_force()
                    return
            except tk.TclError:
                pass
        handlers = {
            "charge_discharge": app.open_six_step,
            "knowledge_assistant": app.open_six_step,
            "performance_plots": lambda: app.open_plot_workspace("rate_capability"),
            "eis": lambda: app.open_plot_workspace("eis_nyquist"),
        }
        app.acceptance_dialog = AcceptanceDialog(app.root, app.project_root, handlers)

    button = ttk.Button(
        parent,
        text="知识点与数据流程核对",
        style="Accent.TButton",
        command=open_dialog,
    )
    button.pack(fill="x", pady=2)
    return button
