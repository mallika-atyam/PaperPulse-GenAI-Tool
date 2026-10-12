"""
===============================================================================
PaperPulse - Google Colab & Local End-to-End Demonstration Script
===============================================================================

This script demonstrates the complete PaperPulse pipeline programmatically:
  1. User Registration (POST /users) & OAuth2 Login (POST /auth/login)
  2. PDF Creation & Multipart Upload with PyMuPDF Extraction (POST /materials/upload)
  3. AI Summarization (POST /materials/{id}/summary)
  4. Structured Pydantic Quiz Generation (POST /materials/{id}/quiz)

-------------------------------------------------------------------------------
GOOGLE COLAB USAGE INSTRUCTIONS (Copy-paste into Colab cells):
-------------------------------------------------------------------------------

# Cell 1: Clone Repository & Install Dependencies
!git clone https://github.com/your-username/paperpulse.git
%cd paperpulse
!pip install -q -r requirements.txt
!apt-get install -y -q tesseract-ocr > /dev/null  # Install Tesseract for OCR fallback

# Cell 2: Run the Demo Script
!python colab_demo.py

===============================================================================
"""

import sys
import os
import io
import json
import time

# Configure UTF-8 encoding for Windows terminals
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Ensure project root is in Python path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

import pymupdf as fitz
from fastapi.testclient import TestClient
from app.main import app

# Initialize the test client
client = TestClient(app)


def print_banner(title: str):
    """Prints a styled terminal banner."""
    separator = "=" * 70
    print(f"\n{separator}")
    print(f"  {title}")
    print(f"{separator}")


def create_sample_academic_pdf() -> bytes:
    """Generates an in-memory academic PDF using PyMuPDF."""
    doc = fitz.open()
    page = doc.new_page()

    academic_text = (
        "PaperPulse Research: The Transformer Architecture and Attention Mechanisms\n\n"
        "Abstract:\n"
        "The Transformer is a deep learning architecture introduced in 'Attention Is All You Need' "
        "(Vaswani et al., 2017). Unlike recurrent neural networks (RNNs) and convolutional networks (CNNs), "
        "the Transformer relies entirely on self-attention mechanisms to compute representations of input "
        "and output sequences without using sequence-aligned recurrence.\n\n"
        "Key Components:\n"
        "1. Scaled Dot-Product Attention: Computes attention scores using queries, keys, and values.\n"
        "2. Multi-Head Attention: Allows the model to jointly attend to information from different "
        "representation subspaces at different positions.\n"
        "3. Positional Encoding: Injects order information into the sequence embeddings since the "
        "architecture contains no recurrence or convolution.\n\n"
        "Impact:\n"
        "Transformers have become the foundational backbone for state-of-the-art Natural Language Processing (NLP) "
        "models such as BERT, GPT, and modern Large Language Models (LLMs)."
    )

    rect = fitz.Rect(40, 40, 550, 750)
    page.insert_textbox(rect, academic_text, fontsize=11, fontname="helv")
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def run_pipeline_demo():
    print_banner("PaperPulse End-to-End Pipeline Demonstration")

    # -------------------------------------------------------------------------
    # Step 1: User Registration & OAuth2 JWT Authentication
    # -------------------------------------------------------------------------
    print("\n[Step 1] Registering User and Authenticating...")
    timestamp = int(time.time())
    demo_email = f"colab_student_{timestamp}@paperpulse.ai"
    demo_password = "SecureColabPassword123!"

    # 1a. POST /users
    print(f" -> POST /users: Registering '{demo_email}'...")
    reg_response = client.post(
        "/users",
        json={"email": demo_email, "password": demo_password},
    )
    if reg_response.status_code == 201:
        user_data = reg_response.json()
        print(f"    SUCCESS: User registered with ID: {user_data['id']}")
    else:
        print(f"    NOTE: Registration status {reg_response.status_code}: {reg_response.text}")

    # 1b. POST /auth/login
    print(" -> POST /auth/login: Fetching OAuth2 JWT Bearer Token...")
    login_response = client.post(
        "/auth/login",
        data={"username": demo_email, "password": demo_password},
    )
    assert login_response.status_code == 200, f"Login failed: {login_response.text}"
    token_data = login_response.json()
    access_token = token_data["access_token"]
    auth_headers = {"Authorization": f"Bearer {access_token}"}
    print(f"    SUCCESS: Received JWT Token: {access_token[:28]}...")

    # -------------------------------------------------------------------------
    # Step 2: Upload PDF with PyMuPDF Extraction & OCR Fallback
    # -------------------------------------------------------------------------
    print("\n[Step 2] Generating & Uploading PDF Material...")
    pdf_bytes = create_sample_academic_pdf()
    filename = "transformer_architecture.pdf"
    print(f" -> Generated in-memory PDF '{filename}' ({len(pdf_bytes)} bytes)")

    files = {"file": (filename, pdf_bytes, "application/pdf")}
    upload_response = client.post("/materials/upload", headers=auth_headers, files=files)
    assert upload_response.status_code == 201, f"Upload failed: {upload_response.text}"

    material_data = upload_response.json()
    material_id = material_data["id"]
    print(f" -> POST /materials/upload: Success!")
    print(f"    Material ID: {material_id}")
    print(f"    Filename:    {material_data['filename']}")
    print(f"    Status:      {material_data['status']}")
    print(f"    Extracted Text Preview: {material_data.get('extracted_text_preview', '')[:100]}...")

    # -------------------------------------------------------------------------
    # Step 3: Request AI Document Summary
    # -------------------------------------------------------------------------
    print(f"\n[Step 3] Generating Summary for Material #{material_id}...")
    summary_response = client.post(f"/materials/{material_id}/summary", headers=auth_headers)
    assert summary_response.status_code == 200, f"Summary failed: {summary_response.text}"

    summary_data = summary_response.json()
    print(" -> POST /materials/{id}/summary: Success!")
    print(f"    Status: {summary_data['status']}")
    print("\n" + "-" * 50)
    print("GENERATED SUMMARY:")
    print("-" * 50)
    print(summary_data["summary"])
    print("-" * 50)

    # -------------------------------------------------------------------------
    # Step 4: Generate Structured Multiple-Choice Quiz
    # -------------------------------------------------------------------------
    print(f"\n[Step 4] Generating Structured Quiz for Material #{material_id}...")
    quiz_response = client.post(
        f"/materials/{material_id}/quiz",
        headers=auth_headers,
        json={"num_questions": 3},
    )
    assert quiz_response.status_code == 200, f"Quiz generation failed: {quiz_response.text}"

    quiz_data = quiz_response.json()
    quiz_body = quiz_data["quiz"]
    questions = quiz_body["questions"]

    print(" -> POST /materials/{id}/quiz: Success!")
    print(f"    Status:     {quiz_data['status']}")
    print(f"    Quiz Title: {quiz_body.get('title', 'Generated Quiz')}")
    print(f"    Total Questions: {len(questions)}")
    print("\n" + "=" * 70)
    print("STRUCTURED MULTIPLE-CHOICE QUESTIONS (Pydantic Validated):")
    print("=" * 70)

    for idx, q in enumerate(questions, start=1):
        print(f"\nQ{idx}: {q['question']}")
        for opt_idx, opt in enumerate(q["options"], start=1):
            marker = " [*]" if opt == q["correct_answer"] else ""
            print(f"    {chr(64 + opt_idx)}. {opt}{marker}")
        print(f"    >> Correct Answer: {q['correct_answer']}")
        if q.get("explanation"):
            print(f"    >> Explanation:    {q['explanation']}")

    print("\n" + "=" * 70)
    print("  DEMO COMPLETE: All 4 Pipeline Steps Executed Successfully!")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    run_pipeline_demo()
