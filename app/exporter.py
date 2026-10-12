import io
import csv
import json
from typing import List, Dict, Any, Optional
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter


def format_steps_for_export(steps: Any) -> str:
    """Formats steps into clean numbered multi-line string for export."""
    if isinstance(steps, list):
        formatted = []
        for i, s in enumerate(steps, 1):
            s_clean = str(s).strip()
            # If already has leading number, preserve
            if s_clean.startswith(f"{i}.") or s_clean.startswith(f"Step {i}"):
                formatted.append(s_clean)
            else:
                formatted.append(f"{i}. {s_clean}")
        return "\n".join(formatted)
    return str(steps or "")


def format_test_data_for_export(test_data: Any) -> str:
    """Formats test data dictionary into clean key-value lines."""
    if isinstance(test_data, dict):
        return "\n".join(f"{k}: {v}" for k, v in test_data.items())
    elif isinstance(test_data, list):
        return "\n".join(str(item) for item in test_data)
    return str(test_data or "")


def export_test_cases_to_csv(test_cases: List[Dict[str, Any]]) -> str:
    """
    Exports a list of test cases to a standard CSV string.
    Only approved or filtered cases are exported as requested.
    """
    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_ALL)

    headers = [
        "Test Case ID",
        "Requirement ID",
        "Requirement Description",
        "Test Case Title",
        "Category",
        "Preconditions",
        "Test Data",
        "Test Steps",
        "Expected Result",
        "Priority",
        "Review Status",
        "Source Document",
    ]
    writer.writerow(headers)

    for tc in test_cases:
        steps_str = format_steps_for_export(tc.get("steps", []))
        precond_str = "\n".join(tc.get("preconditions", [])) if isinstance(tc.get("preconditions"), list) else str(tc.get("preconditions") or "")
        test_data_str = format_test_data_for_export(tc.get("test_data"))

        writer.writerow([
            tc.get("id", ""),
            tc.get("requirement_id", ""),
            tc.get("requirement_description", ""),
            tc.get("title", ""),
            tc.get("category", ""),
            precond_str,
            test_data_str,
            steps_str,
            tc.get("expected_result", ""),
            tc.get("priority", ""),
            tc.get("review_status", ""),
            tc.get("source_document", ""),
        ])

    return output.getvalue()


def export_test_cases_to_excel(
    test_cases: List[Dict[str, Any]],
    traceability_data: Optional[List[Dict[str, Any]]] = None,
    metrics_data: Optional[Dict[str, Any]] = None,
) -> bytes:
    """
    Generates a professional, multi-sheet Excel (.xlsx) workbook using openpyxl:
    - Sheet 1: 'Approved Test Cases' (formatted table with auto-wrap)
    - Sheet 2: 'Traceability Matrix' (bidirectional requirement-to-test links)
    - Sheet 3: 'Coverage & Quality Metrics' (executive summary KPIs)
    """
    wb = openpyxl.Workbook()

    # Styling definitions
    header_fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    accent_fill = PatternFill(start_color="0284C7", end_color="0284C7", fill_type="solid")
    thin_border = Border(
        left=Side(style="thin", color="E2E8F0"),
        right=Side(style="thin", color="E2E8F0"),
        top=Side(style="thin", color="E2E8F0"),
        bottom=Side(style="thin", color="E2E8F0"),
    )
    align_top_left = Alignment(horizontal="left", vertical="top", wrap_text=True)
    align_center = Alignment(horizontal="center", vertical="top")

    # -------------------------------------------------------------------------
    # Sheet 1: Approved Test Cases
    # -------------------------------------------------------------------------
    ws_tests = wb.active
    ws_tests.title = "Test Cases"
    ws_tests.views.sheetView[0].showGridLines = True

    tc_headers = [
        "Test Case ID",
        "Requirement ID",
        "Requirement Summary",
        "Test Case Title",
        "Category",
        "Priority",
        "Preconditions",
        "Test Data",
        "Execution Steps",
        "Expected Result",
        "Review Status",
        "Source Document",
    ]
    ws_tests.append(tc_headers)

    for col_num in range(1, len(tc_headers) + 1):
        cell = ws_tests.cell(row=1, column=col_num)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = thin_border
    ws_tests.row_dimensions[1].height = 28

    for row_idx, tc in enumerate(test_cases, start=2):
        steps_str = format_steps_for_export(tc.get("steps", []))
        precond_str = "\n".join(tc.get("preconditions", [])) if isinstance(tc.get("preconditions"), list) else str(tc.get("preconditions") or "")
        test_data_str = format_test_data_for_export(tc.get("test_data"))

        row_values = [
            tc.get("id", ""),
            tc.get("requirement_id", ""),
            tc.get("requirement_description", ""),
            tc.get("title", ""),
            tc.get("category", ""),
            tc.get("priority", ""),
            precond_str,
            test_data_str,
            steps_str,
            tc.get("expected_result", ""),
            tc.get("review_status", ""),
            tc.get("source_document", ""),
        ]
        ws_tests.append(row_values)

        for col_num in range(1, len(row_values) + 1):
            cell = ws_tests.cell(row=row_idx, column=col_num)
            cell.border = thin_border
            if col_num in [1, 2, 5, 6, 11]:
                cell.alignment = align_center
            else:
                cell.alignment = align_top_left

    # Set column widths
    col_widths = [14, 16, 28, 30, 16, 12, 26, 24, 40, 40, 16, 22]
    for i, w in enumerate(col_widths, start=1):
        ws_tests.column_dimensions[get_column_letter(i)].width = w

    # -------------------------------------------------------------------------
    # Sheet 2: Traceability Matrix
    # -------------------------------------------------------------------------
    if traceability_data:
        ws_trace = wb.create_sheet(title="Traceability Matrix")
        ws_trace.views.sheetView[0].showGridLines = True

        trace_headers = [
            "Requirement ID",
            "Requirement Title",
            "Category",
            "Review Status",
            "Coverage Status",
            "Linked Test Count",
            "Linked Test Cases (IDs & Titles)",
        ]
        ws_trace.append(trace_headers)

        for col_num in range(1, len(trace_headers) + 1):
            cell = ws_trace.cell(row=1, column=col_num)
            cell.fill = accent_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = thin_border
        ws_trace.row_dimensions[1].height = 28

        for row_idx, r in enumerate(traceability_data, start=2):
            linked_tcs = r.get("linked_test_cases", [])
            linked_str = "\n".join(f"- {tc.get('id')}: {tc.get('title')} [{tc.get('category')}] ({tc.get('review_status')})" for tc in linked_tcs)

            row_values = [
                r.get("requirement_id", ""),
                r.get("title", ""),
                r.get("category", ""),
                r.get("review_status", ""),
                r.get("coverage_status", ""),
                r.get("linked_test_cases_count", 0),
                linked_str,
            ]
            ws_trace.append(row_values)

            for col_num in range(1, len(row_values) + 1):
                cell = ws_trace.cell(row=row_idx, column=col_num)
                cell.border = thin_border
                if col_num in [1, 3, 4, 5, 6]:
                    cell.alignment = align_center
                else:
                    cell.alignment = align_top_left

        trace_widths = [16, 32, 18, 16, 24, 18, 50]
        for i, w in enumerate(trace_widths, start=1):
            ws_trace.column_dimensions[get_column_letter(i)].width = w

    # -------------------------------------------------------------------------
    # Sheet 3: Quality & Coverage Metrics
    # -------------------------------------------------------------------------
    if metrics_data:
        ws_metrics = wb.create_sheet(title="Quality Metrics")
        ws_metrics.views.sheetView[0].showGridLines = True

        ws_metrics.append(["Metric Name", "Value", "Description"])
        for col_num in range(1, 4):
            cell = ws_metrics.cell(row=1, column=col_num)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = thin_border
        ws_metrics.row_dimensions[1].height = 26

        metric_rows = [
            ("Total Requirements Extracted", metrics_data.get("total_requirements", 0), "Total distinct requirements identified in document"),
            ("Approved Requirements", metrics_data.get("approved_requirements", 0), "Requirements approved by human reviewers"),
            ("Total Generated Test Cases", metrics_data.get("total_test_cases", 0), "Total test scenarios generated across all categories"),
            ("Approved Test Cases", metrics_data.get("approved_test_cases", 0), "Test cases approved for production test suites"),
            ("Requirements with Approved Tests", metrics_data.get("requirements_with_approved_tests", 0), "Approved requirements linked to >= 1 approved test case"),
            ("Uncovered Requirements", metrics_data.get("requirements_uncovered", 0), "Approved requirements currently lacking approved test cases"),
            ("Requirement Coverage (%)", f"{metrics_data.get('coverage_percentage')}%" if metrics_data.get("coverage_percentage") is not None else "N/A", "Requirement coverage formula: (Approved Linked / Total Approved) * 100"),
            ("Human Acceptance Rate (%)", f"{metrics_data.get('human_acceptance_rate')}%" if metrics_data.get("human_acceptance_rate") is not None else "N/A", "Percentage of generated test cases approved by human review"),
            ("Schema Validation Success Rate (%)", f"{metrics_data.get('schema_validation_rate', 100.0)}%", "Output conformance rate to Pydantic schemas"),
        ]

        for row_idx, (m_name, m_val, m_desc) in enumerate(metric_rows, start=2):
            ws_metrics.append([m_name, m_val, m_desc])
            for col_num in range(1, 4):
                cell = ws_metrics.cell(row=row_idx, column=col_num)
                cell.border = thin_border
                cell.alignment = align_center if col_num == 2 else align_top_left

        ws_metrics.column_dimensions["A"].width = 36
        ws_metrics.column_dimensions["B"].width = 20
        ws_metrics.column_dimensions["C"].width = 60

    # Save to buffer
    excel_buffer = io.BytesIO()
    wb.save(excel_buffer)
    excel_buffer.seek(0)
    return excel_buffer.getvalue()
