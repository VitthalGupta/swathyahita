"""Escalation service — uses SQS delay queue + asyncio for durable critical report timers."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime

from app.config import config
from app.models import AuditAction, Report
from app.services.audit import log_action
from app.services.notifications import notify_escalation
from app.store import store

logger = logging.getLogger(__name__)


def _enqueue_escalation_sqs(report_id: str, urgency_score: int) -> None:
    """
    Put a delayed SQS message for escalation.
    The message fires after ESCALATION_TIMEOUT_SECONDS (300s = 5 min).
    A Lambda consumer (or /api/internal/escalation endpoint) processes it.
    """
    if not config.SQS_ESCALATION_QUEUE_URL:
        logger.warning("SQS_ESCALATION_QUEUE_URL not configured; skipping SQS escalation enqueue")
        return
    try:
        from app.aws.clients import get_sqs
        get_sqs().send_message(
            QueueUrl=config.SQS_ESCALATION_QUEUE_URL,
            MessageBody=json.dumps({"report_id": report_id, "urgency_score": urgency_score}),
            DelaySeconds=min(config.ESCALATION_TIMEOUT_SECONDS, 900),  # SQS max = 900s
        )
        logger.info(f"Escalation SQS message queued for report {report_id} (delay={config.ESCALATION_TIMEOUT_SECONDS}s)")
    except Exception as exc:
        logger.error(f"Failed to enqueue SQS escalation for {report_id}: {exc}")


async def _escalation_timer(report_id: str, timeout: int) -> None:
    """In-process asyncio fallback timer (covers the ECS/container case)."""
    await asyncio.sleep(timeout)

    report = store.get_report(report_id)
    if report is None:
        return
    if report.reviewed_at is not None:
        logger.info(f"Report {report_id} already reviewed; skipping asyncio escalation")
        return

    await _do_escalate(report, "Not reviewed within 5 minutes (asyncio timer)")


async def _do_escalate(report: Report, reason: str) -> None:
    """Perform the actual escalation: update DynamoDB, notify via SNS, audit log."""
    report.escalated_at = datetime.utcnow()
    report.updated_at = datetime.utcnow()
    store.update_report(report)

    notify_escalation(report)

    log_action(
        AuditAction.ESCALATE,
        report_id=report.report_id,
        details={
            "escalated_at": report.escalated_at.isoformat(),
            "urgency_score": report.urgency_score,
            "reason": reason,
        },
        note="AI-assisted recommendation",
    )
    logger.warning(f"Report {report.report_id} escalated: {reason}")


def start_escalation_timer(report: Report) -> None:
    """
    Start escalation for a critical report (score >= 8):
    1. Enqueue SQS delay message (durable, survives restarts)
    2. Start asyncio task (immediate, for ECS/same-process execution)
    """
    if report.urgency_score < 8:
        return
    if store.has_escalation_task(report.report_id):
        return

    # Durable: SQS delayed message
    _enqueue_escalation_sqs(report.report_id, report.urgency_score)

    # In-process: asyncio task (fast feedback during demo / ECS)
    task = asyncio.create_task(_escalation_timer(report.report_id, config.ESCALATION_TIMEOUT_SECONDS))
    store.set_escalation_task(report.report_id, task)
    logger.info(f"Escalation started for critical report {report.report_id} (score={report.urgency_score})")


def cancel_escalation_timer(report_id: str) -> bool:
    """Cancel in-process asyncio escalation timer when report is reviewed."""
    cancelled = store.cancel_escalation_task(report_id)
    if cancelled:
        logger.info(f"Asyncio escalation timer cancelled for report {report_id}")
    # Note: the SQS message cannot be cancelled, but the consumer checks reviewed_at
    return cancelled


async def escalate_immediately(report: Report, clinician_id: str = "default-clinician") -> None:
    """Manually escalate a report (clinician-triggered)."""
    cancel_escalation_timer(report.report_id)
    await _do_escalate(report, "Manual escalation by clinician")

    log_action(
        AuditAction.ESCALATE,
        report_id=report.report_id,
        user_id=clinician_id,
        details={"reason": "Manual escalation by clinician"},
        note="Clinician action",
    )


async def process_sqs_escalation(report_id: str) -> dict:
    """
    Process an escalation SQS message.
    Called by /api/internal/escalation or a Lambda triggered by SQS.
    """
    report = store.get_report(report_id)
    if not report:
        return {"status": "skipped", "reason": "report not found"}
    if report.reviewed_at is not None:
        return {"status": "skipped", "reason": "already reviewed"}
    if report.escalated_at is not None:
        return {"status": "skipped", "reason": "already escalated"}

    await _do_escalate(report, "Not reviewed within 5 minutes (SQS consumer)")
    return {"status": "escalated", "report_id": report_id}
