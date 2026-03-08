#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# AFM AWS Infrastructure Setup Script
# Run once to create all required AWS resources.
# Prerequisites: AWS CLI configured with sufficient permissions
# Usage: chmod +x infrastructure/setup_aws.sh && ./infrastructure/setup_aws.sh
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

REGION="${AWS_REGION:-us-east-2}"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
PREFIX="afm"

echo "Creating AFM infrastructure in ${REGION} (account: ${ACCOUNT_ID})"

# ── DynamoDB Tables ───────────────────────────────────────────────────────────
echo "Creating DynamoDB tables..."

for TABLE in "afm-reports:report_id" "afm-audit-logs:log_id" "afm-notifications:notification_id"; do
  NAME="${TABLE%%:*}"
  PK="${TABLE##*:}"
  aws dynamodb create-table \
    --table-name "$NAME" \
    --attribute-definitions AttributeName="$PK",AttributeType=S \
    --key-schema AttributeName="$PK",KeyType=HASH \
    --billing-mode PAY_PER_REQUEST \
    --region "$REGION" \
    --no-cli-pager 2>/dev/null && echo "  Created: $NAME" || echo "  Already exists: $NAME"
done

# GSI on afm-reports for patient_id queries (production optimization)
aws dynamodb update-table \
  --table-name afm-reports \
  --attribute-definitions AttributeName=patient_id,AttributeType=S AttributeName=report_id,AttributeType=S \
  --global-secondary-index-updates \
    '[{"Create":{"IndexName":"patient_id-index","KeySchema":[{"AttributeName":"patient_id","KeyType":"HASH"}],"Projection":{"ProjectionType":"ALL"}}}]' \
  --region "$REGION" \
  --no-cli-pager 2>/dev/null && echo "  Created GSI: patient_id-index on afm-reports" || echo "  GSI may already exist"

# ── S3 Bucket ─────────────────────────────────────────────────────────────────
echo "Creating S3 bucket..."
BUCKET_NAME="afm-pdf-reports-${ACCOUNT_ID}"
aws s3api create-bucket \
  --bucket "$BUCKET_NAME" \
  --region "$REGION" \
  $([ "$REGION" != "us-east-1" ] && echo "--create-bucket-configuration LocationConstraint=$REGION") \
  --no-cli-pager 2>/dev/null && echo "  Created: $BUCKET_NAME" || echo "  Already exists: $BUCKET_NAME"

# Enable server-side encryption
aws s3api put-bucket-encryption \
  --bucket "$BUCKET_NAME" \
  --server-side-encryption-configuration \
    '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}' \
  --no-cli-pager
echo "  S3 encryption enabled on $BUCKET_NAME"

# Block public access
aws s3api put-public-access-block \
  --bucket "$BUCKET_NAME" \
  --public-access-block-configuration \
    "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true" \
  --no-cli-pager
echo "  S3 public access blocked on $BUCKET_NAME"

# ── SQS Queues ────────────────────────────────────────────────────────────────
echo "Creating SQS queues..."

# Report processing FIFO queue
PROCESSING_URL=$(aws sqs create-queue \
  --queue-name afm-processing.fifo \
  --attributes FifoQueue=true,ContentBasedDeduplication=true \
  --region "$REGION" \
  --query QueueUrl --output text \
  --no-cli-pager 2>/dev/null) && echo "  Created/found: afm-processing.fifo"

# Escalation delay queue (standard, DelaySeconds set per-message)
ESCALATION_URL=$(aws sqs create-queue \
  --queue-name afm-escalation \
  --attributes VisibilityTimeout=60,MessageRetentionPeriod=3600 \
  --region "$REGION" \
  --query QueueUrl --output text \
  --no-cli-pager 2>/dev/null) && echo "  Created/found: afm-escalation"

# Snooze expiry queue
SNOOZE_URL=$(aws sqs create-queue \
  --queue-name afm-snooze \
  --attributes VisibilityTimeout=60,MessageRetentionPeriod=7200 \
  --region "$REGION" \
  --query QueueUrl --output text \
  --no-cli-pager 2>/dev/null) && echo "  Created/found: afm-snooze"

# ── SNS Topics ────────────────────────────────────────────────────────────────
echo "Creating SNS topics..."

CRITICAL_ARN=$(aws sns create-topic --name afm-critical-reports --region "$REGION" --query TopicArn --output text --no-cli-pager)
ESCALATION_ARN=$(aws sns create-topic --name afm-escalations --region "$REGION" --query TopicArn --output text --no-cli-pager)
SNOOZE_ARN=$(aws sns create-topic --name afm-snooze-expiry --region "$REGION" --query TopicArn --output text --no-cli-pager)
echo "  SNS topics created"

# ── Enable Bedrock Model Access ───────────────────────────────────────────────
echo ""
echo "IMPORTANT: Enable Bedrock model access manually in the AWS Console:"
echo "  1. Go to AWS Bedrock → Model access"
echo "  2. Enable: Claude 3.5 Sonnet (anthropic.claude-3-5-sonnet-20241022-v2:0)"
echo "  3. Region: ${REGION}"

# ── Output .env values ────────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Copy these values into your .env file:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "AWS_REGION=${REGION}"
echo "DYNAMODB_TABLE_REPORTS=afm-reports"
echo "DYNAMODB_TABLE_AUDIT=afm-audit-logs"
echo "DYNAMODB_TABLE_NOTIFICATIONS=afm-notifications"
echo "S3_BUCKET_PDF=${BUCKET_NAME}"
echo "SQS_PROCESSING_QUEUE_URL=${PROCESSING_URL:-<check AWS console>}"
echo "SQS_ESCALATION_QUEUE_URL=${ESCALATION_URL:-<check AWS console>}"
echo "SQS_SNOOZE_QUEUE_URL=${SNOOZE_URL:-<check AWS console>}"
echo "SNS_TOPIC_CRITICAL_REPORTS=${CRITICAL_ARN}"
echo "SNS_TOPIC_ESCALATIONS=${ESCALATION_ARN}"
echo "SNS_TOPIC_SNOOZE_EXPIRY=${SNOOZE_ARN}"
echo "BEDROCK_MODEL_ID=anthropic.claude-3-5-sonnet-20241022-v2:0"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Done!"
