from pathlib import Path

import pymupdf

from dehydrater.domain.slides import SlidePage
from dehydrater.ports import Fingerprint


class PyMuPDFSlideReader:
    def __init__(self, dpi: int = 110) -> None:
        self._dpi = dpi

    def fingerprint(self) -> Fingerprint:
        return {"reader": "pymupdf", "dpi": self._dpi}

    def read(self, pdf: Path, image_dir: Path) -> list[SlidePage]:
        image_dir.mkdir(parents=True, exist_ok=True)
        pages: list[SlidePage] = []
        with pymupdf.open(pdf) as document:
            for number in range(1, document.page_count + 1):
                page = document.load_page(number - 1)
                image = image_dir / f"page-{number:03d}.png"
                page.get_pixmap(dpi=self._dpi).save(image)
                text = str(page.get_text("text")).strip()
                pages.append(SlidePage(index=number, text=text, image=image))
        return pages
