"""
MVP Batch Processor for Acuity-First Middleware (AFM).

Usage:
    uv run python mvp/processor.py [--mock-dir mvp/mock_reports] [--output mvp/output.json]

Reads all PDF files from the mock_reports directory, runs the full AFM pipeline on each,
and outputs a prioritized JSON file sorted by urgency score.

Requirements 15.1-15.5
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# Ensure project root is in path
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def _mock_report_type(filename: str) -> str:
    name = filename.lower()
    if "rad" in name or "xray" in name or "ct" in name or "mri" in name:
        return "RAD"
    if "path" in name or "biopsy" in name or "histology" in name:
        return "PATH"
    return "LAB"


def process_pdf(pdf_path: str, patient_id: str, report_type: str) -> dict[str, Any]:
    """Process a single PDF through the AFM pipeline."""
    from app.services.classifier import extract_key_findings
    from app.services.contextual_bridge import adjust_score_with_history
    from app.services.pdf_extractor import extract_text_from_path
    from app.services.scoring import calculate_urgency_score, get_score_breakdown
    from app.models import Report, ReportStatus, ReportType
    from app.store import store

    report_id = str(uuid.uuid4())
    filename = os.path.basename(pdf_path)
    logger.info(f"Processing: {filename} (patient={patient_id}, type={report_type})")

    # Step 1: Extract text
    try:
        text, ocr_processed = extract_text_from_path(pdf_path)
        if not text.strip():
            raise ValueError("No text extracted from PDF")
    except Exception as exc:
        logger.error(f"Extraction failed for {filename}: {exc}")
        return {
            "reportId": report_id,
            "filename": filename,
            "patientId": patient_id,
            "reportType": report_type,
            "status": "EXTRACTION_FAILED",
            "error": str(exc),
        }

    # Step 2: LLM classification
    try:
        findings = extract_key_findings(text, ReportType(report_type))
    except Exception as exc:
        logger.error(f"LLM classification failed for {filename}: {exc}")
        return {
            "reportId": report_id,
            "filename": filename,
            "patientId": patient_id,
            "reportType": report_type,
            "status": "LLM_FAILED",
            "error": str(exc),
        }

    # Step 3: Score calculation
    base_score = calculate_urgency_score(findings, report_id)

    # Step 4: Build report for contextual bridge
    # Use a staggered timestamp for demo purposes
    timestamp = datetime.utcnow() - timedelta(minutes=hash(filename) % 120)
    report = Report(
        report_id=report_id,
        patient_id=patient_id,
        report_type=ReportType(report_type),
        status=ReportStatus.COMPLETED,
        original_text=text[:500],  # truncate for storage
        key_findings=findings,
        urgency_score=base_score,
        base_score=base_score,
        timestamp=timestamp,
        ehr_link=f"https://ehr.example.com/reports/{report_id}",
        ocr_processed=ocr_processed,
    )
    store.add_report(report)
    # Update (bypass queue processing since we set it directly)
    store.update_report(report)

    # Step 5: Contextual bridge
    adjusted_score, adjustment = adjust_score_with_history(report)
    report.urgency_score = adjusted_score
    report.score_adjustment = adjustment
    store.update_report(report)

    breakdown = get_score_breakdown(findings)

    logger.info(f"  → urgency_score={adjusted_score} (base={base_score}, adj={adjustment:+d}) findings={len(findings)}")

    return {
        "reportId": report_id,
        "filename": filename,
        "patientId": patient_id,
        "reportType": report_type,
        "urgencyScore": adjusted_score,
        "baseScore": base_score,
        "scoreAdjustment": adjustment,
        "scoreBreakdown": breakdown,
        "timestamp": timestamp.isoformat(),
        "keyFindingsSummary": report.key_findings_summary(),
        "keyFindings": [f.model_dump() for f in findings],
        "ehrLink": report.ehr_link,
        "ocrProcessed": ocr_processed,
        "disclaimer": "AI-generated flags for review only. Not a diagnostic conclusion. Clinician review required.",
        "scoreNote": "Score calculated by AI. Clinical judgment required for final prioritization.",
        "urgencyColor": "red" if adjusted_score >= 8 else ("yellow" if adjusted_score >= 5 else "green"),
        "status": "completed",
    }


def run(mock_dir: str, output_path: str) -> None:
    pdf_files = sorted(Path(mock_dir).glob("*.pdf"))
    if not pdf_files:
        logger.warning(f"No PDF files found in {mock_dir}")
        return

    logger.info(f"Found {len(pdf_files)} PDF files to process")
    results = []

    for i, pdf_path in enumerate(pdf_files):
        # Assign patient IDs cycling through a pool (for contextual bridge testing)
        patient_id = f"patient-{(i % 10) + 1:03d}"
        report_type = _mock_report_type(pdf_path.name)
        result = process_pdf(str(pdf_path), patient_id, report_type)
        results.append(result)

    # Sort by urgency score descending, timestamp descending as tiebreaker
    completed = [r for r in results if r.get("status") == "completed"]
    failed = [r for r in results if r.get("status") != "completed"]

    completed.sort(
        key=lambda r: (r.get("urgencyScore", 0), r.get("timestamp", "")),
        reverse=True,
    )

    output = {
        "generated_at": datetime.utcnow().isoformat(),
        "total_reports": len(results),
        "completed": len(completed),
        "failed": len(failed),
        "disclaimer": "AI-generated flags for review only. Not a diagnostic conclusion. Clinician review required.",
        "reports": completed + failed,
    }

    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, default=str)

    logger.info(f"Output written to {output_path}")
    logger.info(f"Summary: {len(completed)} completed, {len(failed)} failed")

    # Print critical reports
    critical = [r for r in completed if r.get("urgencyScore", 0) >= 8]
    if critical:
        logger.info(f"\nCRITICAL REPORTS ({len(critical)}):")
        for r in critical:
            logger.info(f"  [{r['urgencyScore']}/10] {r['filename']} - Patient {r['patientId']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AFM MVP Batch Processor")
    parser.add_argument(
        "--mock-dir",
        default=str(Path(__file__).parent / "mock_reports"),
        help="Directory containing mock PDF reports",
    )
    parser.add_argument(
        "--output",
        default=str(Path(__file__).parent / "output.json"),
        help="Output JSON file path",
    )
    args = parser.parse_args()

    if not os.path.isdir(args.mock_dir):
        logger.error(f"Mock reports directory not found: {args.mock_dir}")
        sys.exit(1)

    run(args.mock_dir, args.output)
