from datetime import date
from pathlib import Path

from dehydrater.domain.base import DomainModel, Seconds


class SourceFile(DomainModel):
    """用户提供的原始文件。大小和修改时间参与缓存键，替换文件后会自动重跑。"""

    path: Path
    """相对于工作区根目录的路径。"""
    size: int
    mtime_ns: int


class Lecture(DomainModel):
    """一节课的输入清单。"""

    title: str
    date: date
    """上课日期，用于把"下周三"之类的相对日期换算成绝对日期。"""
    recording: SourceFile
    """课堂录像或录音，任何带音轨的音视频文件均可。"""
    slides: SourceFile | None
    """PDF 课件，可选。"""


class AudioFile(DomainModel):
    """从录像或录音中抽出、统一格式后的音频。"""

    path: Path
    """相对于工作区根目录的路径。"""
    sha256: str
    duration: Seconds
