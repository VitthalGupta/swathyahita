# AFM Deployment Guide

## Prerequisites

- AWS account with admin access (for initial setup)
- [AWS CLI](https://aws.amazon.com/cli/) configured (`aws configure`)
- [Docker](https://docs.docker.com/get-docker/) (for ECS deployment)
- [uv](https://docs.astral.sh/uv/) package manager

---

## Step 1 — Provision AWS Resources

Run the setup script once per environment:

```bash
export AWS_REGION=us-east-1
chmod +x infrastructure/setup_aws.sh
./infrastructure/setup_aws.sh
```

This creates:

| Resource | Name |
|---|---|
| DynamoDB table | `afm-reports` |
| DynamoDB table | `afm-audit-logs` |
| DynamoDB table | `afm-notifications` |
| S3 bucket | `afm-pdf-reports-<ACCOUNT_ID>` |
| SQS FIFO queue | `afm-processing.fifo` |
| SQS standard queue | `afm-escalation` |
| SQS standard queue | `afm-snooze` |
| SNS topic | `afm-critical-reports` |
| SNS topic | `afm-escalations` |
| SNS topic | `afm-snooze-expiry` |

The script prints all URLs and ARNs to copy into `.env`.

---

## Step 2 — Enable Bedrock Model Access

1. Open [AWS Console → Bedrock → Model access](https://console.aws.amazon.com/bedrock/home#/modelaccess)
2. Click **Manage model access**
3. Enable: **Claude 3.5 Sonnet** (`anthropic.claude-3-5-sonnet-20241022-v2:0`)
4. Click **Save changes** (takes 1–5 minutes)

---

## Step 3 — Configure Environment

```bash
cp .env.example .env
# Paste values from setup_aws.sh output into .env
```

Required environment variables:

```env
AWS_REGION=us-east-1
BEDROCK_MODEL_ID=anthropic.claude-3-5-sonnet-20241022-v2:0
DYNAMODB_TABLE_REPORTS=afm-reports
DYNAMODB_TABLE_AUDIT=afm-audit-logs
DYNAMODB_TABLE_NOTIFICATIONS=afm-notifications
S3_BUCKET_PDF=afm-pdf-reports-<ACCOUNT_ID>
SQS_ESCALATION_QUEUE_URL=https://sqs.us-east-1.amazonaws.com/<ACCOUNT_ID>/afm-escalation
SNS_TOPIC_CRITICAL_REPORTS=arn:aws:sns:us-east-1:<ACCOUNT_ID>:afm-critical-reports
SNS_TOPIC_ESCALATIONS=arn:aws:sns:us-east-1:<ACCOUNT_ID>:afm-escalations
SNS_TOPIC_SNOOZE_EXPIRY=arn:aws:sns:us-east-1:<ACCOUNT_ID>:afm-snooze-expiry
```

---

## Option A — Local Development

```bash
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

Visit **http://localhost:8000/docs** for the Swagger UI.

For local dev, credentials from `aws configure` are used automatically.

---

## Option B — ECS Fargate (Recommended for Production)

### 1. Create the Dockerfile

```dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --frozen

COPY app/ ./app/

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 2. Push to ECR

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_URI="$ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/afm-backend"

aws ecr create-repository --repository-name afm-backend --region us-east-1

aws ecr get-login-password | docker login --username AWS --password-stdin $ECR_URI

docker build -t afm-backend .
docker tag afm-backend:latest $ECR_URI:latest
docker push $ECR_URI:latest
```

### 3. Create ECS Task Definition

Key settings:
- **Image**: `$ECR_URI:latest`
- **CPU**: 1024 (1 vCPU), **Memory**: 2048 MB
- **Task role**: IAM role with the permissions from `docs/ARCHITECTURE.md`
- **Environment variables**: inject from AWS Secrets Manager or Parameter Store
- **Port**: 8000

### 4. Create ECS Service

```bash
aws ecs create-service \
  --cluster afm-cluster \
  --service-name afm-backend \
  --task-definition afm-backend \
  --desired-count 2 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[subnet-xxx],securityGroups=[sg-xxx],assignPublicIp=ENABLED}"
```

---

## Option C — AWS Lambda

The FastAPI app is wrapped with [Mangum](https://mangum.io/) for Lambda compatibility.

### 1. Package with Lambda layers

```bash
uv export --no-dev --format requirements-txt > requirements.txt
pip install -r requirements.txt -t lambda_package/
cp -r app/ lambda_package/app/
cd lambda_package && zip -r ../afm-lambda.zip . && cd ..
```

### 2. Create Lambda function

```bash
aws lambda create-function \
  --function-name afm-backend \
  --runtime python3.12 \
  --handler app.main.lambda_handler \
  --zip-file fileb://afm-lambda.zip \
  --role arn:aws:iam::ACCOUNT_ID:role/afm-lambda-role \
  --timeout 30 \
  --memory-size 512 \
  --environment Variables="{AWS_REGION=us-east-1,...}"
```

### 3. Add API Gateway trigger

Create an HTTP API Gateway and connect it to the Lambda function.

---

## Escalation Consumer Setup (SQS → Lambda)

For durable escalation timers, create a Lambda triggered by the `afm-escalation` SQS queue:

```python
import json, urllib.request

def handler(event, context):
    for record in event["Records"]:
        body = json.loads(record["body"])
        report_id = body["report_id"]
        # Call AFM internal endpoint
        req = urllib.request.Request(
            f"{AFM_BASE_URL}/api/reports/internal/escalation",
            data=json.dumps({"report_id": report_id}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req)
```

Connect via:
```bash
aws lambda create-event-source-mapping \
  --function-name afm-escalation-consumer \
  --event-source-arn arn:aws:sqs:us-east-1:ACCOUNT_ID:afm-escalation \
  --batch-size 10
```

---

## SNS Subscriptions

To receive notifications, subscribe endpoints to SNS topics:

```bash
# Email subscription (for department head)
aws sns subscribe \
  --topic-arn arn:aws:sns:us-east-1:ACCOUNT_ID:afm-escalations \
  --protocol email \
  --notification-endpoint dept-head@hospital.org

# Mobile push: integrate SNS with your FCM/APNS application
```

---

## GitHub Actions CI/CD

The `.github/workflows/deploy.yml` workflow:
1. Builds and pushes Docker image to ECR on every push to `main`
2. Updates ECS service and waits for deployment stability
3. Uses OIDC for keyless AWS authentication (no long-lived credentials)

Required GitHub Secrets:
- `AWS_DEPLOY_ROLE_ARN` — IAM role ARN with ECR push + ECS deploy permissions

---

## Health Check

```bash
curl https://your-afm-endpoint/health
# {"status": "ok", "service": "AFM Backend", "runtime": "AWS"}
```

---

## Monitoring

- **CloudWatch Logs**: All `logging.*` calls are captured automatically in ECS/Lambda
- **CloudWatch Metrics**: ECS CPU/memory, Lambda invocations/errors
- **DynamoDB**: Enable CloudWatch contributor insights for query patterns
- **Bedrock**: Monitor via CloudWatch `bedrock:InvokeModel` metrics
