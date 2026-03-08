"""FHIR report ingestion and validation service."""
from __future__ import annotations

import base64
from datetime import datetime

from app.models import (
    FHIRIngestRequest,
    IngestResponse,
    Report,
    ReportStatus,
    ReportType,
)
from app.store import store
from app.services.audit import log_action
from app.models import AuditAction

VALID_STATUSES = {"final", "preliminary", "amended"}
VALID_CATEGORIES = {"LAB", "RAD", "PATH"}


class FHIRValidationError(Exception):
    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


def validate_fhir(data: dict) -> FHIRIngestRequest:
    """Validate a raw dict against required FHIR DiagnosticReport fields."""
    if data.get("resourceType") != "DiagnosticReport":
        raise FHIRValidationError("resourceType must be 'DiagnosticReport'")

    for field in ("status", "category", "subject", "issued", "presentedForm"):
        if field not in data:
            raise FHIRValidationError(f"Missing required field: {field}")

    if data["status"] not in VALID_STATUSES:
        raise FHIRValidationError(
            f"Invalid status '{data['status']}'. Must be one of: {', '.join(VALID_STATUSES)}"
        )

    category = data.get("category", "")
    if isinstance(category, list):
        # FHIR category can be an array of CodeableConcept
        codes = []
        for cat in category:
            if isinstance(cat, dict):
                for coding in cat.get("coding", []):
                    codes.append(coding.get("code", ""))
        category = next((c for c in codes if c in VALID_CATEGORIES), category[0] if category else "")
    if category not in VALID_CATEGORIES:
        raise FHIRValidationError(
            f"Invalid category '{category}'. Must be one of: {', '.join(VALID_CATEGORIES)}"
        )

    subject = data.get("subject", {})
    if not isinstance(subject, dict) or not subject.get("reference"):
        raise FHIRValidationError("Missing required field: subject.reference")

    presented = data.get("presentedForm", [])
    if not presented or not isinstance(presented, list):
        raise FHIRValidationError("presentedForm must be a non-empty array")
    if not presented[0].get("data"):
        raise FHIRValidationError("presentedForm[0].data is required (base64 encoded content)")

    return FHIRIngestRequest(
        resourceType=data["resourceType"],
        id=data.get("id"),
        status=data["status"],
        category=category,
        subject={"reference": subject["reference"]},
        issued=data["issued"],
        presentedForm=[{"contentType": p.get("contentType", "text/plain"), "data": p["data"]} for p in presented],
    )


def extract_patient_id(fhir: FHIRIngestRequest) -> str:
    """Extract patient ID from FHIR subject reference (e.g. 'Patient/123' → '123')."""
    ref = fhir.subject.reference
    if "/" in ref:
        return ref.split("/")[-1]
    return ref


def decode_report_content(fhir: FHIRIngestRequest) -> tuple[str, bool]:
    """Decode base64 content from presentedForm. Returns (content_bytes_or_text, is_pdf)."""
    form = fhir.presentedForm[0]
    raw = base64.b64decode(form.data)
    is_pdf = form.contentType == "application/pdf"
    if not is_pdf:
        return raw.decode("utf-8", errors="replace"), False
    return raw.decode("latin-1"), True  # return raw bytes as str for PDF extractor


def ingest_report(fhir: FHIRIngestRequest, raw_content: bytes, is_pdf: bool) -> Report:
    """Create and store a new Report from validated FHIR data."""
    patient_id = extract_patient_id(fhir)
    try:
        timestamp = datetime.fromisoformat(fhir.issued.replace("Z", "+00:00"))
    except ValueError:
        timestamp = datetime.utcnow()

    report = Report(
        patient_id=patient_id,
        report_type=ReportType(fhir.category),
        status=ReportStatus.QUEUED,
        timestamp=timestamp,
        ehr_link=f"https://ehr.example.com/reports/",  # updated after ID assigned
    )
    report.ehr_link = f"https://ehr.example.com/reports/{report.report_id}"
    store.add_report(report)

    log_action(
        action=AuditAction.INGEST,
        report_id=report.report_id,
        details={"patient_id": patient_id, "report_type": fhir.category, "is_pdf": is_pdf},
    )

    return report
