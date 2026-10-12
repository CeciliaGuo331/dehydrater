from dehydrater.domain.base import DomainModel


class SlidePage(DomainModel):
    index: int
    """从 1 开始，等于 PDF 页码。"""
    text: str


class Deck(DomainModel):
    """一份课件。没有课件时为空 Deck，下游阶段据此退化为只按讲课内容组织。"""

    pages: list[SlidePage]

    @classmethod
    def empty(cls) -> "Deck":
        return cls(pages=[])
