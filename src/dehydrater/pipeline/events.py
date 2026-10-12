"""流水线向外报告的事件。CLI 和将来的 UI 各自决定如何展示。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class StageStarted:
    stage: str


@dataclass(frozen=True)
class StageSkipped:
    """缓存命中。"""

    stage: str


@dataclass(frozen=True)
class StageProgress:
    stage: str
    done: int
    total: int


@dataclass(frozen=True)
class StageFinished:
    stage: str
    elapsed_seconds: float


@dataclass(frozen=True)
class StageFailed:
    stage: str
    error: BaseException


type PipelineEvent = StageStarted | StageSkipped | StageProgress | StageFinished | StageFailed
