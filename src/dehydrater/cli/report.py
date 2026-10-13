"""把一节课的耗时和 token 用量渲染成表格，供完成摘要和 `status` 使用。"""

from rich.table import Table

from dehydrater.cli.display import format_duration
from dehydrater.domain.timecode import format_timecode
from dehydrater.service import LectureReport, Usage


def report_table(report: LectureReport, *, show_state: bool) -> Table:
    table = Table(box=None, padding=(0, 2), show_edge=False, header_style="bold")
    if show_state:
        table.add_column("")
    table.add_column("步骤")
    for title in ("耗时", "录音", "输入 token", "输出 token"):
        table.add_column(title, justify="right")

    for step in report.steps:
        state = ["[green]✓[/green]" if step.done else "[dim]·[/dim]"] if show_state else []
        table.add_row(*state, step.step.label, *_cells(step.usage))
    table.add_section()
    table.add_row(*([""] if show_state else []), "合计", *_cells(report.total))
    return table


def _cells(usage: Usage) -> tuple[str, str, str, str]:
    return (
        format_duration(usage.elapsed_seconds) if usage.elapsed_seconds else "",
        format_timecode(usage.audio_seconds) if usage.audio_seconds else "",
        f"{usage.prompt_tokens:,}" if usage.prompt_tokens else "",
        f"{usage.completion_tokens:,}" if usage.completion_tokens else "",
    )
