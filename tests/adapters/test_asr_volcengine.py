import base64
import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from dehydrater.adapters.asr_volcengine import (
    VolcengineApi,
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


def _transcriber(api: VolcengineApi, handler: Handler) -> VolcengineTranscriber:
    return VolcengineTranscriber(
        api_key="secret",
        resource_id="volc.seedasr.auc",
        api=api,
        poll_interval=0,
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

    transcript = await _transcriber(VolcengineApi.STANDARD, server).transcribe(
        audio, TranscriptionHints(hotwords=["TLB"])
    )

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
        await _transcriber(VolcengineApi.STANDARD, handler).transcribe(audio, TranscriptionHints())


async def test_flash_returns_in_one_request(audio: Path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _respond("20000000", _OK_BODY)

    transcript = await _transcriber(VolcengineApi.FLASH, handler).transcribe(
        audio, TranscriptionHints()
    )

    assert transcript.segments == _EXPECTED
    assert [r.url.path for r in requests] == ["/api/v3/auc/bigmodel/recognize/flash"]
    assert "corpus" not in json.loads(requests[0].content)["request"]


async def test_silent_audio_gives_empty_transcript(audio: Path) -> None:
    server = _StandardServer(final=_respond("20000003", message="silent"))

    transcript = await _transcriber(VolcengineApi.STANDARD, server).transcribe(
        audio, TranscriptionHints()
    )

    assert transcript.segments == []
