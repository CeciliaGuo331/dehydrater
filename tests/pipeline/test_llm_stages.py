"""用预设回复的假模型跑脱水与导读阶段，验证编号到时间的换算、校验与缓存。"""

import json
from datetime import date
from pathlib import Path

import pytest

from dehydrater.domain.lecture import Lecture, SourceFile
from dehydrater.domain.notes import Outline, OutlineChapter, ParagraphRange
from dehydrater.domain.slides import Deck, SlidePage
from dehydrater.domain.transcript import Transcript, TranscriptSegment
from dehydrater.pipeline.artifacts import (
    DECK,
    DEHYDRATED_TRANSCRIPT,
    LECTURE,
    NOTES,
    OUTLINE,
    RAW_TRANSCRIPT,
)
from dehydrater.pipeline.runner import Runner
from dehydrater.pipeline.stages.dehydrate import DehydrateStage
from dehydrater.pipeline.stages.outline import OutlineStage
from dehydrater.pipeline.stages.write_notes import WriteNotesStage
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
    lecture = Lecture(title="进程调度", date=date(2026, 9, 30), recording=recording, slides=None)
    store.write(LECTURE, lecture)
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


_DECK = Deck(pages=[SlidePage(index=1, text="FCFS"), SlidePage(index=2, text="SJF")])
_OPENING: dict[str, object] = {
    "title": "开场",
    "first_page": None,
    "last_page": None,
    "paragraphs": [{"first": 0, "last": 0}],
}
_FCFS: dict[str, object] = {
    "title": "FCFS",
    "first_page": 1,
    "last_page": 2,
    "paragraphs": [{"first": 1, "last": 2}],
}


def _outline_reply(*chapters: dict[str, object]) -> str:
    reply = {
        "overview": "讲进程调度。",
        "chapters": chapters,
        "key_terms": [{"term": "FCFS", "explanation": "先来先服务"}],
        "notices": [{"text": "下周交作业", "paragraph": 1}],
    }
    return json.dumps(reply, ensure_ascii=False)


@pytest.fixture
def notes_workspace(workspace: Workspace) -> Workspace:
    store = ArtifactStore(workspace)
    store.write(DECK, _DECK)
    store.write(DEHYDRATED_TRANSCRIPT, _RAW)
    return workspace


async def test_outline_maps_pages_and_paragraphs(notes_workspace: Workspace) -> None:
    chat = ScriptedChat(_outline_reply(_OPENING, _FCFS))
    stage = OutlineStage(chat, TemplateSet("prompts"))

    await Runner([stage], notes_workspace, sources=_NOTES_SOURCES).run()

    outline = ArtifactStore(notes_workspace).read(OUTLINE)
    assert [c.pages for c in outline.chapters] == [None, (1, 2)]
    assert outline.notices[0].at == 2.0
    assert "=== 第 2 页 ===" in chat.calls[0][1].content


async def test_outline_rejects_unassigned_paragraphs(notes_workspace: Workspace) -> None:
    chat = ScriptedChat(_outline_reply(_OPENING), _outline_reply(_OPENING, _FCFS))

    await Runner(
        [OutlineStage(chat, TemplateSet("prompts"))], notes_workspace, sources=_NOTES_SOURCES
    ).run()

    assert "[1, 2]" in chat.calls[1][-1].content


async def test_outline_rejects_chapter_without_lecture(notes_workspace: Workspace) -> None:
    untaught: dict[str, object] = {**_FCFS, "title": "未讲", "paragraphs": []}
    chat = ScriptedChat(_outline_reply(_OPENING, _FCFS, untaught), _outline_reply(_OPENING, _FCFS))

    await Runner(
        [OutlineStage(chat, TemplateSet("prompts"))], notes_workspace, sources=_NOTES_SOURCES
    ).run()

    assert "没讲到的课件页不要建章" in chat.calls[1][-1].content


async def test_notes_replace_citations_with_timestamps(notes_workspace: Workspace) -> None:
    store = ArtifactStore(notes_workspace)
    store.write(OUTLINE, _outline())
    chat = ScriptedChat("开场白[@0]", "FCFS 按到达顺序调度[@2][@1][@2]。")
    stage = WriteNotesStage(chat, TemplateSet("prompts"))

    await Runner([stage], notes_workspace, sources=[*_NOTES_SOURCES, OUTLINE]).run()

    notes = store.read(NOTES)
    assert [c.body for c in notes.chapters] == [
        "开场白`▶ 00:00`",
        "FCFS 按到达顺序调度`▶ 00:02 · 00:05`。",
    ]
    assert notes.chapters[1].start == 2.0
    assert chat.json_modes == [False, False]


async def test_notes_reject_top_level_headings(notes_workspace: Workspace) -> None:
    ArtifactStore(notes_workspace).write(OUTLINE, _outline())
    chat = ScriptedChat("## 开场", "开场白", "正文")

    await Runner(
        [WriteNotesStage(chat, TemplateSet("prompts"))],
        notes_workspace,
        sources=[*_NOTES_SOURCES, OUTLINE],
    ).run()

    assert "###" in chat.calls[1][-1].content


def _outline() -> Outline:
    return Outline(
        overview="",
        chapters=[
            OutlineChapter(title="开场", pages=None, paragraphs=[ParagraphRange(first=0, last=0)]),
            OutlineChapter(
                title="FCFS", pages=(1, 2), paragraphs=[ParagraphRange(first=1, last=2)]
            ),
        ],
        key_terms=[],
        notices=[],
    )


_NOTES_SOURCES = [LECTURE, DECK, DEHYDRATED_TRANSCRIPT]
_SOURCES = [LECTURE, RAW_TRANSCRIPT]
