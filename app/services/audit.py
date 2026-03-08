"""Audit logging service."""
from __future__ import annotations

from typing import Any, Optional

from app.models import AuditAction, AuditLog
from app.store import store


def log_action(
    action: AuditAction,
    report_id: str,
    details: dict[str, Any] | None = None,
    user_id: Optional[str] = None,
    note: str = "AI-assisted recommendation",
) -> AuditLog:
    log = AuditLog(
        action=action,
        report_id=report_id,
        user_id=user_id,
        details=details or {},
        note=note,
    )
    store.add_audit_log(log)
    return log
