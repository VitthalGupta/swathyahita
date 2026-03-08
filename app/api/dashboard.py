"""Dashboard API endpoints — chronological and prioritized report views."""
from __future__ import annotations

from fastapi import APIRouter, Query

from app.services.prioritizer import get_chronological_list, get_prioritized_list

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/prioritized")
async def prioritized_view(include_snoozed: bool = Query(False)) -> dict:
    """
    AI-prioritized report list sorted by urgency score DESC.
    Color coding: red=8-10 (critical), yellow=5-7 (moderate), green=1-4 (low).
    """
    reports = get_prioritized_list(include_snoozed=include_snoozed)
    return {
        "view": "prioritized",
        "disclaimer": "AI-generated flags for review only. Not a diagnostic conclusion. Clinician review required.",
        "reports": [
            {
                **r.model_dump(),
                "urgencyColor": _urgency_color(r.urgency_score),
                "timestamp": r.timestamp.isoformat(),
                "escalatedAt": r.escalated_at.isoformat() if r.escalated_at else None,
                "reviewedAt": r.reviewed_at.isoformat() if r.reviewed_at else None,
            }
            for r in reports
        ],
    }


@router.get("/chronological")
async def chronological_view(include_snoozed: bool = Query(False)) -> dict:
    """Chronological report list sorted by timestamp DESC (most recent first)."""
    reports = get_chronological_list(include_snoozed=include_snoozed)
    return {
        "view": "chronological",
        "reports": [
            {
                **r.model_dump(),
                "timestamp": r.timestamp.isoformat(),
                "escalatedAt": r.escalated_at.isoformat() if r.escalated_at else None,
                "reviewedAt": r.reviewed_at.isoformat() if r.reviewed_at else None,
            }
            for r in reports
        ],
    }


def _urgency_color(score: int) -> str:
    if score >= 8:
        return "red"
    if score >= 5:
        return "yellow"
    return "green"
