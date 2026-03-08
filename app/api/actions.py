"""Report action endpoints — snooze, escalate, review."""
from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException

from app.models import AuditAction, EscalateRequest, ReviewRequest, SnoozeRequest
from app.services.audit import log_action
from app.services.escalation import cancel_escalation_timer, escalate_immediately
from app.services.snooze import snooze_report, unsnooze_report
from app.store import store

router = APIRouter(prefix="/api/reports", tags=["actions"])
logger = logging.getLogger(__name__)


def _get_report_or_404(report_id: str):
    report = store.get_report(report_id)
    if not report:
        raise HTTPException(status_code=404, detail={"error": "REPORT_NOT_FOUND", "reportId": report_id})
    return report


@router.post("/{report_id}/snooze")
async def snooze(report_id: str, body: SnoozeRequest) -> dict:
    """Snooze a report for 5, 15, 30, or 60 minutes."""
    report = _get_report_or_404(report_id)

    try:
        snoozed_until = snooze_report(report, body.duration_minutes, body.clinician_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": "INVALID_DURATION", "details": str(exc)})

    return {
        "reportId": report_id,
        "snoozed": True,
        "snoozedUntil": snoozed_until.isoformat(),
        "durationMinutes": body.duration_minutes,
        "message": f"Report snoozed for {body.duration_minutes} minutes",
    }


@router.post("/{report_id}/unsnooze")
async def unsnooze(report_id: str, clinician_id: str = "default-clinician") -> dict:
    """Manually unsnooze a report — immediately restores it to dashboard."""
    report = _get_report_or_404(report_id)
    unsnooze_report(report, clinician_id)
    return {"reportId": report_id, "snoozed": False, "message": "Report restored to dashboard"}


@router.post("/{report_id}/escalate")
async def escalate(report_id: str, body: EscalateRequest) -> dict:
    """Manually escalate a report to the department head."""
    report = _get_report_or_404(report_id)

    await escalate_immediately(report, body.clinician_id)

    return {
        "reportId": report_id,
        "escalated": True,
        "escalatedAt": report.escalated_at.isoformat() if report.escalated_at else None,
        "message": "Report escalated to department head",
    }


@router.post("/{report_id}/review")
async def mark_reviewed(report_id: str, body: ReviewRequest) -> dict:
    """Mark a report as reviewed — cancels any pending escalation timer."""
    report = _get_report_or_404(report_id)

    report.reviewed_at = datetime.utcnow()
    report.reviewed_by = body.clinician_id
    report.updated_at = datetime.utcnow()
    store.update_report(report)

    cancel_escalation_timer(report_id)

    log_action(
        AuditAction.REVIEW,
        report_id=report_id,
        user_id=body.clinician_id,
        details={"reviewed_at": report.reviewed_at.isoformat()},
        note="Clinician action",
    )

    return {
        "reportId": report_id,
        "reviewed": True,
        "reviewedAt": report.reviewed_at.isoformat(),
        "reviewedBy": body.clinician_id,
        "message": "Report marked as reviewed",
    }
