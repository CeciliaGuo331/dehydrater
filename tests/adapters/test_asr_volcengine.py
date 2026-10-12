import base64
import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from dehydrater.adapters.asr_volcengine import (
    AsrNetworkError,
    VolcengineAsrError,
    VolcengineTranscriber,
)
from dehydrater.domain.transcript import TranscriptSegment
from dehydrater.ports import TranscriptionHints

_OK_BODY = {
    "audio_info": {"duration": 3696},
    "result": {
        "text": "这是 TLB，今日头条母公司。",
        "utterances": [
            {"start_time": 0, "end_time": 1705, "text": "这是 TLB，", "words": []},
            {"start_time": 2110, "end_time": 3696, "text": "今日头条母公司。", "words": []},
        ],
    },
}
_EXPECTED = [
    TranscriptSegment(start=0.0, end=1.705, text="这是 TLB，"),
    TranscriptSegment(start=2.11, end=3.696, text="今日头条母公司。"),
]

type Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture
def audio(tmp_path: Path) -> Path:
    path = tmp_path / "audio.mp3"
    path.write_bytes(b"fake mp3")
    return path


def _transcriber(handler: Handler) -> VolcengineTranscriber:
    return VolcengineTranscriber(
        base_url="https://asr.example.com/api/v3/auc/bigmodel/",
        api_key="secret",
        resource_id="volc.seedasr.auc",
        poll_interval=0,
        retry_delay=0,
        transport=httpx.MockTransport(handler),
    )


def _respond(status: str, body: object = None, message: str = "OK") -> httpx.Response:
    headers = {"X-Api-Status-Code": status, "X-Api-Message": message, "X-Tt-Logid": "log-1"}
    return httpx.Response(200, headers=headers, json=body or {})


class _StandardServer:
    """模拟标准版：提交成功后，查询先返回"处理中"，再返回结果。"""

    def __init__(self, *, final: httpx.Response) -> None:
        self.requests: list[httpx.Request] = []
        self._pending = [_respond("20000001", message="processing"), final]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path.endswith("/submit"):
            return _respond("20000000")
        return self._pending.pop(0)


async def test_standard_submits_inline_audio_then_polls(audio: Path) -> None:
    server = _StandardServer(final=_respond("20000000", _OK_BODY))

    transcript = await _transcriber(server).transcribe(audio, TranscriptionHints(hotwords=["TLB"]))

    assert transcript.segments == _EXPECTED
    submit, *queries = server.requests
    assert [q.url.path for q in queries] == ["/api/v3/auc/bigmodel/query"] * 2
    assert {q.headers["X-Api-Request-Id"] for q in queries} == {submit.headers["X-Api-Request-Id"]}
    body = json.loads(submit.content)
    assert body["audio"] == {"format": "mp3", "data": base64.b64encode(b"fake mp3").decode()}
    assert json.loads(body["request"]["corpus"]["context"]) == {"hotwords": [{"word": "TLB"}]}


async def test_standard_raises_when_submit_is_rejected(audio: Path) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return _respond("45000030", message="requested resource not granted")

    with pytest.raises(VolcengineAsrError, match=r"45000030.*not granted.*log-1"):
        await _transcriber(handler).transcribe(audio, TranscriptionHints())


async def test_verify_accepts_valid_key_and_rejects_invalid_one() -> None:
    def server(key_ok: bool) -> Handler:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/v3/auc/bigmodel/query"
            if key_ok:
                return _respond("45000092", message="The task was not found")
            return httpx.Response(401, headers={"X-Api-Status-Code": "45000010"})

        return handler

    await _transcriber(server(key_ok=True)).verify()
    with pytest.raises(VolcengineAsrError, match="45000010"):
        await _transcriber(server(key_ok=False)).verify()


async def test_silent_audio_gives_empty_transcript(audio: Path) -> None:
    server = _StandardServer(final=_respond("20000003", message="silent"))

    transcript = await _transcriber(server).transcribe(audio, TranscriptionHints())

    assert transcript.segments == []


async def test_submit_is_retried_after_network_error(audio: Path) -> None:
    server = _StandardServer(final=_respond("20000000", _OK_BODY))
    failures = [httpx.ReadError("connection reset")]

    def flaky(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/submit") and failures:
            raise failures.pop()
        return server(request)

    transcript = await _transcriber(flaky).transcribe(audio, TranscriptionHints())

    assert transcript.segments == _EXPECTED


async def test_persistent_network_error_names_the_phase(audio: Path) -> None:
    def broken(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadError("")

    with pytest.raises(AsrNetworkError, match=r"上传录音时网络连接出错（ReadError）.*3 次"):
        await _transcriber(broken).transcribe(audio, TranscriptionHints())
