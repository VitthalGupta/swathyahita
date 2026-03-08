# Design Document: Acuity-First Middleware (AFM)

## Overview

The Acuity-First Middleware (AFM) is a medical diagnostic report prioritization system that augments existing EHR systems by reordering diagnostic reports by clinical urgency rather than chronological order. The system consists of five core components:

1. **Report Ingestion Service**: Accepts FHIR-formatted diagnostic reports via REST API
2. **Report Classifier**: Extracts clinical findings using medical LLMs (Med-PaLM or GPT-4o)
3. **Scoring Engine**: Calculates urgency scores (1-10) based on clinical guidelines
4. **Contextual Bridge**: Adjusts scores based on patient history
5. **Dashboard UI**: Displays both chronological and AI-prioritized report lists

The system maintains a clear separation between AI-assisted recommendations and clinical decision-making, with prominent disclaimers and audit logging throughout.

## Architecture

### High-Level System Flow

```
Diagnostic Report (FHIR)
    ↓
[Report Ingestion Service] → Validate & Queue
    ↓
[PDF Extractor] → Extract Text (PyMuPDF)
    ↓
[Report Classifier] → Extract Key Findings (Medical LLM)
    ↓
[Scoring Engine] → Calculate Urgency Score (1-10)
    ↓
[Contextual Bridge] → Adjust Score Based on History
    ↓
[Report Prioritizer] → Sort by Urgency Score
    ↓
[Dashboard UI] → Display Chronological & Prioritized Views
    ↓
[Notification Service] → Send Push Notifications
    ↓
[Escalation Service] → Escalate Critical Reports (Score ≥ 8)
```

### Component Architecture

**Report Ingestion Service**:
- REST API endpoint accepting FHIR DiagnosticReport objects
- Validates incoming reports against FHIR schema
- Extracts metadata (patient ID, report type, timestamp)
- Queues reports for processing in FIFO order
- Returns unique report ID to caller

**PDF Extractor**:
- Extracts text from PDF diagnostic reports using PyMuPDF
- Preserves document structure and order
- Attempts OCR for scanned documents
- Flags OCR-processed reports in metadata
- Outputs plain text for LLM processing

**Report Classifier**:
- Sends diagnostic report text to medical LLM with strict system prompt
- System prompt instructs LLM to identify abnormal values, critical results, and clinically significant findings
- Parses LLM response into structured JSON format
- Validates JSON structure (finding_name, finding_value, reference_range, clinical_significance)
- Supports report-type-specific extraction (blood labs, radiology, pathology)

**Scoring Engine**:
- Calculates Urgency Score (1-10) based on Key Findings severity
- Applies weighted scoring: critical=10, abnormal=5, normal=1
- Aggregates multiple findings using weighted average formula
- Resolves conflicts by using highest severity finding
- Stores score with report for downstream use

**Contextual Bridge**:
- Queries patient's historical reports (last 12 months) from EHR
- Compares current findings against historical trends
- Adjusts score: +2 for new/worse findings, -1 for stable/improving findings
- Gracefully handles unavailable history (uses base score)

**Report Prioritizer**:
- Generates prioritized list sorted by Urgency Score (descending)
- Uses timestamp as tiebreaker for identical scores
- Includes metadata: patient ID, report type, score, timestamp, Key Findings summary
- Returns JSON format suitable for dashboard consumption
- Updates list in real-time as new reports are processed

**Dashboard UI**:
- React-based web interface
- Displays two side-by-side views: chronological (left) and AI-prioritized (right)
- Chronological view: sorted by timestamp (most recent first)
- Prioritized view: sorted by Urgency Score with color-coded highlighting
- Color coding: red (8-10, critical), yellow (5-7, moderate), green (1-4, low)
- Includes snooze and escalate buttons for each report
- Displays 3-bullet Key Findings summary in list view
- Shows full report details, score breakdown, and disclaimer in detail view

**Notification Service**:
- Sends push notifications for critical reports (score ≥ 8)
- Sends notifications for escalations to department head
- Sends notifications when snoozed reports expire
- Includes report ID, patient ID, score, and Key Findings summary
- Logs all notification events for audit purposes

**Escalation Service**:
- Monitors critical reports (score ≥ 8) for review
- Starts 5-minute review timer when critical report is generated
- Cancels timer when report is reviewed by clinician
- Escalates to department head if timer expires without review
- Sends escalation notification with report summary and disclaimer
- Logs escalation events for audit purposes

**EHR Bridge**:
- Integrates with existing EHR systems (Epic, Cerner)
- Does not modify or delete original reports in EHR
- Provides links to original reports in EHR
- Logs AFM actions (snooze, escalate) in EHR audit trail
- Ensures EHR continues functioning if AFM is unavailable
- Allows clinicians to bypass AFM and use EHR directly

## Components and Interfaces

### Report Ingestion Service API

```typescript
// Request
POST /api/reports/ingest
{
  "resourceType": "DiagnosticReport",
  "id": "string",
  "status": "final" | "preliminary" | "amended",
  "category": "LAB" | "RAD" | "PATH",
  "subject": { "reference": "Patient/[id]" },
  "issued": "ISO8601 timestamp",
  "presentedForm": [
    {
      "contentType": "application/pdf" | "text/plain",
      "data": "base64 encoded content"
    }
  ]
}

// Response
{
  "reportId": "unique-report-id",
  "status": "queued",
  "message": "Report successfully ingested"
}

// Error Response
{
  "status": 400,
  "error": "FHIR_VALIDATION_FAILED",
  "details": "Missing required field: subject.reference"
}
```

### Report Classifier Output

```typescript
{
  "reportId": "unique-report-id",
  "reportType": "LAB" | "RAD" | "PATH",
  "keyFindings": [
    {
      "finding_name": "Hemoglobin",
      "finding_value": "7.2 g/dL",
      "reference_range": "13.5-17.5 g/dL",
      "clinical_significance": "CRITICAL - Severe anemia"
    },
    {
      "finding_name": "White Blood Cell Count",
      "finding_value": "2.1 K/uL",
      "reference_range": "4.5-11.0 K/uL",
      "clinical_significance": "ABNORMAL - Leukopenia"
    }
  ]
}
```

### Urgency Score Calculation

```typescript
// Scoring Rules
const SEVERITY_WEIGHTS = {
  CRITICAL: 10,
  ABNORMAL: 5,
  NORMAL: 1
};

// Formula: (sum of weighted findings) / (count of findings)
// Example: [CRITICAL, ABNORMAL, NORMAL] = (10 + 5 + 1) / 3 = 5.33 → rounds to 5

// Score Adjustments (Contextual Bridge)
const ADJUSTMENT_RULES = {
  NEW_OR_WORSE: +2,
  STABLE: 0,
  IMPROVING: -1
};

// Final Score Range: 1-10
```

### Prioritized Report List Output

```typescript
{
  "reports": [
    {
      "reportId": "report-001",
      "patientId": "patient-123",
      "reportType": "LAB",
      "urgencyScore": 9,
      "timestamp": "2024-01-15T14:30:00Z",
      "keyFindingsSummary": [
        "Hemoglobin 7.2 g/dL (CRITICAL)",
        "White Blood Cell Count 2.1 K/uL (ABNORMAL)",
        "Platelet Count 45 K/uL (ABNORMAL)"
      ],
      "ehrLink": "https://ehr.example.com/reports/report-001",
      "disclaimer": "AI-generated flags for review only. Not a diagnostic conclusion. Clinician review required."
    },
    {
      "reportId": "report-002",
      "patientId": "patient-456",
      "reportType": "RAD",
      "urgencyScore": 6,
      "timestamp": "2024-01-15T13:45:00Z",
      "keyFindingsSummary": [
        "Pulmonary nodule 8mm (ABNORMAL)",
        "No acute cardiopulmonary process",
        "Recommend follow-up CT in 3 months"
      ],
      "ehrLink": "https://ehr.example.com/reports/report-002",
      "disclaimer": "AI-generated flags for review only. Not a diagnostic conclusion. Clinician review required."
    }
  ]
}
```

### Dashboard UI Components

**Report List Item**:
- Patient ID
- Report Type (LAB/RAD/PATH)
- Urgency Score (with color coding)
- Timestamp
- 3-bullet Key Findings summary
- Snooze button
- Escalate button
- View Details link

**Report Detail View**:
- Full report text
- All Key Findings with clinical significance
- Urgency Score with calculation breakdown
- Historical context (if available)
- Disclaimer: "AI-generated flags for review only. Not a diagnostic conclusion. Clinician review required."
- Score note: "Score calculated by AI. Clinical judgment required for final prioritization."
- EHR link to original report
- Snooze and Escalate buttons

**Snooze Dialog**:
- Duration options: 5 min, 15 min, 30 min, 1 hour
- Confirmation message after selection
- Countdown timer showing remaining snooze time

## Data Models

### Report Model

```typescript
interface Report {
  reportId: string;
  patientId: string;
  reportType: "LAB" | "RAD" | "PATH";
  status: "queued" | "processing" | "completed" | "failed";
  originalText: string;
  keyFindings: KeyFinding[];
  urgencyScore: number;
  baseScore: number;
  scoreAdjustment: number;
  timestamp: ISO8601;
  createdAt: ISO8601;
  updatedAt: ISO8601;
  ehrLink: string;
  snoozedUntil?: ISO8601;
  escalatedAt?: ISO8601;
  reviewedAt?: ISO8601;
  reviewedBy?: string;
}

interface KeyFinding {
  finding_name: string;
  finding_value: string;
  reference_range: string;
  clinical_significance: string;
  severity: "CRITICAL" | "ABNORMAL" | "NORMAL";
}
```

### Notification Model

```typescript
interface Notification {
  notificationId: string;
  recipientId: string;
  reportId: string;
  type: "CRITICAL_REPORT" | "ESCALATION" | "SNOOZE_EXPIRED";
  title: string;
  body: string;
  data: {
    reportId: string;
    patientId: string;
    urgencyScore: number;
    keyFindingsSummary: string[];
  };
  sentAt: ISO8601;
  readAt?: ISO8601;
}
```

### Audit Log Model

```typescript
interface AuditLog {
  logId: string;
  timestamp: ISO8601;
  action: "INGEST" | "CLASSIFY" | "SCORE" | "SNOOZE" | "ESCALATE" | "REVIEW";
  reportId: string;
  userId?: string;
  details: Record<string, any>;
  note: "AI-assisted recommendation" | "Clinician action";
}
```



## Correctness Properties

A property is a characteristic or behavior that should hold true across all valid executions of a system—essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.

### Property-Based Testing Overview

Property-based testing (PBT) validates software correctness by testing universal properties across many generated inputs. Each property is a formal specification that should hold for all valid inputs.

### Core Principles

1. **Universal Quantification**: Every property must contain an explicit "for all" statement
2. **Requirements Traceability**: Each property must reference the requirements it validates
3. **Executable Specifications**: Properties must be implementable as automated tests
4. **Comprehensive Coverage**: Properties should cover all testable acceptance criteria

### Correctness Properties

**Property 1: FHIR Validation**
*For any* diagnostic report submitted to the ingestion API, if it is valid according to FHIR DiagnosticReport schema, it SHALL be accepted and queued; if it is invalid, it SHALL be rejected with a 400 error and descriptive message.
**Validates: Requirements 1.1, 1.3**

**Property 2: Unique Report IDs**
*For any* set of diagnostic reports ingested into the system, each report SHALL receive a unique report ID, and no two reports SHALL share the same ID.
**Validates: Requirements 1.4**

**Property 3: FIFO Queue Processing**
*For any* sequence of reports submitted to the ingestion service when the queue is at capacity, the reports SHALL be processed in the order they were submitted (FIFO).
**Validates: Requirements 1.5**

**Property 4: PDF Text Extraction**
*For any* PDF diagnostic report, the extracted text SHALL contain all text content from the original PDF in the same order and structure.
**Validates: Requirements 2.1, 2.2**

**Property 5: OCR Flagging**
*For any* PDF containing scanned images without OCR, the system SHALL attempt OCR extraction and mark the report as "OCR_processed" in metadata.
**Validates: Requirements 2.3**

**Property 6: Key Findings JSON Structure**
*For any* extracted Key Findings, each finding SHALL be a valid JSON object containing all required fields: finding_name, finding_value, reference_range, clinical_significance.
**Validates: Requirements 3.3, 3.4**

**Property 7: Urgency Score Range**
*For any* diagnostic report processed by the Scoring Engine, the calculated Urgency Score SHALL be an integer between 1 and 10 (inclusive).
**Validates: Requirements 4.1**

**Property 8: Weighted Scoring Formula**
*For any* set of Key Findings with known severity levels, the Urgency Score SHALL equal (sum of weighted findings) / (count of findings), where critical=10, abnormal=5, normal=1.
**Validates: Requirements 4.2, 4.3**

**Property 9: Conflict Resolution**
*For any* report containing conflicting Key Findings with different severity levels, the final Urgency Score SHALL be determined by the highest severity finding.
**Validates: Requirements 4.4**

**Property 10: Historical Context Adjustment**
*For any* report with a new or significantly worse finding compared to historical baseline, the Urgency Score SHALL be increased by up to 2 points; for stable or improving findings, it SHALL be decreased by up to 1 point.
**Validates: Requirements 5.3, 5.4**

**Property 11: Prioritized List Sorting**
*For any* set of processed reports, the prioritized list SHALL be sorted by Urgency Score in descending order (highest first), with timestamp as tiebreaker for identical scores.
**Validates: Requirements 6.1, 6.2**

**Property 12: Prioritized List Metadata**
*For any* report in the prioritized list, it SHALL include all required metadata: patient ID, report type, Urgency Score, timestamp, and Key Findings summary.
**Validates: Requirements 6.3**

**Property 13: Dashboard Chronological Sorting**
*For any* set of reports displayed in the chronological view, they SHALL be sorted by timestamp in descending order (most recent first).
**Validates: Requirements 7.1**

**Property 14: Dashboard Chronological Metadata**
*For any* report in the chronological view, it SHALL display: patient ID, report type, timestamp, and a 3-bullet summary of Key Findings.
**Validates: Requirements 7.2**

**Property 15: Dashboard Prioritized Sorting**
*For any* set of reports displayed in the prioritized view, they SHALL be sorted by Urgency Score in descending order (highest first).
**Validates: Requirements 8.1**

**Property 16: Color-Coded Urgency Highlighting**
*For any* report displayed in the prioritized view, the color coding SHALL be: red for scores 8-10, yellow for scores 5-7, green for scores 1-4.
**Validates: Requirements 8.3**

**Property 17: Snooze Duration Enforcement**
*For any* report snoozed with a specified duration, the report SHALL remain hidden from the dashboard for exactly that duration, then be restored.
**Validates: Requirements 9.2**

**Property 18: Snooze Audit Logging**
*For any* snooze action, the system SHALL log the action with timestamp and clinician ID for audit purposes.
**Validates: Requirements 9.4**

**Property 19: Critical Report Timer Initialization**
*For any* report with Urgency Score ≥ 8, the system SHALL start a 5-minute review timer immediately upon generation.
**Validates: Requirements 10.1**

**Property 20: Escalation on Timer Expiration**
*For any* critical report (score ≥ 8) not reviewed within 5 minutes, the system SHALL escalate it to the department head and send a notification.
**Validates: Requirements 10.3, 10.4**

**Property 21: Escalation Audit Logging**
*For any* escalation event, the system SHALL log the event with timestamp and report ID for audit purposes.
**Validates: Requirements 10.5**

**Property 22: Critical Report Notification**
*For any* critical report (score ≥ 8) generated, the system SHALL send a push notification to the assigned clinician.
**Validates: Requirements 11.1**

**Property 23: Notification Content Completeness**
*For any* notification sent, it SHALL include: report ID, patient ID, Urgency Score, and a brief summary of Key Findings.
**Validates: Requirements 11.4**

**Property 24: Notification Audit Logging**
*For any* notification sent, the system SHALL log the event with timestamp and recipient ID for audit purposes.
**Validates: Requirements 11.5**

**Property 25: Report Type Identification**
*For any* diagnostic report ingested, the system SHALL correctly identify its type as one of: blood labs, radiology text, or pathology reports.
**Validates: Requirements 12.1**

**Property 26: Report-Type-Specific Scoring**
*For any* report of a specific type, the Scoring Engine SHALL apply the appropriate report-type-specific scoring rules.
**Validates: Requirements 12.5**

**Property 27: Disclaimer Display**
*For any* report displayed on the dashboard, the system SHALL display the disclaimer: "AI-generated flags for review only. Not a diagnostic conclusion. Clinician review required."
**Validates: Requirements 13.1**

**Property 28: Key Findings Labeling**
*For any* Key Findings displayed, they SHALL be labeled as "AI-Extracted Findings" to distinguish from clinician-verified findings.
**Validates: Requirements 13.2**

**Property 29: Score Note Display**
*For any* Urgency Score displayed, the system SHALL include the note: "Score calculated by AI. Clinical judgment required for final prioritization."
**Validates: Requirements 13.3**

**Property 30: Original Report Preservation**
*For any* diagnostic report processed by AFM, the original report in the EHR SHALL remain unmodified and undeleted.
**Validates: Requirements 14.1**

**Property 31: EHR Link Provision**
*For any* report reviewed in AFM, the system SHALL provide a link to the original report in the EHR.
**Validates: Requirements 14.2**

**Property 32: EHR Audit Trail Logging**
*For any* clinician action on a report (snooze, escalate), the system SHALL log the action in the EHR audit trail.
**Validates: Requirements 14.3**

**Property 33: MVP PDF Processing**
*For any* PDF file in the mock report folder, the MVP processor SHALL extract text, send it to the LLM, calculate urgency score, and include it in the output.
**Validates: Requirements 15.1, 15.2, 15.3, 15.4**

**Property 34: MVP Output Format**
*For any* set of processed mock reports, the MVP processor SHALL output a JSON file with all reports sorted by Urgency Score in descending order.
**Validates: Requirements 15.5**

**Property 35: Dashboard Side-by-Side Display**
*For any* dashboard load, the system SHALL display two side-by-side views: chronological list (left) and AI-prioritized list (right).
**Validates: Requirements 16.1**

**Property 36: Critical Reports Prominence**
*For any* dashboard load with mock reports, the 2 critical reports (score ≥ 8) SHALL appear at the top of the AI-prioritized view.
**Validates: Requirements 16.5**

**Property 37: Snooze Button Functionality**
*For any* report displayed on the dashboard, clicking the snooze button SHALL display a duration selector with options: 5 min, 15 min, 30 min, 1 hour.
**Validates: Requirements 17.1, 17.2**

**Property 38: Escalate Button Functionality**
*For any* report displayed on the dashboard, clicking the escalate button SHALL escalate the report and display a confirmation message.
**Validates: Requirements 17.3**

**Property 39: Real-Time List Updates**
*For any* new report ingested into the system, the dashboard prioritized list SHALL be updated in real-time to reflect the new report's position based on its Urgency Score.
**Validates: Requirements 6.5, 7.5, 8.5**



## Error Handling

### FHIR Validation Errors

**Scenario**: Invalid FHIR DiagnosticReport submitted to ingestion API
- **Response**: HTTP 400 with error code `FHIR_VALIDATION_FAILED`
- **Details**: Include specific field that failed validation
- **Logging**: Log validation error with report ID and timestamp
- **User Impact**: API caller receives descriptive error message

### PDF Extraction Errors

**Scenario**: PDF file is corrupted or unreadable
- **Response**: Log error with report ID and error details
- **Fallback**: Mark report as "EXTRACTION_FAILED" and skip to next report
- **Notification**: Alert system administrator of extraction failure
- **User Impact**: Report is not processed; clinician may need to manually review

**Scenario**: PDF contains only scanned images without OCR
- **Response**: Attempt OCR extraction
- **Fallback**: If OCR fails, mark as "OCR_FAILED" and skip
- **Logging**: Log OCR attempt and result
- **User Impact**: Report may not be processed if OCR unavailable

### LLM Processing Errors

**Scenario**: Medical LLM API is unavailable or returns error
- **Response**: Log error with report ID and LLM error details
- **Fallback**: Retry up to 3 times with exponential backoff
- **Escalation**: If all retries fail, mark report as "LLM_PROCESSING_FAILED"
- **Notification**: Alert system administrator
- **User Impact**: Report is not prioritized; clinician may need to manually review

**Scenario**: LLM returns invalid JSON or missing required fields
- **Response**: Log validation error with LLM response
- **Fallback**: Attempt to parse partial response or use default values
- **Escalation**: If parsing fails completely, mark as "CLASSIFICATION_FAILED"
- **User Impact**: Report may have incomplete Key Findings

### EHR Integration Errors

**Scenario**: EHR API is unavailable when querying patient history
- **Response**: Log error with patient ID and timestamp
- **Fallback**: Proceed with base Urgency Score without historical adjustment
- **User Impact**: Score may be less accurate but system continues functioning

**Scenario**: EHR link is invalid or patient record not found
- **Response**: Log error with patient ID
- **Fallback**: Provide generic EHR link or skip link provision
- **User Impact**: Clinician cannot access original report in EHR

### Notification Errors

**Scenario**: Push notification service is unavailable
- **Response**: Log error with notification ID and recipient
- **Fallback**: Queue notification for retry; attempt delivery when service recovers
- **User Impact**: Clinician may not receive timely notification

### Escalation Errors

**Scenario**: Department head contact information is invalid or unavailable
- **Response**: Log error with report ID and escalation details
- **Fallback**: Escalate to backup contact or system administrator
- **User Impact**: Critical report may not reach intended recipient

### Database Errors

**Scenario**: Database connection fails during report storage
- **Response**: Log error with report ID and connection details
- **Fallback**: Retry connection up to 3 times; queue report for later storage
- **User Impact**: Report processing may be delayed

## Testing Strategy

### Dual Testing Approach

AFM uses both unit testing and property-based testing to ensure comprehensive correctness:

- **Unit Tests**: Verify specific examples, edge cases, and error conditions
- **Property Tests**: Verify universal properties across all inputs
- Together: Comprehensive coverage (unit tests catch concrete bugs, property tests verify general correctness)

### Unit Testing

Unit tests focus on:
- Specific examples that demonstrate correct behavior
- Integration points between components
- Edge cases and error conditions
- Error handling and recovery

**Example Unit Tests**:
- Test FHIR validation with valid and invalid reports
- Test PDF extraction with various PDF formats
- Test LLM response parsing with valid and invalid JSON
- Test urgency score calculation with known inputs
- Test snooze functionality with various durations
- Test escalation timer behavior
- Test notification sending and logging

### Property-Based Testing

Property-based testing uses randomized input generation to verify universal properties. Each property test:
- Generates random valid inputs
- Executes the system under test
- Verifies the property holds for all generated inputs
- Runs minimum 100 iterations per test

**Property Test Configuration**:
- Framework: Hypothesis (Python) or fast-check (TypeScript/JavaScript)
- Minimum iterations: 100 per property test
- Seed: Use fixed seed for reproducibility
- Timeout: 30 seconds per test

**Property Test Tagging**:
Each property test includes a comment referencing the design property:
```
# Feature: acuity-first-middleware, Property 1: FHIR Validation
# Validates: Requirements 1.1, 1.3
```

### Test Coverage by Component

**Report Ingestion Service**:
- Property 1: FHIR Validation (valid and invalid reports)
- Property 2: Unique Report IDs (no duplicates)
- Property 3: FIFO Queue Processing (order preservation)
- Unit tests: Error handling, metadata extraction, queue capacity

**PDF Extractor**:
- Property 4: PDF Text Extraction (content preservation)
- Property 5: OCR Flagging (scanned document handling)
- Unit tests: Corrupted PDFs, various formats, OCR failures

**Report Classifier**:
- Property 6: Key Findings JSON Structure (required fields)
- Property 25: Report Type Identification (correct classification)
- Unit tests: LLM API errors, invalid JSON, missing fields

**Scoring Engine**:
- Property 7: Urgency Score Range (1-10)
- Property 8: Weighted Scoring Formula (correct calculation)
- Property 9: Conflict Resolution (highest severity wins)
- Unit tests: Edge cases, boundary values, multiple findings

**Contextual Bridge**:
- Property 10: Historical Context Adjustment (score adjustments)
- Unit tests: Unavailable history, missing patient records

**Report Prioritizer**:
- Property 11: Prioritized List Sorting (correct order)
- Property 12: Prioritized List Metadata (all fields present)
- Property 39: Real-Time List Updates (new reports reflected)
- Unit tests: Empty lists, single report, identical scores

**Dashboard UI**:
- Property 13: Chronological Sorting (timestamp order)
- Property 14: Chronological Metadata (all fields displayed)
- Property 15: Prioritized Sorting (score order)
- Property 16: Color-Coded Highlighting (correct colors)
- Property 35: Side-by-Side Display (both views present)
- Property 36: Critical Reports Prominence (top of list)
- Unit tests: UI rendering, button interactions, detail view

**Notification Service**:
- Property 22: Critical Report Notification (sent for score ≥ 8)
- Property 23: Notification Content (all fields included)
- Property 24: Notification Audit Logging (events logged)
- Unit tests: API errors, invalid recipients, retry logic

**Escalation Service**:
- Property 19: Critical Report Timer (5-minute timer)
- Property 20: Escalation on Timer Expiration (escalates after 5 min)
- Property 21: Escalation Audit Logging (events logged)
- Unit tests: Timer cancellation, backup contacts, error handling

**EHR Bridge**:
- Property 30: Original Report Preservation (not modified)
- Property 31: EHR Link Provision (link provided)
- Property 32: EHR Audit Trail Logging (actions logged)
- Unit tests: EHR API errors, invalid links, graceful degradation

**MVP Processor**:
- Property 33: MVP PDF Processing (all PDFs processed)
- Property 34: MVP Output Format (JSON with sorted reports)
- Unit tests: Empty folder, invalid PDFs, LLM errors

### Test Execution

**Local Development**:
```bash
# Run all unit tests
pytest tests/unit/ -v

# Run all property tests
pytest tests/properties/ -v --hypothesis-seed=0

# Run specific property test
pytest tests/properties/test_scoring.py::test_urgency_score_range -v
```

**CI/CD Pipeline**:
- Run all tests on every commit
- Fail build if any test fails
- Generate coverage report (target: >80% coverage)
- Run property tests with multiple seeds for robustness

### Test Data

**Mock Reports**:
- 20 mock PDF lab reports (2 critical, 18 normal)
- Mock radiology reports with various findings
- Mock pathology reports with different severities
- Invalid/corrupted PDFs for error testing

**Test Fixtures**:
- Valid FHIR DiagnosticReport objects
- Invalid FHIR objects (missing fields, wrong types)
- Sample Key Findings with various severities
- Patient history data for contextualization tests
