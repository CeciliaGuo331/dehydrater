from dehydrater.domain.base import DomainModel, Seconds


class AlignedSpan(DomainModel):
    page: int | None
    """None 表示未匹配到任何页（课外拓展、闲聊）。"""
    start: Seconds
    end: Seconds


class Alignment(DomainModel):
    spans: list[AlignedSpan]
    """按时间排序、首尾相接、覆盖整节课。"""


class Cited(DomainModel):
    """一条带出处的内容，可以跳回视频核对。"""

    text: str
    at: Seconds


class SectionNote(DomainModel):
    pages: list[int]
    heading: str
    key_points: list[Cited]
    """课件上有、老师讲到了的内容。"""
    elaborations: list[Cited]
    """老师口头补充、课件上没有的内容。"""
    exam_hints: list[Cited]
    """"这个要考"、反复强调的内容。"""


class LectureNotes(DomainModel):
    sections: list[SectionNote]
