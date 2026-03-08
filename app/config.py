"""Centralized AWS and application configuration loaded from environment variables."""
from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()


class AWSConfig:
    # Core AWS settings
    REGION: str = os.getenv("AWS_REGION", "us-east-1")

    # DynamoDB table names
    DYNAMODB_TABLE_REPORTS: str = os.getenv("DYNAMODB_TABLE_REPORTS", "afm-reports")
    DYNAMODB_TABLE_AUDIT: str = os.getenv("DYNAMODB_TABLE_AUDIT", "afm-audit-logs")
    DYNAMODB_TABLE_NOTIFICATIONS: str = os.getenv("DYNAMODB_TABLE_NOTIFICATIONS", "afm-notifications")

    # S3 bucket for PDF storage
    S3_BUCKET_PDF: str = os.getenv("S3_BUCKET_PDF", "afm-pdf-reports")

    # SQS queues
    # FIFO queue for report processing (ensures ordered processing)
    SQS_PROCESSING_QUEUE_URL: str = os.getenv("SQS_PROCESSING_QUEUE_URL", "")
    # Standard queue for escalation delay messages (DelaySeconds=300)
    SQS_ESCALATION_QUEUE_URL: str = os.getenv("SQS_ESCALATION_QUEUE_URL", "")
    # Standard queue for snooze expiry messages
    SQS_SNOOZE_QUEUE_URL: str = os.getenv("SQS_SNOOZE_QUEUE_URL", "")

    # SNS topics
    SNS_TOPIC_CRITICAL_REPORTS: str = os.getenv("SNS_TOPIC_CRITICAL_REPORTS", "")
    SNS_TOPIC_ESCALATIONS: str = os.getenv("SNS_TOPIC_ESCALATIONS", "")
    SNS_TOPIC_SNOOZE_EXPIRY: str = os.getenv("SNS_TOPIC_SNOOZE_EXPIRY", "")

    # Bedrock model — use Claude 3.5 Sonnet on Bedrock
    BEDROCK_MODEL_ID: str = os.getenv(
        "BEDROCK_MODEL_ID",
        "us.anthropic.claude-3-7-sonnet-20250219-v1:0",
    )

    # Escalation settings
    ESCALATION_TIMEOUT_SECONDS: int = int(os.getenv("ESCALATION_TIMEOUT_SECONDS", "300"))  # 5 min

    # EHR base URL (for report links)
    EHR_BASE_URL: str = os.getenv("EHR_BASE_URL", "https://ehr.example.com")

    # Department head recipient for escalations
    DEPT_HEAD_ID: str = os.getenv("DEPT_HEAD_ID", "dept-head")


config = AWSConfig()
