"""Pure extraction + heading-aware chunking. No database, network or Celery here.

Every chunk's text is an exact slice ``page_text[char_start:char_end]`` of its page's normalised
text, so a citation can always be located again. Chunks never cross page boundaries.
"""

import hashlib
import io
import re
import subprocess
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

CHUNK_TARGET = 1200
CHUNK_OVERLAP = 160
MAX_HEADING_CHARS = 120
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class ExtractionError(Exception):
    """Carries a safe, user-presentable failure code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Block:
    text: str
    heading_level: int | None = None  # 1 = top level


@dataclass
class ExtractedPage:
    page: int | None
    blocks: list[Block] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(block.text for block in self.blocks)


@dataclass(frozen=True)
class ChunkDraft:
    chunk_index: int
    page: int | None
    char_start: int
    char_end: int
    text: str
    heading_path: tuple[str, ...]

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


def detect_source_language(text: str) -> str:
    """Identify supported scripts by majority letters; never guesses a translation."""
    counts = {
        "hi": len(re.findall(r"[ऀ-ॿ]", text)),
        "pa": len(re.findall(r"[਀-੿]", text)),
        "te": len(re.findall(r"[ఀ-౿]", text)),
        "en": len(re.findall(r"[A-Za-z]", text)),
    }
    language, count = max(counts.items(), key=lambda item: item[1])
    return language if count else "und"


def _clean(line: str) -> str:
    return re.sub(r"[ \t ]+", " ", line).strip()


# ---- file signature verification ("scanning" stage) ---------------------------------------------


def verify_signature(mime_type: str, raw: bytes) -> None:
    if not raw:
        raise ExtractionError("EMPTY_DOCUMENT")
    if mime_type == "application/pdf" and not raw.lstrip()[:5] == b"%PDF-":
        raise ExtractionError("UNSUPPORTED_FILE_SIGNATURE")
    if mime_type == DOCX_MIME and not raw.startswith(b"PK\x03\x04"):
        raise ExtractionError("UNSUPPORTED_FILE_SIGNATURE")
    if mime_type == "text/plain":
        decode_text(raw)


def decode_text(raw: bytes) -> str:
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ExtractionError("UNREADABLE_TEXT_ENCODING") from error


# ---- TXT ------------------------------------------------------------------------------------------

_TXT_HEADING = re.compile(
    r"^(?:(#{1,3})\s+(.+)|((?:unit|chapter|section|module|part)\s+[\dIVXLC]+[.:)\-\s].{0,100}))$",
    re.IGNORECASE,
)


def _txt_heading_level(line: str) -> int | None:
    match = _TXT_HEADING.match(line)
    if match:
        return len(match.group(1)) if match.group(1) else 1
    letters = re.sub(r"[^A-Za-z]", "", line)
    if (
        3 <= len(line) <= 80
        and len(letters) >= 3
        and letters.isupper()
        and not line.endswith(".")
    ):
        return 1
    return None


def extract_txt(raw: bytes) -> list[ExtractedPage]:
    page = ExtractedPage(page=None)
    for line in decode_text(raw).splitlines():
        cleaned = _clean(line)
        if cleaned:
            level = _txt_heading_level(cleaned)
            text = re.sub(r"^#{1,3}\s+", "", cleaned) if level else cleaned
            page.blocks.append(Block(text, level))
    return [page]


# ---- DOCX -----------------------------------------------------------------------------------------


def extract_docx(raw: bytes) -> list[ExtractedPage]:
    from docx import Document as DocxDocument
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    try:
        document = DocxDocument(io.BytesIO(raw))
    except Exception as error:
        raise ExtractionError("CORRUPT_FILE") from error
    page = ExtractedPage(page=None)
    for element in document.element.body.iterchildren():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag == "p":
            paragraph = Paragraph(element, document)
            text = _clean(paragraph.text)
            if not text:
                continue
            style = (paragraph.style.name if paragraph.style is not None else "") or ""
            level: int | None = None
            if style == "Title":
                level = 1
            elif style.startswith("Heading"):
                digits = re.sub(r"\D", "", style)
                level = min(int(digits), 3) if digits else 1
            page.blocks.append(Block(text, level))
        elif tag == "tbl":
            for row in Table(element, document).rows:
                cells = [_clean(cell.text) for cell in row.cells]
                text = " | ".join(dict.fromkeys(cell for cell in cells if cell))
                if text:
                    page.blocks.append(Block(text))
    return [page]


# ---- PDF ------------------------------------------------------------------------------------------


def _pdf_lines(pdf: object) -> list[list[tuple[str, float, bool]]]:
    pages: list[list[tuple[str, float, bool]]] = []
    for page in pdf:  # type: ignore[attr-defined]
        lines: list[tuple[str, float, bool]] = []
        for block in page.get_text("dict").get("blocks", []):
            for line in block.get("lines", []):
                spans = [s for s in line.get("spans", []) if s.get("text", "").strip()]
                if not spans:
                    continue
                text = _clean("".join(s["text"] for s in line["spans"]))
                size = max(float(s.get("size", 0)) for s in spans)
                bold = all(int(s.get("flags", 0)) & 16 for s in spans)
                if text:
                    lines.append((text, round(size, 1), bold))
        pages.append(lines)
    return pages


def pdf_blocks(pages: list[list[tuple[str, float, bool]]]) -> list[ExtractedPage]:
    """Headings = lines clearly larger than body text (or bold, short, unpunctuated)."""
    sizes: Counter[float] = Counter()
    for lines in pages:
        for text, size, _ in lines:
            sizes[size] += len(text)
    body = sizes.most_common(1)[0][0] if sizes else 0.0
    heading_sizes = sorted(
        {s for lines in pages for _, s, _ in lines if body and s >= body * 1.15},
        reverse=True,
    )
    level_of = {size: min(index + 1, 3) for index, size in enumerate(heading_sizes)}
    result: list[ExtractedPage] = []
    for number, lines in enumerate(pages, start=1):
        page = ExtractedPage(page=number)
        for text, size, bold in lines:
            level = None
            if len(text) <= MAX_HEADING_CHARS and not text.endswith((".", ",", ";")):
                if size in level_of:
                    level = level_of[size]
                elif bold and len(text) <= 80 and len(text.split()) <= 12:
                    level = len(heading_sizes) + 1 if heading_sizes else 1
                    level = min(level, 3)
            page.blocks.append(Block(text, level))
        result.append(page)
    return result


def extract_pdf(raw: bytes, ocr_languages: str) -> list[ExtractedPage]:
    import pymupdf as fitz

    try:
        pdf = fitz.open(stream=raw, filetype="pdf")
    except Exception as error:
        raise ExtractionError("CORRUPT_FILE") from error
    if pdf.needs_pass:
        raise ExtractionError("PASSWORD_PROTECTED_PDF")
    pages = pdf_blocks(_pdf_lines(pdf))
    if any(page.blocks for page in pages):
        return pages
    return extract_scanned_pdf(raw, ocr_languages)


def ocr_command(source: str, output: str, languages: str) -> list[str]:
    return [
        "ocrmypdf",
        "--skip-text",
        "--rotate-pages",
        "--deskew",
        "--output-type",
        "pdf",
        "--language",
        languages,
        source,
        output,
    ]


def extract_scanned_pdf(raw: bytes, languages: str) -> list[ExtractedPage]:
    """OCR locally with OCRmyPDF/Tesseract; page numbers map 1:1 to the original PDF."""
    import pymupdf as fitz

    with tempfile.TemporaryDirectory() as folder:
        source, output = Path(folder) / "source.pdf", Path(folder) / "ocr.pdf"
        source.write_bytes(raw)
        try:
            subprocess.run(
                ocr_command(str(source), str(output), languages),
                check=True,
                capture_output=True,
                text=True,
                timeout=900,
            )
        except FileNotFoundError as error:
            raise ExtractionError("OCR_RUNTIME_UNAVAILABLE") from error
        except subprocess.TimeoutExpired as error:
            raise ExtractionError("OCR_TIMED_OUT") from error
        except subprocess.CalledProcessError as error:
            raise ExtractionError("OCR_FAILED") from error
        pages = pdf_blocks(_pdf_lines(fitz.open(str(output))))
    if not any(page.blocks for page in pages):
        raise ExtractionError("EMPTY_OCR_RESULT")
    return pages


def extract(
    mime_type: str, raw: bytes, ocr_languages: str = "eng+hin+pan+tel"
) -> list[ExtractedPage]:
    if mime_type == "text/plain":
        return extract_txt(raw)
    if mime_type == DOCX_MIME:
        return extract_docx(raw)
    if mime_type == "application/pdf":
        return extract_pdf(raw, ocr_languages)
    raise ExtractionError("UNSUPPORTED_MIME_TYPE")


# ---- chunking -------------------------------------------------------------------------------------


def chunk_pages(
    pages: list[ExtractedPage], target: int = CHUNK_TARGET, overlap: int = CHUNK_OVERLAP
) -> list[ChunkDraft]:
    chunks: list[ChunkDraft] = []
    stack: list[tuple[int, str]] = []  # (level, heading) carried across pages

    def path() -> tuple[str, ...]:
        return tuple(text for _, text in stack)

    def emit(
        page: ExtractedPage, text: str, start: int, end: int, heading: tuple[str, ...]
    ) -> None:
        if text[start:end].strip():
            chunks.append(
                ChunkDraft(len(chunks), page.page, start, end, text[start:end], heading)
            )

    for page in pages:
        text = page.text
        offset = 0
        span_start: int | None = None
        span_path = path()
        for block in page.blocks:
            begin, finish = offset, offset + len(block.text)
            offset = finish + 1  # "\n" separator
            if block.heading_level is not None:
                if span_start is not None:
                    emit(page, text, span_start, begin - 1, span_path)
                    span_start = None
                while stack and stack[-1][0] >= block.heading_level:
                    stack.pop()
                stack.append((block.heading_level, block.text))
                span_start, span_path = begin, path()
                continue
            if span_start is None:
                span_start, span_path = begin, path()
            if finish - span_start <= target:
                continue
            # The span is too long: close it before this block, or split an oversized block.
            if begin - 1 > span_start and begin - span_start > target // 2:
                emit(page, text, span_start, begin - 1, span_path)
                span_start = begin
            while finish - span_start > target:
                cut = text.rfind(" ", span_start + target // 2, span_start + target)
                cut = cut if cut > span_start else span_start + target
                emit(page, text, span_start, cut, span_path)
                span_start = max(span_start + 1, cut - overlap)
                while span_start < cut and not text[span_start - 1].isspace():
                    span_start += 1  # start overlap on a word boundary
        if span_start is not None and span_start < len(text):
            emit(page, text, span_start, len(text), span_path)
    return chunks
