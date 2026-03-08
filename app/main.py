"""Acuity-First Middleware (AFM) — FastAPI application.
Supports both ECS/EC2 (uvicorn) and AWS Lambda (Mangum) deployment.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import actions, dashboard, reports

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.getLogger(__name__).info("AFM backend starting up (AWS-native mode)")
    yield
    logging.getLogger(__name__).info("AFM backend shutting down")


app = FastAPI(
    title="Acuity-First Middleware (AFM)",
    description=(
        "Medical diagnostic report prioritization system. "
        "AI-generated flags for review only. Not a diagnostic conclusion. "
        "Clinician review required."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — allow all origins for MVP; restrict to frontend domain in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount routers
app.include_router(reports.router)
app.include_router(dashboard.router)
app.include_router(actions.router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "AFM Backend", "runtime": "AWS"}


@app.get("/")
async def root() -> dict:
    return {
        "service": "Acuity-First Middleware (AFM)",
        "version": "0.1.0",
        "aws_services": ["Bedrock (Claude LLM)", "DynamoDB (storage)", "S3 (PDFs)", "SQS (queue)", "SNS (notifications)"],
        "disclaimer": "AI-generated flags for review only. Not a diagnostic conclusion. Clinician review required.",
        "endpoints": {
            "ingest": "POST /api/reports/ingest",
            "reports": "GET /api/reports/",
            "report_detail": "GET /api/reports/{id}",
            "prioritized": "GET /api/dashboard/prioritized",
            "chronological": "GET /api/dashboard/chronological",
            "snooze": "POST /api/reports/{id}/snooze",
            "escalate": "POST /api/reports/{id}/escalate",
            "review": "POST /api/reports/{id}/review",
            "internal_escalation": "POST /api/reports/internal/escalation",
            "audit_logs": "GET /api/reports/audit/logs",
            "docs": "/docs",
        },
    }


# AWS Lambda handler (via Mangum)
# Set handler = "app.main.lambda_handler" in Lambda function config
try:
    from mangum import Mangum
    lambda_handler = Mangum(app, lifespan="off")
except ImportError:
    pass
