from pathlib import Path

import pymupdf

from dehydrater.ports import Fingerprint


class PyMuPDFSlideReader:
    def fingerprint(self) -> Fingerprint:
        return {"reader": "pymupdf"}

    def read(self, pdf: Path) -> list[str]:
        with pymupdf.open(pdf) as document:
            return [
                str(document.load_page(index).get_text()).strip()
                for index in range(document.page_count)
            ]
