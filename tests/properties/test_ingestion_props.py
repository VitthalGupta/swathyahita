"""Property-based tests for FHIR Ingestion.

# Feature: acuity-first-middleware, Property 1: FHIR Validation
# Property 2: Unique Report IDs
# Validates: Requirements 1.1, 1.3, 1.4
"""
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.services.ingestion import FHIRValidationError, validate_fhir

VALID_BASE = {
    "resourceType": "DiagnosticReport",
    "status": "final",
    "category": "LAB",
    "subject": {"reference": "Patient/123"},
    "issued": "2024-01-15T14:30:00Z",
    "presentedForm": [{"contentType": "text/plain", "data": "SGVsbG8="}],
}


# Feature: acuity-first-middleware, Property 1: FHIR Validation
# Validates: Requirements 1.1, 1.3
@given(
    status=st.sampled_from(["final", "preliminary", "amended"]),
    category=st.sampled_from(["LAB", "RAD", "PATH"]),
    patient_id=st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd"))),
)
@settings(max_examples=100)
def test_valid_fhir_always_accepted(status, category, patient_id):
    """For any valid FHIR DiagnosticReport, it must be accepted without error."""
    data = {
        **VALID_BASE,
        "status": status,
        "category": category,
        "subject": {"reference": f"Patient/{patient_id}"},
    }
    result = validate_fhir(data)
    assert result.resourceType == "DiagnosticReport"
    assert result.status == status
    assert result.category == category


# Feature: acuity-first-middleware, Property 1: FHIR Validation (invalid)
# Validates: Requirements 1.3
@given(
    wrong_type=st.text(min_size=1, max_size=50).filter(lambda t: t != "DiagnosticReport"),
)
@settings(max_examples=50)
def test_wrong_resource_type_always_rejected(wrong_type):
    """Any resourceType other than DiagnosticReport must be rejected."""
    data = {**VALID_BASE, "resourceType": wrong_type}
    with pytest.raises(FHIRValidationError):
        validate_fhir(data)


# Feature: acuity-first-middleware, Property 1: FHIR Validation (missing fields)
# Validates: Requirements 1.3
@given(
    missing_field=st.sampled_from(["status", "category", "subject", "issued", "presentedForm"]),
)
@settings(max_examples=50)
def test_missing_required_field_always_rejected(missing_field):
    """Any valid FHIR report missing a required field must be rejected."""
    data = {k: v for k, v in VALID_BASE.items() if k != missing_field}
    with pytest.raises(FHIRValidationError):
        validate_fhir(data)


# Feature: acuity-first-middleware, Property 2: Unique Report IDs
# Validates: Requirements 1.4
def test_unique_report_ids():
    """Ingesting multiple reports must produce unique IDs."""
    import base64
    from app.services.ingestion import ingest_report, validate_fhir

    ids = set()
    for i in range(50):
        data = {
            **VALID_BASE,
            "subject": {"reference": f"Patient/{i}"},
            "presentedForm": [{"contentType": "text/plain", "data": base64.b64encode(b"test").decode()}],
        }
        fhir = validate_fhir(data)
        raw = base64.b64decode(fhir.presentedForm[0].data)
        report = ingest_report(fhir, raw, False)
        assert report.report_id not in ids, f"Duplicate report ID: {report.report_id}"
        ids.add(report.report_id)
