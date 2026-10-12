from dehydrater.domain.base import DomainModel, Seconds


class ParagraphRange(DomainModel):
    """脱水逐字稿中连续的一段，first 和 last 都包含在内。"""

    first: int
    last: int


class OutlineChapter(DomainModel):
    title: str
    pages: tuple[int, int] | None
    """对应的课件页码范围（含两端）；None 表示课件之外的课堂内容。"""
    paragraphs: list[ParagraphRange]
    """对应的讲课段落。老师可能回翻、跳讲，所以允许多个不连续的范围。"""


class Term(DomainModel):
    term: str
    explanation: str


class Notice(DomainModel):
    """课堂上的通知：签到、考试、作业 DDL、调课等。"""

    text: str
    at: Seconds


class Outline(DomainModel):
    """笔记的骨架：把课件和讲课内容分成章，并给出全局信息。"""

    overview: str
    chapters: list[OutlineChapter]
    key_terms: list[Term]
    notices: list[Notice]


class NoteChapter(DomainModel):
    title: str
    slides: str | None
    """对应课件位置的描述，例如"调度.pdf 第 3–5 页"；课件之外的内容为 None。"""
    start: Seconds | None
    """该章讲解开始的时间；没有对应讲课内容时为 None。"""
    body: str
    """Markdown 正文，引用的讲课内容已替换为时间戳。"""


class LectureNotes(DomainModel):
    """以课件为主线、融入课堂讲解的完整笔记。"""

    overview: str
    chapters: list[NoteChapter]
    key_terms: list[Term]
    notices: list[Notice]
