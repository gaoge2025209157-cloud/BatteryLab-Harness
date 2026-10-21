import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from electrochem_harness.evidence import (  # noqa: E402
    EvidenceKind,
    EvidenceLocation,
    EvidenceRecord,
)
from electrochem_harness.fulltext import classify_source, evidence_record_from_source  # noqa: E402
from electrochem_harness.knowledge_governance import (  # noqa: E402
    REQUIRED_EXPERIMENT_ISSUES,
    GateStatus,
    ReviewerConfirmation,
    evaluate_publication_gate,
)
from electrochem_harness.scientific_reasoning import (  # noqa: E402
    HypothesisCandidate,
    HypothesisMatrix,
    render_hypothesis_matrix,
)


class EvidenceTests(unittest.TestCase):
    def test_abstract_is_not_body_fact(self):
        availability = classify_source(
            doi="10.1234/example",
            abstract_text="The abstract reports a capacity.",
        )
        record = evidence_record_from_source(
            claim_id="A-001",
            claim="The abstract reports a capacity.",
            availability=availability,
            doi="10.1234/example",
            doi_verified=True,
        )

        self.assertEqual(record.source_kind, EvidenceKind.ABSTRACT)
        self.assertFalse(record.is_body_fact)
        self.assertNotIn("section", record.to_dict()["location"] or {})

    def test_html_body_requires_location(self):
        availability = classify_source(
            doi="10.1234/example",
            html_text="<section>Results</section><p>Observed value.</p>",
        )
        with self.assertRaisesRegex(ValueError, "section"):
            evidence_record_from_source(
                claim_id="A-002",
                claim="Observed value.",
                availability=availability,
                doi="10.1234/example",
                doi_verified=True,
            )

        record = evidence_record_from_source(
            claim_id="A-002",
            claim="Observed value.",
            availability=availability,
            doi="10.1234/example",
            doi_verified=True,
            location=EvidenceLocation(section="Results", paragraph="p-3"),
        )
        self.assertTrue(record.is_body_fact)

    def test_local_pdf_has_priority_over_abstract(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "authorized.pdf"
            pdf.write_bytes(b"%PDF-test")
            availability = classify_source(
                doi="10.1234/example",
                abstract_text="Abstract",
                local_pdf=pdf,
            )

        self.assertEqual(availability.kind, EvidenceKind.LOCAL_PDF)
        self.assertTrue(availability.available)


class GovernanceTests(unittest.TestCase):
    def _record(self):
        return EvidenceRecord(
            claim_id="A-003",
            claim="A located body fact.",
            source_kind=EvidenceKind.LOCAL_PDF,
            source_uri="approved-local-source",
            doi="10.1234/example",
            doi_verified=True,
            location=EvidenceLocation(section="Results", page=4),
        )

    def test_gate_is_blocked_without_real_review_and_tolerance_confirmation(self):
        decision = evaluate_publication_gate(evidence_records=[self._record()])

        self.assertEqual(decision.status, GateStatus.BLOCKED)
        self.assertFalse(decision.can_publish)
        self.assertIn("private real-data", " ".join(decision.reasons))

    def test_gate_opens_only_after_j_and_c_confirm(self):
        confirmations = [
            ReviewerConfirmation("J", True),
            ReviewerConfirmation("C", True),
        ]
        decision = evaluate_publication_gate(
            evidence_records=[self._record()],
            reviewer_confirmations=confirmations,
            real_data_reviewed=True,
            metric_tolerances_confirmed=True,
            resolved_experiment_issues=REQUIRED_EXPERIMENT_ISSUES,
        )

        self.assertEqual(decision.status, GateStatus.OPEN)
        self.assertTrue(decision.can_publish)

    def test_each_unresolved_experimental_issue_blocks_even_with_approvals(self):
        for missing in REQUIRED_EXPERIMENT_ISSUES:
            with self.subTest(missing=missing):
                decision = evaluate_publication_gate(
                    real_data_reviewed=True,
                    metric_tolerances_confirmed=True,
                    reviewer_confirmations=[
                        ReviewerConfirmation("J", True),
                        ReviewerConfirmation("C", True),
                    ],
                    resolved_experiment_issues=[
                        issue for issue in REQUIRED_EXPERIMENT_ISSUES
                        if issue != missing
                    ],
                )
                self.assertEqual(decision.status, GateStatus.BLOCKED)
                self.assertFalse(decision.can_publish)
                self.assertIn(missing, " ".join(decision.reasons))

    def test_legacy_call_cannot_open_gate_without_experimental_review(self):
        decision = evaluate_publication_gate(
            real_data_reviewed=True,
            metric_tolerances_confirmed=True,
            reviewer_confirmations=[
                ReviewerConfirmation("J", True),
                ReviewerConfirmation("C", True),
            ],
        )
        self.assertEqual(decision.status, GateStatus.BLOCKED)
        self.assertEqual(len(decision.reasons), 4)

    def test_resolved_issues_do_not_replace_reviewer_confirmation(self):
        decision = evaluate_publication_gate(
            real_data_reviewed=True,
            metric_tolerances_confirmed=True,
            resolved_experiment_issues=REQUIRED_EXPERIMENT_ISSUES,
            reviewer_confirmations=[ReviewerConfirmation("J", True)],
        )
        self.assertEqual(decision.status, GateStatus.PENDING_CONFIRMATION)
        self.assertEqual(decision.missing_reviewers, ("C",))

    def test_unverified_doi_keeps_gate_blocked(self):
        record = EvidenceRecord(
            claim_id="A-004",
            claim="Unverified citation.",
            source_kind=EvidenceKind.ABSTRACT,
            source_uri="abstract-metadata",
            doi="10.1234/example",
            doi_verified=False,
        )
        decision = evaluate_publication_gate(
            evidence_records=[record],
            real_data_reviewed=True,
            metric_tolerances_confirmed=True,
            reviewer_confirmations=[ReviewerConfirmation("J", True), ReviewerConfirmation("C", True)],
        )

        self.assertEqual(decision.status, GateStatus.BLOCKED)
        self.assertIn("doi_verified", " ".join(decision.reasons))


class ReasoningTests(unittest.TestCase):
    def test_each_candidate_requires_falsifiable_experiment(self):
        candidate = HypothesisCandidate(
            hypothesis_id="H-001",
            candidate_reason="Polarization may increase.",
            supporting_evidence=("voltage gap increased",),
            contrary_or_missing_evidence=("no replicate yet",),
            minimum_discriminating_experiment="Repeat at the same rate and temperature.",
            expected_if_supported="The gap repeats across independent cells.",
            expected_if_falsified="The gap does not repeat.",
        )
        matrix = HypothesisMatrix("Voltage gap increased.", (candidate,))

        self.assertEqual(matrix.validation_errors(), [])
        self.assertIn("H-001", render_hypothesis_matrix(matrix))

    def test_incomplete_candidate_is_rejected(self):
        candidate = HypothesisCandidate(
            hypothesis_id="H-002",
            candidate_reason="Possible leakage.",
            supporting_evidence=("low CE",),
            contrary_or_missing_evidence=(),
            minimum_discriminating_experiment="",
            expected_if_supported="",
            expected_if_falsified="",
        )
        matrix = HypothesisMatrix("Low CE.", (candidate,))

        self.assertTrue(matrix.validation_errors())
        with self.assertRaises(ValueError):
            matrix.validate()


if __name__ == "__main__":
    unittest.main()
