"""Snooze service — temporarily hides reports from the dashboard."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from app.models import AuditAction, Report
from app.services.audit import log_action
from app.services.notifications import notify_snooze_expired
from app.store import store

logger = logging.getLogger(__name__)

VALID_DURATIONS = {5, 15, 30, 60}


async def _snooze_timer(report_id: str, clinician_id: str, duration_seconds: int) -> None:
    """Wait for snooze to expire, then restore report and notify."""
    await asyncio.sleep(duration_seconds)

    report = store.get_report(report_id)
    if report is None:
        return

    report.snoozed_until = None
    report.updated_at = datetime.utcnow()
    store.update_report(report)

    notify_snooze_expired(report, clinician_id)
    logger.info(f"Snooze expired for report {report_id}; restored to dashboard")


def snooze_report(report: Report, duration_minutes: int, clinician_id: str) -> datetime:
    """
    Snooze a report for the specified duration.

    Args:
        report: The report to snooze
        duration_minutes: Must be one of 5, 15, 30, 60
        clinician_id: ID of the clinician performing the snooze

    Returns:
        snoozed_until: datetime when snooze expires
    """
    if duration_minutes not in VALID_DURATIONS:
        raise ValueError(f"Invalid snooze duration. Must be one of: {sorted(VALID_DURATIONS)}")

    # Cancel any existing snooze
    store.cancel_snooze_task(report.report_id)

    snoozed_until = datetime.utcnow() + timedelta(minutes=duration_minutes)
    report.snoozed_until = snoozed_until
    report.updated_at = datetime.utcnow()
    store.update_report(report)

    # Start async restore timer
    task = asyncio.create_task(
        _snooze_timer(report.report_id, clinician_id, duration_minutes * 60)
    )
    store.set_snooze_task(report.report_id, task)

    log_action(
        AuditAction.SNOOZE,
        report_id=report.report_id,
        user_id=clinician_id,
        details={
            "duration_minutes": duration_minutes,
            "snoozed_until": snoozed_until.isoformat(),
        },
        note="Clinician action",
    )
    logger.info(f"Report {report.report_id} snoozed for {duration_minutes} min by {clinician_id}")
    return snoozed_until


def unsnooze_report(report: Report, clinician_id: str) -> None:
    """Manually unsnooze a report — immediately restores it to the dashboard."""
    store.cancel_snooze_task(report.report_id)
    report.snoozed_until = None
    report.updated_at = datetime.utcnow()
    store.update_report(report)

    log_action(
        AuditAction.SNOOZE,
        report_id=report.report_id,
        user_id=clinician_id,
        details={"action": "manual_unsnooze"},
        note="Clinician action",
    )
    logger.info(f"Report {report.report_id} manually unsnoozed by {clinician_id}")
