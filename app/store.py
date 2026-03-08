"""DynamoDB-backed storage for AFM. Replaces in-memory store with persistent AWS storage."""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from app.config import config
from app.models import AuditLog, Notification, Report

logger = logging.getLogger(__name__)


def _serialize(obj) -> dict:
    """Serialize a Pydantic model to a DynamoDB item (stores JSON body in 'data' attr)."""
    return {"data": obj.model_dump_json()}


def _deserialize_report(item: dict) -> Report:
    return Report.model_validate_json(item["data"])


def _deserialize_audit(item: dict) -> AuditLog:
    return AuditLog.model_validate_json(item["data"])


def _deserialize_notification(item: dict) -> Notification:
    return Notification.model_validate_json(item["data"])


class DynamoDBStore:
    """
    DynamoDB-backed store with the same interface as the previous InMemoryStore.

    DynamoDB tables required:
      - {DYNAMODB_TABLE_REPORTS}:       PK=report_id (S)
      - {DYNAMODB_TABLE_AUDIT}:         PK=log_id (S)
      - {DYNAMODB_TABLE_NOTIFICATIONS}: PK=notification_id (S)

    All items store the full Pydantic model as a JSON string in 'data' to avoid
    DynamoDB Decimal/float type restrictions.
    """

    def __init__(self) -> None:
        # In-process asyncio task tracking (ephemeral; SQS messages provide durability)
        self._escalation_tasks: dict[str, asyncio.Task] = {}
        self._snooze_tasks: dict[str, asyncio.Task] = {}

    def _reports_table(self):
        from app.aws.clients import get_dynamodb_table
        return get_dynamodb_table(config.DYNAMODB_TABLE_REPORTS)

    def _audit_table(self):
        from app.aws.clients import get_dynamodb_table
        return get_dynamodb_table(config.DYNAMODB_TABLE_AUDIT)

    def _notifications_table(self):
        from app.aws.clients import get_dynamodb_table
        return get_dynamodb_table(config.DYNAMODB_TABLE_NOTIFICATIONS)

    # ─── Reports ─────────────────────────────────────────────────────────────

    def add_report(self, report: Report) -> None:
        self._reports_table().put_item(
            Item={"report_id": report.report_id, **_serialize(report)}
        )

    def get_report(self, report_id: str) -> Optional[Report]:
        response = self._reports_table().get_item(Key={"report_id": report_id})
        item = response.get("Item")
        if not item:
            return None
        return _deserialize_report(item)

    def update_report(self, report: Report) -> None:
        self._reports_table().update_item(
            Key={"report_id": report.report_id},
            UpdateExpression="SET #d = :data",
            ExpressionAttributeNames={"#d": "data"},
            ExpressionAttributeValues={":data": report.model_dump_json()},
        )

    def list_reports(self) -> list[Report]:
        response = self._reports_table().scan()
        return [_deserialize_report(item) for item in response.get("Items", [])]

    def get_patient_reports(self, patient_id: str) -> list[Report]:
        # For production, add a GSI on patient_id for efficiency
        return [r for r in self.list_reports() if r.patient_id == patient_id]

    # ─── Audit logs ──────────────────────────────────────────────────────────

    def add_audit_log(self, log: AuditLog) -> None:
        self._audit_table().put_item(
            Item={"log_id": log.log_id, **_serialize(log)}
        )

    def list_audit_logs(self) -> list[AuditLog]:
        response = self._audit_table().scan()
        return [_deserialize_audit(item) for item in response.get("Items", [])]

    # ─── Notifications ───────────────────────────────────────────────────────

    def add_notification(self, notification: Notification) -> None:
        self._notifications_table().put_item(
            Item={"notification_id": notification.notification_id, **_serialize(notification)}
        )

    def list_notifications(self) -> list[Notification]:
        response = self._notifications_table().scan()
        return [_deserialize_notification(item) for item in response.get("Items", [])]

    # ─── Escalation task management (in-process asyncio) ─────────────────────

    def set_escalation_task(self, report_id: str, task: asyncio.Task) -> None:
        self._escalation_tasks[report_id] = task

    def cancel_escalation_task(self, report_id: str) -> bool:
        task = self._escalation_tasks.pop(report_id, None)
        if task and not task.done():
            task.cancel()
            return True
        return False

    def has_escalation_task(self, report_id: str) -> bool:
        return report_id in self._escalation_tasks

    # ─── Snooze task management (in-process asyncio) ─────────────────────────

    def set_snooze_task(self, report_id: str, task: asyncio.Task) -> None:
        self._snooze_tasks[report_id] = task

    def cancel_snooze_task(self, report_id: str) -> bool:
        task = self._snooze_tasks.pop(report_id, None)
        if task and not task.done():
            task.cancel()
            return True
        return False

    # ─── Processing queue (managed by SQS) ───────────────────────────────────

    def pop_from_queue(self) -> Optional[str]:
        """Processing queue is managed by SQS; returns None here."""
        return None


# Singleton store instance
store = DynamoDBStore()
