"""流水线对外部能力的需求。adapters 实现这些接口，pipeline 只依赖这些接口。"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from dehydrater.domain.base import Seconds
from dehydrater.domain.slides import SlidePage
from dehydrater.domain.transcript import Transcript

type Fingerprint = Mapping[str, str | int | float | bool | None]
"""决定输出结果的全部参数（不含密钥）。参与缓存键：参数变了，缓存就失效。"""


@dataclass(frozen=True)
class ExtractedAudio:
    duration: Seconds


class AudioExtractor(Protocol):
    def fingerprint(self) -> Fingerprint: ...

    def extract(self, video: Path, dest: Path) -> ExtractedAudio:
        """把视频的音轨转成适合 ASR 的音频，写入 dest。"""
        ...


class SlideReader(Protocol):
    def fingerprint(self) -> Fingerprint: ...

    def read(self, pdf: Path, image_dir: Path) -> list[SlidePage]:
        """读取课件每页的文本，并把页面渲染图写入 image_dir。

        返回的 SlidePage.image 是 image_dir 下的绝对路径，由调用方负责转成相对路径。
        """
        ...


@dataclass(frozen=True)
class TranscriptionHints:
    hotwords: Sequence[str] = ()


class Transcriber(Protocol):
    def fingerprint(self) -> Fingerprint: ...

    async def transcribe(self, audio: Path, hints: TranscriptionHints) -> Transcript: ...


@dataclass(frozen=True)
class ChatMessage:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True)
class TokenUsage:
    prompt_tokens: int
    completion_tokens: int


@dataclass(frozen=True)
class ChatReply:
    content: str
    usage: TokenUsage


class ChatModel(Protocol):
    def fingerprint(self) -> Fingerprint: ...

    async def complete(self, messages: Sequence[ChatMessage]) -> ChatReply: ...
