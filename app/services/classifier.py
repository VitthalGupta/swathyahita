"""LLM-based key findings extraction using AWS Bedrock (Claude)."""
from __future__ import annotations

import json
import logging
import time
from typing import Optional

from app.config import config
from app.models import KeyFinding, ReportType, Severity

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a medical AI assistant specializing in clinical report analysis.
Extract all clinically significant findings from the diagnostic report provided.

Return ONLY a valid JSON array of findings. Each finding must have exactly these fields:
- finding_name: string (name of the finding, e.g. "Hemoglobin")
- finding_value: string (measured value with units, e.g. "7.2 g/dL")
- reference_range: string (normal range, e.g. "13.5-17.5 g/dL", or "N/A" if not applicable)
- clinical_significance: string (must start with exactly one of: CRITICAL, ABNORMAL, or NORMAL, followed by a dash and explanation, e.g. "CRITICAL - Severe anemia")

Rules:
- CRITICAL: life-threatening values requiring immediate action
- ABNORMAL: values outside reference range but not immediately life-threatening
- NORMAL: values within acceptable range but clinically noteworthy
- Include ALL significant findings, not just abnormal ones
- For radiology: include imaging findings, impressions, and critical observations
- For pathology: include specimen findings, diagnoses, and critical results
- For labs: include all abnormal values and critical results

Return ONLY the JSON array. No markdown, no explanation."""

LAB_SUPPLEMENT = "\n\nThis is a blood laboratory report. Focus on lab values, reference ranges, and abnormal flags."
RAD_SUPPLEMENT = "\n\nThis is a radiology report. Focus on imaging findings, impressions, and critical observations."
PATH_SUPPLEMENT = "\n\nThis is a pathology report. Focus on specimen information, diagnoses, and critical findings."

REPORT_TYPE_PROMPTS = {
    ReportType.LAB: LAB_SUPPLEMENT,
    ReportType.RAD: RAD_SUPPLEMENT,
    ReportType.PATH: PATH_SUPPLEMENT,
}


def _parse_severity(clinical_significance: str) -> Severity:
    upper = clinical_significance.upper()
    if upper.startswith("CRITICAL"):
        return Severity.CRITICAL
    if upper.startswith("ABNORMAL"):
        return Severity.ABNORMAL
    return Severity.NORMAL


def _validate_findings(raw: list[dict]) -> list[KeyFinding]:
    required = {"finding_name", "finding_value", "reference_range", "clinical_significance"}
    findings = []
    for item in raw:
        missing = required - set(item.keys())
        if missing:
            logger.warning(f"Skipping finding with missing fields: {missing}")
            continue
        severity = _parse_severity(item["clinical_significance"])
        findings.append(KeyFinding(
            finding_name=item["finding_name"],
            finding_value=item["finding_value"],
            reference_range=item["reference_range"],
            clinical_significance=item["clinical_significance"],
            severity=severity,
        ))
    return findings


def _call_bedrock(system: str, user_text: str) -> str:
    """
    Call AWS Bedrock Runtime using the Converse API (model-agnostic).
    Works with Claude 3/3.5 models on Bedrock.
    """
    from app.aws.clients import get_bedrock

    client = get_bedrock()
    response = client.converse(
        modelId=config.BEDROCK_MODEL_ID,
        system=[{"text": system}],
        messages=[{"role": "user", "content": [{"text": user_text}]}],
        inferenceConfig={
            "maxTokens": 2048,
            "temperature": 0.0,  # deterministic for medical extraction
        },
    )
    return response["output"]["message"]["content"][0]["text"].strip()


def extract_key_findings(
    report_text: str,
    report_type: ReportType,
    max_retries: int = 3,
) -> list[KeyFinding]:
    """
    Use Claude on AWS Bedrock to extract key findings from report text.
    Retries up to max_retries times with exponential backoff.
    """
    supplement = REPORT_TYPE_PROMPTS.get(report_type, "")
    system = SYSTEM_PROMPT + supplement

    last_error: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            content = _call_bedrock(system, report_text)

            # Strip markdown code fences if present
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()

            raw = json.loads(content)
            if not isinstance(raw, list):
                raise ValueError("Bedrock response is not a JSON array")

            findings = _validate_findings(raw)
            if not findings:
                raise ValueError("No valid findings extracted")

            logger.info(f"Bedrock extracted {len(findings)} findings using {config.BEDROCK_MODEL_ID}")
            return findings

        except (json.JSONDecodeError, ValueError, KeyError) as exc:
            last_error = exc
            logger.warning(f"Attempt {attempt + 1}/{max_retries} failed parsing Bedrock response: {exc}")
        except Exception as exc:
            last_error = exc
            logger.warning(f"Attempt {attempt + 1}/{max_retries} Bedrock API error: {exc}")

        if attempt < max_retries - 1:
            time.sleep(2 ** attempt)  # exponential backoff: 1s, 2s

    raise RuntimeError(f"Failed to extract key findings after {max_retries} attempts: {last_error}")
