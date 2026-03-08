"""Unit tests for API endpoints — moto mocking is handled by conftest.py.

# Feature: acuity-first-middleware
# Validates: Requirements 1.1, 1.3, 1.4, 6.1, 6.2, 7.1, 8.1
"""
from __future__ import annotations

import base64
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

SAMPLE_TEXT = base64.b64encode(
    b"Patient: John Doe\nHemoglobin: 7.2 g/dL (ref: 13.5-17.5)\nWBC: 2.1 K/uL (ref: 4.5-11.0)"
).decode()

VALID_FHIR_BODY = {
    "resourceType": "DiagnosticReport",
    "status": "final",
    "category": "LAB",
    "subject": {"reference": "Patient/test-001"},
    "issued": "2024-01-15T14:30:00Z",
    "presentedForm": [{"contentType": "text/plain", "data": SAMPLE_TEXT}],
}


def _add_completed_report(urgency_score: int, patient_id: str = "p1"):
    """Helper: insert a completed report directly via DynamoDB store."""
    from app.models import Report, ReportStatus, ReportType
    from app.store import DynamoDBStore
    from datetime import datetime
    store = DynamoDBStore()
    r = Report(
        patient_id=patient_id,
        report_type=ReportType.LAB,
        status=ReportStatus.COMPLETED,
        timestamp=datetime.utcnow(),
        urgency_score=urgency_score,
    )
    store.add_report(r)
    return r


# ─── Health ──────────────────────────────────────────────────────────────────

def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert resp.json()["runtime"] == "AWS"


# ─── FHIR Validation (Req 1.1, 1.3) ─────────────────────────────────────────

def test_wrong_resource_type_returns_400():
    body = {**VALID_FHIR_BODY, "resourceType": "Patient"}
    resp = client.post("/api/reports/ingest", json=body)
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "FHIR_VALIDATION_FAILED"


def test_missing_subject_returns_400():
    body = {k: v for k, v in VALID_FHIR_BODY.items() if k != "subject"}
    resp = client.post("/api/reports/ingest", json=body)
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "FHIR_VALIDATION_FAILED"


def test_invalid_status_returns_400():
    body = {**VALID_FHIR_BODY, "status": "garbage"}
    resp = client.post("/api/reports/ingest", json=body)
    assert resp.status_code == 400


def test_missing_presented_form_data_returns_400():
    body = {**VALID_FHIR_BODY, "presentedForm": [{"contentType": "text/plain"}]}
    resp = client.post("/api/reports/ingest", json=body)
    assert resp.status_code == 400


# ─── DynamoDB store ops ───────────────────────────────────────────────────────

def test_dynamodb_add_and_get_report():
    from app.models import Report, ReportStatus, ReportType
    from app.store import DynamoDBStore
    from datetime import datetime
    store = DynamoDBStore()
    r = Report(patient_id="p1", report_type=ReportType.LAB,
               status=ReportStatus.COMPLETED, timestamp=datetime.utcnow(), urgency_score=7)
    store.add_report(r)
    fetched = store.get_report(r.report_id)
    assert fetched is not None
    assert fetched.urgency_score == 7


def test_dynamodb_update_report():
    from app.models import Report, ReportStatus, ReportType
    from app.store import DynamoDBStore
    from datetime import datetime
    store = DynamoDBStore()
    r = Report(patient_id="p2", report_type=ReportType.RAD,
               status=ReportStatus.QUEUED, timestamp=datetime.utcnow(), urgency_score=3)
    store.add_report(r)
    r.urgency_score = 9
    r.status = ReportStatus.COMPLETED
    store.update_report(r)
    fetched = store.get_report(r.report_id)
    assert fetched.urgency_score == 9


def test_dynamodb_get_nonexistent_returns_none():
    from app.store import DynamoDBStore
    assert DynamoDBStore().get_report("nonexistent") is None


def test_dynamodb_list_reports():
    from app.models import Report, ReportStatus, ReportType
    from app.store import DynamoDBStore
    from datetime import datetime
    store = DynamoDBStore()
    for i in range(3):
        r = Report(patient_id=f"p{i}", report_type=ReportType.LAB,
                   status=ReportStatus.COMPLETED, timestamp=datetime.utcnow())
        store.add_report(r)
    assert len(store.list_reports()) >= 3


# ─── Dashboard (Req 6.1, 7.1, 8.1) ──────────────────────────────────────────

def test_chronological_view_returns_ok():
    resp = client.get("/api/dashboard/chronological")
    assert resp.status_code == 200
    assert resp.json()["view"] == "chronological"


def test_prioritized_view_returns_ok():
    resp = client.get("/api/dashboard/prioritized")
    assert resp.status_code == 200
    data = resp.json()
    assert data["view"] == "prioritized"
    assert "disclaimer" in data


def test_prioritized_sorted_by_score_desc():
    _add_completed_report(3, "pa")
    _add_completed_report(9, "pb")
    _add_completed_report(6, "pc")
    resp = client.get("/api/dashboard/prioritized")
    scores = [r["urgency_score"] for r in resp.json()["reports"]]
    assert scores == sorted(scores, reverse=True)


def test_chronological_sorted_by_timestamp_desc():
    from datetime import datetime, timedelta
    from app.models import Report, ReportStatus, ReportType
    from app.store import DynamoDBStore
    store = DynamoDBStore()
    now = datetime.utcnow()
    for delta in [120, 60, 0]:
        r = Report(patient_id=f"p-ts-{delta}", report_type=ReportType.LAB,
                   status=ReportStatus.COMPLETED, timestamp=now - timedelta(minutes=delta))
        store.add_report(r)
    resp = client.get("/api/dashboard/chronological")
    timestamps = [r["timestamp"] for r in resp.json()["reports"]]
    assert timestamps == sorted(timestamps, reverse=True)


def test_report_not_found_returns_404():
    resp = client.get("/api/reports/nonexistent-id")
    assert resp.status_code == 404


# ─── Actions (Req 9, 10) ─────────────────────────────────────────────────────

def test_snooze_invalid_duration_returns_400():
    r = _add_completed_report(5)
    resp = client.post(f"/api/reports/{r.report_id}/snooze", json={"duration_minutes": 99})
    assert resp.status_code == 400


def test_snooze_valid_duration_returns_200():
    r = _add_completed_report(5)
    resp = client.post(f"/api/reports/{r.report_id}/snooze", json={"duration_minutes": 15})
    assert resp.status_code == 200
    assert resp.json()["snoozed"] is True


def test_review_report_returns_200():
    r = _add_completed_report(5)
    resp = client.post(f"/api/reports/{r.report_id}/review", json={"clinician_id": "dr-smith"})
    assert resp.status_code == 200
    assert resp.json()["reviewed"] is True


def test_review_nonexistent_report_returns_404():
    resp = client.post("/api/reports/fake-id/review", json={"clinician_id": "doc1"})
    assert resp.status_code == 404
