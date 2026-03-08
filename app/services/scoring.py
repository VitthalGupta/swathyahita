"""Urgency score calculation engine."""
from __future__ import annotations

from app.models import AuditAction, KeyFinding, ReportType, Severity
from app.services.audit import log_action

SEVERITY_WEIGHTS: dict[Severity, int] = {
    Severity.CRITICAL: 10,
    Severity.ABNORMAL: 5,
    Severity.NORMAL: 1,
}


def calculate_urgency_score(findings: list[KeyFinding], report_id: str) -> int:
    """
    Calculate urgency score (1-10) from key findings.

    Formula: weighted_average = sum(weights) / count
    Conflict resolution: if any CRITICAL finding, score >= 7.
    Result clamped to [1, 10].
    """
    if not findings:
        score = 1
        log_action(AuditAction.SCORE, report_id, {"score": score, "reason": "no findings"})
        return score

    weights = [SEVERITY_WEIGHTS[f.severity] for f in findings]
    raw_score = sum(weights) / len(weights)

    has_critical = any(f.severity == Severity.CRITICAL for f in findings)
    if has_critical:
        # Conflict resolution: critical findings dominate
        raw_score = max(raw_score, 7.0)

    score = int(round(min(max(raw_score, 1.0), 10.0)))

    log_action(
        AuditAction.SCORE,
        report_id,
        {
            "score": score,
            "raw_score": raw_score,
            "finding_count": len(findings),
            "has_critical": has_critical,
            "weights": weights,
        },
    )
    return score


def get_score_breakdown(findings: list[KeyFinding]) -> dict:
    """Return score calculation breakdown for dashboard display."""
    if not findings:
        return {"findings": [], "formula": "No findings", "raw_score": 1, "final_score": 1}

    rows = []
    for f in findings:
        rows.append({
            "finding_name": f.finding_name,
            "severity": f.severity.value,
            "weight": SEVERITY_WEIGHTS[f.severity],
        })

    weights = [SEVERITY_WEIGHTS[f.severity] for f in findings]
    raw = sum(weights) / len(weights)
    has_critical = any(f.severity == Severity.CRITICAL for f in findings)
    if has_critical:
        raw = max(raw, 7.0)
    final = int(round(min(max(raw, 1.0), 10.0)))

    return {
        "findings": rows,
        "formula": f"({' + '.join(str(w) for w in weights)}) / {len(weights)} = {sum(weights)/len(weights):.2f}",
        "conflict_resolved": has_critical,
        "raw_score": round(raw, 2),
        "final_score": final,
    }
