import asyncio
import base64
import json
import time
import uuid
from enum import StrEnum
from pathlib import Path

import httpx
from pydantic import BaseModel

from dehydrater.domain.transcript import Transcript, TranscriptSegment
from dehydrater.ports import Fingerprint, TranscriptionHints

_BASE_URL = "https://openspeech.bytedance.com/api/v3/auc/bigmodel"

_STATUS_OK = "20000000"
_STATUS_PROCESSING = "20000001"
_STATUS_QUEUED = "20000002"
_STATUS_SILENT = "20000003"
_SUPPORTED_FORMATS = frozenset({"mp3", "wav", "ogg"})
# 极速版在服务端同步识别一整节课，读超时要留足
_TIMEOUT = httpx.Timeout(connect=10, write=120, read=900, pool=10)


class VolcengineApi(StrEnum):
    STANDARD = "standard"
    """标准版：提交任务后轮询结果。资源 ID 如 volc.seedasr.auc（2.0）、volc.bigasr.auc（1.0）。"""
    FLASH = "flash"
    """极速版：一次请求同步返回。资源 ID 如 volc.bigasr.auc_turbo。"""


class VolcengineAsrError(Exception):
    def __init__(self, status: str, message: str, log_id: str) -> None:
        super().__init__(f"火山 ASR 返回 {status}：{message}（logid={log_id}）")


class _Utterance(BaseModel):
    start_time: int
    """毫秒。"""
    end_time: int
    text: str


class _Result(BaseModel):
    utterances: list[_Utterance] = []


class _Response(BaseModel):
    result: _Result


class VolcengineTranscriber:
    """豆包语音「大模型录音文件识别」，音频以 base64 内联在请求体中。

    接口文档：docs/豆包语音_录音文件识别标准版HTTP_*.pdf。文档中标准版只列出 audio.url，
    但实测 audio.data 同样可用，因此无需对象存储。
    """

    def __init__(
        self,
        *,
        api_key: str,
        resource_id: str,
        api: VolcengineApi = VolcengineApi.STANDARD,
        poll_interval: float = 2.0,
        poll_timeout: float = 3600.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._resource_id = resource_id
        self._api = api
        self._poll_interval = poll_interval
        self._poll_timeout = poll_timeout
        self._transport = transport

    def fingerprint(self) -> Fingerprint:
        return {"service": "volcengine-asr", "api": self._api, "resource_id": self._resource_id}

    async def transcribe(self, audio: Path, hints: TranscriptionHints) -> Transcript:
        payload = _payload(audio, hints)
        async with httpx.AsyncClient(timeout=_TIMEOUT, transport=self._transport) as client:
            match self._api:
                case VolcengineApi.FLASH:
                    response = await self._recognize_flash(client, payload)
                case VolcengineApi.STANDARD:
                    response = await self._recognize_standard(client, payload)
        return _to_transcript(response)

    async def _recognize_flash(
        self, client: httpx.AsyncClient, payload: dict[str, object]
    ) -> httpx.Response:
        headers = self._headers(str(uuid.uuid4()), with_sequence=True)
        return await client.post(f"{_BASE_URL}/recognize/flash", headers=headers, json=payload)

    async def _recognize_standard(
        self, client: httpx.AsyncClient, payload: dict[str, object]
    ) -> httpx.Response:
        request_id = str(uuid.uuid4())
        submitted = await client.post(
            f"{_BASE_URL}/submit",
            headers=self._headers(request_id, with_sequence=True),
            json=payload,
        )
        _raise_unless(submitted, {_STATUS_OK})

        deadline = time.monotonic() + self._poll_timeout
        while time.monotonic() < deadline:
            await asyncio.sleep(self._poll_interval)
            queried = await client.post(
                f"{_BASE_URL}/query",
                headers=self._headers(request_id, with_sequence=False),
                json={},
            )
            if _status(queried) not in {_STATUS_PROCESSING, _STATUS_QUEUED}:
                return queried
        raise TimeoutError(f"火山 ASR 任务 {request_id} 在 {self._poll_timeout:.0f} 秒内未完成")

    def _headers(self, request_id: str, *, with_sequence: bool) -> dict[str, str]:
        headers = {
            "X-Api-Key": self._api_key,
            "X-Api-Resource-Id": self._resource_id,
            "X-Api-Request-Id": request_id,
        }
        if with_sequence:
            headers["X-Api-Sequence"] = "-1"
        return headers


def _payload(audio: Path, hints: TranscriptionHints) -> dict[str, object]:
    audio_format = audio.suffix.removeprefix(".").lower()
    if audio_format not in _SUPPORTED_FORMATS:
        raise ValueError(f"火山 ASR 不支持 {audio_format} 格式")

    request: dict[str, object] = {
        "model_name": "bigmodel",
        "enable_itn": True,
        "enable_punc": True,
        "show_utterances": True,
    }
    if hints.hotwords:
        # 热词以 JSON 字符串形式放在 corpus.context 中
        hotwords = {"hotwords": [{"word": word} for word in hints.hotwords]}
        request["corpus"] = {"context": json.dumps(hotwords, ensure_ascii=False)}

    return {
        "user": {"uid": "dehydrater"},
        "audio": {"format": audio_format, "data": base64.b64encode(audio.read_bytes()).decode()},
        "request": request,
    }


def _status(response: httpx.Response) -> str:
    return response.headers.get("X-Api-Status-Code", "")


def _raise_unless(response: httpx.Response, accepted: set[str]) -> None:
    if _status(response) not in accepted:
        message = response.headers.get("X-Api-Message") or f"HTTP {response.status_code}"
        raise VolcengineAsrError(_status(response), message, response.headers.get("X-Tt-Logid", ""))


def _to_transcript(response: httpx.Response) -> Transcript:
    _raise_unless(response, {_STATUS_OK, _STATUS_SILENT})
    if _status(response) == _STATUS_SILENT:
        return Transcript(segments=[])

    result = _Response.model_validate_json(response.content).result
    return Transcript(
        segments=[
            TranscriptSegment(
                start=utterance.start_time / 1000,
                end=utterance.end_time / 1000,
                text=utterance.text.strip(),
            )
            for utterance in result.utterances
            if utterance.text.strip()
        ]
    )
