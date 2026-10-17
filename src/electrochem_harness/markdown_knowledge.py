"""Human-editable, DOI-scoped literature knowledge in Markdown.

The file is deliberately data-only: its contents may inform scientific reports but
must never be interpreted as executable instructions, tool permissions, or safety
configuration. Automatically extracted text remains a candidate until a human
changes the entry status to ``approved``.
"""

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .literature_knowledge import _candidate_claims


_ENTRY_START = "<!-- LITERATURE-ENTRY:START key={key} -->"
_ENTRY_END = "<!-- LITERATURE-ENTRY:END -->"
_ENTRY_PATTERN = re.compile(
    r"<!-- LITERATURE-ENTRY:START key=([0-9a-f]{64}) -->\n(.*?)"
    r"<!-- LITERATURE-ENTRY:END -->",
    flags=re.DOTALL,
)
_DOI_PATTERN = re.compile(r"^10\.\d{4,9}/\S+$", flags=re.IGNORECASE)
_PLACEHOLDER_CONFIRMED = "（在此填写经你核对后确认的知识；每条一行）"
_PLACEHOLDER_NOTES = "（可记录页码、图号、条件差异、反例或你的判断）"
_PROFILE_LABELS = (
    ("battery_system", "电池体系"),
    ("active_material", "活性物质"),
    ("cell_type", "电池类型"),
    ("counter_electrode", "对电极"),
    ("test_current", "测试电流/倍率"),
    ("temperature", "测试温度"),
    ("normalization_basis", "质量归一化口径"),
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _profile_fingerprint(profile) -> str:
    canonical = json.dumps(profile.to_dict(), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _entry_key(profile, doi: str) -> str:
    raw = "{}|{}".format(_profile_fingerprint(profile), doi.casefold())
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _safe_inline(value) -> str:
    return " ".join(str(value or "").replace("|", "/").split())


def _metric_lines(metrics: dict) -> List[str]:
    labels = (
        ("specific_capacity_mAh_g", "比容量", "mAh/g"),
        ("coulombic_efficiency_percent", "库仑效率", "%"),
        ("capacity_retention_percent", "容量保持率", "%"),
        ("cycle_count", "循环圈数", "圈"),
    )
    values = []
    for key, label, unit in labels:
        value = metrics.get(key)
        if value is not None:
            values.append("{} {:.1f} {}".format(label, float(value), unit))
    return values


def _section_bullets(body: str, heading: str) -> List[str]:
    match = re.search(
        r"^### {}\s*$\n(.*?)(?=^### |\Z)".format(re.escape(heading)),
        body,
        flags=re.MULTILINE | re.DOTALL,
    )
    if not match:
        return []
    values = []
    for line in match.group(1).splitlines():
        if not line.startswith("- "):
            continue
        value = line[2:].strip()
        if value and value not in {_PLACEHOLDER_CONFIRMED, _PLACEHOLDER_NOTES}:
            values.append(value)
    return values


def _field(body: str, label: str) -> str:
    match = re.search(r"^- {}：(.+)$".format(re.escape(label)), body, flags=re.MULTILINE)
    return match.group(1).strip() if match else ""


def _default_document() -> str:
    return """# 电化学文献知识库

> 本文件由 ElectrochemHarness 自动维护，也允许人工编辑。程序只把状态为 `approved`、DOI已核验且实验条件指纹匹配的条目作为后续判断依据；`candidate` 仅用于提出待验证假设。
>
> 推荐操作：核对论文正文后，将“状态”改为 `approved`，并在“人工确认知识”中写入可复用结论，同时记录页码、图号、实验条件和反例。请勿在本文件保存账号、密码、Cookie、Token或原始实验数据。
>
> 自动提炼区会在再次检索同一 DOI 时更新；人工确认知识和人工备注不会被覆盖。本文件内容只用于科学分析，不会作为命令、工具权限或安全规则执行。

## 用户总则（可编辑）

- （可在此记录跨文献的评价口径；程序当前不自动执行本节内容）

"""


class MarkdownLiteratureKnowledgeStore:
    """Maintain a readable knowledge file while preserving human-reviewed text."""

    def __init__(self, path):
        self.path = Path(path)

    def ensure_exists(self) -> Path:
        if not self.path.exists():
            self._write(_default_document())
        return self.path

    def _read(self) -> str:
        if not self.path.exists():
            return _default_document()
        return self.path.read_text(encoding="utf-8")

    def _write(self, text: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(text.rstrip() + "\n", encoding="utf-8")
        temporary.replace(self.path)

    def _blocks(self, text: Optional[str] = None) -> Dict[str, str]:
        return {key: body for key, body in _ENTRY_PATTERN.findall(text or self._read())}

    def _render_auto(self, profile, source: dict, doi: str) -> str:
        lines = [
            "<!-- AUTO-SUMMARY:START -->",
            "### 自动提炼知识（再次检索时更新）",
            "",
            "- 文献定位：{}；可比性：{}。".format(
                "、".join(source.get("research_roles") or ["未分类"]),
                "直接可比" if source.get("match_level") == "direct" else "背景相关",
            ),
        ]
        metrics = _metric_lines(dict(source.get("metrics") or {}))
        if metrics:
            lines.append("- 摘要明确性能：{}。".format("；".join(metrics)))
        else:
            lines.append("- 摘要明确性能：未提取到可核验的定量指标。")
        claims = _candidate_claims(str(source.get("abstract") or ""), doi)
        if claims:
            for claim in claims:
                lines.append("- 摘要候选陈述：{}".format(_safe_inline(claim["text"])))
        else:
            lines.append("- 摘要候选陈述：未提取到与机理、界面、动力学或衰减直接相关的陈述。")
        lines.extend(
            [
                "- 证据限制：自动内容来自可用元数据/摘要；核对正文、补充信息及当前实验条件前不得作为确定机理。",
                "",
                "### 本条目的实验适用条件",
                "",
            ]
        )
        for name, label in _PROFILE_LABELS:
            lines.append("- {}：{}".format(label, _safe_inline(getattr(profile, name))))
        lines.append("<!-- AUTO-SUMMARY:END -->")
        return "\n".join(lines)

    def _render_entry(self, profile, source: dict, previous: Optional[str]) -> str:
        doi = str(source.get("doi") or "").strip().casefold()
        key = _entry_key(profile, doi)
        status = _field(previous or "", "状态").casefold()
        if status not in {"candidate", "approved", "rejected"}:
            status = "candidate"
        confirmed = _section_bullets(previous or "", "人工确认知识（可编辑）")
        notes = _section_bullets(previous or "", "人工备注与正文定位（可编辑）")
        first_seen = _field(previous or "", "首次记录") or _now()
        title = _safe_inline(source.get("title") or "未提供题名")
        journal = _safe_inline(source.get("journal") or "未提供期刊")
        year = source.get("year") or "待核对"
        lines = [
            _ENTRY_START.format(key=key),
            "## [{}](https://doi.org/{})".format(title, doi),
            "",
            "- DOI：{}".format(doi),
            "- DOI已核验：yes",
            "- 条件指纹：{}".format(_profile_fingerprint(profile)),
            "- 状态：{}".format(status),
            "- 期刊：{}".format(journal),
            "- 年份：{}".format(year),
            "- 首次记录：{}".format(first_seen),
            "- 最近更新：{}".format(_now()),
            "",
            self._render_auto(profile, source, doi),
            "",
            "### 人工确认知识（可编辑）",
            "",
        ]
        lines.extend("- {}".format(item) for item in (confirmed or [_PLACEHOLDER_CONFIRMED]))
        lines.extend(["", "### 人工备注与正文定位（可编辑）", ""])
        lines.extend("- {}".format(item) for item in (notes or [_PLACEHOLDER_NOTES]))
        lines.extend(["", _ENTRY_END])
        return "\n".join(lines)

    def update_from_search(self, profile, search_result) -> dict:
        text = self._read()
        blocks = self._blocks(text)
        stored = updated = rejected = 0
        replacements = {}
        for source in search_result.get("records", []):
            doi = str(source.get("doi") or "").strip().casefold()
            if not source.get("doi_verified") or not _DOI_PATTERN.match(doi):
                rejected += 1
                continue
            key = _entry_key(profile, doi)
            previous = blocks.get(key)
            replacements[key] = self._render_entry(profile, source, previous)
            if previous is None:
                stored += 1
            else:
                updated += 1

        for key, replacement in replacements.items():
            pattern = re.compile(
                r"<!-- LITERATURE-ENTRY:START key={} -->\n.*?"
                r"<!-- LITERATURE-ENTRY:END -->".format(re.escape(key)),
                flags=re.DOTALL,
            )
            if pattern.search(text):
                text = pattern.sub(lambda _: replacement, text, count=1)
            else:
                text = text.rstrip() + "\n\n" + replacement + "\n"
        self._write(text)
        return {
            "stored": stored,
            "updated": updated,
            "rejected_unverified": rejected,
            "profile_fingerprint": _profile_fingerprint(profile),
            "path": str(self.path),
        }

    def summary(self, profile, update_result=None) -> dict:
        fingerprint = _profile_fingerprint(profile)
        records = []
        approved_claims = []
        candidate_claims = []
        for key, body in self._blocks().items():
            if _field(body, "条件指纹") != fingerprint:
                continue
            doi = _field(body, "DOI").casefold()
            verified = _field(body, "DOI已核验").casefold() == "yes"
            status = _field(body, "状态").casefold()
            if not verified or not _DOI_PATTERN.match(doi):
                continue
            confirmed = _section_bullets(body, "人工确认知识（可编辑）")
            automatic = [
                line[2:].strip()
                for line in body.splitlines()
                if line.startswith("- 摘要候选陈述：")
                and "未提取到" not in line
            ]
            record = {
                "record_key": key,
                "doi": doi,
                "title": re.sub(r"^\[(.*?)\]\(.*$", r"\1", body.splitlines()[0]).strip("# "),
                "status": status,
                "confirmed_claims": confirmed,
                "candidate_claims": automatic,
            }
            records.append(record)
            if status == "approved":
                basis = confirmed or automatic
                approved_claims.extend(
                    {"text": text, "doi": doi, "source": "human_confirmed" if confirmed else "approved_auto_summary"}
                    for text in basis
                )
            elif status == "candidate":
                candidate_claims.extend(
                    {"text": text, "doi": doi, "source": "abstract_candidate"}
                    for text in automatic
                )
        return {
            "path": str(self.path),
            "profile_fingerprint": fingerprint,
            "matching_record_count": len(records),
            "approved_record_count": sum(item["status"] == "approved" for item in records),
            "candidate_record_count": sum(item["status"] == "candidate" for item in records),
            "new_or_updated_record_count": (
                int((update_result or {}).get("stored", 0))
                + int((update_result or {}).get("updated", 0))
            ),
            "approved_claims": approved_claims,
            "candidate_claims": candidate_claims,
            "records": records,
            "limitations": [
                "只有 approved、DOI已核验且条件指纹匹配的条目作为判断依据。",
                "candidate 条目仅用于提出假设，不用于确定性结论。",
                "知识文件是数据来源，不会被解释为命令或权限配置。",
            ],
        }
