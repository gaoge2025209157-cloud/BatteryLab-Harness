"""Human review of learned literature knowledge and the data-analysis flow.

The checklist follows concrete outputs from one research run. It does not model
roles, signatures, release gates, software installation, Git, CI, or policy
compliance. State is local under ``outputs/`` and excluded from Git.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Dict, Mapping, Optional, Tuple


VALID_STATUSES = ("pending", "passed", "failed", "blocked")
STATUS_LABELS = {
    "pending": "待核对",
    "passed": "已确认",
    "failed": "有误",
    "blocked": "缺少材料",
}


@dataclass(frozen=True)
class AcceptanceItem:
    item_id: str
    group: str
    title: str
    review_object: str
    operation: str
    expected: str
    action_key: Optional[str] = None


ACCEPTANCE_ITEMS: Tuple[AcceptanceItem, ...] = (
    AcceptanceItem(
        "KN-01", "文献原文知识点", "逐篇核心结论",
        "article_core_findings：研究问题、方法、核心发现、正文位置和限制",
        "在本轮文献列表中依次打开每篇原文，对照模型提炼的研究问题、实验方法、核心发现和限制。记录DOI及正文页码、章节或图号。",
        "每个保留知识点都来自实际读到的正文；模型没有把摘要、题名或读图猜测写成作者结论；原文没有说明的内容被删除或退回修改。",
        "knowledge_assistant",
    ),
    AcceptanceItem(
        "KN-02", "文献原文知识点", "领域背景与专业基础",
        "research_background与electrochemistry_foundations",
        "核对本轮新增的领域背景、概念解释、物理化学逻辑、适用条件和失效边界，确认它们确实帮助理解当前课题。",
        "背景知识有原文来源并说明适用边界；专业概念没有脱离测试条件；重复、空泛或不能迁移到当前课题的条目不进入已批准知识。",
        "knowledge_assistant",
    ),
    AcceptanceItem(
        "KN-03", "文献原文知识点", "图表参数与实验逻辑",
        "key_figures_tables：数值、单位、图表位置、条件和科学逻辑",
        "逐项对照原文图、表、图注和方法，核对容量、电压、电导率、温度、压力、载量、倍率、循环数等参数及其测试条件。",
        "数值、单位、图号和实验条件与原文一致；读图估计有明确标记；参数背后的比较逻辑没有越过原文证据。",
        "knowledge_assistant",
    ),
    AcceptanceItem(
        "KN-04", "文献原文知识点", "与本实验相关的候选知识",
        "knowledge_candidates：结论、来源、适用条件、置信度和待核验内容",
        "在最终结果页逐条选择知识点。核对原文和适用条件后填写依据，再决定批准、拒绝或暂不处理。",
        "只改变当前选中的知识点；批准项有DOI、正文位置和适用条件；证据不足或条件不匹配的条目不被批准。",
        "knowledge_assistant",
    ),
    AcceptanceItem(
        "KN-05", "文献原文知识点", "本轮新增认识与冲突",
        "learning_delta：相对既有已批准知识新增、支持、冲突和未解决的问题",
        "比较本轮学习结果与知识库已有内容，核对系统是否指出真正新增的认识、与旧知识的关系、冲突证据和仍待回答的问题。",
        "知识库不是重复摘要堆积；冲突内容被并列保留而非强行统一；下一轮检索问题由当前证据缺口产生。",
        "knowledge_assistant",
    ),
    AcceptanceItem(
        "DF-01", "实验数据流程", "数据识别与循环划分",
        "输入列、单位、时间顺序、充放电方向、容量段和完整循环",
        "对照原始文件和设备软件，抽查首圈、一个中间循环及末圈，核对列识别、单位换算、充放电方向、循环边界和中断循环处理。",
        "循环映射与原始数据一致；不完整循环不会被当作完整循环计算效率或保持率；异常点和缺失信息在结果中可见。",
        "charge_discharge",
    ),
    AcceptanceItem(
        "DF-02", "实验数据流程", "关键指标计算结果",
        "容量、比容量、库仑效率、保持率、平均充放电电压、极化差、主平台、能量或比能量",
        "抽查至少一个完整循环：按原始数据和公式独立复算，并与设备软件、Harness结果核对。特别检查质量口径和能量口径。",
        "各指标数值和单位一致；按比容量计算的结果只称为文件质量口径下的比能量；缺少整电池质量或体积时不报告整电池质量/体积能量密度。",
        "charge_discharge",
    ),
    AcceptanceItem(
        "DF-03", "实验数据流程", "循环趋势与异常",
        "首末变化、每圈变化率、效率稳定性、平均电压与平台漂移、极化变化和异常循环",
        "查看结果中的趋势段，回到曲线核对容量下降或回升、效率波动、电压变化、平台漂移和异常循环是否真实存在。",
        "趋势由多个有效循环支持并给出具体数值；单点波动不被写成长期趋势；数据异常与材料现象明确区分。",
        "charge_discharge",
    ),
    AcceptanceItem(
        "DF-04", "实验数据流程", "数据结论与文献依据",
        "数据能说明的问题、不能说明的问题、候选解释、支持证据和证据缺口",
        "逐条核对最终结论：先看本次数据依据，再看已批准原文知识。检查每个候选解释是否同时列出支持信息、缺失证据和替代解释。",
        "容量、电压、效率和能量结论紧邻具体数值；文献结论紧邻DOI和正文位置；恒流曲线不会被单独用于确定阻抗、扩散或界面化学机理。",
        "charge_discharge",
    ),
    AcceptanceItem(
        "DF-05", "实验数据流程", "下一轮实验与课题建议",
        "优先问题、单变量、对照组、表征时点、支持结果、反证结果和决策分支",
        "检查建议是否直接回应当前最重要的数据现象与知识缺口，并判断实验室是否能按建议实施。",
        "建议具体到变量、对照、测试/表征时点和判别结果；能够区分至少两个候选解释；不会只给出“做EIS、做XPS”之类泛泛列表。",
        "charge_discharge",
    ),
)


class AcceptanceStore:
    """Persist review decisions atomically below outputs/."""

    SCHEMA_VERSION = 3

    def __init__(self, path: Path):
        self.path = Path(path)
        self.records = self._load()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def _blank(self) -> Dict[str, Dict[str, str]]:
        return {
            item.item_id: {"status": "pending", "note": "", "updated_at": ""}
            for item in ACCEPTANCE_ITEMS
        }

    def _load(self) -> Dict[str, Dict[str, str]]:
        records = self._blank()
        if not self.path.is_file():
            return records
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return records
        if payload.get("schema_version") != self.SCHEMA_VERSION:
            return records
        saved = payload.get("items", {})
        if not isinstance(saved, Mapping):
            return records
        for item_id, record in records.items():
            incoming = saved.get(item_id)
            if not isinstance(incoming, Mapping):
                continue
            status = str(incoming.get("status", "pending"))
            if status not in VALID_STATUSES:
                status = "pending"
            record.update(
                status=status,
                note=str(incoming.get("note", "")),
                updated_at=str(incoming.get("updated_at", "")),
            )
        return records

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "updated_at": self._now(),
            "items": self.records,
        }
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(str(temporary), str(self.path))

    def record(self, item_id: str) -> Mapping[str, str]:
        if item_id not in self.records:
            raise KeyError("Unknown acceptance item: {}".format(item_id))
        return dict(self.records[item_id])

    def mark(self, item_id: str, status: str, note: Optional[str] = None) -> None:
        if status not in VALID_STATUSES:
            raise ValueError("Invalid acceptance status: {}".format(status))
        if item_id not in self.records:
            raise KeyError("Unknown acceptance item: {}".format(item_id))
        current_note = self.records[item_id]["note"] if note is None else str(note).strip()
        self.records[item_id] = {
            "status": status,
            "note": current_note,
            "updated_at": self._now(),
        }
        self._save()

    def reset_all(self) -> None:
        self.records = self._blank()
        self._save()

    def summary(self) -> Mapping[str, int]:
        counts = {status: 0 for status in VALID_STATUSES}
        for record in self.records.values():
            counts[record["status"]] += 1
        counts["total"] = len(self.records)
        return counts

    def export_markdown(self, target: Optional[Path] = None) -> Path:
        target = Path(target or self.path.with_name("知识点与数据流程验收报告.md"))
        target.parent.mkdir(parents=True, exist_ok=True)
        counts = self.summary()
        lines = [
            "# ElectrochemHarness 知识点与数据流程验收记录",
            "",
            "更新时间：{}".format(self._now()),
            "",
            "共{}项：已确认{}，有误{}，缺少材料{}，待核对{}。".format(
                counts["total"], counts["passed"], counts["failed"],
                counts["blocked"], counts["pending"],
            ),
        ]
        current_group = None
        for item in ACCEPTANCE_ITEMS:
            if item.group != current_group:
                current_group = item.group
                lines.extend(["", "## {}".format(current_group)])
            record = self.records[item.item_id]
            lines.extend(
                [
                    "",
                    "### {} {} — {}".format(
                        item.item_id, item.title, STATUS_LABELS[record["status"]]
                    ),
                    "",
                    "- 核对对象：{}".format(item.review_object),
                    "- 实际核对：{}".format(item.operation),
                    "- 确认要点：{}".format(item.expected),
                    "- 证据/备注：{}".format(record["note"] or "待填写"),
                    "- 记录时间：{}".format(record["updated_at"] or "待核对"),
                ]
            )
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        os.replace(str(temporary), str(target))
        return target
