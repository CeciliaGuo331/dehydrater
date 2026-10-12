from datetime import date
from pathlib import Path

from dehydrater.domain.guide import Guide, GuideNotice, GuideSection, GuideTerm
from dehydrater.domain.lecture import Lecture, SourceFile
from dehydrater.domain.transcript import Transcript, TranscriptSegment
from dehydrater.pipeline.templating import TemplateSet

_LECTURE = Lecture(
    title="进程调度",
    date=date(2026, 9, 30),
    recording=SourceFile(path=Path("r.mp3"), size=1, mtime_ns=1),
)


def test_transcript_lines_carry_timecodes() -> None:
    transcript = Transcript(segments=[TranscriptSegment(start=754, end=760, text="讲 TLB。")])

    text = TemplateSet("templates").render(
        "dehydrated.md.j2", lecture=_LECTURE, transcript=transcript
    )

    assert text.startswith("# 进程调度 · 脱水逐字稿")
    assert "`12:34` 讲 TLB。" in text


def test_guide_lists_notices_sections_and_terms() -> None:
    guide = Guide(
        overview="概览",
        sections=[GuideSection(title="FCFS", start=65, summary="先来先服务", key_points=["要考"])],
        key_terms=[GuideTerm(term="FCFS", explanation="先来先服务")],
        notices=[GuideNotice(text="周五交作业", at=5)],
    )

    text = TemplateSet("templates").render("guide.md.j2", lecture=_LECTURE, guide=guide)

    assert "- `00:05` 周五交作业" in text
    assert "### `01:05` FCFS" in text
    assert "| FCFS | 先来先服务 |" in text


def test_prompt_digest_changes_with_template() -> None:
    prompts = TemplateSet("prompts")
    assert prompts.digest("dehydrate.system.j2") != prompts.digest("guide.system.j2")
