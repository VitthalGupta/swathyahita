"""Unit tests for Scoring Engine.

# Feature: acuity-first-middleware
# Validates: Requirements 4.1, 4.2, 4.3, 4.4
"""
import pytest

from app.models import KeyFinding, Severity
from app.services.scoring import calculate_urgency_score, get_score_breakdown


def make_finding(severity: Severity) -> KeyFinding:
    sig_map = {
        Severity.CRITICAL: "CRITICAL - Test finding",
        Severity.ABNORMAL: "ABNORMAL - Test finding",
        Severity.NORMAL: "NORMAL - Test finding",
    }
    return KeyFinding(
        finding_name="Test",
        finding_value="1.0",
        reference_range="N/A",
        clinical_significance=sig_map[severity],
        severity=severity,
    )


class TestUrgencyScoreRange:
    """Property 7: Urgency Score Range — score must be 1-10."""

    def test_single_critical(self):
        findings = [make_finding(Severity.CRITICAL)]
        score = calculate_urgency_score(findings, "test-id")
        assert 1 <= score <= 10

    def test_single_normal(self):
        findings = [make_finding(Severity.NORMAL)]
        score = calculate_urgency_score(findings, "test-id")
        assert 1 <= score <= 10

    def test_empty_findings(self):
        score = calculate_urgency_score([], "test-id")
        assert score == 1

    def test_all_critical(self):
        findings = [make_finding(Severity.CRITICAL)] * 5
        score = calculate_urgency_score(findings, "test-id")
        assert score == 10

    def test_all_normal(self):
        findings = [make_finding(Severity.NORMAL)] * 5
        score = calculate_urgency_score(findings, "test-id")
        assert score == 1


class TestWeightedScoringFormula:
    """Property 8: Weighted Scoring Formula — (sum of weighted findings) / count."""

    def test_single_abnormal(self):
        # ABNORMAL = 5, weighted avg = 5/1 = 5
        findings = [make_finding(Severity.ABNORMAL)]
        score = calculate_urgency_score(findings, "test-id")
        assert score == 5

    def test_mixed_findings(self):
        # [CRITICAL=10, ABNORMAL=5, NORMAL=1] → (10+5+1)/3 = 5.33 → 5
        findings = [
            make_finding(Severity.CRITICAL),
            make_finding(Severity.ABNORMAL),
            make_finding(Severity.NORMAL),
        ]
        score = calculate_urgency_score(findings, "test-id")
        # Has critical, so min(avg, 7) but avg=5.33, so max(5.33, 7) = 7
        assert score == 7

    def test_two_abnormal(self):
        # [ABNORMAL=5, ABNORMAL=5] → (5+5)/2 = 5
        findings = [make_finding(Severity.ABNORMAL)] * 2
        score = calculate_urgency_score(findings, "test-id")
        assert score == 5


class TestConflictResolution:
    """Property 9: Conflict Resolution — critical findings dominate."""

    def test_critical_overrides_normals(self):
        # Many normals with one critical → score >= 7
        findings = [make_finding(Severity.NORMAL)] * 9 + [make_finding(Severity.CRITICAL)]
        score = calculate_urgency_score(findings, "test-id")
        assert score >= 7

    def test_no_critical_no_override(self):
        # All normals → low score
        findings = [make_finding(Severity.NORMAL)] * 5
        score = calculate_urgency_score(findings, "test-id")
        assert score == 1


class TestScoreBreakdown:
    def test_breakdown_structure(self):
        findings = [make_finding(Severity.CRITICAL), make_finding(Severity.ABNORMAL)]
        breakdown = get_score_breakdown(findings)
        assert "findings" in breakdown
        assert "formula" in breakdown
        assert "final_score" in breakdown
        assert breakdown["final_score"] >= 7  # has critical

    def test_empty_breakdown(self):
        breakdown = get_score_breakdown([])
        assert breakdown["final_score"] == 1
