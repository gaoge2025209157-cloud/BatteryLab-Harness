"""Persistent, DOI-scoped literature knowledge for repeated analyses."""

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List


_CLAIM_KEYWORDS = (
    "mechanism", "interface", "interfacial", "kinetic", "diffusion",
    "transport", "thermodynamic", "degradation", "stability", "conductivity",
    "polarization", "resistance", "impedance", "reaction pathway",
)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _profile_fingerprint(profile):
    canonical = json.dumps(profile.to_dict(), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _candidate_claims(abstract: str, doi: str) -> List[dict]:
    claims = []
    sentences = re.split(r"(?<=[.!?])\s+", " ".join((abstract or "").split()))
    for sentence in sentences:
        lowered = sentence.casefold()
        if len(sentence) < 25 or not any(word in lowered for word in _CLAIM_KEYWORDS):
            continue
        claims.append(
            {
                "text": sentence[:1000],
                "status": "candidate",
                "evidence_type": "indexed_abstract_metadata",
                "source_doi": doi,
                "limitation": "摘要级陈述；用于提出假设，引用或定论前须核对论文正文。",
            }
        )
        if len(claims) >= 5:
            break
    return claims


class LiteratureKnowledgeStore:
    """Append-only literature snapshots; latest row wins for each profile and DOI."""

    def __init__(self, path):
        self.path = Path(path)

    def _latest(self) -> Dict[str, dict]:
        latest = {}
        if not self.path.exists():
            return latest
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                record = json.loads(line)
                latest[record["record_key"]] = record
        return latest

    def _append(self, record):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    def find(self, profile) -> List[dict]:
        fingerprint = _profile_fingerprint(profile)
        return sorted(
            [
                record
                for record in self._latest().values()
                if record.get("profile_fingerprint") == fingerprint
            ],
            key=lambda record: (
                record.get("match_level") == "direct",
                record.get("year") or 0,
                record.get("times_seen") or 0,
            ),
            reverse=True,
        )

    def update_from_search(self, profile, search_result):
        """Do not persist metadata/abstract discovery results as knowledge."""

        return {
            "stored": 0,
            "updated": 0,
            "rejected_unverified": sum(
                1 for source in search_result.get("records", []) if not source.get("doi_verified")
            ),
            "skipped_discovery_only": len(search_result.get("records", [])),
            "profile_fingerprint": _profile_fingerprint(profile),
            "write_policy": "fulltext_llm_learning_only",
        }

    def summary(self, profile, update_result=None):
        records = self.find(profile)
        return {
            "path": str(self.path),
            "profile_fingerprint": _profile_fingerprint(profile),
            "reused_record_count": len(records),
            "new_or_updated_record_count": (
                (update_result or {}).get("stored", 0)
                + (update_result or {}).get("updated", 0)
            ),
            "candidate_claim_count": sum(
                len(record.get("candidate_claims", [])) for record in records
            ),
            "records": records,
            "limitations": [
                "只沉淀经 DOI 单篇接口核验的记录。",
                "摘要中的机理陈述标记为 candidate，核对正文前不能作为已证实事实。",
                "知识按完整实验条件指纹隔离，避免跨体系直接套用。",
            ],
        }
