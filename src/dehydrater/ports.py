"""流水线对外部能力的需求。adapters 实现这些接口，pipeline 只依赖这些接口。"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

from dehydrater.domain.base import Seconds
from dehydrater.domain.transcript import Transcript

type Fingerprint = Mapping[str, str | int | float | bool | None]
"""决定输出结果的全部参数（不含密钥）。参与缓存键：参数变了，缓存就失效。"""


@dataclass(frozen=True)
class ExtractedAudio:
    duration: Seconds


@dataclass(frozen=True)
class MediaInfo:
    duration: Seconds
    recorded_at: datetime | None
    """文件元数据中的录制时间，很多文件没有。"""


class NotAMediaFileError(Exception):
    """文件不是音视频，或者没有音轨。"""


class AudioExtractor(Protocol):
    def fingerprint(self) -> Fingerprint: ...

    def probe(self, recording: Path) -> MediaInfo:
        """读取时长和录制时间，不解码。不是带音轨的音视频文件时抛出 NotAMediaFileError。"""
        ...

    def extract(self, recording: Path, dest: Path) -> ExtractedAudio:
        """把录像或录音的音轨转成适合 ASR 的音频，写入 dest。"""
        ...


class SlideReader(Protocol):
    def fingerprint(self) -> Fingerprint: ...

    def read(self, pdf: Path) -> list[str]:
        """按页返回课件的文字。"""
        ...


@dataclass(frozen=True)
class TranscriptionHints:
    hotwords: Sequence[str] = ()


class Transcriber(Protocol):
    def fingerprint(self) -> Fingerprint: ...

    async def verify(self) -> None:
        """用最小的请求检查接入地址和 API Key 是否可用，不可用时抛出异常。"""
        ...

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

    async def verify(self) -> None:
        """用最小的请求检查接入地址和 API Key 是否可用，不可用时抛出异常。"""
        ...

    async def complete(self, messages: Sequence[ChatMessage], *, json: bool = False) -> ChatReply:
        """json=True 时要求服务端保证输出是一个合法的 JSON 对象（OpenAI 的 JSON 模式）。"""
        ...
