"""Resume text extraction from PDF and DOCX files."""

import io
import logging
import re

logger = logging.getLogger(__name__)


def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extract text from a PDF file."""
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            pages = []
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    pages.append(text)
            return "\n\n".join(pages)
    except Exception as e:
        logger.error("PDF extraction failed: %s", e)
        return ""


def extract_text_from_docx(file_bytes: bytes) -> str:
    """Extract text from a DOCX file."""
    try:
        from docx import Document
        doc = Document(io.BytesIO(file_bytes))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n".join(paragraphs)
    except Exception as e:
        logger.error("DOCX extraction failed: %s", e)
        return ""


def extract_text(file_bytes: bytes, file_type: str) -> str:
    """Extract text from a resume file."""
    if file_type == "pdf":
        return extract_text_from_pdf(file_bytes)
    elif file_type == "docx":
        return extract_text_from_docx(file_bytes)
    return ""


def extract_keywords(text: str) -> set[str]:
    """Extract known tech/role keywords from resume text."""
    from app.workers.tasks._ats_scoring import ALL_TECH_KEYWORDS
    text_lower = text.lower()
    found = set()
    for keyword in ALL_TECH_KEYWORDS:
        if len(keyword) <= 2:
            # Short keywords need word boundary matching
            if re.search(r'\b' + re.escape(keyword) + r'\b', text_lower):
                found.add(keyword)
        else:
            if keyword in text_lower:
                found.add(keyword)
    return found
