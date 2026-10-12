from functools import cached_property
from pathlib import Path

from openai import AsyncOpenAI

from dehydrater.domain.transcript import Transcript, TranscriptSegment
from dehydrater.ports import Fingerprint, TranscriptionHints

# Whisper 的 prompt 上限约 224 token，热词只取前面一部分
_MAX_PROMPT_CHARS = 400


class OpenAICompatibleTranscriber:
    """兼容 OpenAI /audio/transcriptions 接口的 ASR，例如 Groq 的 whisper-large-v3。"""

    def __init__(self, *, base_url: str, api_key: str, model: str) -> None:
        self._base_url = base_url
        self._api_key = api_key
        self._model = model

    @cached_property
    def _client(self) -> AsyncOpenAI:
        # 首次调用时才创建：SDK 在密钥为空时会直接报错，而 status 等命令不需要密钥
        return AsyncOpenAI(base_url=self._base_url, api_key=self._api_key)

    def fingerprint(self) -> Fingerprint:
        return {"base_url": self._base_url, "model": self._model}

    async def transcribe(self, audio: Path, hints: TranscriptionHints) -> Transcript:
        prompt = "、".join(hints.hotwords)[:_MAX_PROMPT_CHARS]
        with audio.open("rb") as file:
            response = await self._client.audio.transcriptions.create(
                model=self._model,
                file=file,
                response_format="verbose_json",
                prompt=prompt,
            )
        return Transcript(
            segments=[
                TranscriptSegment(start=segment.start, end=segment.end, text=segment.text.strip())
                for segment in response.segments or []
            ]
        )
