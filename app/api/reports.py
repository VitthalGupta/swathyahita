"""Report ingestion and listing API endpoints."""
from __future__ import annotations

import base64
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app.models import (
    AuditAction,
    IngestResponse,
    ReportStatus,
)
from app.services.audit import log_action
from app.services.classifier import extract_key_findings
from app.services.contextual_bridge import adjust_score_with_history
from app.services.escalation import process_sqs_escalation, start_escalation_timer
from app.services.ingestion import FHIRValidationError, ingest_report, validate_fhir
from app.services.notifications import notify_critical_report
from app.services.pdf_extractor import extract_text_from_pdf, upload_pdf_to_s3
from app.services.scoring import calculate_urgency_score
from app.store import store

router = APIRouter(prefix="/api/reports", tags=["reports"])
logger = logging.getLogger(__name__)


@router.post("/ingest", response_model=IngestResponse, status_code=201)
async def ingest(request: Request) -> IngestResponse:
    """
    Ingest a FHIR DiagnosticReport.
    Pipeline: validate → S3 upload → extract text → Bedrock classify → score → adjust → DynamoDB store.
    """
    try:
        body: dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail={
            "error": "INVALID_JSON",
            "details": "Request body must be valid JSON",
        })

    # Step 1: FHIR validation
    try:
        fhir = validate_fhir(body)
    except FHIRValidationError as exc:
        raise HTTPException(status_code=400, detail={
            "status": 400,
            "error": "FHIR_VALIDATION_FAILED",
            "details": exc.detail,
        })

    # Step 2: Decode content
    try:
        raw_bytes = base64.b64decode(fhir.presentedForm[0].data)
        is_pdf = fhir.presentedForm[0].contentType == "application/pdf"
    except Exception as exc:
        raise HTTPException(status_code=400, detail={
            "error": "DECODE_FAILED",
            "details": f"Failed to decode presentedForm.data: {exc}",
        })

    # Step 3: Create report record in DynamoDB (queued status)
    report = ingest_report(fhir, raw_bytes, is_pdf)

    # Step 4: Upload original PDF to S3 (preserves original, Req 14.1)
    if is_pdf:
        s3_uri = upload_pdf_to_s3(raw_bytes, report.report_id)
        if s3_uri:
            report.ehr_link = s3_uri  # S3 link for original document access
            store.update_report(report)

    # Step 5: Extract text
    report.status = ReportStatus.PROCESSING
    store.update_report(report)

    try:
        if is_pdf:
            text, ocr_processed = extract_text_from_pdf(raw_bytes)
            report.ocr_processed = ocr_processed
        else:
            text = raw_bytes.decode("utf-8", errors="replace")
        report.original_text = text
    except Exception as exc:
        logger.error(f"PDF extraction failed for {report.report_id}: {exc}")
        report.status = ReportStatus.EXTRACTION_FAILED
        store.update_report(report)
        raise HTTPException(status_code=422, detail={
            "error": "EXTRACTION_FAILED",
            "details": str(exc),
            "reportId": report.report_id,
        })

    # Step 6: Bedrock LLM classification
    try:
        findings = extract_key_findings(text, report.report_type)
        report.key_findings = findings
        log_action(AuditAction.CLASSIFY, report.report_id, {"finding_count": len(findings)})
    except Exception as exc:
        logger.error(f"Bedrock classification failed for {report.report_id}: {exc}")
        report.status = ReportStatus.LLM_PROCESSING_FAILED
        store.update_report(report)
        raise HTTPException(status_code=422, detail={
            "error": "LLM_PROCESSING_FAILED",
            "details": str(exc),
            "reportId": report.report_id,
        })

    # Step 7: Score calculation
    base_score = calculate_urgency_score(findings, report.report_id)
    report.base_score = base_score
    report.urgency_score = base_score
    store.update_report(report)

    # Step 8: Contextual bridge (patient history from DynamoDB)
    adjusted_score, adjustment = adjust_score_with_history(report)
    report.urgency_score = adjusted_score
    report.score_adjustment = adjustment
    report.status = ReportStatus.COMPLETED
    store.update_report(report)

    # Step 9: SNS notifications + SQS escalation for critical reports
    if report.urgency_score >= 8:
        notify_critical_report(report)
        start_escalation_timer(report)

    return IngestResponse(reportId=report.report_id)


@router.get("/", response_model=list[dict])
async def list_reports() -> list[dict]:
    """Return all reports from DynamoDB."""
    reports = store.list_reports()
    return [
        {
            "reportId": r.report_id,
            "patientId": r.patient_id,
            "reportType": r.report_type.value,
            "status": r.status.value,
            "urgencyScore": r.urgency_score,
            "timestamp": r.timestamp.isoformat(),
            "snoozed": r.is_snoozed(),
        }
        for r in reports
    ]


@router.get("/audit/logs")
async def get_audit_logs() -> list[dict]:
    """Return all audit logs from DynamoDB."""
    return [log.model_dump() for log in store.list_audit_logs()]


@router.get("/{report_id}")
async def get_report(report_id: str) -> dict:
    """Return full report details including score breakdown."""
    report = store.get_report(report_id)
    if not report:
        raise HTTPException(status_code=404, detail={"error": "REPORT_NOT_FOUND", "reportId": report_id})

    from app.services.scoring import get_score_breakdown
    from app.services.pdf_extractor import get_pdf_presigned_url
    breakdown = get_score_breakdown(report.key_findings)
    presigned_url = get_pdf_presigned_url(report_id)

    return {
        "reportId": report.report_id,
        "patientId": report.patient_id,
        "reportType": report.report_type.value,
        "status": report.status.value,
        "urgencyScore": report.urgency_score,
        "baseScore": report.base_score,
        "scoreAdjustment": report.score_adjustment,
        "scoreBreakdown": breakdown,
        "timestamp": report.timestamp.isoformat(),
        "keyFindings": [f.model_dump() for f in report.key_findings],
        "s3PdfUrl": presigned_url,
        "ehrLink": report.ehr_link,
        "disclaimer": report.disclaimer,
        "scoreNote": report.score_note,
        "snoozed": report.is_snoozed(),
        "snoozedUntil": report.snoozed_until.isoformat() if report.snoozed_until else None,
        "escalatedAt": report.escalated_at.isoformat() if report.escalated_at else None,
        "reviewedAt": report.reviewed_at.isoformat() if report.reviewed_at else None,
        "ocrProcessed": report.ocr_processed,
    }


@router.post("/internal/escalation")
async def process_escalation(body: dict) -> dict:
    """
    Internal endpoint for processing SQS escalation messages.
    Can be called by:
      - An AWS Lambda triggered by SQS
      - An EventBridge cron for batch escalation checks
    """
    report_id = body.get("report_id")
    if not report_id:
        raise HTTPException(status_code=400, detail={"error": "report_id required"})
    result = await process_sqs_escalation(report_id)
    return result
