from pathlib import Path

from dehydrater.domain.base import DomainModel


class SlidePage(DomainModel):
    index: int
    """从 1 开始，等于 PDF 页码。"""
    text: str
    image: Path
    """页面渲染图，相对于工作区根目录的路径。"""


class Deck(DomainModel):
    """一份课件。没有课件时为空 Deck，下游阶段据此退化处理。"""

    pages: list[SlidePage]
    glossary: list[str]
    """从课件中抽取的术语，用作 ASR 热词和 LLM 纠错依据。"""

    @classmethod
    def empty(cls) -> "Deck":
        return cls(pages=[], glossary=[])
