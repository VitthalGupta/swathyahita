"""Property-based tests for Scoring Engine.

# Feature: acuity-first-middleware, Property 7: Urgency Score Range
# Validates: Requirements 4.1, 4.2, 4.3, 4.4

Uses Hypothesis to verify scoring properties across many generated inputs.
"""
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.models import KeyFinding, Severity
from app.services.scoring import calculate_urgency_score

SEVERITIES = [Severity.CRITICAL, Severity.ABNORMAL, Severity.NORMAL]

finding_strategy = st.builds(
    KeyFinding,
    finding_name=st.text(min_size=1, max_size=50),
    finding_value=st.text(min_size=1, max_size=20),
    reference_range=st.text(min_size=1, max_size=30),
    clinical_significance=st.sampled_from([
        "CRITICAL - Severe finding",
        "ABNORMAL - Out of range",
        "NORMAL - Within range",
    ]),
    severity=st.sampled_from(SEVERITIES),
)


# Feature: acuity-first-middleware, Property 7: Urgency Score Range
# Validates: Requirements 4.1
@given(findings=st.lists(finding_strategy, min_size=0, max_size=20))
@settings(max_examples=100)
def test_urgency_score_always_1_to_10(findings):
    """For any set of findings, score must be between 1 and 10 inclusive."""
    score = calculate_urgency_score(findings, "prop-test-id")
    assert 1 <= score <= 10, f"Score {score} out of range [1, 10]"


# Feature: acuity-first-middleware, Property 8: Weighted Scoring Formula
# Validates: Requirements 4.2, 4.3
@given(findings=st.lists(finding_strategy, min_size=1, max_size=20))
@settings(max_examples=100)
def test_critical_finding_raises_score_above_threshold(findings):
    """Any set of findings containing a CRITICAL finding must produce score >= 7."""
    critical_finding = KeyFinding(
        finding_name="Critical Finding",
        finding_value="0.0",
        reference_range="N/A",
        clinical_significance="CRITICAL - Severe",
        severity=Severity.CRITICAL,
    )
    findings_with_critical = findings + [critical_finding]
    score = calculate_urgency_score(findings_with_critical, "prop-test-id")
    assert score >= 7, f"Critical finding should produce score >= 7, got {score}"


# Feature: acuity-first-middleware, Property 9: Conflict Resolution
# Validates: Requirements 4.4
@given(
    normals=st.lists(finding_strategy.filter(lambda f: f.severity == Severity.NORMAL), min_size=1, max_size=10),
)
@settings(max_examples=100)
def test_all_normal_findings_produce_low_score(normals):
    """A set of only NORMAL findings should produce urgency score of 1."""
    # Force all to be NORMAL severity
    findings = [
        KeyFinding(
            finding_name=f.finding_name,
            finding_value=f.finding_value,
            reference_range=f.reference_range,
            clinical_significance="NORMAL - Within range",
            severity=Severity.NORMAL,
        )
        for f in normals
    ]
    score = calculate_urgency_score(findings, "prop-test-id")
    assert score == 1, f"All-normal findings should score 1, got {score}"


# Feature: acuity-first-middleware, Property 7: Score is integer
# Validates: Requirements 4.1
@given(findings=st.lists(finding_strategy, min_size=0, max_size=10))
@settings(max_examples=100)
def test_urgency_score_is_integer(findings):
    """Score must always be an integer."""
    score = calculate_urgency_score(findings, "prop-test-id")
    assert isinstance(score, int), f"Score must be int, got {type(score)}"
