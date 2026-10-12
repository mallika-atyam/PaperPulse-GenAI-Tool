import io
import json
import uuid
import asyncio
import pytest
import pymupdf as fitz
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient

from app.main import app
from app.database import Base, engine, SessionLocal
from app import models, schemas
from app.extractor import (
    extract_detailed_from_pdf,
    extract_text_from_pdf,
    CorruptedDocumentError,
    PasswordProtectedPDFError,
)
from app.llm import extract_requirements, generate_test_cases_for_requirement
from app.evaluation import calculate_coverage_metrics, generate_traceability_matrix
from app.exporter import export_test_cases_to_csv, export_test_cases_to_excel

# Initialize test client
client = TestClient(app)


@pytest.fixture(scope="module")
def auth_headers():
    """Registers and authenticates a test user, returning Bearer auth headers."""
    email = "test_qa_suite@paperpulse.ai"
    password = "SecurePassword123!"
    client.post("/users", json={"email": email, "password": password})

    login_res = client.post("/auth/login", data={"username": email, "password": password})
    token = login_res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def sample_pdf_bytes() -> bytes:
    """Generates an in-memory sample requirements PDF using PyMuPDF."""
    doc = fitz.open()
    page = doc.new_page()
    text = (
        "SOFTWARE REQUIREMENTS SPECIFICATION\n\n"
        "REQ-001: User Authentication Module\n"
        "The system must authenticate users via email and password.\n"
        "Passwords must be at least 8 characters.\n"
        "Failed attempts return HTTP 401 Unauthorized.\n\n"
        "REQ-002: Session Token Expiration\n"
        "Session tokens must expire after 24 hours of inactivity."
    )
    page.insert_text((50, 72), text, fontsize=12)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


# -----------------------------------------------------------------------------
# Test 1: PDF Text Extraction
# -----------------------------------------------------------------------------
def test_pdf_text_extraction(sample_pdf_bytes):
    result = extract_detailed_from_pdf(sample_pdf_bytes)
    assert result.pages_total == 1
    assert result.character_count > 0
    assert "User Authentication Module" in result.text
    assert result.ocr_used is False


# -----------------------------------------------------------------------------
# Test 2: OCR Fallback Behavior on Image-Only / Sparse Page
# -----------------------------------------------------------------------------
def test_ocr_fallback_sparse_page():
    # Create empty page with no digital text
    doc = fitz.open()
    doc.new_page()
    pdf_bytes = doc.tobytes()
    doc.close()

    result = extract_detailed_from_pdf(pdf_bytes, ocr_threshold=50)
    assert result.pages_total == 1
    # Triggered fallback evaluation without crashing
    assert isinstance(result.text, str)


# -----------------------------------------------------------------------------
# Test 3: Invalid & Empty PDF Handling
# -----------------------------------------------------------------------------
def test_invalid_pdf_handling():
    with pytest.raises(CorruptedDocumentError):
        extract_detailed_from_pdf(b"not a valid pdf content")

    with pytest.raises(CorruptedDocumentError):
        extract_detailed_from_pdf(b"")


# -----------------------------------------------------------------------------
# Test 4: Requirement Schema Validation (Pydantic v2)
# -----------------------------------------------------------------------------
def test_requirement_schema_validation():
    valid_req = schemas.SoftwareRequirement(
        id="REQ-001",
        title="Valid Authentication",
        description="The system shall validate user credentials upon login.",
        category=schemas.RequirementCategory.SECURITY,
        confidence_score=0.95,
        review_status=schemas.ReviewStatus.PENDING_REVIEW,
    )
    assert valid_req.id == "REQ-001"
    assert valid_req.category == schemas.RequirementCategory.SECURITY

    # ID format normalization
    normalized_req = schemas.SoftwareRequirement(
        id="req-2",
        title="Auto Normalized ID",
        description="The system shall normalize IDs to REQ-XXX format.",
        category=schemas.RequirementCategory.FUNCTIONAL,
    )
    assert normalized_req.id == "REQ-002"

    # Invalid ID with no digits
    with pytest.raises(ValueError):
        schemas.SoftwareRequirement(
            id="INVALID",
            title="Invalid ID Req",
            description="Should fail validation due to invalid ID format.",
            category=schemas.RequirementCategory.FUNCTIONAL,
        )


# -----------------------------------------------------------------------------
# Test 5: Test Case Schema Validation (Pydantic v2)
# -----------------------------------------------------------------------------
def test_test_case_schema_validation():
    valid_tc = schemas.TestCase(
        id="TC-001",
        requirement_id="REQ-001",
        title="Verify successful login with valid credentials",
        category=schemas.TestCategory.POSITIVE,
        objective="Ensure user is granted JWT token upon correct credentials.",
        steps=["1. Navigate to login", "2. Submit valid credentials", "3. Assert 200 OK"],
        expected_result="User session created and JWT token returned.",
        priority=schemas.TestPriority.CRITICAL,
    )
    assert valid_tc.id == "TC-001"
    assert valid_tc.priority == schemas.TestPriority.CRITICAL

    # Steps cannot be empty
    with pytest.raises(ValueError):
        schemas.TestCase(
            id="TC-002",
            requirement_id="REQ-001",
            title="Empty steps test case",
            category=schemas.TestCategory.NEGATIVE,
            objective="Ensure rejection when steps are empty.",
            steps=[],
            expected_result="Should fail validation.",
        )


# -----------------------------------------------------------------------------
# Test 6: Mocked LLM / Malformed Gemini Response Handling
# -----------------------------------------------------------------------------
def test_invalid_gemini_response_fallback():
    # Mock call_llm returning malformed JSON
    with patch("app.llm.call_llm", new=AsyncMock(return_value="INVALID_MALFORMED_JSON{{{")):
        req_list = asyncio.run(
            extract_requirements(
                text="User Login Specification text content",
                filename="mock_spec.pdf",
                max_retries=1,
            )
        )
        # Should gracefully fall back to grounded synthetic requirements without throwing 500
        assert req_list.total_found > 0
        assert len(req_list.requirements) > 0


# -----------------------------------------------------------------------------
# Test 7: Traceability Matrix Generation
# -----------------------------------------------------------------------------
def test_traceability_matrix_generation():
    db = SessionLocal()
    try:
        # Create user & material with unique email
        email = f"trace_{uuid.uuid4().hex[:6]}@paperpulse.ai"
        user = models.User(email=email, hashed_password="pw")
        db.add(user)
        db.commit()

        mat = models.Material(owner_id=user.id, filename="trace.pdf", status="uploaded")
        db.add(mat)
        db.commit()

        req = models.RequirementModel(
            req_id="REQ-001",
            material_id=mat.id,
            owner_id=user.id,
            title="Traceability Test Req",
            description="Testing traceability mapping.",
            category="functional",
            review_status="Approved",
        )
        db.add(req)
        db.commit()

        tc = models.TestCaseModel(
            tc_id="TC-001",
            requirement_id=req.id,
            req_code="REQ-001",
            material_id=mat.id,
            owner_id=user.id,
            title="Traceability Test Scenario",
            category="positive",
            objective="Assert traceability linkage",
            steps_json=json.dumps(["Step 1", "Step 2"]),
            expected_result="Traceability asserted",
            priority="High",
            review_status="Approved",
        )
        db.add(tc)
        db.commit()

        matrix = generate_traceability_matrix(db, material_id=mat.id, user_id=user.id)
        assert len(matrix) == 1
        assert matrix[0]["requirement_id"] == "REQ-001"
        assert matrix[0]["coverage_status"] == "Covered (Approved)"
        assert matrix[0]["linked_test_cases_count"] == 1
    finally:
        db.close()


# -----------------------------------------------------------------------------
# Test 8: Coverage Calculation Formula
# -----------------------------------------------------------------------------
def test_coverage_calculation_formula():
    db = SessionLocal()
    try:
        email = f"cov_{uuid.uuid4().hex[:6]}@paperpulse.ai"
        user = models.User(email=email, hashed_password="pw")
        db.add(user)
        db.commit()

        mat = models.Material(owner_id=user.id, filename="coverage.pdf", status="uploaded")
        db.add(mat)
        db.commit()

        # Case A: Zero approved requirements -> coverage should be None (N/A)
        metrics_zero = calculate_coverage_metrics(db, material_id=mat.id, user_id=user.id)
        assert metrics_zero.coverage_percentage is None
        assert metrics_zero.approved_requirements == 0

        # Case B: 2 approved requirements, 1 has approved test case -> coverage should be 50.0%
        r1 = models.RequirementModel(req_id="REQ-001", material_id=mat.id, owner_id=user.id, title="R1", description="D1", review_status="Approved")
        r2 = models.RequirementModel(req_id="REQ-002", material_id=mat.id, owner_id=user.id, title="R2", description="D2", review_status="Approved")
        db.add_all([r1, r2])
        db.commit()

        tc1 = models.TestCaseModel(
            tc_id="TC-001", requirement_id=r1.id, req_code="REQ-001",
            material_id=mat.id, owner_id=user.id, title="T1", category="positive",
            objective="O1", steps_json="[]", expected_result="E1", review_status="Approved"
        )
        db.add(tc1)
        db.commit()

        metrics_fifty = calculate_coverage_metrics(db, material_id=mat.id, user_id=user.id)
        assert metrics_fifty.coverage_percentage == 50.0
        assert metrics_fifty.requirements_with_approved_tests == 1
        assert metrics_fifty.requirements_uncovered == 1
    finally:
        db.close()


# -----------------------------------------------------------------------------
# Test 9: Human-in-the-Loop Approval & Rejection Workflow
# -----------------------------------------------------------------------------
def test_approval_and_rejection_workflow(auth_headers):
    # Upload document
    up = client.post(
        "/sdlc/documents/upload",
        files={"file": ("workflow_test.txt", b"System requires login and registration.", "text/plain")},
        headers=auth_headers,
    )
    assert up.status_code == 201
    doc_id = up.json()["id"]

    # Extract requirements
    ext = client.post(f"/sdlc/documents/{doc_id}/extract-requirements", headers=auth_headers)
    assert ext.status_code == 200
    reqs = ext.json()
    assert len(reqs) > 0

    # Human review: Approve requirement
    req_update = client.put(
        f"/sdlc/requirements/{reqs[0]['id']}",
        json={"review_status": "Approved", "title": "Updated by Human Reviewer"},
        headers=auth_headers,
    )
    assert req_update.status_code == 200
    assert req_update.json()["review_status"] == "Approved"
    assert req_update.json()["title"] == "Updated by Human Reviewer"


# -----------------------------------------------------------------------------
# Test 10: CSV and Excel Exports
# -----------------------------------------------------------------------------
def test_csv_and_excel_exports():
    test_cases_data = [
        {
            "id": "TC-001",
            "requirement_id": "REQ-001",
            "requirement_description": "User Login Requirement",
            "title": "Valid Login",
            "category": "positive",
            "priority": "Critical",
            "preconditions": ["User exists"],
            "test_data": {"user": "admin", "password": "Secret123!"},
            "steps": ["1. Submit valid credentials", "2. Verify 200 OK"],
            "expected_result": "Session token issued",
            "review_status": "Approved",
            "source_document": "auth.pdf",
        }
    ]

    # CSV Test
    csv_str = export_test_cases_to_csv(test_cases_data)
    assert "TC-001" in csv_str
    assert "REQ-001" in csv_str
    assert "Session token issued" in csv_str

    # Excel Test
    excel_bytes = export_test_cases_to_excel(test_cases_data)
    assert isinstance(excel_bytes, bytes)
    assert len(excel_bytes) > 2000  # Valid zip-based xlsx container
