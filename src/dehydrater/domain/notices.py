from datetime import date, datetime
from enum import StrEnum

from dehydrater.domain.base import DomainModel, Seconds


class NoticeKind(StrEnum):
    ATTENDANCE = "attendance"
    """签到、点名。"""
    EXAM = "exam"
    """考试时间、范围、形式。"""
    ASSIGNMENT = "assignment"
    """作业、实验、DDL。"""
    SCHEDULE = "schedule"
    """调课、停课、换教室。"""
    GRADING = "grading"
    """成绩构成。"""
    OTHER = "other"


class Notice(DomainModel):
    kind: NoticeKind
    summary: str
    quote: str
    """原话。ASR 最容易听错数字和日期，必须保留以便核对。"""
    at: Seconds
    due: date | datetime | None
    """根据上课日期换算后的绝对时间。"""
    due_phrase: str | None
    """原话中的时间表达，例如"下周三上课前"。"""


class NoticeBoard(DomainModel):
    notices: list[Notice]
