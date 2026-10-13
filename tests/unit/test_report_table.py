from rich.console import Console

from dehydrater.cli.report import report_table
from dehydrater.pipeline.steps import STEPS
from dehydrater.service import LectureReport, StepReport, Usage


def test_table_shows_usage_per_step_and_total() -> None:
    usages = {
        "transcribe": Usage(elapsed_seconds=600, audio_seconds=7150),
        "dehydrate": Usage(elapsed_seconds=36, prompt_tokens=40815, completion_tokens=7185),
        "notes": Usage(elapsed_seconds=97, prompt_tokens=39047, completion_tokens=11673),
    }
    report = LectureReport(
        steps=[StepReport(step, True, usages.get(step.name, Usage())) for step in STEPS]
    )
    console = Console(record=True, width=120)

    console.print(report_table(report, show_state=True))
    text = console.export_text()

    assert "1:59:10" in text
    assert "40,815" in text
    assert "79,862" in text  # 合计输入 token
    assert "18,858" in text  # 合计输出 token
