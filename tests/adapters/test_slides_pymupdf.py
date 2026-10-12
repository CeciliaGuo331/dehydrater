from pathlib import Path

import pymupdf

from dehydrater.adapters.slides_pymupdf import PyMuPDFSlideReader


def test_reads_text_and_renders_each_page(tmp_path: Path) -> None:
    pdf = tmp_path / "slides.pdf"
    with pymupdf.open() as document:
        for text in ("Process Scheduling", "Round Robin"):
            document.new_page().insert_text((72, 72), text)
        document.save(pdf)

    pages = PyMuPDFSlideReader(dpi=30).read(pdf, tmp_path / "images")

    assert [page.index for page in pages] == [1, 2]
    assert [page.text for page in pages] == ["Process Scheduling", "Round Robin"]
    assert all(page.image.is_file() for page in pages)
