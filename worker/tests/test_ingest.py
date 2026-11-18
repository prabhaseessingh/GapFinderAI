import io

import pytest
from docx import Document as DocxDocument
from tasks import extraction
from tasks.extraction import (
    DOCX_MIME,
    Block,
    ExtractedPage,
    ExtractionError,
    chunk_pages,
    detect_source_language,
    extract,
    ocr_command,
    verify_signature,
)


def _pdf(pages: list[list[tuple[str, float]]]) -> bytes:
    fitz = pytest.importorskip("fitz")
    pdf = fitz.open()
    for lines in pages:
        page = pdf.new_page()
        y = 72
        for text, size in lines:
            page.insert_text((72, y), text, fontsize=size)
            y += size * 2
    return pdf.tobytes()


def _assert_exact_slices(pages: list[ExtractedPage]) -> None:
    by_page = {page.page: page.text for page in pages}
    for chunk in chunk_pages(pages):
        assert by_page[chunk.page][chunk.char_start : chunk.char_end] == chunk.text


def test_txt_extraction_detects_headings_and_preserves_text() -> None:
    pages = extract(
        "text/plain",
        b"# Unit 1 Cells\nCells are units of life.\nUNIT TWO\nGenes carry traits.",
    )
    assert pages[0].blocks == [
        Block("Unit 1 Cells", 1),
        Block("Cells are units of life."),
        Block("UNIT TWO", 1),
        Block("Genes carry traits."),
    ]
    chunks = chunk_pages(pages)
    assert [c.heading_path for c in chunks] == [("Unit 1 Cells",), ("UNIT TWO",)]
    _assert_exact_slices(pages)


def test_docx_extraction_keeps_heading_styles_and_tables() -> None:
    document = DocxDocument()
    document.add_heading("Chapter 1", level=1)
    document.add_paragraph("Photosynthesis uses light.")
    document.add_heading("Section 1.1", level=2)
    table = document.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text, table.rows[0].cells[1].text = "Input", "Light"
    stream = io.BytesIO()
    document.save(stream)
    pages = extract(DOCX_MIME, stream.getvalue())
    assert (
        Block("Chapter 1", 1) in pages[0].blocks
        and Block("Section 1.1", 2) in pages[0].blocks
    )
    assert Block("Input | Light") in pages[0].blocks
    assert chunk_pages(pages)[-1].heading_path == ("Chapter 1", "Section 1.1")


def test_text_pdf_keeps_page_numbers_and_font_headings() -> None:
    raw = _pdf(
        [
            [
                ("Cell Biology", 20),
                ("Cells divide by mitosis.", 11),
                ("Body text again here.", 11),
            ],
            [("Genetics", 20), ("DNA stores information.", 11)],
        ]
    )
    pages = extract("application/pdf", raw)
    assert [p.page for p in pages] == [1, 2]
    chunks = chunk_pages(pages)
    assert [(c.page, c.heading_path) for c in chunks] == [
        (1, ("Cell Biology",)),
        (2, ("Genetics",)),
    ]
    _assert_exact_slices(pages)


def test_scanned_pdf_routes_to_local_ocr(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = _pdf([[]])
    expected = [ExtractedPage(1, [Block("OCR evidence")])]
    monkeypatch.setattr(extraction, "extract_scanned_pdf", lambda _raw, _lang: expected)
    assert extract("application/pdf", raw) == expected


@pytest.mark.parametrize(
    ("mime", "raw", "code"),
    [
        ("application/pdf", b"this is not a PDF", "UNSUPPORTED_FILE_SIGNATURE"),
        (DOCX_MIME, b"not a zip", "UNSUPPORTED_FILE_SIGNATURE"),
        ("text/plain", b"\xff\xfeok"[:0] + b"\x80\x81bad", "UNREADABLE_TEXT_ENCODING"),
        ("text/plain", b"", "EMPTY_DOCUMENT"),
    ],
)
def test_bad_files_fail_with_safe_codes(mime: str, raw: bytes, code: str) -> None:
    with pytest.raises(ExtractionError) as error:
        verify_signature(mime, raw)
    assert error.value.code == code


def test_corrupt_pdf_with_valid_header_fails_safely() -> None:
    with pytest.raises(ExtractionError) as error:
        extract("application/pdf", b"%PDF-1.7 garbage")
    assert error.value.code in {"CORRUPT_FILE", "OCR_RUNTIME_UNAVAILABLE", "OCR_FAILED"}


def test_empty_text_produces_no_chunks() -> None:
    assert chunk_pages(extract("text/plain", b"\n\t ")) == []


def test_long_text_splits_with_overlap_on_word_boundaries() -> None:
    words = " ".join(f"word{i}" for i in range(600))
    pages = [ExtractedPage(3, [Block(words)])]
    chunks = chunk_pages(pages)
    assert len(chunks) > 2 and all(len(c.text) <= 1200 for c in chunks)
    assert all(c.page == 3 for c in chunks)
    assert chunks[1].char_start < chunks[0].char_end  # overlap
    assert all(c.text.split()[0].startswith("word") for c in chunks)
    _assert_exact_slices(pages)


def test_repeated_text_yields_distinct_chunk_indexes() -> None:
    pages = [
        ExtractedPage(1, [Block("Header", 1), Block("Same line")]),
        ExtractedPage(2, [Block("Header", 1), Block("Same line")]),
    ]
    chunks = chunk_pages(pages)
    assert len({c.content_hash for c in chunks}) == 1
    assert [c.chunk_index for c in chunks] == [0, 1]


def test_ocr_command_is_local_and_multilingual() -> None:
    command = ocr_command("source.pdf", "output.pdf", "eng+hin+pan+tel")
    assert (
        command[0] == "ocrmypdf"
        and command[command.index("--language") + 1] == "eng+hin+pan+tel"
    )
    assert command[-2:] == ["source.pdf", "output.pdf"]


def test_detect_source_language_uses_majority_script() -> None:
    assert detect_source_language("Sets and functions") == "en"
    assert detect_source_language("समुच्चय और फलन (Sets)") == "hi"
    assert detect_source_language("ਸੈੱਟ") == "pa"
    assert detect_source_language("సమితులు") == "te"
    assert detect_source_language("12345") == "und"
