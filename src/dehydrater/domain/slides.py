from dehydrater.domain.base import DomainModel


class SlidePage(DomainModel):
    number: int
    """在所有课件中的全局页码，从 1 开始；多份课件按输入顺序依次编号。"""
    source: str
    """所属课件的文件名。"""
    page: int
    """在所属课件中的页码，从 1 开始。"""
    text: str


class Deck(DomainModel):
    """一节课的全部课件。没有课件时为空，下游阶段据此退化为只按讲课内容组织。"""

    pages: list[SlidePage]

    @classmethod
    def empty(cls) -> "Deck":
        return cls(pages=[])

    def describe(self, first: int, last: int) -> str:
        """把全局页码范围写成人能看懂的形式，例如"调度.pdf 第 3–5 页"。"""
        start, end = self.pages[first - 1], self.pages[last - 1]
        single_file = len({page.source for page in self.pages}) == 1
        prefix = "" if single_file else f"{start.source} "
        if start.source != end.source:
            return f"{start.source} 第 {start.page} 页 – {end.source} 第 {end.page} 页"
        if start.page == end.page:
            return f"{prefix}第 {start.page} 页"
        return f"{prefix}第 {start.page}–{end.page} 页"
