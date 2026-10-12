import json
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app import models, schemas

logger = logging.getLogger(__name__)


def calculate_coverage_metrics(
    db: Session,
    material_id: int,
    user_id: int,
) -> schemas.CoverageMetric:
    """
    Computes rigorous requirement-to-test coverage metrics for a given document.
    
    Formula:
    Requirement Coverage (%) = 
        (Approved Requirements linked to >= 1 Approved Test Case / Total Approved Requirements) * 100
        
    If total approved requirements == 0, returns None (displayed as 'N/A' in UI).
    """
    # Fetch requirements
    reqs = db.query(models.RequirementModel).filter(
        models.RequirementModel.material_id == material_id,
        models.RequirementModel.owner_id == user_id,
    ).all()

    # Fetch test cases
    tcs = db.query(models.TestCaseModel).filter(
        models.TestCaseModel.material_id == material_id,
        models.TestCaseModel.owner_id == user_id,
    ).all()

    total_requirements = len(reqs)
    approved_reqs = [r for r in reqs if r.review_status == schemas.ReviewStatus.APPROVED.value]
    approved_req_ids = {r.id for r in approved_reqs}
    approved_req_codes = {r.req_id for r in approved_reqs}

    total_test_cases = len(tcs)
    approved_tcs = [tc for tc in tcs if tc.review_status == schemas.ReviewStatus.APPROVED.value]

    # Map approved test cases to their parent requirements
    approved_reqs_with_tests = set()
    for tc in approved_tcs:
        if tc.requirement_id and tc.requirement_id in approved_req_ids:
            approved_reqs_with_tests.add(tc.requirement_id)
        elif tc.req_code in approved_req_codes:
            for r in approved_reqs:
                if r.req_id == tc.req_code:
                    approved_reqs_with_tests.add(r.id)

    num_approved_with_tests = len(approved_reqs_with_tests)
    num_approved_reqs = len(approved_reqs)
    uncovered_count = max(0, num_approved_reqs - num_approved_with_tests)

    # Coverage percentage
    if num_approved_reqs > 0:
        coverage_pct = round((num_approved_with_tests / num_approved_reqs) * 100.0, 2)
    else:
        coverage_pct = None  # Represents N/A

    # Category distribution
    cat_dist: Dict[str, int] = {}
    for tc in tcs:
        cat_dist[tc.category] = cat_dist.get(tc.category, 0) + 1

    # Priority distribution
    pri_dist: Dict[str, int] = {}
    for tc in tcs:
        pri_dist[tc.priority] = pri_dist.get(tc.priority, 0) + 1

    # Human acceptance rate: approved test cases / total test cases
    if total_test_cases > 0:
        acceptance_rate = round((len(approved_tcs) / total_test_cases) * 100.0, 2)
    else:
        acceptance_rate = None

    return schemas.CoverageMetric(
        total_requirements=total_requirements,
        approved_requirements=num_approved_reqs,
        total_test_cases=total_test_cases,
        approved_test_cases=len(approved_tcs),
        requirements_with_approved_tests=num_approved_with_tests,
        requirements_uncovered=uncovered_count,
        coverage_percentage=coverage_pct,
        category_distribution=cat_dist,
        priority_distribution=pri_dist,
        schema_validation_rate=100.0,
        human_acceptance_rate=acceptance_rate,
        processing_time_seconds=None,
    )


def generate_traceability_matrix(
    db: Session,
    material_id: int,
    user_id: int,
) -> List[Dict[str, Any]]:
    """
    Builds a bidirectional traceability matrix mapping requirements to their linked test cases.
    Identifies coverage state for each requirement:
    - 'Covered (Approved)'
    - 'In Review (Tests Generated)'
    - 'Uncovered'
    """
    reqs = db.query(models.RequirementModel).filter(
        models.RequirementModel.material_id == material_id,
        models.RequirementModel.owner_id == user_id,
    ).order_by(models.RequirementModel.id.asc()).all()

    matrix: List[Dict[str, Any]] = []

    for r in reqs:
        # Fetch test cases linked by requirement PK or req_code
        linked_tcs = db.query(models.TestCaseModel).filter(
            models.TestCaseModel.material_id == material_id,
            (models.TestCaseModel.requirement_id == r.id) | (models.TestCaseModel.req_code == r.req_id),
        ).all()

        has_approved_test = any(tc.review_status == schemas.ReviewStatus.APPROVED.value for tc in linked_tcs)

        if has_approved_test:
            cov_status = "Covered (Approved)"
        elif len(linked_tcs) > 0:
            cov_status = "In Review (Tests Generated)"
        else:
            cov_status = "Uncovered"

        tc_summaries = []
        for tc in linked_tcs:
            tc_summaries.append({
                "id": tc.tc_id,
                "title": tc.title,
                "category": tc.category,
                "priority": tc.priority,
                "review_status": tc.review_status,
            })

        matrix.append({
            "requirement_id": r.req_id,
            "title": r.title,
            "category": r.category,
            "review_status": r.review_status,
            "coverage_status": cov_status,
            "linked_test_cases_count": len(linked_tcs),
            "linked_test_cases": tc_summaries,
        })

    return matrix


def evaluate_ground_truth_benchmarks(
    ground_truth_reqs: List[str],
    extracted_reqs: List[str],
) -> Dict[str, Any]:
    """
    Evaluates requirement extraction precision, recall, and F1 score against
    a human-verified ground-truth sample. Uses normalized keyword/token matching.
    """
    if not ground_truth_reqs:
        return {
            "error": "Ground truth list cannot be empty.",
            "precision": None,
            "recall": None,
            "f1_score": None,
        }

    # Normalize tokens for matching
    def normalize(text: str) -> set:
        return set(text.lower().replace("-", " ").replace("_", " ").split())

    gt_sets = [normalize(g) for g in ground_truth_reqs]
    ext_sets = [normalize(e) for e in extracted_reqs]

    matched_gt = set()
    matched_ext = set()

    for i, e_toks in enumerate(ext_sets):
        for j, g_toks in enumerate(gt_sets):
            intersection = e_toks.intersection(g_toks)
            overlap = len(intersection) / max(len(g_toks), 1)
            if overlap >= 0.5:
                matched_ext.add(i)
                matched_gt.add(j)

    true_positives = len(matched_gt)
    false_positives = len(ext_sets) - len(matched_ext)
    false_negatives = len(gt_sets) - len(matched_gt)

    precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) > 0 else 0.0
    recall = true_positives / (true_positives + false_negatives) if (true_positives + false_negatives) > 0 else 0.0
    f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0

    return {
        "ground_truth_count": len(ground_truth_reqs),
        "extracted_count": len(extracted_reqs),
        "true_positives": true_positives,
        "false_positives": false_positives,
        "false_negatives": false_negatives,
        "precision": round(precision * 100, 2),
        "recall": round(recall * 100, 2),
        "f1_score": round(f1 * 100, 2),
        "methodology": "Token-overlap semantic containment with 0.5 threshold.",
    }
