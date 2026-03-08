# Requirements Document: Acuity-First Middleware (AFM)

## Introduction

The Acuity-First Middleware (AFM) is a medical diagnostic report prioritization system that reorders patient diagnostic reports by clinical urgency rather than chronological order. The system ingests diagnostic reports via FHIR API, uses medical LLMs to extract key clinical findings, calculates urgency scores based on clinical guidelines, and outputs a prioritized list to clinicians. AFM augments existing EHR systems (Epic/Cerner) without replacing them, providing AI-assisted triage while maintaining human oversight and liability protection.

## Glossary

- **Diagnostic Report**: A clinical document containing test results (lab values, radiology findings, pathology results)
- **Key Findings**: Critical clinical data extracted from diagnostic reports by the LLM classifier
- **Urgency Score**: A numerical value (1-10) representing clinical priority, where 10 is most urgent
- **FHIR API**: Fast Healthcare Interoperability Resources API for standardized healthcare data exchange
- **Medical LLM**: Large Language Model trained on medical data (Med-PaLM, GPT-4o) for clinical text analysis
- **Report Classifier**: The LLM component that extracts Key Findings from diagnostic reports
- **Scoring Engine**: The component that calculates Urgency Scores based on clinical guidelines and Key Findings
- **Contextual Bridge**: The component that checks patient history to contextualize findings and adjust urgency
- **EHR**: Electronic Health Record system (Epic, Cerner) that AFM augments
- **Critical Report**: A diagnostic report with Urgency Score ≥ 8 requiring immediate physician review
- **Dashboard**: Web-based UI displaying prioritized diagnostic reports to clinicians
- **Mock Report**: Simulated diagnostic report used for MVP testing
- **Report Type**: Category of diagnostic report (blood labs, radiology text, pathology reports)

## Requirements

### Requirement 1: Report Ingestion via FHIR API

**User Story:** As a system administrator, I want diagnostic reports to be ingested via FHIR API, so that AFM can integrate with existing EHR systems without requiring manual data entry.

#### Acceptance Criteria

1. WHEN a diagnostic report is submitted to the FHIR API endpoint, THE Report_Ingestion_Service SHALL validate the report against FHIR DiagnosticReport schema
2. WHEN a valid FHIR DiagnosticReport is received, THE Report_Ingestion_Service SHALL extract the report text and metadata (patient ID, report type, timestamp) and store it in the processing queue
3. WHEN an invalid FHIR DiagnosticReport is received, THE Report_Ingestion_Service SHALL return a 400 error with a descriptive error message indicating which schema validation failed
4. WHEN a report is successfully ingested, THE Report_Ingestion_Service SHALL assign it a unique report ID and return it to the caller
5. WHEN the processing queue reaches capacity, THE Report_Ingestion_Service SHALL queue incoming reports and process them in FIFO order

---

### Requirement 2: Report Text Extraction from PDF

**User Story:** As a system operator, I want diagnostic reports in PDF format to be automatically converted to text, so that the LLM classifier can process them.

#### Acceptance Criteria

1. WHEN a PDF diagnostic report is provided, THE PDF_Extractor SHALL extract all text content from the PDF
2. WHEN text is extracted from a PDF, THE PDF_Extractor SHALL preserve the order and structure of the original document
3. WHEN a PDF contains scanned images without OCR, THE PDF_Extractor SHALL attempt OCR extraction and flag the report as "OCR_processed" in metadata
4. WHEN PDF extraction fails, THE PDF_Extractor SHALL log the error with the report ID and return a descriptive error message
5. WHEN text extraction is complete, THE PDF_Extractor SHALL output plain text suitable for LLM processing

---

### Requirement 3: Key Findings Extraction via Medical LLM

**User Story:** As a clinician, I want the system to automatically extract critical clinical findings from diagnostic reports, so that I can quickly understand the most important information without reading the entire report.

#### Acceptance Criteria

1. WHEN a diagnostic report text is provided, THE Report_Classifier SHALL use a medical LLM (Med-PaLM or GPT-4o) with a strict system prompt to extract Key Findings
2. WHEN the Report_Classifier processes a report, THE system prompt SHALL instruct the LLM to identify abnormal values, critical results, and clinically significant findings
3. WHEN Key Findings are extracted, THE Report_Classifier SHALL format them as a JSON object with fields: finding_name, finding_value, reference_range, clinical_significance
4. WHEN the LLM response is received, THE Report_Classifier SHALL validate that all required JSON fields are present and properly formatted
5. WHEN Key Findings extraction is complete, THE Report_Classifier SHALL store the findings in the processing pipeline for urgency scoring

---

### Requirement 4: Urgency Score Calculation

**User Story:** As a clinician, I want diagnostic reports to be scored by clinical urgency, so that the most critical cases are prioritized for immediate review.

#### Acceptance Criteria

1. WHEN Key Findings are extracted from a report, THE Scoring_Engine SHALL calculate an Urgency Score (1-10) based on clinical guidelines and finding severity
2. WHEN calculating the Urgency Score, THE Scoring_Engine SHALL apply weighted scoring rules: critical values receive weight 10, abnormal values receive weight 5, normal values receive weight 1
3. WHEN multiple Key Findings are present, THE Scoring_Engine SHALL aggregate scores using a weighted average formula: (sum of weighted findings) / (count of findings)
4. WHEN a report contains conflicting findings, THE Scoring_Engine SHALL use the highest severity finding to determine the final score
5. WHEN the Urgency Score is calculated, THE Scoring_Engine SHALL store it with the report for dashboard display and escalation logic

---

### Requirement 5: Patient History Contextualization

**User Story:** As a clinician, I want the system to consider patient history when prioritizing reports, so that findings are contextualized appropriately (e.g., a repeated abnormal value may be less urgent than a new critical finding).

#### Acceptance Criteria

1. WHEN a report is scored, THE Contextual_Bridge SHALL query the patient's historical reports (last 12 months) from the EHR
2. WHEN historical reports are retrieved, THE Contextual_Bridge SHALL compare current findings against historical trends
3. WHEN a finding is new or significantly worse than historical baseline, THE Contextual_Bridge SHALL increase the Urgency Score by up to 2 points
4. WHEN a finding is stable or improving compared to historical baseline, THE Contextual_Bridge SHALL decrease the Urgency Score by up to 1 point
5. WHEN patient history is unavailable, THE Contextual_Bridge SHALL proceed with the base Urgency Score without adjustment

---

### Requirement 6: Prioritized Report List Generation

**User Story:** As a clinician, I want to see diagnostic reports sorted by clinical urgency rather than chronological order, so that I can focus on the most critical cases first.

#### Acceptance Criteria

1. WHEN reports are processed and scored, THE Report_Prioritizer SHALL generate a prioritized list sorted by Urgency Score in descending order (highest urgency first)
2. WHEN reports have identical Urgency Scores, THE Report_Prioritizer SHALL sort by timestamp (most recent first) as a tiebreaker
3. WHEN the prioritized list is generated, THE Report_Prioritizer SHALL include report metadata: patient ID, report type, Urgency Score, timestamp, and Key Findings summary
4. WHEN the prioritized list is requested, THE Report_Prioritizer SHALL return it in JSON format suitable for dashboard consumption
5. WHEN new reports are ingested, THE Report_Prioritizer SHALL update the prioritized list in real-time

---

### Requirement 7: Dashboard Display - Chronological View

**User Story:** As a clinician, I want to see diagnostic reports in chronological order (the traditional way), so that I can compare with the AI-prioritized view and understand the difference.

#### Acceptance Criteria

1. WHEN the dashboard loads, THE Dashboard_UI SHALL display a chronological list of diagnostic reports sorted by timestamp (most recent first)
2. WHEN the chronological list is displayed, THE Dashboard_UI SHALL show: patient ID, report type, timestamp, and a 3-bullet summary of Key Findings
3. WHEN a report is selected from the chronological list, THE Dashboard_UI SHALL display the full report text and all extracted Key Findings
4. WHEN the chronological view is active, THE Dashboard_UI SHALL highlight the view selector to indicate the current display mode
5. WHEN reports are updated, THE Dashboard_UI SHALL refresh the chronological list in real-time

---

### Requirement 8: Dashboard Display - AI-Prioritized View

**User Story:** As a clinician, I want to see diagnostic reports prioritized by AI-calculated urgency with visual urgency indicators, so that I can quickly identify critical cases.

#### Acceptance Criteria

1. WHEN the dashboard loads, THE Dashboard_UI SHALL display an AI-prioritized list of diagnostic reports sorted by Urgency Score (highest first)
2. WHEN the prioritized list is displayed, THE Dashboard_UI SHALL show: patient ID, report type, Urgency Score, timestamp, and a 3-bullet summary of Key Findings
3. WHEN displaying the prioritized list, THE Dashboard_UI SHALL use color-coded urgency highlighting: red for scores 8-10 (critical), yellow for scores 5-7 (moderate), green for scores 1-4 (low)
4. WHEN a report is selected from the prioritized list, THE Dashboard_UI SHALL display the full report text, all extracted Key Findings, and the Urgency Score calculation breakdown
5. WHEN reports are updated, THE Dashboard_UI SHALL refresh the prioritized list in real-time

---

### Requirement 9: Report Snooze Functionality

**User Story:** As a clinician, I want to temporarily hide a report from my dashboard, so that I can focus on other cases and review it later.

#### Acceptance Criteria

1. WHEN a clinician clicks the snooze button on a report, THE Dashboard_UI SHALL display a snooze duration selector (5 min, 15 min, 30 min, 1 hour)
2. WHEN a snooze duration is selected, THE Report_Manager SHALL hide the report from the dashboard for the specified duration
3. WHEN the snooze duration expires, THE Report_Manager SHALL restore the report to the dashboard and send a notification to the clinician
4. WHEN a report is snoozed, THE Report_Manager SHALL log the snooze action with timestamp and clinician ID for audit purposes
5. WHEN a snoozed report is manually unsnoozed, THE Report_Manager SHALL immediately restore it to the dashboard

---

### Requirement 10: Report Escalation to Department Head

**User Story:** As a system administrator, I want critical reports to be automatically escalated if not reviewed within a specified timeframe, so that urgent cases receive timely attention.

#### Acceptance Criteria

1. WHEN a report with Urgency Score ≥ 8 is generated, THE Escalation_Service SHALL start a 5-minute review timer
2. WHEN a critical report is reviewed by a clinician, THE Escalation_Service SHALL cancel the escalation timer
3. WHEN the 5-minute timer expires without review, THE Escalation_Service SHALL escalate the report to the department head
4. WHEN a report is escalated, THE Escalation_Service SHALL send a push notification to the department head with the report summary
5. WHEN a report is escalated, THE Escalation_Service SHALL log the escalation event with timestamp and report ID for audit purposes

---

### Requirement 11: Push Notifications

**User Story:** As a clinician, I want to receive push notifications for critical reports and escalations, so that I am immediately aware of urgent cases.

#### Acceptance Criteria

1. WHEN a critical report (Urgency Score ≥ 8) is generated, THE Notification_Service SHALL send a push notification to the assigned clinician
2. WHEN a report is escalated to the department head, THE Notification_Service SHALL send a push notification to the department head
3. WHEN a snoozed report's timer expires, THE Notification_Service SHALL send a push notification to the clinician who snoozed it
4. WHEN a notification is sent, THE Notification_Service SHALL include: report ID, patient ID, Urgency Score, and a brief summary of Key Findings
5. WHEN a notification is sent, THE Notification_Service SHALL log the notification event with timestamp and recipient ID for audit purposes

---

### Requirement 12: Support for Multiple Report Types

**User Story:** As a system operator, I want AFM to process different types of diagnostic reports (blood labs, radiology text, pathology reports), so that the system can handle diverse clinical data.

#### Acceptance Criteria

1. WHEN a diagnostic report is ingested, THE Report_Classifier SHALL identify the report type (blood labs, radiology text, pathology reports)
2. WHEN processing a blood lab report, THE Report_Classifier SHALL extract lab values, reference ranges, and abnormal flags
3. WHEN processing a radiology text report, THE Report_Classifier SHALL extract imaging findings, impressions, and critical observations
4. WHEN processing a pathology report, THE Report_Classifier SHALL extract specimen information, diagnoses, and critical findings
5. WHEN the report type is identified, THE Scoring_Engine SHALL apply report-type-specific scoring rules

---

### Requirement 13: AI Flags for Review (Not Diagnosis)

**User Story:** As a clinician, I want the system to clearly indicate that AI flags are for review only and not diagnostic conclusions, so that I maintain full clinical responsibility and liability protection.

#### Acceptance Criteria

1. WHEN a report is displayed on the dashboard, THE Dashboard_UI SHALL display a disclaimer: "AI-generated flags for review only. Not a diagnostic conclusion. Clinician review required."
2. WHEN Key Findings are displayed, THE Dashboard_UI SHALL label them as "AI-Extracted Findings" to distinguish from clinician-verified findings
3. WHEN an Urgency Score is displayed, THE Dashboard_UI SHALL include a note: "Score calculated by AI. Clinical judgment required for final prioritization."
4. WHEN a report is escalated, THE Escalation_Service SHALL include the disclaimer in the escalation notification
5. WHEN audit logs are generated, THE Audit_Logger SHALL record that all actions are AI-assisted recommendations, not autonomous decisions

---

### Requirement 14: EHR Integration (Non-Replacement)

**User Story:** As a system administrator, I want AFM to augment existing EHR systems without replacing them, so that clinicians can continue using their familiar workflows.

#### Acceptance Criteria

1. WHEN AFM processes a report, THE EHR_Bridge SHALL not modify or delete the original report in the EHR
2. WHEN a clinician reviews a report in AFM, THE EHR_Bridge SHALL provide a link to the original report in the EHR
3. WHEN a clinician takes action on a report (snooze, escalate), THE EHR_Bridge SHALL log the action in the EHR audit trail
4. WHEN AFM is unavailable, THE EHR_Bridge SHALL ensure the EHR continues to function normally without AFM features
5. WHEN a clinician prefers to use the EHR directly, THE EHR_Bridge SHALL not force AFM usage

---

### Requirement 15: MVP - Mock Report Processing

**User Story:** As a developer, I want to process a folder of 20 mock PDF lab reports (including 2 critical reports) for MVP demonstration, so that I can validate the system end-to-end.

#### Acceptance Criteria

1. WHEN the MVP script is executed, THE MVP_Processor SHALL read all PDF files from the designated mock report folder
2. WHEN a PDF is read, THE MVP_Processor SHALL extract text using PyMuPDF
3. WHEN text is extracted, THE MVP_Processor SHALL send it to the Medical LLM for Key Findings extraction
4. WHEN Key Findings are extracted, THE MVP_Processor SHALL calculate Urgency Scores
5. WHEN all reports are processed, THE MVP_Processor SHALL output a JSON file with prioritized reports sorted by Urgency Score

---

### Requirement 16: MVP - Dashboard Display

**User Story:** As a hackathon judge, I want to see a React dashboard displaying both chronological and AI-prioritized report lists, so that I can evaluate the system's effectiveness.

#### Acceptance Criteria

1. WHEN the dashboard loads, THE Dashboard_UI SHALL display two side-by-side views: chronological list (left) and AI-prioritized list (right)
2. WHEN the chronological list is displayed, THE Dashboard_UI SHALL show reports sorted by timestamp with a 3-bullet Key Findings summary
3. WHEN the AI-prioritized list is displayed, THE Dashboard_UI SHALL show reports sorted by Urgency Score with color-coded urgency highlighting
4. WHEN a report is clicked, THE Dashboard_UI SHALL display the full report details including all Key Findings and Urgency Score breakdown
5. WHEN the dashboard is loaded, THE Dashboard_UI SHALL display the 2 critical reports prominently in the AI-prioritized view

---

### Requirement 17: MVP - Snooze and Escalate Loop

**User Story:** As a hackathon judge, I want to interact with the dashboard using snooze and escalate buttons, so that I can test the system's responsiveness and notification system.

#### Acceptance Criteria

1. WHEN a report is displayed on the dashboard, THE Dashboard_UI SHALL display snooze and escalate buttons
2. WHEN the snooze button is clicked, THE Dashboard_UI SHALL hide the report for the selected duration and display a confirmation message
3. WHEN the escalate button is clicked, THE Dashboard_UI SHALL escalate the report and display a confirmation message
4. WHEN a report is escalated, THE Notification_Service SHALL send a push notification (or browser notification for MVP)
5. WHEN the snooze timer expires, THE Dashboard_UI SHALL restore the report and display a notification
