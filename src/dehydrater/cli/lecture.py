"""整理一节课：交互式（`dehydrater`）与脚本式（`dehydrater process`）共用执行和展示逻辑。"""

import asyncio
import logging
import time
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path

import typer
from rich.table import Table

from dehydrater.bootstrap import load_settings
from dehydrater.cli.console import console, fail
from dehydrater.cli.display import ProgressDisplay
from dehydrater.cli.logs import log_settings, workspace_log
from dehydrater.cli.prompts import Ask, split_paths, terminal_ask
from dehydrater.cli.report import report_table
from dehydrater.config import Settings
from dehydrater.domain.timecode import format_timecode
from dehydrater.pipeline.workspace import Workspace, WorkspaceError
from dehydrater.service import (
    LecturePlan,
    LectureReport,
    PlanError,
    check_output,
    inspect_materials,
    lecture_report,
    plan_lecture,
    run_lecture,
)

logger = logging.getLogger(__name__)

_MATERIALS_HINT = (
    "[dim]  录音或录像一个，PDF 课件零到多个，用空格分隔。\n"
    "  路径含空格时用引号括起来（把文件拖进终端会自动处理）；按 Tab 可补全路径。[/dim]"
)


def interactive(ask: Ask = terminal_ask) -> None:
    settings = _require_settings()
    console.print("[bold]开始整理课程[/bold]\n")

    title = _ask_valid(ask, "课堂名称", _non_empty)
    console.print(_MATERIALS_HINT)
    materials = _ask_valid(
        ask, "课堂资料", lambda text: inspect_materials(split_paths(text)), paths=True
    )
    output = _ask_valid(ask, "输出路径", _output_path, paths=True)

    plan = plan_lecture(title, materials, output)
    _show_plan(plan)
    if not ask("确认开始？(Y/n)", default="y").lower().startswith("y"):
        raise typer.Exit()
    execute(plan, settings)


def process(
    title: str,
    inputs: Sequence[Path],
    output: Path,
    *,
    lecture_date: date | None,
    redo: str | None,
) -> None:
    settings = _require_settings()
    try:
        plan = plan_lecture(title, inspect_materials(inputs), output, lecture_date=lecture_date)
    except PlanError as error:
        fail(str(error))
    _show_plan(plan)
    execute(plan, settings, redo=redo)


def execute(plan: LecturePlan, settings: Settings, *, redo: str | None = None) -> None:
    log_path = Workspace(plan.output).log_path
    with workspace_log(log_path):
        logger.info("===== 开始整理：%s =====", plan)
        log_settings(settings)
        outputs = _run_with_progress(plan, settings, redo, log_path)
        report = lecture_report(plan.output, settings)
        logger.info("===== 整理完成：%s =====", report.total)
    _show_outputs(outputs, report)


def _run_with_progress(
    plan: LecturePlan, settings: Settings, redo: str | None, log_path: Path
) -> list[tuple[str, Path]]:
    started = time.monotonic()
    hidden = () if plan.slides else ("slides",)
    try:
        with ProgressDisplay(console, hidden_steps=hidden) as display:
            outputs = asyncio.run(run_lecture(plan, settings, redo=redo, on_event=display.handle))
    except KeyboardInterrupt:
        logger.warning("用户中断")
        console.print(
            "\n[yellow]已中断。已完成的部分都已保存，重新运行同样的命令即可继续。[/yellow]"
        )
        raise typer.Exit(130) from None
    except WorkspaceError as error:
        logger.exception("工作区错误")
        fail(str(error))
    except Exception:
        # 失败原因已在进度界面中显示，完整堆栈已由 runner 写入日志
        logger.exception("整理失败")
        fail(
            "\n整理未完成。排除问题后重新运行同样的命令，已完成的步骤不会重做。\n"
            f"详细日志：{log_path}"
        )
    logger.info("总耗时 %.0f 秒", time.monotonic() - started)
    return outputs


def _show_outputs(outputs: list[tuple[str, Path]], report: LectureReport) -> None:
    console.print("\n[green]✓ 完成[/green]\n")
    console.print(report_table(report, show_state=False))
    console.print()
    files = Table.grid(padding=(0, 4))
    files.add_column()
    files.add_column(overflow="fold")  # 路径太长时换行，而不是截断成省略号
    for label, path in outputs:
        files.add_row(f"  {label}", str(path))
    console.print(files)


def _require_settings() -> Settings:
    settings = load_settings()
    if settings.missing():
        fail("尚未完成设置，请先运行 [bold]dehydrater setup[/bold]")
    return settings


def _show_plan(plan: LecturePlan) -> None:
    console.print()
    console.print(f"  课堂    {plan.title}")
    console.print(f"  录音    {plan.recording.name}（{format_timecode(plan.duration)}）")
    for slides in plan.slides:
        console.print(f"  课件    {slides.name}")
    console.print(f"  日期    {plan.lecture_date}（{plan.date_source}）")
    console.print(f"  输出    {plan.output}")
    if plan.resumes:
        console.print("  [cyan]输出路径中已有这节课的进度，将从断点继续[/cyan]")
    if plan.crowded:
        console.print(
            "  [yellow]注意：输出路径中已有其他文件，将在其中生成 lecture.toml、cache/ "
            "和三个 .md 文件。建议为每节课使用单独的目录。[/yellow]"
        )
    console.print()


def _ask_valid[T](ask: Ask, label: str, parse: Callable[[str], T], *, paths: bool = False) -> T:
    """反复询问，直到输入非空且能通过校验。"""
    while True:
        text = ask(label, paths=paths)
        if not text:
            console.print(f"[red]{label}不能为空[/red]")
            continue
        try:
            return parse(text)
        except (PlanError, ValueError) as error:  # shlex 遇到未闭合的引号时抛出 ValueError
            console.print(f"[red]{error}[/red]")


def _non_empty(text: str) -> str:
    return text.strip()


def _output_path(text: str) -> Path:
    """输出路径只有一个，整行都是路径，不需要给空格加引号；首尾的引号（如拖入终端时自动加的）会去掉。"""
    stripped = text.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in "'\"":
        stripped = stripped[1:-1]
    path = Path(stripped).expanduser()
    check_output(path)
    return path
