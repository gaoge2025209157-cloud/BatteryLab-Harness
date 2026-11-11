"""Validate Codex project assessments before they appear in a research report."""
from __future__ import annotations

from typing import Any, Mapping


REQUIRED_FIELDS = frozenset({"assessment", "data_facts", "hypotheses", "cannot_determine", "theoretical_energy_assessment", "next_experiments"})


def validate_guidance_payload(payload: Mapping[str, Any]) -> dict:
    if not isinstance(payload, Mapping):
        raise ValueError("Codex guidance lacks required assessment sections.")
    payload = dict(payload)
    payload.setdefault("benchmark_comparisons", [])
    if not REQUIRED_FIELDS.issubset(payload):
        raise ValueError("Codex guidance lacks required assessment sections.")
    assessment = str(payload["assessment"] or "").strip()
    if not assessment:
        raise ValueError("Codex guidance assessment is empty.")
    for field in ("data_facts", "hypotheses", "cannot_determine", "benchmark_comparisons", "next_experiments"):
        if not isinstance(payload[field], list):
            raise ValueError("Codex guidance field {} must be an array.".format(field))
    hypotheses = []
    for item in payload["hypotheses"]:
        if not isinstance(item, Mapping):
            raise ValueError("Every hypothesis must be an object.")
        claim = str(item.get("claim") or item.get("hypothesis") or "").strip()
        test = str(item.get("test") or item.get("falsification_test") or item.get("proposed_test") or "").strip()
        if not claim or not test:
            raise ValueError("Every hypothesis requires a claim and a falsification test.")
        hypotheses.append({
            "claim": claim,
            "support": [str(value) for value in item.get("support") or item.get("supporting_evidence") or []],
            "against": [str(value) for value in item.get("against") or item.get("contrary_evidence") or []],
            "test": test,
        })
    experiments = []
    for item in payload["next_experiments"]:
        if isinstance(item, str):
            action = item.strip()
            row = {}
        elif isinstance(item, Mapping):
            action = str(item.get("action") or item.get("experiment") or item.get("recommendation") or "").strip()
            row = item
        else:
            action = ""
            row = {}
        if not action:
            raise ValueError("Every next experiment requires an action.")
        experiments.append({
            "action": action,
            "hypothesis": str(row.get("hypothesis") or "").strip(),
            "purpose": str(row.get("purpose") or "").strip(),
            "variable": str(row.get("variable") or row.get("controlled_variable") or "").strip(),
            "controls": [str(value) for value in row.get("controls") or [] if str(value).strip()],
            "expected_evidence": str(row.get("expected_evidence") or row.get("expected_result") or "").strip(),
            "expected_if_supported": str(row.get("expected_if_supported") or "").strip(),
            "expected_if_refuted": str(row.get("expected_if_refuted") or "").strip(),
            "requires_confirmation": bool(row.get("requires_confirmation", True)),
        })
    comparisons = []
    for item in payload["benchmark_comparisons"]:
        if not isinstance(item, Mapping) or not str(item.get("metric") or "").strip() or not str(item.get("conclusion") or "").strip():
            raise ValueError("Every benchmark comparison requires a metric and conclusion.")
        comparisons.append({
            "metric": str(item["metric"]).strip(),
            "observed": str(item.get("observed") or "").strip(),
            "reference": str(item.get("reference") or "").strip(),
            "comparability": str(item.get("comparability") or "insufficient_context").strip(),
            "conclusion": str(item["conclusion"]).strip(),
            "source_urls": [str(value) for value in item.get("source_urls") or []],
        })
    theory = payload["theoretical_energy_assessment"]
    if not isinstance(theory, Mapping) or not str(theory.get("conclusion") or "").strip():
        raise ValueError("Theoretical energy assessment requires a conclusion.")
    return {
        "assessment": assessment,
        "data_facts": [str(value) for value in payload["data_facts"] if str(value).strip()],
        "hypotheses": hypotheses,
        "cannot_determine": [str(value) for value in payload["cannot_determine"] if str(value).strip()],
        "benchmark_comparisons": comparisons,
        "theoretical_energy_assessment": dict(theory),
        "next_experiments": experiments,
    }
