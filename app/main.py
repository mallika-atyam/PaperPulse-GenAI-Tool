import os
import json
import logging
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Query, status, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

# Load environment variables
load_dotenv()

from app.database import engine, Base, get_db
from app import models, schemas
from app.auth import (
    get_current_user,
    get_password_hash,
    authenticate_user,
    create_access_token,
)
from app.extractor import (
    extract_text_from_pdf,
    extract_detailed_from_pdf,
    DetailedExtractionResult,
    LimitExceededError,
    PasswordProtectedPDFError,
    CorruptedDocumentError,
    ExtractionError,
)
from app.llm import (
    generate_summary,
    generate_quiz,
    extract_requirements,
    generate_test_cases_for_requirement,
    generate_all_test_cases,
)
from app.evaluation import (
    calculate_coverage_metrics,
    generate_traceability_matrix,
    evaluate_ground_truth_benchmarks,
)
from app.exporter import (
    export_test_cases_to_csv,
    export_test_cases_to_excel,
)
from app.agent import GoalDrivenTestingAgent

logger = logging.getLogger(__name__)

# Initialize database tables on startup
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="PaperPulse: GenAI-Powered Requirements-to-Test Automation for SDLC Productivity",
    description=(
        "Transforms software requirement documents into structured, validated, reviewable "
        "test cases using Google Gemini, PyMuPDF, Tesseract OCR, and Pydantic validation."
    ),
    version="2.0.0",
)

# Enable CORS for browser access and API consumers
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security headers middleware
@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response

# Mount static files and dashboard routes
static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir, exist_ok=True)

app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/", response_class=FileResponse, tags=["Frontend"])
@app.get("/dashboard", response_class=FileResponse, tags=["Frontend"])
@app.get("/app", response_class=FileResponse, tags=["Frontend"])
def serve_dashboard():
    """Serves the interactive PaperPulse SDLC Copilot web interface."""
    return FileResponse(os.path.join(static_dir, "index.html"))


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    """Serves the dashboard favicon."""
    fav_path = os.path.join(static_dir, "favicon.svg")
    if os.path.exists(fav_path):
        return FileResponse(fav_path, media_type="image/svg+xml")
    return Response(status_code=204)



# ==========================================
# Serialization Helpers
# ==========================================

def db_requirement_to_schema(rm: models.RequirementModel) -> schemas.SoftwareRequirement:
    """Converts a SQLAlchemy RequirementModel into a Pydantic SoftwareRequirement."""
    ac_list: List[schemas.AcceptanceCriterion] = []
    if rm.acceptance_criteria_json:
        try:
            raw_ac = json.loads(rm.acceptance_criteria_json)
            for ac in raw_ac:
                if isinstance(ac, dict):
                    ac_list.append(schemas.AcceptanceCriterion(**ac))
                elif isinstance(ac, str):
                    ac_list.append(schemas.AcceptanceCriterion(description=ac))
        except Exception:
            pass

    preconditions: List[str] = []
    if rm.preconditions_json:
        try:
            preconditions = json.loads(rm.preconditions_json)
        except Exception:
            pass

    ambiguities: List[str] = []
    if rm.ambiguities_json:
        try:
            ambiguities = json.loads(rm.ambiguities_json)
        except Exception:
            pass

    ai_assumptions: List[str] = []
    if rm.ai_assumptions_json:
        try:
            ai_assumptions = json.loads(rm.ai_assumptions_json)
        except Exception:
            pass

    cat = schemas.RequirementCategory.FUNCTIONAL
    for c in schemas.RequirementCategory:
        if c.value == rm.category:
            cat = c
            break

    rev_status = schemas.ReviewStatus.PENDING_REVIEW
    for s in schemas.ReviewStatus:
        if s.value == rm.review_status:
            rev_status = s
            break

    return schemas.SoftwareRequirement(
        id=rm.req_id,
        title=rm.title,
        description=rm.description,
        category=cat,
        source_document=rm.source_document or "Uploaded Document",
        page_number=rm.page_number,
        preconditions=preconditions,
        acceptance_criteria=ac_list,
        ambiguities=ambiguities,
        confidence_score=rm.confidence_score,
        review_status=rev_status,
        original_text=rm.original_text,
        ai_assumptions=ai_assumptions,
    )


def db_test_case_to_schema(tc: models.TestCaseModel) -> schemas.TestCase:
    """Converts a SQLAlchemy TestCaseModel into a Pydantic TestCase."""
    steps: List[str] = []
    if tc.steps_json:
        try:
            steps = json.loads(tc.steps_json)
        except Exception:
            steps = [tc.steps_json]

    preconditions: List[str] = []
    if tc.preconditions_json:
        try:
            preconditions = json.loads(tc.preconditions_json)
        except Exception:
            pass

    test_data: Optional[Dict[str, Any]] = None
    if tc.test_data_json:
        try:
            test_data = json.loads(tc.test_data_json)
        except Exception:
            pass

    ai_assumptions: List[str] = []
    if tc.ai_assumptions_json:
        try:
            ai_assumptions = json.loads(tc.ai_assumptions_json)
        except Exception:
            pass

    cat = schemas.TestCategory.POSITIVE
    for c in schemas.TestCategory:
        if c.value == tc.category:
            cat = c
            break

    pri = schemas.TestPriority.MEDIUM
    for p in schemas.TestPriority:
        if p.value == tc.priority:
            pri = p
            break

    rev_status = schemas.ReviewStatus.PENDING_REVIEW
    for s in schemas.ReviewStatus:
        if s.value == tc.review_status:
            rev_status = s
            break

    return schemas.TestCase(
        id=tc.tc_id,
        requirement_id=tc.req_code,
        title=tc.title,
        category=cat,
        objective=tc.objective,
        preconditions=preconditions,
        test_data=test_data,
        steps=steps if steps else ["Execute test steps as specified."],
        expected_result=tc.expected_result,
        priority=pri,
        test_type=tc.test_type,
        source_requirement_ref=tc.source_requirement_ref,
        requires_human_review=tc.requires_human_review,
        ai_assumptions=ai_assumptions,
        review_status=rev_status,
        user_notes=tc.user_notes,
    )


def _find_requirement(db: Session, identifier: str, user_id: int) -> Optional[models.RequirementModel]:
    """Finds requirement by either integer DB primary key or string REQ code."""
    ident_str = str(identifier).strip()
    if ident_str.isdigit():
        req = db.query(models.RequirementModel).filter(
            models.RequirementModel.id == int(ident_str),
            models.RequirementModel.owner_id == user_id,
        ).first()
        if req:
            return req
    return db.query(models.RequirementModel).filter(
        models.RequirementModel.req_id == ident_str.upper(),
        models.RequirementModel.owner_id == user_id,
    ).first()


def _find_test_case(db: Session, identifier: str, user_id: int) -> Optional[models.TestCaseModel]:
    """Finds test case by either integer DB primary key or string TC code."""
    ident_str = str(identifier).strip()
    if ident_str.isdigit():
        tc = db.query(models.TestCaseModel).filter(
            models.TestCaseModel.id == int(ident_str),
            models.TestCaseModel.owner_id == user_id,
        ).first()
        if tc:
            return tc
    return db.query(models.TestCaseModel).filter(
        models.TestCaseModel.tc_id == ident_str.upper(),
        models.TestCaseModel.owner_id == user_id,
    ).first()



# ==========================================
# Health & Root Endpoint
# ==========================================

@app.get("/", tags=["Health"])
def root():
    """Root health-check and metadata endpoint."""
    return {
        "project": "PaperPulse",
        "title": "PaperPulse: GenAI-Powered Requirements-to-Test Automation for SDLC Productivity",
        "tagline": "From software requirements to validated test cases — faster, smarter, and with human oversight.",
        "status": "online",
        "docs_url": "/docs",
        "version": "2.0.0",
    }


# ==========================================
# Authentication & User Endpoints (Preserved)
# ==========================================

@app.post(
    "/users",
    response_model=schemas.UserResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Users"],
)
def register_user(
    user_in: schemas.UserCreate,
    db: Session = Depends(get_db),
):
    """Register a new user account with duplicate email rejection and bcrypt hashing."""
    existing_user = db.query(models.User).filter(models.User.email == user_in.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email is already registered.",
        )

    hashed_pw = get_password_hash(user_in.password)
    user = models.User(email=user_in.email, hashed_password=hashed_pw)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.post(
    "/auth/login",
    response_model=schemas.Token,
    tags=["Auth"],
)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """Authenticate user credentials via OAuth2 and return a signed JWT access token."""
    user = authenticate_user(db, email=form_data.username, password=form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(data={"sub": user.email})
    return {"access_token": access_token, "token_type": "bearer"}


@app.get(
    "/users/me",
    response_model=schemas.UserResponse,
    tags=["Users"],
)
def get_me(current_user: models.User = Depends(get_current_user)):
    """Fetch profile of current authenticated user."""
    return current_user


# ==========================================
# SDLC Core Feature 1: Document Upload & Management
# ==========================================

@app.post(
    "/sdlc/documents/upload",
    response_model=schemas.DocumentUploadDetails,
    status_code=status.HTTP_201_CREATED,
    tags=["SDLC - Documents"],
)
async def upload_sdlc_document(
    file: UploadFile = File(...),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Ingests software requirement documents in PDF format.
    Uses PyMuPDF with Tesseract OCR fallback for scanned pages.
    Enforces file size, page limits, encryption checks, and sanitization.
    """
    file_bytes = await file.read()
    filename = file.filename or "requirement_specification.pdf"

    try:
        if filename.lower().endswith(".pdf") or file.content_type == "application/pdf":
            extraction = extract_detailed_from_pdf(file_bytes)
        else:
            # Plain text fallback
            text = file_bytes.decode("utf-8", errors="ignore")
            extraction = DetailedExtractionResult(
                text=text,
                pages_total=1,
                pages_ocr=0,
                character_count=len(text),
                ocr_used=False,
                pages=[],
            )

    except LimitExceededError as err:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(err))
    except PasswordProtectedPDFError as err:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(err))
    except CorruptedDocumentError as err:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(err))
    except ExtractionError as err:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(err))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Unexpected extraction failure: {str(exc)}")

    # Persist document metadata and extracted text
    material = models.Material(
        owner_id=current_user.id,
        filename=filename,
        status="uploaded",
        extracted_text=extraction.text,
        pages_total=extraction.pages_total,
        pages_ocr=extraction.pages_ocr,
        character_count=extraction.character_count,
    )
    db.add(material)
    db.commit()
    db.refresh(material)

    preview = (extraction.text[:300] + "...") if len(extraction.text) > 300 else extraction.text

    return schemas.DocumentUploadDetails(
        id=material.id,
        filename=material.filename,
        pages_total=material.pages_total,
        pages_ocr=material.pages_ocr,
        character_count=material.character_count,
        status=material.status,
        extracted_text_preview=preview,
        created_at=material.created_at.isoformat() if material.created_at else None,
    )


@app.get(
    "/sdlc/documents",
    response_model=List[schemas.DocumentUploadDetails],
    tags=["SDLC - Documents"],
)
def list_sdlc_documents(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all software requirement documents uploaded by the user."""
    docs = db.query(models.Material).filter(models.Material.owner_id == current_user.id).order_by(models.Material.id.desc()).all()
    results = []
    for d in docs:
        preview = (d.extracted_text[:200] + "...") if d.extracted_text and len(d.extracted_text) > 200 else (d.extracted_text or "")
        results.append(
            schemas.DocumentUploadDetails(
                id=d.id,
                filename=d.filename,
                pages_total=d.pages_total or 1,
                pages_ocr=d.pages_ocr or 0,
                character_count=d.character_count or len(d.extracted_text or ""),
                status=d.status,
                extracted_text_preview=preview,
                created_at=d.created_at.isoformat() if d.created_at else None,
            )
        )
    return results


@app.get(
    "/sdlc/documents/{id}",
    response_model=schemas.DocumentUploadDetails,
    tags=["SDLC - Documents"],
)
def get_sdlc_document(
    id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve details for a specific uploaded requirements document."""
    d = db.query(models.Material).filter(models.Material.id == id, models.Material.owner_id == current_user.id).first()
    if not d:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    preview = (d.extracted_text[:300] + "...") if d.extracted_text and len(d.extracted_text) > 300 else (d.extracted_text or "")
    return schemas.DocumentUploadDetails(
        id=d.id,
        filename=d.filename,
        pages_total=d.pages_total or 1,
        pages_ocr=d.pages_ocr or 0,
        character_count=d.character_count or len(d.extracted_text or ""),
        status=d.status,
        extracted_text_preview=preview,
        created_at=d.created_at.isoformat() if d.created_at else None,
    )


# ==========================================
# SDLC Core Feature 2: Requirements Extraction & Review
# ==========================================

@app.post(
    "/sdlc/documents/{id}/extract-requirements",
    response_model=List[schemas.SoftwareRequirement],
    tags=["SDLC - Requirements"],
)
async def extract_document_requirements(
    id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Extracts and categorizes requirements from document text using Google Gemini.
    Classifies requirements into functional, non-functional, security, performance,
    usability, and business rules. Flags ambiguities for human review.
    """
    doc = db.query(models.Material).filter(models.Material.id == id, models.Material.owner_id == current_user.id).first()
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    doc.status = "processing_requirements"
    db.commit()

    # Extract requirements via Gemini LLM engine with Pydantic validation
    req_list_schema = await extract_requirements(text=doc.extracted_text or "", filename=doc.filename)

    # Clear existing draft requirements for this document if re-extracting
    db.query(models.RequirementModel).filter(models.RequirementModel.material_id == doc.id).delete()

    saved_requirements: List[schemas.SoftwareRequirement] = []
    for req in req_list_schema.requirements:
        ac_json = json.dumps([ac.model_dump() for ac in req.acceptance_criteria])
        req_db = models.RequirementModel(
            req_id=req.id,
            material_id=doc.id,
            owner_id=current_user.id,
            title=req.title,
            description=req.description,
            category=req.category.value,
            source_document=doc.filename,
            page_number=req.page_number,
            preconditions_json=json.dumps(req.preconditions),
            acceptance_criteria_json=ac_json,
            ambiguities_json=json.dumps(req.ambiguities),
            confidence_score=req.confidence_score,
            review_status=req.review_status.value,
            original_text=req.original_text,
            ai_assumptions_json=json.dumps(req.ai_assumptions),
        )
        db.add(req_db)
        saved_requirements.append(req)

    doc.status = "requirements_extracted"
    db.commit()

    return saved_requirements


@app.get(
    "/sdlc/documents/{id}/requirements",
    response_model=List[schemas.SoftwareRequirement],
    tags=["SDLC - Requirements"],
)
def get_document_requirements(
    id: int,
    category: Optional[schemas.RequirementCategory] = Query(None, description="Filter by requirement category"),
    review_status: Optional[schemas.ReviewStatus] = Query(None, description="Filter by review status"),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve requirements extracted from a document with optional category and status filters."""
    query = db.query(models.RequirementModel).filter(
        models.RequirementModel.material_id == id,
        models.RequirementModel.owner_id == current_user.id,
    )
    if category:
        query = query.filter(models.RequirementModel.category == category.value)
    if review_status:
        query = query.filter(models.RequirementModel.review_status == review_status.value)

    reqs = query.order_by(models.RequirementModel.id.asc()).all()
    return [db_requirement_to_schema(r) for r in reqs]


@app.get(
    "/sdlc/requirements/{id}",
    response_model=schemas.SoftwareRequirement,
    tags=["SDLC - Requirements"],
)
def get_single_requirement(
    id: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve a single requirement by database ID or requirement code (e.g. REQ-001)."""
    rm = _find_requirement(db, id, current_user.id)
    if not rm:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requirement not found.")
    return db_requirement_to_schema(rm)


@app.put(
    "/sdlc/requirements/{id}",
    response_model=schemas.SoftwareRequirement,
    tags=["SDLC - Requirements"],
)
def update_requirement(
    id: str,
    payload: schemas.RequirementUpdateRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Human-in-the-Loop Review: Edit requirement description, category,
    acceptance criteria, ambiguities, AI assumptions, or update approval status
    ('Draft', 'Pending Review', 'Approved', 'Rejected', 'Needs Revision').
    Accepts database ID or requirement code (e.g. REQ-001).
    """
    rm = _find_requirement(db, id, current_user.id)
    if not rm:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requirement not found.")

    if payload.title is not None:
        rm.title = payload.title
    if payload.description is not None:
        rm.description = payload.description
    if payload.category is not None:
        rm.category = payload.category.value
    if payload.preconditions is not None:
        rm.preconditions_json = json.dumps(payload.preconditions)
    if payload.acceptance_criteria is not None:
        rm.acceptance_criteria_json = json.dumps([ac.model_dump() for ac in payload.acceptance_criteria])
    if payload.ambiguities is not None:
        rm.ambiguities_json = json.dumps(payload.ambiguities)
    if payload.review_status is not None:
        rm.review_status = payload.review_status.value
    if payload.ai_assumptions is not None:
        rm.ai_assumptions_json = json.dumps(payload.ai_assumptions)

    rm.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(rm)
    return db_requirement_to_schema(rm)


# ==========================================
# SDLC Core Feature 3 & 4: Test Case Generation & Validation
# ==========================================

@app.post(
    "/sdlc/requirements/{id}/generate-tests",
    response_model=Dict[str, Any],
    tags=["SDLC - Test Cases"],
)
async def generate_tests_for_single_requirement(
    id: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Generates typed test cases (Positive, Negative, Boundary, Edge Case, Integration)
    for a specific requirement using Google Gemini, strictly validated with Pydantic.
    """
    rm = _find_requirement(db, id, current_user.id)
    if not rm:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requirement not found.")

    req_schema = db_requirement_to_schema(rm)
    doc = db.query(models.Material).filter(models.Material.id == rm.material_id).first()
    doc_context = doc.extracted_text if doc else None

    # Count existing test cases for document to determine sequential TC numbering
    existing_count = db.query(models.TestCaseModel).filter(models.TestCaseModel.material_id == rm.material_id).count()
    start_idx = existing_count + 1

    test_cases, val_result = await generate_test_cases_for_requirement(
        requirement=req_schema,
        document_context=doc_context,
        starting_index=start_idx,
    )

    # Persist generated test cases with original AI payload preserved for human comparison
    saved_cases = []
    for tc in test_cases:
        tc_db = models.TestCaseModel(
            tc_id=tc.id,
            requirement_id=rm.id,
            req_code=rm.req_id,
            material_id=rm.material_id,
            owner_id=current_user.id,
            title=tc.title,
            category=tc.category.value,
            objective=tc.objective,
            preconditions_json=json.dumps(tc.preconditions),
            test_data_json=json.dumps(tc.test_data) if tc.test_data else None,
            steps_json=json.dumps(tc.steps),
            expected_result=tc.expected_result,
            priority=tc.priority.value,
            test_type=tc.test_type,
            source_requirement_ref=tc.source_requirement_ref or f"{rm.req_id}: {rm.title}",
            requires_human_review=tc.requires_human_review,
            ai_assumptions_json=json.dumps(tc.ai_assumptions),
            review_status=tc.review_status.value,
            original_ai_payload=tc.model_dump_json(),
        )
        db.add(tc_db)
        saved_cases.append(tc)

    db.commit()

    return {
        "requirement_id": rm.req_id,
        "test_cases": [tc.model_dump() for tc in saved_cases],
        "validation": val_result.model_dump(),
    }


@app.post(
    "/sdlc/documents/{id}/generate-all-tests",
    response_model=Dict[str, Any],
    tags=["SDLC - Test Cases"],
)
async def generate_all_tests_for_document(
    id: int,
    only_approved: bool = Query(False, description="Generate tests only for Approved requirements"),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Batch generates a complete test suite for all requirements in a document.
    Prioritizes Approved requirements or all active requirements if none are approved yet.
    """
    doc = db.query(models.Material).filter(models.Material.id == id, models.Material.owner_id == current_user.id).first()
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    query = db.query(models.RequirementModel).filter(
        models.RequirementModel.material_id == doc.id,
        models.RequirementModel.owner_id == current_user.id,
    )
    if only_approved:
        query = query.filter(models.RequirementModel.review_status == schemas.ReviewStatus.APPROVED.value)
    else:
        query = query.filter(models.RequirementModel.review_status != schemas.ReviewStatus.REJECTED.value)

    req_models = query.order_by(models.RequirementModel.id.asc()).all()
    if not req_models:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No eligible requirements found. Extract requirements first or check review statuses.",
        )

    req_schemas = [db_requirement_to_schema(rm) for rm in req_models]

    suite, val_result = await generate_all_test_cases(
        requirements=req_schemas,
        document_context=doc.extracted_text,
    )

    # Clear old test cases for this document if regenerated
    db.query(models.TestCaseModel).filter(models.TestCaseModel.material_id == doc.id).delete()

    # Create mapping from req_id (e.g. REQ-001) to requirement primary key
    req_pk_map = {rm.req_id: rm.id for rm in req_models}

    for tc in suite.test_cases:
        tc_db = models.TestCaseModel(
            tc_id=tc.id,
            requirement_id=req_pk_map.get(tc.requirement_id),
            req_code=tc.requirement_id,
            material_id=doc.id,
            owner_id=current_user.id,
            title=tc.title,
            category=tc.category.value,
            objective=tc.objective,
            preconditions_json=json.dumps(tc.preconditions),
            test_data_json=json.dumps(tc.test_data) if tc.test_data else None,
            steps_json=json.dumps(tc.steps),
            expected_result=tc.expected_result,
            priority=tc.priority.value,
            test_type=tc.test_type,
            source_requirement_ref=tc.source_requirement_ref,
            requires_human_review=tc.requires_human_review,
            ai_assumptions_json=json.dumps(tc.ai_assumptions),
            review_status=tc.review_status.value,
            original_ai_payload=tc.model_dump_json(),
        )
        db.add(tc_db)

    doc.status = "tests_generated"
    db.commit()

    return {
        "test_suite": suite.model_dump(),
        "validation": val_result.model_dump(),
    }


@app.get(
    "/sdlc/documents/{id}/test-cases",
    response_model=List[schemas.TestCase],
    tags=["SDLC - Test Cases"],
)
def get_document_test_cases(
    id: int,
    requirement_code: Optional[str] = Query(None, description="Filter by requirement code (e.g. REQ-001)"),
    category: Optional[schemas.TestCategory] = Query(None, description="Filter by test category"),
    priority: Optional[schemas.TestPriority] = Query(None, description="Filter by priority"),
    review_status: Optional[schemas.ReviewStatus] = Query(None, description="Filter by review status"),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve test cases linked to a document with category, priority, and review status filters."""
    query = db.query(models.TestCaseModel).filter(
        models.TestCaseModel.material_id == id,
        models.TestCaseModel.owner_id == current_user.id,
    )
    if requirement_code:
        query = query.filter(models.TestCaseModel.req_code == requirement_code)
    if category:
        query = query.filter(models.TestCaseModel.category == category.value)
    if priority:
        query = query.filter(models.TestCaseModel.priority == priority.value)
    if review_status:
        query = query.filter(models.TestCaseModel.review_status == review_status.value)

    cases = query.order_by(models.TestCaseModel.id.asc()).all()
    return [db_test_case_to_schema(c) for c in cases]


@app.get(
    "/sdlc/test-cases/{id}",
    response_model=schemas.TestCase,
    tags=["SDLC - Test Cases"],
)
def get_single_test_case(
    id: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve a single test case by database ID or TC code (e.g. TC-001)."""
    tc = _find_test_case(db, id, current_user.id)
    if not tc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test case not found.")
    return db_test_case_to_schema(tc)


@app.put(
    "/sdlc/test-cases/{id}",
    response_model=schemas.TestCase,
    tags=["SDLC - Test Cases"],
)
def update_test_case(
    id: str,
    payload: schemas.TestCaseUpdateRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Human-in-the-Loop Review: Edit test case title, steps, expected result,
    priority, category, user comments, or approve/reject the test case.
    Accepts database ID or TC code (e.g. TC-001).
    """
    tc = _find_test_case(db, id, current_user.id)
    if not tc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test case not found.")

    if payload.title is not None:
        tc.title = payload.title
    if payload.category is not None:
        tc.category = payload.category.value
    if payload.objective is not None:
        tc.objective = payload.objective
    if payload.preconditions is not None:
        tc.preconditions_json = json.dumps(payload.preconditions)
    if payload.test_data is not None:
        tc.test_data_json = json.dumps(payload.test_data)
    if payload.steps is not None:
        tc.steps_json = json.dumps(payload.steps)
    if payload.expected_result is not None:
        tc.expected_result = payload.expected_result
    if payload.priority is not None:
        tc.priority = payload.priority.value
    if payload.test_type is not None:
        tc.test_type = payload.test_type
    if payload.requires_human_review is not None:
        tc.requires_human_review = payload.requires_human_review
    if payload.review_status is not None:
        tc.review_status = payload.review_status.value
    if payload.user_notes is not None:
        tc.user_notes = payload.user_notes

    tc.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(tc)
    return db_test_case_to_schema(tc)


@app.post(
    "/sdlc/test-cases/{id}/regenerate",
    response_model=schemas.TestCase,
    tags=["SDLC - Test Cases"],
)
async def regenerate_test_case(
    id: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Regenerates a single test case using Gemini while preserving linked requirement context."""
    tc = _find_test_case(db, id, current_user.id)
    if not tc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test case not found.")

    rm = db.query(models.RequirementModel).filter(models.RequirementModel.id == tc.requirement_id).first()
    if not rm:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parent requirement not found.")

    req_schema = db_requirement_to_schema(rm)
    cases, _ = await generate_test_cases_for_requirement(requirement=req_schema, starting_index=1)

    matching = next((c for c in cases if c.category.value == tc.category), cases[0])
    tc.title = matching.title
    tc.objective = matching.objective
    tc.steps_json = json.dumps(matching.steps)
    tc.expected_result = matching.expected_result
    tc.ai_assumptions_json = json.dumps(matching.ai_assumptions)
    tc.review_status = schemas.ReviewStatus.PENDING_REVIEW.value
    tc.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(tc)
    return db_test_case_to_schema(tc)


# ==========================================
# SDLC Core Feature 5 & 6: Evaluation Dashboard & Coverage
# ==========================================

@app.get(
    "/sdlc/documents/{id}/coverage",
    response_model=schemas.CoverageMetric,
    tags=["SDLC - Evaluation & Coverage"],
)
def get_document_coverage(
    id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Computes rigorous requirement coverage and quality metrics for an SDLC document.
    Requirement Coverage (%) = (Approved Reqs linked to >= 1 Approved Test Case / Total Approved Reqs) * 100.
    Returns None (N/A) if zero approved requirements exist.
    """
    doc = db.query(models.Material).filter(
        models.Material.id == id,
        models.Material.owner_id == current_user.id,
    ).first()
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    return calculate_coverage_metrics(db=db, material_id=doc.id, user_id=current_user.id)


@app.get(
    "/sdlc/documents/{id}/traceability-matrix",
    response_model=List[Dict[str, Any]],
    tags=["SDLC - Evaluation & Coverage"],
)
def get_document_traceability_matrix(
    id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Generates a bidirectional requirements-to-test traceability matrix.
    Maps each requirement to its linked test scenarios and coverage status.
    """
    doc = db.query(models.Material).filter(
        models.Material.id == id,
        models.Material.owner_id == current_user.id,
    ).first()
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    return generate_traceability_matrix(db=db, material_id=doc.id, user_id=current_user.id)


@app.post(
    "/sdlc/evaluation/benchmark",
    tags=["SDLC - Evaluation & Coverage"],
)
def run_benchmark_evaluation(
    payload: Dict[str, List[str]],
    current_user: models.User = Depends(get_current_user),
):
    """
    Evaluates extraction precision, recall, and F1 score against a provided
    ground-truth list of expected requirements.
    """
    ground_truth = payload.get("ground_truth", [])
    extracted = payload.get("extracted", [])
    return evaluate_ground_truth_benchmarks(ground_truth_reqs=ground_truth, extracted_reqs=extracted)


# ==========================================
# SDLC Core Feature 7: Export Engine (CSV & Excel)
# ==========================================

@app.get(
    "/sdlc/documents/{id}/export/csv",
    tags=["SDLC - Export"],
)
def export_approved_tests_csv(
    id: int,
    only_approved: bool = Query(True, description="Filter for Approved test cases only"),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Exports approved test cases into a standardized, readable CSV file.
    Includes Test Case ID, Requirement ID, Description, Title, Steps, and Assertions.
    """
    doc = db.query(models.Material).filter(
        models.Material.id == id,
        models.Material.owner_id == current_user.id,
    ).first()
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    query = db.query(models.TestCaseModel).filter(
        models.TestCaseModel.material_id == id,
        models.TestCaseModel.owner_id == current_user.id,
    )
    if only_approved:
        query = query.filter(models.TestCaseModel.review_status == schemas.ReviewStatus.APPROVED.value)

    test_cases_db = query.order_by(models.TestCaseModel.id.asc()).all()
    if not test_cases_db:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No test cases match the export criteria (ensure test cases are Approved or set only_approved=false).",
        )

    export_records = []
    for tc in test_cases_db:
        steps = json.loads(tc.steps_json) if tc.steps_json else []
        preconds = json.loads(tc.preconditions_json) if tc.preconditions_json else []
        test_data = json.loads(tc.test_data_json) if tc.test_data_json else None

        req = db.query(models.RequirementModel).filter(models.RequirementModel.id == tc.requirement_id).first()
        req_desc = req.description if req else ""

        export_records.append({
            "id": tc.tc_id,
            "requirement_id": tc.req_code,
            "requirement_description": req_desc,
            "title": tc.title,
            "category": tc.category,
            "priority": tc.priority,
            "preconditions": preconds,
            "test_data": test_data,
            "steps": steps,
            "expected_result": tc.expected_result,
            "review_status": tc.review_status,
            "source_document": doc.filename,
        })

    csv_data = export_test_cases_to_csv(export_records)
    base_name = doc.filename.rsplit(".", 1)[0]
    filename = f"{base_name}_approved_test_suite.csv"

    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get(
    "/sdlc/documents/{id}/export/excel",
    tags=["SDLC - Export"],
)
def export_approved_tests_excel(
    id: int,
    only_approved: bool = Query(True, description="Filter for Approved test cases only"),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Exports a styled Excel (.xlsx) workbook containing:
    1. Approved Test Cases sheet (auto-wrapped, styled headers)
    2. Bidirectional Traceability Matrix sheet
    3. Executive Quality & Coverage Metrics sheet
    """
    doc = db.query(models.Material).filter(
        models.Material.id == id,
        models.Material.owner_id == current_user.id,
    ).first()
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    query = db.query(models.TestCaseModel).filter(
        models.TestCaseModel.material_id == id,
        models.TestCaseModel.owner_id == current_user.id,
    )
    if only_approved:
        query = query.filter(models.TestCaseModel.review_status == schemas.ReviewStatus.APPROVED.value)

    test_cases_db = query.order_by(models.TestCaseModel.id.asc()).all()
    if not test_cases_db:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No test cases match the export criteria (ensure test cases are Approved or set only_approved=false).",
        )

    export_records = []
    for tc in test_cases_db:
        steps = json.loads(tc.steps_json) if tc.steps_json else []
        preconds = json.loads(tc.preconditions_json) if tc.preconditions_json else []
        test_data = json.loads(tc.test_data_json) if tc.test_data_json else None

        req = db.query(models.RequirementModel).filter(models.RequirementModel.id == tc.requirement_id).first()
        req_desc = req.description if req else ""

        export_records.append({
            "id": tc.tc_id,
            "requirement_id": tc.req_code,
            "requirement_description": req_desc,
            "title": tc.title,
            "category": tc.category,
            "priority": tc.priority,
            "preconditions": preconds,
            "test_data": test_data,
            "steps": steps,
            "expected_result": tc.expected_result,
            "review_status": tc.review_status,
            "source_document": doc.filename,
        })

    trace_data = generate_traceability_matrix(db=db, material_id=doc.id, user_id=current_user.id)
    metrics_obj = calculate_coverage_metrics(db=db, material_id=doc.id, user_id=current_user.id)
    metrics_dict = metrics_obj.model_dump()

    excel_bytes = export_test_cases_to_excel(
        test_cases=export_records,
        traceability_data=trace_data,
        metrics_data=metrics_dict,
    )

    base_name = doc.filename.rsplit(".", 1)[0]
    filename = f"{base_name}_traceability_and_test_suite.xlsx"

    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ==========================================
# SDLC Core Feature 8: Goal-Driven Autonomous Agent
# ==========================================

@app.post(
    "/sdlc/documents/{id}/agent-prepare",
    response_model=schemas.AgentGoalResponse,
    tags=["SDLC - Autonomous Agent"],
)
async def run_agent_test_preparation(
    id: int,
    request: schemas.AgentGoalRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Executes a bounded, goal-driven testing preparation agent.
    Plans and orchestrates requirements extraction, gap analysis,
    test case generation, and validation, presenting an audit trail for human sign-off.
    """
    agent = GoalDrivenTestingAgent(
        db=db,
        material_id=id,
        user_id=current_user.id,
        max_iterations=request.max_iterations or 5,
    )
    return await agent.execute_goal(goal=request.goal)


# ==========================================
# Legacy Document Processing Endpoints (Preserved)
# ==========================================

@app.post(
    "/materials/upload",
    response_model=schemas.MaterialUploadResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Materials"],
)
async def upload_material(
    file: UploadFile = File(...),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Legacy upload endpoint maintained for backward compatibility."""
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty.")

    filename = file.filename or "uploaded_document.pdf"
    try:
        if filename.lower().endswith(".pdf") or file.content_type == "application/pdf":
            extracted_text = extract_text_from_pdf(file_bytes)
        else:
            extracted_text = file_bytes.decode("utf-8", errors="ignore")
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Failed to process document: {str(exc)}")

    material = models.Material(
        owner_id=current_user.id,
        filename=filename,
        status="uploaded",
        extracted_text=extracted_text,
    )
    db.add(material)
    db.commit()
    db.refresh(material)

    preview = (extracted_text[:200] + "...") if extracted_text and len(extracted_text) > 200 else extracted_text
    return schemas.MaterialUploadResponse(
        id=material.id,
        filename=material.filename,
        status=material.status,
        extracted_text_preview=preview,
    )


@app.get(
    "/materials",
    response_model=List[schemas.MaterialResponse],
    tags=["Materials"],
)
def list_materials(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Legacy materials list endpoint."""
    return db.query(models.Material).filter(models.Material.owner_id == current_user.id).all()


@app.get(
    "/materials/{id}",
    response_model=schemas.MaterialResponse,
    tags=["Materials"],
)
def get_material(
    id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Legacy material retrieval endpoint."""
    material = db.query(models.Material).filter(models.Material.id == id, models.Material.owner_id == current_user.id).first()
    if not material:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Material not found.")
    return material


@app.post(
    "/materials/{id}/summary",
    response_model=schemas.SummaryResponse,
    tags=["Materials"],
)
async def generate_material_summary(
    id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Legacy summary endpoint."""
    material = db.query(models.Material).filter(models.Material.id == id, models.Material.owner_id == current_user.id).first()
    if not material:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Material not found.")

    material.status = "processing"
    db.commit()

    summary_text = await generate_summary(text=material.extracted_text or "", filename=material.filename)
    material.summary = summary_text
    material.status = "completed"
    db.commit()
    db.refresh(material)

    return schemas.SummaryResponse(
        material_id=material.id,
        summary=material.summary,
        status=material.status,
    )


@app.post(
    "/materials/{id}/quiz",
    response_model=schemas.QuizResponse,
    tags=["Materials"],
)
async def generate_material_quiz(
    id: int,
    request: Optional[schemas.QuizGenerateRequest] = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Legacy quiz endpoint."""
    material = db.query(models.Material).filter(models.Material.id == id, models.Material.owner_id == current_user.id).first()
    if not material:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Material not found.")

    material.status = "processing"
    db.commit()

    num_q = request.num_questions if request and request.num_questions else 4
    quiz_result = await generate_quiz(text=material.extracted_text or "", filename=material.filename, num_questions=num_q)

    material.quiz_json = quiz_result.model_dump_json()
    material.status = "completed"
    db.commit()
    db.refresh(material)

    return schemas.QuizResponse(
        material_id=material.id,
        quiz=quiz_result,
        status=material.status,
    )
