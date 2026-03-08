from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field
import uuid


class ReportType(str, Enum):
    LAB = "LAB"
    RAD = "RAD"
    PATH = "PATH"


class ReportStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    EXTRACTION_FAILED = "EXTRACTION_FAILED"
    LLM_PROCESSING_FAILED = "LLM_PROCESSING_FAILED"
    CLASSIFICATION_FAILED = "CLASSIFICATION_FAILED"


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    ABNORMAL = "ABNORMAL"
    NORMAL = "NORMAL"


class KeyFinding(BaseModel):
    finding_name: str
    finding_value: str
    reference_range: str
    clinical_significance: str
    severity: Severity = Severity.NORMAL


class Report(BaseModel):
    report_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    patient_id: str
    report_type: ReportType
    status: ReportStatus = ReportStatus.QUEUED
    original_text: str = ""
    key_findings: list[KeyFinding] = []
    urgency_score: int = 0
    base_score: int = 0
    score_adjustment: int = 0
    timestamp: datetime
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    ehr_link: str = ""
    snoozed_until: Optional[datetime] = None
    escalated_at: Optional[datetime] = None
    reviewed_at: Optional[datetime] = None
    reviewed_by: Optional[str] = None
    ocr_processed: bool = False
    disclaimer: str = "AI-generated flags for review only. Not a diagnostic conclusion. Clinician review required."
    score_note: str = "Score calculated by AI. Clinical judgment required for final prioritization."

    def key_findings_summary(self) -> list[str]:
        return [
            f"{f.finding_name} {f.finding_value} ({f.severity.value})"
            for f in self.key_findings[:3]
        ]

    def is_snoozed(self) -> bool:
        if self.snoozed_until is None:
            return False
        return datetime.utcnow() < self.snoozed_until


class FHIRPresentedForm(BaseModel):
    contentType: str
    data: str  # base64 encoded


class FHIRSubject(BaseModel):
    reference: str  # e.g. "Patient/123"


class FHIRIngestRequest(BaseModel):
    resourceType: str
    id: Optional[str] = None
    status: str
    category: str  # LAB | RAD | PATH
    subject: FHIRSubject
    issued: str  # ISO8601
    presentedForm: list[FHIRPresentedForm]


class IngestResponse(BaseModel):
    reportId: str
    status: str = "queued"
    message: str = "Report successfully ingested"


class SnoozeRequest(BaseModel):
    duration_minutes: int = Field(..., description="5, 15, 30, or 60")
    clinician_id: str = "default-clinician"


class EscalateRequest(BaseModel):
    clinician_id: str = "default-clinician"
    reason: Optional[str] = None


class ReviewRequest(BaseModel):
    clinician_id: str = "default-clinician"


class NotificationType(str, Enum):
    CRITICAL_REPORT = "CRITICAL_REPORT"
    ESCALATION = "ESCALATION"
    SNOOZE_EXPIRED = "SNOOZE_EXPIRED"


class Notification(BaseModel):
    notification_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    recipient_id: str
    report_id: str
    type: NotificationType
    title: str
    body: str
    data: dict[str, Any] = {}
    sent_at: datetime = Field(default_factory=datetime.utcnow)
    read_at: Optional[datetime] = None


class AuditAction(str, Enum):
    INGEST = "INGEST"
    CLASSIFY = "CLASSIFY"
    SCORE = "SCORE"
    SNOOZE = "SNOOZE"
    ESCALATE = "ESCALATE"
    REVIEW = "REVIEW"
    NOTIFY = "NOTIFY"


class AuditLog(BaseModel):
    log_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    action: AuditAction
    report_id: str
    user_id: Optional[str] = None
    details: dict[str, Any] = {}
    note: str = "AI-assisted recommendation"


class DashboardReport(BaseModel):
    report_id: str
    patient_id: str
    report_type: ReportType
    urgency_score: int
    timestamp: datetime
    key_findings_summary: list[str]
    ehr_link: str
    disclaimer: str
    score_note: str
    status: ReportStatus
    snoozed: bool = False
    escalated_at: Optional[datetime] = None
    reviewed_at: Optional[datetime] = None
