"""
Document processing module for AI Interview Copilot.
Extracts clean, formatted text from candidate Resumes & Job Descriptions (PDF, DOCX, TXT).
"""

import io
import os
import re
import logging
from typing import Optional

logger = logging.getLogger("document_processor")

def extract_text_from_document(file_bytes: bytes, filename: str) -> str:
    """
    Extracts plain text from uploaded resume/JD document.
    Supported formats: .pdf, .docx, .doc, .txt, .md
    """
    ext = os.path.splitext(filename)[1].lower()
    text = ""

    if ext == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(file_bytes))
            pages_text = []
            for idx, page in enumerate(reader.pages):
                page_str = page.extract_text() or ""
                if page_str.strip():
                    pages_text.append(page_str.strip())
            text = "\n\n".join(pages_text)
            logger.info(f"Extracted {len(text)} characters from PDF ({len(reader.pages)} pages).")
        except Exception as e:
            logger.error(f"Error extracting text from PDF: {e}")
            raise ValueError(f"Could not parse PDF file: {e}")

    elif ext in (".docx", ".doc"):
        try:
            import docx
            doc = docx.Document(io.BytesIO(file_bytes))
            paras = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
            # Also extract from tables if any
            for table in doc.tables:
                for row in table.rows:
                    row_text = " | ".join([cell.text.strip() for cell in row.cells if cell.text.strip()])
                    if row_text:
                        paras.append(row_text)
            text = "\n".join(paras)
            logger.info(f"Extracted {len(text)} characters from DOCX.")
        except Exception as e:
            logger.error(f"Error extracting text from DOCX: {e}")
            raise ValueError(f"Could not parse Word (.docx) file: {e}")

    elif ext in (".txt", ".md", ""):
        try:
            text = file_bytes.decode("utf-8", errors="ignore").strip()
        except Exception as e:
            text = str(file_bytes)

    else:
        # Fallback to UTF-8
        try:
            text = file_bytes.decode("utf-8", errors="ignore").strip()
        except Exception:
            raise ValueError(f"Unsupported file format '{ext}'. Please upload a PDF, DOCX, or TXT file.")

    # Clean up excessive whitespace
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    return text
