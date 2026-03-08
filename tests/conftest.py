"""Global test configuration — activates moto AWS mocks for all tests."""
from __future__ import annotations

import os
import pytest
import boto3
from moto import mock_aws

# Set fake AWS credentials before any boto3 imports
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_SECURITY_TOKEN", "testing")
os.environ.setdefault("AWS_SESSION_TOKEN", "testing")
os.environ.setdefault("AWS_REGION", "us-east-1")


@pytest.fixture(autouse=True)
def aws_mock():
    """
    Auto-use fixture: wraps every test in moto's mock_aws context.
    Creates all required DynamoDB tables before each test.
    """
    with mock_aws():
        # Clear lru_cache so fresh mocked clients are created
        from app.aws.clients import (
            get_dynamodb, get_dynamodb_client,
            get_s3, get_sqs, get_sns, get_bedrock,
        )
        for fn in [get_dynamodb, get_dynamodb_client, get_s3, get_sqs, get_sns, get_bedrock]:
            fn.cache_clear()

        # Create DynamoDB tables
        ddb = boto3.client("dynamodb", region_name="us-east-1")
        for table_name, pk in [
            ("afm-reports", "report_id"),
            ("afm-audit-logs", "log_id"),
            ("afm-notifications", "notification_id"),
        ]:
            try:
                ddb.create_table(
                    TableName=table_name,
                    AttributeDefinitions=[{"AttributeName": pk, "AttributeType": "S"}],
                    KeySchema=[{"AttributeName": pk, "KeyType": "HASH"}],
                    BillingMode="PAY_PER_REQUEST",
                )
            except Exception:
                pass

        yield

        # Clear cache again after test so next test gets fresh mocked clients
        for fn in [get_dynamodb, get_dynamodb_client, get_s3, get_sqs, get_sns, get_bedrock]:
            fn.cache_clear()
