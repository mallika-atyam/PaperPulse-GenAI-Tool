from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    ForeignKey,
    Integer,
    String,
    Text,
    Boolean,
    Float,
    DateTime,
)
from sqlalchemy.orm import relationship
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)

    materials = relationship("Material", back_populates="owner", cascade="all, delete-orphan")


class Material(Base):
    __tablename__ = "materials"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    filename = Column(String, nullable=False)
    status = Column(String, default="uploaded", nullable=False)  # e.g., "uploaded", "processing", "completed", "failed"
    extracted_text = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    quiz_json = Column(Text, nullable=True)
    
    # Enhanced extraction metadata
    pages_total = Column(Integer, default=1, nullable=False)
    pages_ocr = Column(Integer, default=0, nullable=False)
    character_count = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    owner = relationship("User", back_populates="materials")
    requirements = relationship("RequirementModel", back_populates="material", cascade="all, delete-orphan")
    test_cases = relationship("TestCaseModel", back_populates="material", cascade="all, delete-orphan")
    agent_logs = relationship("AgentExecutionLog", back_populates="material", cascade="all, delete-orphan")


class RequirementModel(Base):
    __tablename__ = "requirements"

    id = Column(Integer, primary_key=True, index=True)
    req_id = Column(String, index=True, nullable=False)  # e.g. REQ-001
    material_id = Column(Integer, ForeignKey("materials.id"), nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    category = Column(String, default="functional", nullable=False)
    source_document = Column(String, nullable=True)
    page_number = Column(Integer, nullable=True)
    preconditions_json = Column(Text, nullable=True)  # JSON array
    acceptance_criteria_json = Column(Text, nullable=True)  # JSON array of objects
    ambiguities_json = Column(Text, nullable=True)  # JSON array
    confidence_score = Column(Float, default=0.9, nullable=False)
    review_status = Column(String, default="Pending Review", nullable=False)  # Draft, Pending Review, Approved, Rejected, Needs Revision
    original_text = Column(Text, nullable=True)
    ai_assumptions_json = Column(Text, nullable=True)  # JSON array
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    material = relationship("Material", back_populates="requirements")
    test_cases = relationship("TestCaseModel", back_populates="requirement", cascade="all, delete-orphan")


class TestCaseModel(Base):
    __tablename__ = "test_cases"

    id = Column(Integer, primary_key=True, index=True)
    tc_id = Column(String, index=True, nullable=False)  # e.g. TC-001
    requirement_id = Column(Integer, ForeignKey("requirements.id"), nullable=True)
    req_code = Column(String, index=True, nullable=False)  # e.g. REQ-001
    material_id = Column(Integer, ForeignKey("materials.id"), nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String, nullable=False)
    category = Column(String, nullable=False)  # positive, negative, boundary, edge_case, integration
    objective = Column(Text, nullable=False)
    preconditions_json = Column(Text, nullable=True)
    test_data_json = Column(Text, nullable=True)
    steps_json = Column(Text, nullable=False)  # JSON array of step strings
    expected_result = Column(Text, nullable=False)
    priority = Column(String, default="Medium", nullable=False)  # Critical, High, Medium, Low
    test_type = Column(String, default="Automated/Manual", nullable=False)
    source_requirement_ref = Column(Text, nullable=True)
    requires_human_review = Column(Boolean, default=True, nullable=False)
    ai_assumptions_json = Column(Text, nullable=True)
    review_status = Column(String, default="Pending Review", nullable=False)  # Draft, Pending Review, Approved, Rejected, Needs Revision
    user_notes = Column(Text, nullable=True)
    original_ai_payload = Column(Text, nullable=True)  # For side-by-side human review comparison
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    requirement = relationship("RequirementModel", back_populates="test_cases")
    material = relationship("Material", back_populates="test_cases")


class AgentExecutionLog(Base):
    __tablename__ = "agent_execution_logs"

    id = Column(Integer, primary_key=True, index=True)
    material_id = Column(Integer, ForeignKey("materials.id"), nullable=False)
    goal = Column(Text, nullable=False)
    plan_json = Column(Text, nullable=False)
    execution_steps_json = Column(Text, nullable=False)
    summary = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    material = relationship("Material", back_populates="agent_logs")
