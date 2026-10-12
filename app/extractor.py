import io
import os
import re
import logging
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from PIL import Image
import pymupdf as fitz
import pytesseract

logger = logging.getLogger(__name__)

# Configure Tesseract executable path if specified in environment
tesseract_cmd = os.getenv("TESSERACT_CMD")
if tesseract_cmd:
    pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

# Configurable limits
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "25"))
MAX_PAGE_COUNT = int(os.getenv("MAX_PAGE_COUNT", "100"))


class ExtractionError(Exception):
    """Base exception for document extraction failures."""
    pass


class PasswordProtectedPDFError(ExtractionError):
    """Raised when PDF is encrypted or password-protected."""
    pass


class CorruptedDocumentError(ExtractionError):
    """Raised when PDF structure is corrupt or unreadable."""
    pass


class LimitExceededError(ExtractionError):
    """Raised when document exceeds size or page limits."""
    pass


@dataclass
class PageExtractionInfo:
    page_number: int
    text: str
    method: str  # "digital" or "ocr"
    char_count: int


@dataclass
class DetailedExtractionResult:
    text: str
    pages_total: int
    pages_ocr: int
    character_count: int
    ocr_used: bool
    pages: List[PageExtractionInfo] = field(default_factory=list)


def sanitize_extracted_text(text: str) -> str:
    """
    Sanitizes extracted document text to prevent prompt injection, control character
    hazards, and script execution attempts embedded within requirements documents.
    """
    if not text:
        return ""
    # Strip null bytes and non-printable control characters (except newline, tab, carriage return)
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    # Neutralize potential prompt injection delimiters that attempt to override system instructions
    cleaned = cleaned.replace("<|im_start|>", "[sanitized_token]")
    cleaned = cleaned.replace("<|im_end|>", "[sanitized_token]")
    cleaned = cleaned.replace("```system", "```sanitized_system")
    return cleaned.strip()


def extract_detailed_from_pdf(
    file_bytes: bytes,
    ocr_threshold: int = 50,
    max_file_size_mb: int = MAX_FILE_SIZE_MB,
    max_pages: int = MAX_PAGE_COUNT,
) -> DetailedExtractionResult:
    """
    Extracts text and page-by-page metadata from PDF bytes using PyMuPDF (fitz)
    with PyTesseract OCR fallback for scanned pages.
    Validates file size, encryption, corruption, and page limits.
    """
    # 1. Enforce file size limits
    file_size_mb = len(file_bytes) / (1024 * 1024)
    if file_size_mb > max_file_size_mb:
        raise LimitExceededError(
            f"File size ({file_size_mb:.2f} MB) exceeds maximum allowed limit of {max_file_size_mb} MB."
        )

    if not file_bytes:
        raise CorruptedDocumentError("Uploaded file is empty (0 bytes).")

    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
    except Exception as exc:
        raise CorruptedDocumentError(f"Unable to parse PDF document. File may be corrupted or not a valid PDF: {str(exc)}")

    try:
        # 2. Check for password protection
        if doc.is_encrypted or doc.needs_pass:
            raise PasswordProtectedPDFError(
                "Document is encrypted or password-protected. Please provide an unencrypted requirement document."
            )

        pages_total = len(doc)
        if pages_total == 0:
            raise CorruptedDocumentError("PDF document contains no pages.")

        if pages_total > max_pages:
            raise LimitExceededError(
                f"Document has {pages_total} pages, exceeding the maximum allowed limit of {max_pages} pages."
            )

        page_records: List[PageExtractionInfo] = []
        pages_ocr_count = 0
        all_chunks: List[str] = []

        # 3. Process each page
        for page_index in range(pages_total):
            page_num = page_index + 1
            page = doc[page_index]
            
            # Step A: Attempt digital text extraction
            raw_page_text = page.get_text("text").strip()
            page_text = sanitize_extracted_text(raw_page_text)

            # Step B: Fall back to OCR if digital text is empty or below threshold
            if len(page_text) < ocr_threshold:
                ocr_text = ""
                try:
                    # Render page at 2.0x zoom (144 DPI) for OCR accuracy
                    matrix = fitz.Matrix(2.0, 2.0)
                    pix = page.get_pixmap(matrix=matrix)
                    img_data = pix.tobytes("png")
                    image = Image.open(io.BytesIO(img_data))
                    ocr_raw = pytesseract.image_to_string(image).strip()
                    ocr_text = sanitize_extracted_text(ocr_raw)
                except pytesseract.TesseractNotFoundError:
                    logger.warning(
                        "Tesseract executable not found. OCR cannot be performed for page %d.", page_num
                    )
                except Exception as ocr_err:
                    logger.error("OCR error on page %d: %s", page_num, str(ocr_err))

                if len(ocr_text) > len(page_text):
                    page_text = ocr_text
                    pages_ocr_count += 1
                    page_records.append(
                        PageExtractionInfo(
                            page_number=page_num,
                            text=page_text,
                            method="ocr",
                            char_count=len(page_text),
                        )
                    )
                    all_chunks.append(f"--- Page {page_num} [OCR] ---\n{page_text}")
                    continue

            # Standard digital page record
            page_records.append(
                PageExtractionInfo(
                    page_number=page_num,
                    text=page_text,
                    method="digital",
                    char_count=len(page_text),
                )
            )
            if page_text:
                all_chunks.append(f"--- Page {page_num} ---\n{page_text}")

        full_text = "\n\n".join(all_chunks).strip()
        total_chars = sum(p.char_count for p in page_records)

        return DetailedExtractionResult(
            text=full_text,
            pages_total=pages_total,
            pages_ocr=pages_ocr_count,
            character_count=total_chars,
            ocr_used=(pages_ocr_count > 0),
            pages=page_records,
        )
    finally:
        doc.close()


def extract_text_from_pdf(file_bytes: bytes, ocr_threshold: int = 50) -> str:
    """
    Backward-compatible wrapper for legacy endpoints.
    Extracts text from PDF bytes using PyMuPDF with PyTesseract fallback.
    """
    res = extract_detailed_from_pdf(file_bytes, ocr_threshold=ocr_threshold)
    return res.text
