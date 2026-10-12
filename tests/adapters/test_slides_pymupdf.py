from pathlib import Path

import pymupdf

from dehydrater.adapters.slides_pymupdf import PyMuPDFSlideReader


def test_reads_text_of_each_page(tmp_path: Path) -> None:
    pdf = tmp_path / "slides.pdf"
    with pymupdf.open() as document:
        for text in ("Process Scheduling", "Round Robin"):
            document.new_page().insert_text((72, 72), text)
        document.save(pdf)

    pages = PyMuPDFSlideReader().read(pdf)

    assert pages == ["Process Scheduling", "Round Robin"]
