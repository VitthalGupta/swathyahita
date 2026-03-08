# Acuity-First Middleware (AFM)

> AI-powered diagnostic report prioritization for clinicians — built on AWS, powered by Claude on Bedrock.

**AFM reorders patient diagnostic reports by clinical urgency rather than chronological order**, surfacing critical cases instantly so clinicians can act before it's too late.

> ⚠️ **Disclaimer**: AI-generated flags are for review only. Not a diagnostic conclusion. Clinician review required.

---

## Overview

AFM augments existing EHR systems (Epic, Cerner) without replacing them. When a lab result, radiology report, or pathology finding arrives, AFM:

1. **Ingests** it via FHIR DiagnosticReport API
2. **Extracts** key findings using Claude (AWS Bedrock)
3. **Scores** clinical urgency from 1–10 using weighted evidence
4. **Contextualizes** scores against the patient's 12-month history
5. **Surfaces** critical reports (score ≥ 8) at the top of the dashboard — with color-coded urgency, snooze, escalation, and push notifications

```
FHIR Report → S3 (PDF) → Bedrock (Claude) → DynamoDB → SNS/SQS → Dashboard
```

---

## AWS Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    AFM Backend (FastAPI)                 │
│                                                         │
│  POST /api/reports/ingest                               │
│       │                                                 │
│       ├─► S3  ──────── store original PDF               │
│       ├─► Bedrock ───── Claude 3.5 Sonnet extraction    │
│       ├─► DynamoDB ──── persist report + audit logs     │
│       ├─► SNS ──────── push notification (score ≥ 8)   │
│       └─► SQS ──────── 5-min escalation delay queue    │
│                                                         │
│  GET  /api/dashboard/prioritized   ← DynamoDB scan     │
│  GET  /api/dashboard/chronological ← DynamoDB scan     │
└─────────────────────────────────────────────────────────┘

Deployment targets:
  • ECS Fargate  — uvicorn app.main:app
  • AWS Lambda   — Mangum handler (app.main.lambda_handler)
  • API Gateway  — routes to Lambda
```

| AWS Service | Role |
|---|---|
| **Bedrock** (Claude 3.5 Sonnet) | Extract key findings from report text |
| **DynamoDB** | Persist reports, audit logs, notifications |
| **S3** | Store original PDFs (encrypted, private) |
| **SQS** | FIFO processing queue + 5-min escalation delay |
| **SNS** | Push notifications to clinicians and dept heads |
| **ECS Fargate / Lambda** | Host FastAPI backend |

---

## Quick Start

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- AWS account with Bedrock model access enabled
- AWS CLI configured (`aws configure`)

### 1. Clone and install

```bash
git clone https://github.com/YOUR_ORG/swathyahita.git
cd swathyahita
uv sync --dev
```

### 2. Provision AWS resources

```bash
chmod +x infrastructure/setup_aws.sh
./infrastructure/setup_aws.sh
```

This creates all DynamoDB tables, S3 bucket, SQS queues, and SNS topics, then prints the values to paste into your `.env`.

### 3. Enable Bedrock model access

In the [AWS Console → Bedrock → Model access](https://console.aws.amazon.com/bedrock/home#/modelaccess), enable:

```
anthropic.claude-3-5-sonnet-20241022-v2:0
```

### 4. Configure environment

```bash
cp .env.example .env
# Fill in the values printed by setup_aws.sh
```

### 5. Run the server

```bash
uv run uvicorn app.main:app --reload
```

Open **http://localhost:8000/docs** for the interactive API explorer.

---

## API Reference

See [docs/API.md](docs/API.md) for the full reference. Key endpoints:

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/reports/ingest` | Ingest a FHIR DiagnosticReport (full pipeline) |
| `GET` | `/api/dashboard/prioritized` | Reports sorted by urgency score ↓ |
| `GET` | `/api/dashboard/chronological` | Reports sorted by timestamp ↓ |
| `GET` | `/api/reports/{id}` | Full report details + score breakdown |
| `POST` | `/api/reports/{id}/snooze` | Snooze for 5, 15, 30, or 60 min |
| `POST` | `/api/reports/{id}/escalate` | Manually escalate to dept head |
| `POST` | `/api/reports/{id}/review` | Mark reviewed, cancel escalation timer |
| `GET` | `/api/reports/audit/logs` | Full audit trail |

---

## Ingest a Report (Example)

```bash
# Encode report content as base64
CONTENT=$(echo "Patient: Jane Doe
Hemoglobin: 6.8 g/dL (ref: 12.0-16.0) - CRITICAL LOW
WBC: 1.9 K/uL (ref: 4.5-11.0) - LOW" | base64)

curl -X POST http://localhost:8000/api/reports/ingest \
  -H "Content-Type: application/json" \
  -d "{
    \"resourceType\": \"DiagnosticReport\",
    \"status\": \"final\",
    \"category\": \"LAB\",
    \"subject\": {\"reference\": \"Patient/jane-doe-001\"},
    \"issued\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\",
    \"presentedForm\": [{
      \"contentType\": \"text/plain\",
      \"data\": \"$CONTENT\"
    }]
  }"
```

Response:
```json
{
  "reportId": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "status": "queued",
  "message": "Report successfully ingested"
}
```

---

## Urgency Scoring

| Finding Severity | Weight | Triggers |
|---|---|---|
| `CRITICAL` | 10 | Score ≥ 7, SNS notification, 5-min escalation timer |
| `ABNORMAL` | 5 | — |
| `NORMAL` | 1 | — |

**Formula**: `score = sum(weights) / count(findings)`, clamped to [1, 10]

**Contextual adjustment** (patient history, last 12 months):
- New or worsening finding → **+2**
- Stable or improving → **-1**
- No history available → no adjustment

**Dashboard color coding**:
- 🔴 **8–10** Critical — immediate review required
- 🟡 **5–7** Moderate — review today
- 🟢 **1–4** Low — routine review

---

## Running Tests

```bash
# All tests (unit + property-based, moto-mocked AWS)
uv run pytest tests/ -v

# Only scoring property tests
uv run pytest tests/properties/test_scoring_props.py -v

# With coverage
uv run pytest tests/ --cov=app --cov-report=term-missing
```

All AWS calls are mocked with [moto](https://docs.getmoto.org/) — no real AWS credentials needed for tests.

---

## MVP Batch Processor

Process a folder of mock PDF reports and output prioritized JSON:

```bash
# Place PDFs in mvp/mock_reports/
uv run python mvp/processor.py \
  --mock-dir mvp/mock_reports \
  --output mvp/output.json

cat mvp/output.json | python -m json.tool
```

---

## Deployment

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for full guides.

### ECS Fargate (recommended)

```bash
docker build -t afm-backend .
docker tag afm-backend:latest $ECR_URI/afm-backend:latest
docker push $ECR_URI/afm-backend:latest
# Deploy via ECS service with task role that has Bedrock/DynamoDB/S3/SQS/SNS permissions
```

### AWS Lambda

Set handler to `app.main.lambda_handler` (Mangum wraps the FastAPI app automatically).

---

## Project Structure

```
swathyahita/
├── app/
│   ├── main.py                  # FastAPI app + Lambda handler
│   ├── config.py                # AWS env config
│   ├── models.py                # Pydantic data models
│   ├── store.py                 # DynamoDB-backed store
│   ├── aws/
│   │   └── clients.py           # boto3 singletons (Bedrock, DDB, S3, SQS, SNS)
│   ├── services/
│   │   ├── ingestion.py         # FHIR validation
│   │   ├── pdf_extractor.py     # PyMuPDF + S3
│   │   ├── classifier.py        # Bedrock (Claude) key findings
│   │   ├── scoring.py           # Urgency score formula
│   │   ├── contextual_bridge.py # Patient history adjustment
│   │   ├── prioritizer.py       # Sort by urgency
│   │   ├── snooze.py            # Snooze timer management
│   │   ├── escalation.py        # SQS delay + asyncio escalation
│   │   ├── notifications.py     # SNS push notifications
│   │   └── audit.py             # Audit log writes
│   └── api/
│       ├── reports.py           # Ingest + list endpoints
│       ├── dashboard.py         # Prioritized + chronological views
│       └── actions.py           # Snooze, escalate, review
├── mvp/
│   ├── processor.py             # Batch MVP script
│   └── mock_reports/            # Place test PDFs here
├── infrastructure/
│   └── setup_aws.sh             # One-click AWS resource creation
├── tests/
│   ├── conftest.py              # Global moto fixture
│   ├── unit/                    # Unit tests
│   └── properties/              # Hypothesis property-based tests
├── docs/
│   ├── API.md                   # Full API reference
│   ├── ARCHITECTURE.md          # System design
│   └── DEPLOYMENT.md            # AWS deployment guide
├── .env.example                 # Environment variable template
└── pyproject.toml
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## License

MIT
