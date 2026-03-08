"""Notification service — publishes to AWS SNS for push notifications."""
from __future__ import annotations

import json
import logging

from app.config import config
from app.models import AuditAction, Notification, NotificationType, Report
from app.services.audit import log_action
from app.store import store

logger = logging.getLogger(__name__)


def _publish_to_sns(topic_arn: str, subject: str, message: dict) -> None:
    """Publish a structured message to an SNS topic."""
    if not topic_arn:
        logger.warning(f"SNS topic ARN not configured; skipping publish for: {subject}")
        return
    try:
        from app.aws.clients import get_sns
        get_sns().publish(
            TopicArn=topic_arn,
            Subject=subject[:100],  # SNS subject max 100 chars
            Message=json.dumps(message),
            MessageAttributes={
                "type": {"DataType": "String", "StringValue": message.get("type", "UNKNOWN")},
            },
        )
        logger.info(f"SNS published to {topic_arn}: {subject}")
    except Exception as exc:
        logger.error(f"SNS publish failed for {subject}: {exc}")


def _send_notification(notification: Notification, topic_arn: str) -> None:
    """Persist notification to DynamoDB and publish to SNS."""
    store.add_notification(notification)

    _publish_to_sns(
        topic_arn=topic_arn,
        subject=notification.title,
        message={
            "type": notification.type.value,
            "notificationId": notification.notification_id,
            "recipientId": notification.recipient_id,
            "reportId": notification.report_id,
            "title": notification.title,
            "body": notification.body,
            "data": notification.data,
        },
    )

    log_action(
        AuditAction.NOTIFY,
        report_id=notification.report_id,
        user_id=notification.recipient_id,
        details={
            "notification_id": notification.notification_id,
            "type": notification.type.value,
            "title": notification.title,
            "sns_topic": topic_arn,
        },
        note="AI-assisted recommendation",
    )


def notify_critical_report(report: Report, clinician_id: str = "default-clinician") -> None:
    """Publish SNS notification when a critical report (score >= 8) is generated."""
    notification = Notification(
        recipient_id=clinician_id,
        report_id=report.report_id,
        type=NotificationType.CRITICAL_REPORT,
        title=f"CRITICAL Report - Patient {report.patient_id}",
        body=(
            f"Urgency Score: {report.urgency_score}/10. "
            f"AI-generated flags for review only. Clinician review required."
        ),
        data={
            "reportId": report.report_id,
            "patientId": report.patient_id,
            "urgencyScore": report.urgency_score,
            "keyFindingsSummary": report.key_findings_summary(),
        },
    )
    _send_notification(notification, config.SNS_TOPIC_CRITICAL_REPORTS)


def notify_escalation(report: Report, dept_head_id: str | None = None) -> None:
    """Publish SNS notification when report is escalated to department head."""
    dept_head_id = dept_head_id or config.DEPT_HEAD_ID
    notification = Notification(
        recipient_id=dept_head_id,
        report_id=report.report_id,
        type=NotificationType.ESCALATION,
        title=f"ESCALATION - Critical Report Not Reviewed - Patient {report.patient_id}",
        body=(
            f"Report {report.report_id} with urgency score {report.urgency_score}/10 "
            f"was not reviewed within 5 minutes. "
            f"AI-generated flags for review only. Not a diagnostic conclusion. Clinician review required."
        ),
        data={
            "reportId": report.report_id,
            "patientId": report.patient_id,
            "urgencyScore": report.urgency_score,
            "keyFindingsSummary": report.key_findings_summary(),
        },
    )
    _send_notification(notification, config.SNS_TOPIC_ESCALATIONS)


def notify_snooze_expired(report: Report, clinician_id: str) -> None:
    """Publish SNS notification when a snoozed report's timer expires."""
    notification = Notification(
        recipient_id=clinician_id,
        report_id=report.report_id,
        type=NotificationType.SNOOZE_EXPIRED,
        title=f"Snoozed Report Restored - Patient {report.patient_id}",
        body=f"Your snoozed report (urgency {report.urgency_score}/10) is now back on your dashboard.",
        data={
            "reportId": report.report_id,
            "patientId": report.patient_id,
            "urgencyScore": report.urgency_score,
            "keyFindingsSummary": report.key_findings_summary(),
        },
    )
    _send_notification(notification, config.SNS_TOPIC_SNOOZE_EXPIRY)
