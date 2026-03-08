# AFM API Reference

Base URL: `http://localhost:8000` (local) or your deployed endpoint.

Interactive docs: `GET /docs` (Swagger UI) · `GET /redoc` (ReDoc)

> All report responses include `"disclaimer"` and `"scoreNote"` fields as required by Req 13.

---

## Report Ingestion

### `POST /api/reports/ingest`

Ingest a FHIR DiagnosticReport. Runs the full pipeline:
**validate → S3 → Bedrock classify → score → contextualize → store → notify**

**Request body** (FHIR DiagnosticReport):

```json
{
  "resourceType": "DiagnosticReport",
  "status": "final",
  "category": "LAB",
  "subject": { "reference": "Patient/patient-001" },
  "issued": "2024-01-15T14:30:00Z",
  "presentedForm": [
    {
      "contentType": "text/plain",
      "data": "<base64-encoded report text or PDF>"
    }
  ]
}
```

| Field | Type | Required | Values |
|---|---|---|---|
| `resourceType` | string | ✅ | `"DiagnosticReport"` |
| `status` | string | ✅ | `final` · `preliminary` · `amended` |
| `category` | string | ✅ | `LAB` · `RAD` · `PATH` |
| `subject.reference` | string | ✅ | `"Patient/<id>"` |
| `issued` | string | ✅ | ISO 8601 timestamp |
| `presentedForm[0].contentType` | string | ✅ | `text/plain` · `application/pdf` |
| `presentedForm[0].data` | string | ✅ | base64-encoded content |

**201 Response:**
```json
{
  "reportId": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "status": "queued",
  "message": "Report successfully ingested"
}
```

**400 Response (FHIR validation failure):**
```json
{
  "status": 400,
  "error": "FHIR_VALIDATION_FAILED",
  "details": "Missing required field: subject.reference"
}
```

**422 Response (extraction/LLM failure):**
```json
{
  "error": "LLM_PROCESSING_FAILED",
  "details": "Failed to extract key findings after 3 attempts",
  "reportId": "f47ac10b-..."
}
```

---

## Report Listing

### `GET /api/reports/`

Returns all reports (any status) from DynamoDB.

```json
[
  {
    "reportId": "f47ac10b-...",
    "patientId": "patient-001",
    "reportType": "LAB",
    "status": "completed",
    "urgencyScore": 9,
    "timestamp": "2024-01-15T14:30:00",
    "snoozed": false
  }
]
```

### `GET /api/reports/{report_id}`

Full report details including score breakdown, key findings, and pre-signed S3 URL.

```json
{
  "reportId": "f47ac10b-...",
  "patientId": "patient-001",
  "reportType": "LAB",
  "status": "completed",
  "urgencyScore": 9,
  "baseScore": 8,
  "scoreAdjustment": 1,
  "scoreBreakdown": {
    "findings": [
      { "finding_name": "Hemoglobin", "severity": "CRITICAL", "weight": 10 },
      { "finding_name": "WBC", "severity": "ABNORMAL", "weight": 5 }
    ],
    "formula": "(10 + 5) / 2 = 7.50",
    "conflict_resolved": true,
    "raw_score": 7.5,
    "final_score": 9
  },
  "keyFindings": [
    {
      "finding_name": "Hemoglobin",
      "finding_value": "6.8 g/dL",
      "reference_range": "12.0-16.0 g/dL",
      "clinical_significance": "CRITICAL - Severe anemia",
      "severity": "CRITICAL"
    }
  ],
  "s3PdfUrl": "https://s3.presigned.url/...",
  "ehrLink": "s3://afm-pdf-reports/reports/f47ac10b-/original.pdf",
  "disclaimer": "AI-generated flags for review only. Not a diagnostic conclusion. Clinician review required.",
  "scoreNote": "Score calculated by AI. Clinical judgment required for final prioritization.",
  "snoozed": false,
  "snoozedUntil": null,
  "escalatedAt": null,
  "reviewedAt": null,
  "ocrProcessed": false
}
```

**404:** `{ "error": "REPORT_NOT_FOUND", "reportId": "..." }`

---

## Dashboard

### `GET /api/dashboard/prioritized`

Reports sorted by urgency score descending. Includes color coding for UI.

Query params:
- `include_snoozed` (bool, default `false`) — include currently snoozed reports

```json
{
  "view": "prioritized",
  "disclaimer": "AI-generated flags for review only...",
  "reports": [
    {
      "report_id": "...",
      "patient_id": "patient-001",
      "report_type": "LAB",
      "urgency_score": 9,
      "timestamp": "2024-01-15T14:30:00",
      "key_findings_summary": [
        "Hemoglobin 6.8 g/dL (CRITICAL)",
        "WBC 1.9 K/uL (ABNORMAL)"
      ],
      "urgencyColor": "red",
      "snoozed": false,
      "escalatedAt": null,
      "reviewedAt": null
    }
  ]
}
```

**Color codes:** `red` (8–10) · `yellow` (5–7) · `green` (1–4)

### `GET /api/dashboard/chronological`

Same shape as prioritized but sorted by `timestamp` descending.

---

## Actions

### `POST /api/reports/{id}/snooze`

Hide a report from the dashboard for a set duration. Fires SNS notification on expiry.

```json
{ "duration_minutes": 15, "clinician_id": "dr-smith" }
```

Valid durations: `5` · `15` · `30` · `60`

```json
{
  "reportId": "...",
  "snoozed": true,
  "snoozedUntil": "2024-01-15T15:00:00",
  "durationMinutes": 15,
  "message": "Report snoozed for 15 minutes"
}
```

### `POST /api/reports/{id}/unsnooze`

Immediately restore a snoozed report to the dashboard.

Query param: `clinician_id` (string, default `"default-clinician"`)

### `POST /api/reports/{id}/escalate`

Manually escalate a report to the department head. Publishes to `SNS_TOPIC_ESCALATIONS`.

```json
{ "clinician_id": "dr-smith", "reason": "Patient deteriorating" }
```

```json
{
  "reportId": "...",
  "escalated": true,
  "escalatedAt": "2024-01-15T14:35:00",
  "message": "Report escalated to department head"
}
```

### `POST /api/reports/{id}/review`

Mark a report as reviewed. Cancels the 5-minute escalation timer.

```json
{ "clinician_id": "dr-smith" }
```

```json
{
  "reportId": "...",
  "reviewed": true,
  "reviewedAt": "2024-01-15T14:33:00",
  "reviewedBy": "dr-smith",
  "message": "Report marked as reviewed"
}
```

---

## Audit & Internal

### `GET /api/reports/audit/logs`

Returns all audit log entries from DynamoDB.

### `POST /api/reports/internal/escalation`

Process an SQS escalation message. Called by an AWS Lambda triggered by SQS or an EventBridge cron.

```json
{ "report_id": "f47ac10b-..." }
```

```json
{ "status": "escalated", "report_id": "f47ac10b-..." }
```

or `{ "status": "skipped", "reason": "already reviewed" }` if already handled.

---

## Health

### `GET /health`

```json
{ "status": "ok", "service": "AFM Backend", "runtime": "AWS" }
```
