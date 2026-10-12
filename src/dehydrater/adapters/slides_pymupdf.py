from pathlib import Path

import pymupdf

from dehydrater.domain.slides import SlidePage
from dehydrater.ports import Fingerprint


class PyMuPDFSlideReader:
    def fingerprint(self) -> Fingerprint:
        return {"reader": "pymupdf"}

    def read(self, pdf: Path) -> list[SlidePage]:
        with pymupdf.open(pdf) as document:
            return [
                SlidePage(index=number, text=str(document.load_page(number - 1).get_text()).strip())
                for number in range(1, document.page_count + 1)
            ]
