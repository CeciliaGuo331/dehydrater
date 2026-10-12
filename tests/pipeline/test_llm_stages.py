"""用预设回复的假模型跑脱水与导读阶段，验证编号到时间的换算、校验与缓存。"""

import json
from datetime import date
from pathlib import Path

import pytest

from dehydrater.domain.lecture import Lecture, SourceFile
from dehydrater.domain.transcript import Transcript, TranscriptSegment
from dehydrater.pipeline.artifacts import DEHYDRATED_TRANSCRIPT, GUIDE, LECTURE, RAW_TRANSCRIPT
from dehydrater.pipeline.runner import Runner
from dehydrater.pipeline.stages.dehydrate import DehydrateStage
from dehydrater.pipeline.stages.write_guide import WriteGuideStage
from dehydrater.pipeline.templating import TemplateSet
from dehydrater.pipeline.workspace import ArtifactStore, Workspace

from ..fakes import ScriptedChat

_RAW = Transcript(
    segments=[
        TranscriptSegment(start=0.0, end=2.0, text="嗯，大家好。"),
        TranscriptSegment(start=2.0, end=5.0, text="今天讲进程调度。"),
        TranscriptSegment(start=5.0, end=9.0, text="那个，先讲 FCFS。"),
    ]
)
_DEHYDRATE_REPLY = json.dumps(
    {"paragraphs": [{"first": 1, "last": 2, "text": "今天讲进程调度，先讲 FCFS。"}]},
    ensure_ascii=False,
)


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    workspace = Workspace(tmp_path)
    store = ArtifactStore(workspace)
    recording = SourceFile(path=Path("r.mp3"), size=1, mtime_ns=1)
    store.write(LECTURE, Lecture(title="进程调度", date=date(2026, 9, 30), recording=recording))
    store.write(RAW_TRANSCRIPT, _RAW)
    return workspace


async def test_dehydrate_takes_timestamps_from_source_segments(workspace: Workspace) -> None:
    chat = ScriptedChat(_DEHYDRATE_REPLY)

    await Runner([DehydrateStage(chat, TemplateSet("prompts"))], workspace, sources=_SOURCES).run()

    result = ArtifactStore(workspace).read(DEHYDRATED_TRANSCRIPT)
    assert result.segments == [
        TranscriptSegment(start=2.0, end=9.0, text="今天讲进程调度，先讲 FCFS。")
    ]
    assert "[2] 那个，先讲 FCFS。" in chat.calls[0][1].content


async def test_dehydrate_rejects_out_of_range_reference(workspace: Workspace) -> None:
    bad = json.dumps({"paragraphs": [{"first": 0, "last": 9, "text": "x"}]})
    chat = ScriptedChat(bad, _DEHYDRATE_REPLY)

    await Runner([DehydrateStage(chat, TemplateSet("prompts"))], workspace, sources=_SOURCES).run()

    assert len(chat.calls) == 2
    assert "无效" in chat.calls[1][-1].content


async def test_dehydrate_reuses_chunk_results_when_forced(workspace: Workspace) -> None:
    chat = ScriptedChat(_DEHYDRATE_REPLY)
    runner = Runner([DehydrateStage(chat, TemplateSet("prompts"))], workspace, sources=_SOURCES)
    await runner.run()

    await runner.run(force_from="dehydrate")

    assert len(chat.calls) == 1


async def test_guide_converts_paragraph_numbers_to_times(workspace: Workspace) -> None:
    store = ArtifactStore(workspace)
    store.write(DEHYDRATED_TRANSCRIPT, _RAW)
    reply: dict[str, object] = {
        "overview": "讲进程调度。",
        "sections": [{"title": "FCFS", "paragraph": 2, "summary": "先来先服务", "key_points": []}],
        "key_terms": [{"term": "FCFS", "explanation": "先来先服务"}],
        "notices": [{"text": "下周交作业", "paragraph": 1}],
    }
    chat = ScriptedChat(json.dumps(reply, ensure_ascii=False))
    stage = WriteGuideStage(chat, TemplateSet("prompts"))

    await Runner([stage], workspace, sources=[LECTURE, DEHYDRATED_TRANSCRIPT]).run()

    guide = store.read(GUIDE)
    assert guide.sections[0].start == 5.0
    assert guide.notices[0].at == 2.0


_SOURCES = [LECTURE, RAW_TRANSCRIPT]
