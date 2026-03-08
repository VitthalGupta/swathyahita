"""Report prioritization — sorts reports by urgency score."""
from __future__ import annotations

from app.models import DashboardReport, Report, ReportStatus
from app.store import store


def _to_dashboard_report(report: Report) -> DashboardReport:
    return DashboardReport(
        report_id=report.report_id,
        patient_id=report.patient_id,
        report_type=report.report_type,
        urgency_score=report.urgency_score,
        timestamp=report.timestamp,
        key_findings_summary=report.key_findings_summary(),
        ehr_link=report.ehr_link,
        disclaimer=report.disclaimer,
        score_note=report.score_note,
        status=report.status,
        snoozed=report.is_snoozed(),
        escalated_at=report.escalated_at,
        reviewed_at=report.reviewed_at,
    )


def get_prioritized_list(include_snoozed: bool = False) -> list[DashboardReport]:
    """Return reports sorted by urgency score DESC, timestamp DESC as tiebreaker."""
    reports = [
        r for r in store.list_reports()
        if r.status == ReportStatus.COMPLETED
        and (include_snoozed or not r.is_snoozed())
    ]
    reports.sort(key=lambda r: (r.urgency_score, r.timestamp), reverse=True)
    return [_to_dashboard_report(r) for r in reports]


def get_chronological_list(include_snoozed: bool = False) -> list[DashboardReport]:
    """Return reports sorted by timestamp DESC (most recent first)."""
    reports = [
        r for r in store.list_reports()
        if r.status == ReportStatus.COMPLETED
        and (include_snoozed or not r.is_snoozed())
    ]
    reports.sort(key=lambda r: r.timestamp, reverse=True)
    return [_to_dashboard_report(r) for r in reports]
