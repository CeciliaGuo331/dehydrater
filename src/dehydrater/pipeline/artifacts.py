"""阶段之间传递的产物。每个产物是一个领域模型，以 JSON 形式落盘。"""

from dataclasses import dataclass
from typing import Generic, TypeVar

from dehydrater.domain.base import DomainModel
from dehydrater.domain.lecture import AudioFile, Lecture
from dehydrater.domain.notes import LectureNotes, Outline
from dehydrater.domain.slides import Deck
from dehydrater.domain.transcript import Transcript

# 显式声明协变，使 ArtifactKey[Transcript] 可以当作 ArtifactKey[DomainModel] 使用。
# 不能用 PEP 695 语法自动推断：dataclass 生成的 __replace__ 会让推断结果变成不变。
M_co = TypeVar("M_co", bound=DomainModel, covariant=True)


@dataclass(frozen=True)
class ArtifactKey(Generic[M_co]):  # noqa: UP046
    name: str
    model: type[M_co]


LECTURE = ArtifactKey("lecture", Lecture)
AUDIO = ArtifactKey("audio", AudioFile)
DECK = ArtifactKey("deck", Deck)
RAW_TRANSCRIPT = ArtifactKey("raw_transcript", Transcript)
DEHYDRATED_TRANSCRIPT = ArtifactKey("dehydrated_transcript", Transcript)
"""脱水后的逐字稿：每个分句是一个自然段，时间取自它所合并的原始分句。"""
OUTLINE = ArtifactKey("outline", Outline)
NOTES = ArtifactKey("notes", LectureNotes)
