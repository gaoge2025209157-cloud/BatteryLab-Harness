import json
import operator
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .models import CycleMetrics, Experience, ExperimentContext


OPERATORS = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
    "==": operator.eq,
}


class ExperienceStore:
    def __init__(self, path: Path):
        self.path = Path(path)

    def _latest(self) -> Dict[str, Experience]:
        if not self.path.exists():
            return {}
        latest = {}
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    item = Experience.from_dict(json.loads(line))
                    latest[item.id] = item
        return latest

    def _append(self, experience: Experience) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(experience.to_dict(), ensure_ascii=False) + "\n")

    def record(
        self,
        experiment_type: str,
        system_type: str,
        observation: str,
        action: str,
        outcome: str,
        evidence: str,
        validated: bool = False,
    ) -> Experience:
        experience = Experience(
            id=str(uuid.uuid4()),
            experiment_type=experiment_type,
            system_type=system_type,
            observation=observation,
            action=action,
            outcome=outcome,
            evidence=evidence,
            validated=validated,
            confidence=0.55 if validated else 0.30,
            supports=1 if validated else 0,
            contradicts=0,
            created_at=datetime.now(timezone.utc).isoformat(),
            feedback_evidence=[evidence] if evidence else [],
        )
        self._append(experience)
        return experience

    def find(
        self, experiment_type: str, system_type: str, min_confidence: float = 0.5
    ) -> List[Experience]:
        return sorted(
            [
                item
                for item in self._latest().values()
                if item.experiment_type == experiment_type
                and item.system_type == system_type
                and item.confidence >= min_confidence
            ],
            key=lambda item: item.confidence,
            reverse=True,
        )

    def apply_feedback(self, experience_id: str, effective: bool, evidence: str) -> Experience:
        current = self._latest().get(experience_id)
        if current is None:
            raise KeyError("Unknown experience id: {}".format(experience_id))
        confidence_delta = 0.10 if effective else -0.15
        updated = replace(
            current,
            validated=current.validated or effective,
            confidence=max(0.0, min(0.95, current.confidence + confidence_delta)),
            supports=current.supports + (1 if effective else 0),
            contradicts=current.contradicts + (0 if effective else 1),
            feedback_evidence=current.feedback_evidence + ([evidence] if evidence else []),
        )
        self._append(updated)
        return updated


class KnowledgeBase:
    def __init__(self, rules_path: Path, experiences_path: Path):
        self.rules_path = Path(rules_path)
        self.experiences = ExperienceStore(experiences_path)

    def rules(self) -> List[dict]:
        if not self.rules_path.exists():
            return []
        payload = json.loads(self.rules_path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError("Knowledge rules must be a JSON list")
        return payload

    def matching_rules(
        self, context: ExperimentContext, latest: CycleMetrics
    ) -> List[dict]:
        matches = []
        context_values = context.to_dict()
        for rule in self.rules():
            conditions = rule.get("conditions", {})
            if any(context_values.get(key) != value for key, value in conditions.items()):
                continue
            metric_name = rule.get("metric")
            metric_value: Optional[float] = getattr(latest, metric_name, None)
            comparison = OPERATORS.get(rule.get("operator"))
            if metric_value is None or comparison is None:
                continue
            if comparison(metric_value, float(rule["threshold"])):
                matches.append(dict(rule, observed_value=metric_value))
        return matches
