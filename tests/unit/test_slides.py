from dehydrater.domain.slides import Deck, SlidePage


def _deck(*sources: tuple[str, int]) -> Deck:
    pages: list[SlidePage] = []
    for source, count in sources:
        pages += [
            SlidePage(number=len(pages) + page, source=source, page=page, text="")
            for page in range(1, count + 1)
        ]
    return Deck(pages=pages)


def test_single_file_omits_file_name() -> None:
    deck = _deck(("调度.pdf", 10))
    assert deck.describe(3, 5) == "第 3–5 页"
    assert deck.describe(4, 4) == "第 4 页"


def test_multiple_files_use_page_numbers_within_each_file() -> None:
    deck = _deck(("调度.pdf", 10), ("线程.pdf", 8))
    assert deck.describe(12, 14) == "线程.pdf 第 2–4 页"
    assert deck.describe(9, 12) == "调度.pdf 第 9 页 – 线程.pdf 第 2 页"
