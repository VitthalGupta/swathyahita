"""Unit tests for FHIR Report Ingestion.

# Feature: acuity-first-middleware
# Validates: Requirements 1.1, 1.3, 1.4
"""
import pytest

from app.services.ingestion import FHIRValidationError, validate_fhir

VALID_FHIR = {
    "resourceType": "DiagnosticReport",
    "status": "final",
    "category": "LAB",
    "subject": {"reference": "Patient/123"},
    "issued": "2024-01-15T14:30:00Z",
    "presentedForm": [{"contentType": "text/plain", "data": "SGVsbG8gV29ybGQ="}],
}


class TestFHIRValidation:
    """Property 1: FHIR Validation — valid reports accepted, invalid rejected with 400."""

    def test_valid_report_accepted(self):
        result = validate_fhir(VALID_FHIR)
        assert result.resourceType == "DiagnosticReport"
        assert result.category == "LAB"

    def test_wrong_resource_type_rejected(self):
        data = {**VALID_FHIR, "resourceType": "Patient"}
        with pytest.raises(FHIRValidationError) as exc:
            validate_fhir(data)
        assert "resourceType" in exc.value.detail

    def test_missing_status_rejected(self):
        data = {k: v for k, v in VALID_FHIR.items() if k != "status"}
        with pytest.raises(FHIRValidationError) as exc:
            validate_fhir(data)
        assert "status" in exc.value.detail.lower()

    def test_missing_subject_rejected(self):
        data = {k: v for k, v in VALID_FHIR.items() if k != "subject"}
        with pytest.raises(FHIRValidationError) as exc:
            validate_fhir(data)
        assert "subject" in exc.value.detail.lower()

    def test_missing_subject_reference_rejected(self):
        data = {**VALID_FHIR, "subject": {"display": "John Doe"}}
        with pytest.raises(FHIRValidationError) as exc:
            validate_fhir(data)
        assert "subject.reference" in exc.value.detail

    def test_invalid_status_rejected(self):
        data = {**VALID_FHIR, "status": "unknown"}
        with pytest.raises(FHIRValidationError) as exc:
            validate_fhir(data)
        assert "status" in exc.value.detail.lower()

    def test_invalid_category_rejected(self):
        data = {**VALID_FHIR, "category": "UNKNOWN"}
        with pytest.raises(FHIRValidationError) as exc:
            validate_fhir(data)
        assert "category" in exc.value.detail.lower()

    def test_missing_presented_form_rejected(self):
        data = {**VALID_FHIR, "presentedForm": []}
        with pytest.raises(FHIRValidationError) as exc:
            validate_fhir(data)
        assert "presentedForm" in exc.value.detail

    def test_missing_data_in_presented_form_rejected(self):
        data = {**VALID_FHIR, "presentedForm": [{"contentType": "text/plain"}]}
        with pytest.raises(FHIRValidationError) as exc:
            validate_fhir(data)
        assert "data" in exc.value.detail.lower()

    def test_rad_category_accepted(self):
        data = {**VALID_FHIR, "category": "RAD"}
        result = validate_fhir(data)
        assert result.category == "RAD"

    def test_path_category_accepted(self):
        data = {**VALID_FHIR, "category": "PATH"}
        result = validate_fhir(data)
        assert result.category == "PATH"

    def test_preliminary_status_accepted(self):
        data = {**VALID_FHIR, "status": "preliminary"}
        result = validate_fhir(data)
        assert result.status == "preliminary"
