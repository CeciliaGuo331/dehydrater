import asyncio
import base64
import json
import logging
import socket
import time
import uuid
from pathlib import Path

import httpx
from pydantic import BaseModel

from dehydrater.domain.transcript import Transcript, TranscriptSegment
from dehydrater.ports import Fingerprint, TranscriptionHints

logger = logging.getLogger(__name__)

_STATUS_OK = "20000000"
_STATUS_PROCESSING = "20000001"
_STATUS_QUEUED = "20000002"
_STATUS_SILENT = "20000003"
_STATUS_INVALID_KEY = "45000010"
_SUPPORTED_FORMATS = frozenset({"mp3", "wav", "ogg"})
_SUBMIT_ATTEMPTS = 3
_QUERY_ATTEMPTS = 5
# 两小时的课 base64 后约 40MB：上行慢时上传要好几分钟，上传完后服务端也要较长时间才响应提交请求
_TIMEOUT = httpx.Timeout(connect=10, write=900, read=900, pool=10)


class AsrNetworkError(Exception):
    pass


def _network_error(phase: str, error: httpx.TransportError, attempts: int) -> AsrNetworkError:
    detail = f"：{error}" if str(error) else ""
    return AsrNetworkError(
        f"{phase}时网络连接出错（{type(error).__name__}{detail}），已尝试 {attempts} 次。"
        "请检查网络后重试"
    )


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
    """豆包语音「大模型录音文件识别」标准版：提交任务后轮询结果。

    接口文档：docs/豆包语音_录音文件识别标准版HTTP_*.pdf。文档中只列出 audio.url，
    但实测 audio.data 内联 base64 同样可用，因此无需对象存储。
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        resource_id: str,
        poll_interval: float = 2.0,
        poll_timeout: float = 3600.0,
        retry_delay: float = 5.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._resource_id = resource_id
        self._poll_interval = poll_interval
        self._poll_timeout = poll_timeout
        self._retry_delay = retry_delay
        self._transport = transport

    def fingerprint(self) -> Fingerprint:
        return {
            "service": "volcengine-asr",
            "url": self._base_url,
            "resource_id": self._resource_id,
        }

    async def verify(self) -> None:
        """查询一个不存在的任务：Key 无效时服务端会明确拒绝，有效时只报"任务不存在"。"""
        async with self._client() as client:
            response = await client.post(
                f"{self._base_url}/query",
                headers=self._headers(str(uuid.uuid4()), with_sequence=False),
                json={},
            )
        if _status(response) == _STATUS_INVALID_KEY or not _status(response):
            _raise_unless(response, set())

    async def transcribe(self, audio: Path, hints: TranscriptionHints) -> Transcript:
        payload = _payload(audio, hints)
        logger.info(
            "语音识别：%s，资源 %s，地址 %s，热词 %d 个",
            audio.name,
            self._resource_id,
            self._base_url,
            len(hints.hotwords),
        )
        async with self._client() as client:
            request_id = await self._submit(client, payload)
            transcript = _to_transcript(await self._poll(client, request_id))
        logger.info("语音识别完成：%d 句", len(transcript.segments))
        return transcript

    async def _submit(self, client: httpx.AsyncClient, payload: dict[str, object]) -> str:
        """上传录音并提交任务，返回任务 ID。网络中断时换一个任务 ID 重新提交。"""
        body_size = len(json.dumps(payload))
        for attempt in range(1, _SUBMIT_ATTEMPTS + 1):
            request_id = str(uuid.uuid4())
            logger.info(
                "提交任务 %s（第 %d 次），请求体 %.1f MB", request_id, attempt, body_size / 1e6
            )
            started = time.monotonic()
            try:
                submitted = await client.post(
                    f"{self._base_url}/submit",
                    headers=self._headers(request_id, with_sequence=True),
                    json=payload,
                )
            except httpx.TransportError as error:
                logger.warning(
                    "提交任务 %s 失败，耗时 %.0f 秒：%r",
                    request_id,
                    time.monotonic() - started,
                    error,
                    exc_info=True,
                )
                if attempt == _SUBMIT_ATTEMPTS:
                    raise _network_error("上传录音", error, attempt) from error
                await asyncio.sleep(self._retry_delay * attempt)
                continue
            logger.info(
                "提交任务 %s 返回，耗时 %.0f 秒：%s",
                request_id,
                time.monotonic() - started,
                _describe_response(submitted),
            )
            _raise_unless(submitted, {_STATUS_OK})
            return request_id
        raise AssertionError("unreachable")

    async def _poll(self, client: httpx.AsyncClient, request_id: str) -> httpx.Response:
        started = time.monotonic()
        deadline = started + self._poll_timeout
        failures = 0
        last_status = ""
        while time.monotonic() < deadline:
            await asyncio.sleep(self._poll_interval)
            try:
                queried = await client.post(
                    f"{self._base_url}/query",
                    headers=self._headers(request_id, with_sequence=False),
                    json={},
                )
            except httpx.TransportError as error:
                # 任务已在服务端运行，查询失败只需稍后再查
                failures += 1
                logger.warning(
                    "查询任务 %s 失败（连续第 %d 次）：%r",
                    request_id,
                    failures,
                    error,
                    exc_info=True,
                )
                if failures == _QUERY_ATTEMPTS:
                    raise _network_error("查询识别结果", error, failures) from error
                continue
            failures = 0
            if _status(queried) != last_status:
                last_status = _status(queried)
                logger.info(
                    "任务 %s 状态（已等待 %.0f 秒）：%s",
                    request_id,
                    time.monotonic() - started,
                    _describe_response(queried),
                )
            if last_status not in {_STATUS_PROCESSING, _STATUS_QUEUED}:
                return queried
        raise TimeoutError(f"火山 ASR 任务 {request_id} 在 {self._poll_timeout:.0f} 秒内未完成")

    def _client(self) -> httpx.AsyncClient:
        transport = self._transport or httpx.AsyncHTTPTransport(socket_options=_keepalive())
        return httpx.AsyncClient(timeout=_TIMEOUT, transport=transport)

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


def _keepalive() -> list[tuple[int, int, int]]:
    """开启 TCP keepalive。

    录音上传完后，服务端要过一两分钟才响应提交请求，期间连接上没有任何数据，
    可能被路由器或 NAT 当作空闲连接断开（表现为 ReadError）。keepalive 定期发送探测包，
    让连接保持活跃。各系统支持的参数不同，缺少的就跳过。
    """
    options = [(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)]
    for name, value in (("TCP_KEEPIDLE", 20), ("TCP_KEEPALIVE", 20), ("TCP_KEEPINTVL", 10)):
        if hasattr(socket, name):
            options.append((socket.IPPROTO_TCP, getattr(socket, name), value))
    return options


def _describe_response(response: httpx.Response) -> str:
    headers = response.headers
    return (
        f"HTTP {response.status_code} · {headers.get('X-Api-Status-Code', '-')} "
        f"{headers.get('X-Api-Message', '')} · logid {headers.get('X-Tt-Logid', '-')} "
        f"· 响应体 {len(response.content)} 字节"
    )


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
