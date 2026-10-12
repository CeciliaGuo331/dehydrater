from datetime import date
from pathlib import Path

from dehydrater.domain.lecture import Lecture, SourceFile
from dehydrater.domain.notes import LectureNotes, NoteChapter, Notice, Term
from dehydrater.domain.transcript import Transcript, TranscriptSegment
from dehydrater.pipeline.templating import TemplateSet

_LECTURE = Lecture(
    title="进程调度",
    date=date(2026, 9, 30),
    recording=SourceFile(path=Path("r.mp3"), size=1, mtime_ns=1),
    slides=None,
)


def test_transcript_lines_carry_timecodes() -> None:
    transcript = Transcript(segments=[TranscriptSegment(start=754, end=760, text="讲 TLB。")])

    text = TemplateSet("templates").render(
        "dehydrated.md.j2", lecture=_LECTURE, transcript=transcript
    )

    assert text.startswith("# 进程调度 · 脱水逐字稿")
    assert "`12:34` 讲 TLB。" in text


def test_notes_render_chapters_with_pages_and_start_time() -> None:
    notes = LectureNotes(
        overview="概览",
        chapters=[
            NoteChapter(title="FCFS", pages=(3, 5), start=65, body="正文"),
            NoteChapter(title="答疑", pages=None, start=None, body="问答"),
        ],
        key_terms=[Term(term="FCFS", explanation="先来先服务")],
        notices=[Notice(text="周五交作业", at=5)],
    )

    text = TemplateSet("templates").render("notes.md.j2", lecture=_LECTURE, notes=notes)

    assert "- `00:05` 周五交作业" in text
    assert "## 1. FCFS" in text
    assert "> 课件第 3–5 页 · 讲解从 `01:05` 开始" in text
    assert "## 2. 答疑\n\n问答" in text
    assert "| FCFS | 先来先服务 |" in text


def test_prompt_digest_changes_with_template() -> None:
    prompts = TemplateSet("prompts")
    assert prompts.digest("dehydrate.system.j2") != prompts.digest("notes.system.j2")
