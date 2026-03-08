"""Boto3 client singletons for all AWS services used by AFM."""
from __future__ import annotations

import boto3
from functools import lru_cache

from app.config import config


@lru_cache(maxsize=1)
def get_dynamodb():
    """DynamoDB resource (high-level Table API)."""
    return boto3.resource("dynamodb", region_name=config.REGION)


@lru_cache(maxsize=1)
def get_dynamodb_client():
    """DynamoDB low-level client (for CreateTable, etc.)."""
    return boto3.client("dynamodb", region_name=config.REGION)


@lru_cache(maxsize=1)
def get_s3():
    """S3 client for PDF storage."""
    return boto3.client("s3", region_name=config.REGION)


@lru_cache(maxsize=1)
def get_sqs():
    """SQS client for processing queue and escalation delay messages."""
    return boto3.client("sqs", region_name=config.REGION)


@lru_cache(maxsize=1)
def get_sns():
    """SNS client for push notifications."""
    return boto3.client("sns", region_name=config.REGION)


@lru_cache(maxsize=1)
def get_bedrock():
    """Bedrock Runtime client for Claude LLM inference."""
    return boto3.client("bedrock-runtime", region_name=config.REGION)


def get_dynamodb_table(table_name: str):
    """Return a DynamoDB Table resource by name."""
    return get_dynamodb().Table(table_name)
