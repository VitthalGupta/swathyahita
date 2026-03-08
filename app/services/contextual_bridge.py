"""Contextual Bridge: adjusts urgency score based on patient history."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.models import Report, Severity
from app.store import store

logger = logging.getLogger(__name__)

HISTORY_WINDOW_DAYS = 365  # last 12 months


def adjust_score_with_history(report: Report) -> tuple[int, int]:
    """
    Compare report findings against patient's historical reports.

    Returns:
        (adjusted_score, adjustment): final score and delta applied
    """
    base_score = report.urgency_score
    cutoff = datetime.now(timezone.utc) - timedelta(days=HISTORY_WINDOW_DAYS)

    prior_reports = [
        r for r in store.get_patient_reports(report.patient_id)
        if r.report_id != report.report_id
        and r.timestamp >= cutoff
        and r.status.value == "completed"
    ]

    if not prior_reports:
        logger.info(f"No historical reports for patient {report.patient_id}; using base score {base_score}")
        return base_score, 0

    # Look at findings severity trend
    prior_critical_count = sum(
        1 for r in prior_reports for f in r.key_findings if f.severity == Severity.CRITICAL
    )
    current_critical_count = sum(1 for f in report.key_findings if f.severity == Severity.CRITICAL)

    prior_avg_score = sum(r.urgency_score for r in prior_reports) / len(prior_reports)

    adjustment = 0

    if current_critical_count > prior_critical_count:
        # New or worse critical findings
        adjustment = +2
        logger.info(f"Report {report.report_id}: new/worse findings, score +2")
    elif base_score < prior_avg_score - 1:
        # Improving compared to history
        adjustment = -1
        logger.info(f"Report {report.report_id}: improving trend, score -1")
    else:
        logger.info(f"Report {report.report_id}: stable findings, no adjustment")

    adjusted = int(min(max(base_score + adjustment, 1), 10))
    return adjusted, adjustment
