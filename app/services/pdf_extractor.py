"""PDF text extraction using PyMuPDF, with PDF stored in AWS S3."""
from __future__ import annotations

import logging

from app.config import config

logger = logging.getLogger(__name__)


def upload_pdf_to_s3(pdf_bytes: bytes, report_id: str) -> str:
    """
    Upload a PDF to S3 and return the S3 key.
    The original report is never modified (Req 14.1).
    """
    if not config.S3_BUCKET_PDF:
        logger.warning("S3_BUCKET_PDF not configured; skipping PDF upload")
        return ""
    try:
        from app.aws.clients import get_s3
        key = f"reports/{report_id}/original.pdf"
        get_s3().put_object(
            Bucket=config.S3_BUCKET_PDF,
            Key=key,
            Body=pdf_bytes,
            ContentType="application/pdf",
            ServerSideEncryption="AES256",
            Metadata={"report_id": report_id},
        )
        s3_uri = f"s3://{config.S3_BUCKET_PDF}/{key}"
        logger.info(f"PDF uploaded to {s3_uri}")
        return s3_uri
    except Exception as exc:
        logger.error(f"S3 upload failed for report {report_id}: {exc}")
        return ""


def get_pdf_presigned_url(report_id: str, expires_in: int = 3600) -> str:
    """Generate a pre-signed S3 URL for secure PDF download."""
    if not config.S3_BUCKET_PDF:
        return ""
    try:
        from app.aws.clients import get_s3
        key = f"reports/{report_id}/original.pdf"
        url = get_s3().generate_presigned_url(
            "get_object",
            Params={"Bucket": config.S3_BUCKET_PDF, "Key": key},
            ExpiresIn=expires_in,
        )
        return url
    except Exception as exc:
        logger.error(f"Failed to generate presigned URL for {report_id}: {exc}")
        return ""


def extract_text_from_pdf(pdf_bytes: bytes) -> tuple[str, bool]:
    """
    Extract text from PDF bytes using PyMuPDF.

    Returns:
        (text, ocr_processed): extracted text and whether OCR was attempted
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        raise RuntimeError("PyMuPDF is not installed. Run: uv add pymupdf")

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        raise ValueError(f"Failed to open PDF: {exc}") from exc

    pages_text: list[str] = []
    ocr_processed = False

    for page_num, page in enumerate(doc):
        text = page.get_text("text")
        if not text.strip():
            # Attempt OCR on image-only pages
            try:
                tp = page.get_textpage_ocr(flags=0, full=True)
                text = page.get_text("text", textpage=tp)
                ocr_processed = True
                logger.info(f"OCR applied to page {page_num}")
            except Exception as ocr_exc:
                logger.warning(f"OCR failed on page {page_num}: {ocr_exc}")
                text = ""
        pages_text.append(text)

    doc.close()
    return "\n".join(pages_text), ocr_processed


def extract_text_from_path(pdf_path: str) -> tuple[str, bool]:
    """Extract text from a PDF file path."""
    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()
    return extract_text_from_pdf(pdf_bytes)
