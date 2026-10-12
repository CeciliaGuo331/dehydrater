from dehydrater.domain.base import DomainModel, Seconds


class GuideSection(DomainModel):
    """导读中的一个章节：一段连续讲解的主题。"""

    title: str
    start: Seconds
    summary: str
    key_points: list[str]


class GuideTerm(DomainModel):
    term: str
    explanation: str


class GuideNotice(DomainModel):
    """课堂上的通知：签到、考试、作业 DDL、调课等。"""

    text: str
    at: Seconds


class Guide(DomainModel):
    """脱水逐字稿的导读：先读它，再决定细看哪一段。"""

    overview: str
    sections: list[GuideSection]
    key_terms: list[GuideTerm]
    notices: list[GuideNotice]
