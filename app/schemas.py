from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, EmailStr, ConfigDict, Field, field_validator
import re


# ==========================================
# Legacy User & Auth Schemas (Preserved)
# ==========================================

class UserBase(BaseModel):
    email: EmailStr


class UserCreate(UserBase):
    password: str


class UserResponse(UserBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    email: Optional[str] = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


# ==========================================
# Legacy Quiz & Material Schemas (Preserved)
# ==========================================

class QuizQuestion(BaseModel):
    question: str
    options: List[str]
    correct_answer: str
    explanation: Optional[str] = None


class QuizSchema(BaseModel):
    title: Optional[str] = "Generated Quiz"
    questions: List[QuizQuestion]


class QuizGenerateRequest(BaseModel):
    num_questions: Optional[int] = 5


class MaterialBase(BaseModel):
    filename: str


class MaterialCreate(MaterialBase):
    extracted_text: Optional[str] = None


class MaterialResponse(MaterialBase):
    id: int
    owner_id: int
    status: str
    extracted_text: Optional[str] = None
    summary: Optional[str] = None
    quiz_json: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class MaterialUploadResponse(BaseModel):
    id: int
    filename: str
    status: str
    extracted_text_preview: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class SummaryResponse(BaseModel):
    material_id: int
    summary: str
    status: str


class QuizResponse(BaseModel):
    material_id: int
    quiz: QuizSchema
    status: str


# ==========================================
# SDLC Enumerations
# ==========================================

class RequirementCategory(str, Enum):
    FUNCTIONAL = "functional"
    NON_FUNCTIONAL = "non_functional"
    SECURITY = "security"
    PERFORMANCE = "performance"
    USABILITY = "usability"
    BUSINESS_RULE = "business_rule"


class TestCategory(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    BOUNDARY = "boundary"
    EDGE_CASE = "edge_case"
    INTEGRATION = "integration"


class TestPriority(str, Enum):
    CRITICAL = "Critical"
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class ReviewStatus(str, Enum):
    DRAFT = "Draft"
    PENDING_REVIEW = "Pending Review"
    APPROVED = "Approved"
    REJECTED = "Rejected"
    NEEDS_REVISION = "Needs Revision"


# ==========================================
# SDLC Core Schemas: Requirements
# ==========================================

class AcceptanceCriterion(BaseModel):
    id: Optional[str] = Field(default=None, description="e.g. AC-01")
    description: str = Field(..., min_length=3, description="Verification condition or expected acceptance criterion")
    verified_by: List[str] = Field(default_factory=list, description="Linked test case IDs verifying this criterion")


class SoftwareRequirement(BaseModel):
    id: str = Field(..., description="Unique Requirement identifier, e.g., REQ-001")
    title: str = Field(..., min_length=3, description="Short, concise requirement summary")
    description: str = Field(..., min_length=10, description="Full detailed specification of the requirement")
    category: RequirementCategory = Field(default=RequirementCategory.FUNCTIONAL, description="Classified category")
    source_document: Optional[str] = Field(default="Uploaded Document", description="Originating document filename")
    page_number: Optional[int] = Field(default=None, description="Document page location where requirement was identified")
    preconditions: List[str] = Field(default_factory=list, description="Stated preconditions or dependencies")
    acceptance_criteria: List[AcceptanceCriterion] = Field(default_factory=list, description="Specific acceptance criteria")
    ambiguities: List[str] = Field(default_factory=list, description="Unclear, incomplete, or ambiguous items requiring human review")
    confidence_score: float = Field(default=0.9, ge=0.0, le=1.0, description="Extraction confidence score (0.0 to 1.0)")
    review_status: ReviewStatus = Field(default=ReviewStatus.PENDING_REVIEW, description="Human review status")
    original_text: Optional[str] = Field(default=None, description="Exact raw text snippet from document")
    ai_assumptions: List[str] = Field(default_factory=list, description="Inferences or assumptions made by AI during extraction")

    @field_validator("id")
    @classmethod
    def validate_req_id(cls, v: str) -> str:
        v = v.strip().upper()
        digits = re.findall(r"\d+", v)
        if digits:
            return f"REQ-{int(digits[0]):03d}"
        raise ValueError(f"Requirement ID '{v}' must contain digits, conforming to 'REQ-XXX' format (e.g. REQ-001)")

    model_config = ConfigDict(from_attributes=True)


class RequirementListSchema(BaseModel):
    document_name: Optional[str] = "Document"
    total_found: int = 0
    requirements: List[SoftwareRequirement] = Field(default_factory=list)


class RequirementUpdateRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[RequirementCategory] = None
    preconditions: Optional[List[str]] = None
    acceptance_criteria: Optional[List[AcceptanceCriterion]] = None
    ambiguities: Optional[List[str]] = None
    review_status: Optional[ReviewStatus] = None
    ai_assumptions: Optional[List[str]] = None


# ==========================================
# SDLC Core Schemas: Test Cases
# ==========================================

class TestCase(BaseModel):
    id: str = Field(..., description="Unique Test Case identifier, e.g. TC-001")
    requirement_id: str = Field(..., description="Linked Requirement identifier, e.g. REQ-001")
    title: str = Field(..., min_length=5, description="Clear, descriptive test title")
    category: TestCategory = Field(..., description="positive, negative, boundary, edge_case, or integration")
    objective: str = Field(..., min_length=10, description="Test goal and scenario being verified")
    preconditions: List[str] = Field(default_factory=list, description="Required system states before test execution")
    test_data: Optional[Dict[str, Any]] = Field(default=None, description="Structured input parameters, payloads, or values")
    steps: List[str] = Field(..., min_length=1, description="Sequential, ordered execution steps")
    expected_result: str = Field(..., min_length=5, description="Expected software behavior and assertions")
    priority: TestPriority = Field(default=TestPriority.MEDIUM, description="Critical, High, Medium, or Low")
    test_type: str = Field(default="Automated/Manual", description="e.g. API, UI, Integration, Unit")
    source_requirement_ref: Optional[str] = Field(default=None, description="Original source requirement description or link")
    requires_human_review: bool = Field(default=True, description="Flag indicating human oversight is recommended")
    ai_assumptions: List[str] = Field(default_factory=list, description="Explicit AI assumptions underlying this test")
    review_status: ReviewStatus = Field(default=ReviewStatus.PENDING_REVIEW, description="Human sign-off status")
    user_notes: Optional[str] = Field(default=None, description="Human reviewer comments or edits")

    @field_validator("id")
    @classmethod
    def validate_tc_id(cls, v: str) -> str:
        v = v.strip().upper()
        digits = re.findall(r"\d+", v)
        if digits:
            return f"TC-{int(digits[0]):03d}"
        raise ValueError(f"Test Case ID '{v}' must contain digits, conforming to 'TC-XXX' format (e.g. TC-001)")

    @field_validator("steps")
    @classmethod
    def validate_steps_not_empty(cls, v: List[str]) -> List[str]:
        cleaned = [s.strip() for s in v if s and s.strip()]
        if not cleaned:
            raise ValueError("Test steps must contain at least one non-empty execution step.")
        return cleaned

    @field_validator("expected_result")
    @classmethod
    def validate_expected_result(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Expected result must not be blank.")
        return v.strip()

    model_config = ConfigDict(from_attributes=True)


class TestSuite(BaseModel):
    title: str = "PaperPulse Test Suite"
    document_name: Optional[str] = "Requirements Document"
    total_test_cases: int = 0
    test_cases: List[TestCase] = Field(default_factory=list)


class TestCaseUpdateRequest(BaseModel):
    title: Optional[str] = None
    category: Optional[TestCategory] = None
    objective: Optional[str] = None
    preconditions: Optional[List[str]] = None
    test_data: Optional[Dict[str, Any]] = None
    steps: Optional[List[str]] = None
    expected_result: Optional[str] = None
    priority: Optional[TestPriority] = None
    test_type: Optional[str] = None
    requires_human_review: Optional[bool] = None
    review_status: Optional[ReviewStatus] = None
    user_notes: Optional[str] = None


# ==========================================
# Quality, Validation & Evaluation Schemas
# ==========================================

class ValidationResult(BaseModel):
    is_valid: bool = True
    total_generated: int = 0
    valid_count: int = 0
    invalid_count: int = 0
    errors: List[str] = Field(default_factory=list)
    retry_count: int = 0
    validated_at: Optional[str] = None


class CoverageMetric(BaseModel):
    total_requirements: int = 0
    approved_requirements: int = 0
    total_test_cases: int = 0
    approved_test_cases: int = 0
    requirements_with_approved_tests: int = 0
    requirements_uncovered: int = 0
    coverage_percentage: Optional[float] = None
    category_distribution: Dict[str, int] = Field(default_factory=dict)
    priority_distribution: Dict[str, int] = Field(default_factory=dict)
    schema_validation_rate: float = 100.0
    human_acceptance_rate: Optional[float] = None
    processing_time_seconds: Optional[float] = None


class EvaluationReport(BaseModel):
    document_id: int
    document_name: str
    coverage: CoverageMetric
    traceability_matrix: List[Dict[str, Any]] = Field(default_factory=list)
    generated_at: str


# ==========================================
# Document Ingestion Enhanced Schemas
# ==========================================

class DocumentUploadDetails(BaseModel):
    id: int
    filename: str
    pages_total: int
    pages_ocr: int
    character_count: int
    status: str
    extracted_text_preview: str
    created_at: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# ==========================================
# Goal-Driven Agent Schemas
# ==========================================

class AgentGoalRequest(BaseModel):
    goal: str = Field(..., min_length=5, description="High-level SDLC testing goal")
    max_iterations: Optional[int] = Field(default=5, ge=1, le=10)


class AgentActionStep(BaseModel):
    step_number: int
    action: str
    observation: str
    status: str = "completed"


class AgentGoalResponse(BaseModel):
    goal: str
    plan: List[str]
    steps_executed: List[AgentActionStep]
    summary: str
    success: bool
    requires_human_approval: bool = True
