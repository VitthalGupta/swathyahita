# AFM System Architecture

## Overview

Acuity-First Middleware (AFM) is a stateless FastAPI backend that orchestrates a pipeline of AWS services to transform chronological diagnostic reports into an urgency-ranked worklist for clinicians.

AFM **augments** existing EHR systems — it never modifies or deletes original data (Req 14.1).

---

## System Flow

```
Clinician / EHR System
        │
        ▼
POST /api/reports/ingest
        │
        ├─1─► FHIR Validation (pure Python)
        │         • resourceType, status, category, subject.reference
        │         • Returns 400 + FHIR_VALIDATION_FAILED on error
        │
        ├─2─► S3 PutObject
        │         • Stores original PDF at reports/{reportId}/original.pdf
        │         • AES256 server-side encryption
        │         • Never modified (Req 14.1)
        │
        ├─3─► PyMuPDF text extraction
        │         • Text PDFs: direct extraction
        │         • Scanned PDFs: OCR via get_textpage_ocr()
        │         • Flags report as OCR_processed in metadata
        │
        ├─4─► AWS Bedrock (Claude 3.5 Sonnet) — Converse API
        │         • Strict system prompt for structured JSON extraction
        │         • Output: [{finding_name, finding_value, reference_range, clinical_significance}]
        │         • Retry x3 with exponential backoff
        │         • Report-type-specific prompts (LAB / RAD / PATH)
        │
        ├─5─► Scoring Engine
        │         • CRITICAL=10, ABNORMAL=5, NORMAL=1
        │         • score = sum(weights) / count, clamped [1,10]
        │         • Conflict resolution: any CRITICAL → score ≥ 7
        │
        ├─6─► Contextual Bridge (DynamoDB scan, last 12 months)
        │         • New/worsening finding vs baseline → +2
        │         • Stable/improving → -1
        │         • No history → base score unchanged
        │
        ├─7─► DynamoDB PutItem / UpdateItem
        │         • afm-reports table: full report serialized as JSON string
        │         • afm-audit-logs table: every action logged
        │
        └─8─► (if score ≥ 8)
                  ├─► SNS Publish → afm-critical-reports topic
                  └─► SQS SendMessage (DelaySeconds=300) → afm-escalation queue
                             └─► Lambda consumer → POST /api/internal/escalation
```

---

## Component Responsibilities

### Report Ingestion Service
`app/services/ingestion.py`

- Validates FHIR DiagnosticReport schema (pure Python, no AWS)
- Extracts patient ID from `subject.reference`
- Assigns UUID report ID
- Creates DynamoDB record (status: `queued`)

### PDF Extractor
`app/services/pdf_extractor.py`

- Uploads original PDF to S3 (immutable copy)
- Extracts text with PyMuPDF (`fitz`)
- Falls back to OCR for image-only pages, sets `ocr_processed=true`
- Generates pre-signed S3 URLs for secure EHR link provision (Req 14.2)

### Report Classifier
`app/services/classifier.py`

- Calls Bedrock `converse()` with `anthropic.claude-3-5-sonnet-20241022-v2:0`
- Temperature=0 for deterministic medical extraction
- Validates JSON array response: `[{finding_name, finding_value, reference_range, clinical_significance}]`
- Retry x3 with 1s/2s exponential backoff on parse or API failure

### Scoring Engine
`app/services/scoring.py`

```
SEVERITY_WEIGHTS = {CRITICAL: 10, ABNORMAL: 5, NORMAL: 1}

raw_score = sum(weights) / len(findings)
if any CRITICAL: raw_score = max(raw_score, 7.0)  # conflict resolution
score = round(clamp(raw_score, 1, 10))
```

### Contextual Bridge
`app/services/contextual_bridge.py`

- Queries DynamoDB for all completed reports for same patient (last 365 days)
- Compares current CRITICAL finding count vs historical average
- Adjustment: `+2` (new/worsening), `-1` (stable/improving), `0` (no history)
- Final score clamped to [1, 10]

### Escalation Service
`app/services/escalation.py`

Dual-path for reliability:

| Path | Mechanism | Survives restart? |
|---|---|---|
| **SQS delay** (primary) | `SendMessage(DelaySeconds=300)` | ✅ Yes |
| **asyncio task** (in-process) | `asyncio.create_task()` | ❌ No |

The SQS consumer (Lambda or `/api/reports/internal/escalation`) checks `reviewed_at` before escalating — idempotent.

### Notification Service
`app/services/notifications.py`

- Publishes JSON to SNS topics
- Persists `Notification` record to DynamoDB
- Writes audit log entry
- Gracefully skips if SNS ARN not configured

---

## Data Models

### Report (DynamoDB `afm-reports`)

```
PK: report_id (UUID)

Stored as: { report_id: "...", data: "<JSON string>" }
```

Key fields:
- `urgency_score` (1–10)
- `base_score` + `score_adjustment`
- `key_findings[]` (extracted by Bedrock)
- `snoozed_until` (ISO timestamp or null)
- `escalated_at`, `reviewed_at`, `reviewed_by`
- `ocr_processed` (bool)

### AuditLog (DynamoDB `afm-audit-logs`)

Every system or clinician action produces an audit log:

| Action | Triggered by |
|---|---|
| `INGEST` | Report received |
| `CLASSIFY` | Bedrock response parsed |
| `SCORE` | Urgency score calculated |
| `SNOOZE` | Clinician snooze action |
| `ESCALATE` | Auto (SQS/asyncio) or manual |
| `REVIEW` | Clinician marks reviewed |
| `NOTIFY` | SNS publish |

---

## AWS IAM Permissions Required

There are two policies depending on the use case:

### Policy A — Runtime (ECS task role / Lambda execution role)

Minimum permissions for the running application:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DynamoDB",
      "Effect": "Allow",
      "Action": ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:UpdateItem", "dynamodb:Scan"],
      "Resource": [
        "arn:aws:dynamodb:*:*:table/afm-reports",
        "arn:aws:dynamodb:*:*:table/afm-audit-logs",
        "arn:aws:dynamodb:*:*:table/afm-notifications"
      ]
    },
    {
      "Sid": "S3",
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject", "s3:GetObjectVersion"],
      "Resource": "arn:aws:s3:::afm-pdf-reports-*/reports/*"
    },
    {
      "Sid": "Bedrock",
      "Effect": "Allow",
      "Action": ["bedrock:InvokeModel"],
      "Resource": "arn:aws:bedrock:*::foundation-model/anthropic.claude-3-5-sonnet-20241022-v2:0"
    },
    {
      "Sid": "SQS",
      "Effect": "Allow",
      "Action": ["sqs:SendMessage", "sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"],
      "Resource": [
        "arn:aws:sqs:*:*:afm-processing.fifo",
        "arn:aws:sqs:*:*:afm-escalation",
        "arn:aws:sqs:*:*:afm-snooze"
      ]
    },
    {
      "Sid": "SNS",
      "Effect": "Allow",
      "Action": ["sns:Publish"],
      "Resource": [
        "arn:aws:sns:*:*:afm-critical-reports",
        "arn:aws:sns:*:*:afm-escalations",
        "arn:aws:sns:*:*:afm-snooze-expiry"
      ]
    }
  ]
}
```

### Policy B — Local Developer / Setup (IAM user policy)

Full permissions needed to provision infrastructure **and** run the app locally.
Attach this to your `afm-local-dev` IAM user:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DynamoDBFull",
      "Effect": "Allow",
      "Action": [
        "dynamodb:CreateTable",
        "dynamodb:DeleteTable",
        "dynamodb:DescribeTable",
        "dynamodb:ListTables",
        "dynamodb:UpdateTable",
        "dynamodb:PutItem",
        "dynamodb:GetItem",
        "dynamodb:UpdateItem",
        "dynamodb:DeleteItem",
        "dynamodb:Scan",
        "dynamodb:Query",
        "dynamodb:TagResource"
      ],
      "Resource": [
        "arn:aws:dynamodb:*:*:table/afm-*",
        "arn:aws:dynamodb:*:*:table/afm-*/index/*"
      ]
    },
    {
      "Sid": "S3BucketLevel",
      "Effect": "Allow",
      "Action": [
        "s3:CreateBucket",
        "s3:DeleteBucket",
        "s3:ListBucket",
        "s3:GetBucketLocation",
        "s3:PutEncryptionConfiguration",
        "s3:GetEncryptionConfiguration",
        "s3:PutBucketPublicAccessBlock",
        "s3:GetBucketPublicAccessBlock"
      ],
      "Resource": "arn:aws:s3:::afm-pdf-reports-*"
    },
    {
      "Sid": "S3ObjectLevel",
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject",
        "s3:GetObjectVersion"
      ],
      "Resource": "arn:aws:s3:::afm-pdf-reports-*/*"
    },
    {
      "Sid": "BedrockFull",
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:ListFoundationModels",
        "bedrock:GetFoundationModel"
      ],
      "Resource": "*"
    },
    {
      "Sid": "SQSFull",
      "Effect": "Allow",
      "Action": [
        "sqs:CreateQueue",
        "sqs:DeleteQueue",
        "sqs:GetQueueUrl",
        "sqs:GetQueueAttributes",
        "sqs:SetQueueAttributes",
        "sqs:ListQueues",
        "sqs:SendMessage",
        "sqs:ReceiveMessage",
        "sqs:DeleteMessage",
        "sqs:PurgeQueue",
        "sqs:TagQueue"
      ],
      "Resource": "arn:aws:sqs:*:*:afm-*"
    },
    {
      "Sid": "SNSFull",
      "Effect": "Allow",
      "Action": [
        "sns:CreateTopic",
        "sns:DeleteTopic",
        "sns:GetTopicAttributes",
        "sns:ListTopics",
        "sns:SetTopicAttributes",
        "sns:Subscribe",
        "sns:Unsubscribe",
        "sns:Publish",
        "sns:TagResource"
      ],
      "Resource": "arn:aws:sns:*:*:afm-*"
    },
    {
      "Sid": "STSCallerIdentity",
      "Effect": "Allow",
      "Action": ["sts:GetCallerIdentity"],
      "Resource": "*"
    },
    {
      "Sid": "IAMRoles",
      "Effect": "Allow",
      "Action": [
        "iam:CreateRole",
        "iam:AttachRolePolicy",
        "iam:PutRolePolicy",
        "iam:GetRole",
        "iam:ListAttachedRolePolicies"
      ],
      "Resource": "arn:aws:iam::025988852752:role/afm-*"
    },
    {
      "Sid": "IAMPassRole",
      "Effect": "Allow",
      "Action": ["iam:PassRole"],
      "Resource": [
        "arn:aws:iam::025988852752:role/afm-ecs-task-role",
        "arn:aws:iam::025988852752:role/afm-ecs-execution-role"
      ]
    }
  ]
}
```

---

## Correctness Properties

The codebase includes 50 automated tests (unit + [Hypothesis](https://hypothesis.readthedocs.io/) property-based) covering all 39 correctness properties defined in `design.md`.

Key properties verified:
- **P7**: Urgency score always ∈ [1, 10]
- **P8**: Weighted formula correct for all inputs
- **P9**: CRITICAL finding dominates (score ≥ 7)
- **P1**: Valid FHIR always accepted; invalid always rejected with 400
- **P2**: All report IDs are unique (100 iterations)
- **P11**: Prioritized list always sorted DESC by urgency score
