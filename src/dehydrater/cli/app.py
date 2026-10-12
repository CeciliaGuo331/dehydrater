"""命令行入口：定义命令和帮助信息，具体流程在同包的其他模块中。"""

import asyncio
import logging
from datetime import date
from importlib.metadata import version
from pathlib import Path
from typing import Annotated

import typer

from dehydrater.bootstrap import load_settings
from dehydrater.cli import lecture
from dehydrater.cli.console import console, fail
from dehydrater.cli.display import describe
from dehydrater.cli.logs import configure_logging, global_log_path, log_settings
from dehydrater.cli.setup import run_setup
from dehydrater.config import Field, Task, env_name
from dehydrater.pipeline.steps import REDOABLE
from dehydrater.service import lecture_status, verify_task

USAGE = """\
[bold]dehydrater[/bold] —— 把课堂录音整理成笔记

  [bold]dehydrater setup[/bold]     首次使用：设置各项服务的接入地址、模型和 API Key
  [bold]dehydrater[/bold]           开始整理一节课（交互式）

整理时需要提供课堂名称、课堂资料（一个录音或录像，加上零到多个 PDF 课件）和输出路径。
输出路径中会生成：
  notes.md        笔记：以课件为主线，融入老师的讲解
  dehydrated.md   脱水稿：精炼后的讲课全文
  raw.md          原始稿：语音识别原文

在脚本中使用：
  dehydrater process   非交互式整理一节课
  dehydrater status    查看一节课的整理进度
  dehydrater check     检查设置是否完整、各项服务能否连通
详见 dehydrater <命令> --help，或项目文档 docs/usage.md。"""

_SUBCOMMAND = {"help_option_names": ["--help", "-h"]}

logger = logging.getLogger(__name__)

app = typer.Typer(
    add_completion=False,
    rich_markup_mode="rich",
    # 顶层的 --help 由下面的 root 自行处理，以便输出简短的中文说明
    context_settings={"help_option_names": []},
)


@app.callback(invoke_without_command=True)
def root(
    ctx: typer.Context,
    show_help: Annotated[bool, typer.Option("--help", "-h", is_eager=True)] = False,
    show_version: Annotated[bool, typer.Option("--version", "-V", is_eager=True)] = False,
) -> None:
    if show_help:
        console.print(USAGE)
        raise typer.Exit()
    if show_version:
        console.print(f"dehydrater {version('dehydrater')}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        lecture.interactive()


@app.command(context_settings=_SUBCOMMAND)
def setup() -> None:
    """交互式设置各项服务的接入地址、模型和 API Key，并帮你保存。"""
    run_setup()


@app.command(context_settings=_SUBCOMMAND)
def process(
    name: Annotated[str, typer.Option("--name", "-n", help="课堂名称。")],
    inputs: Annotated[
        list[Path],
        typer.Option(
            "--input",
            "-i",
            help="课堂资料，可重复：恰好一个录音或录像，零到多个 PDF 课件。",
        ),
    ],
    output: Annotated[Path, typer.Option("--output", "-o", help="输出目录。")],
    lecture_date: Annotated[
        str | None,
        typer.Option("--date", help="上课日期 YYYY-MM-DD；默认从文件名或录制时间推断。"),
    ] = None,
    redo: Annotated[
        str | None,
        typer.Option(
            help=f"从某一步起重做（忽略已有结果）：{' / '.join(REDOABLE)}。",
        ),
    ] = None,
) -> None:
    """非交互式整理一节课，适合在脚本中使用。

    同一个输出目录重复运行时，已完成的步骤会直接沿用；中断后重新运行即可继续。

    示例：

      dehydrater process -n "操作系统 第3讲" -i 第3讲.mp4 -i 调度.pdf -o ~/笔记/OS-03

      dehydrater process -n "操作系统 第3讲" -i 第3讲.mp4 -o ~/笔记/OS-03 --redo notes
    """
    if redo is not None and redo not in REDOABLE:
        fail(f"--redo 只能是 {' / '.join(REDOABLE)}")
    try:
        parsed_date = date.fromisoformat(lecture_date) if lecture_date else None
    except ValueError:
        fail(f"日期格式应为 YYYY-MM-DD：{lecture_date}")
    lecture.process(name, inputs, output, lecture_date=parsed_date, redo=redo)


@app.command(context_settings=_SUBCOMMAND)
def status(output: Annotated[Path, typer.Argument(help="整理时指定的输出目录。")]) -> None:
    """查看一节课各步骤是否完成及耗时。"""
    if not (output / "lecture.toml").exists():
        fail(f"{output} 中没有整理记录")
    for item in lecture_status(output, load_settings()):
        mark = "[green]✓[/green]" if item.done else "[dim]·[/dim]"
        elapsed = f"{item.elapsed_seconds:.0f} 秒" if item.done else "未完成"
        console.print(f"  {mark} {item.step.label:<8} {elapsed}")


@app.command(context_settings=_SUBCOMMAND)
def check() -> None:
    """检查设置是否完整，并逐项测试各服务能否连通。"""
    settings = load_settings()
    log_settings(settings)
    if missing := settings.missing():
        fail("以下设置缺失，请运行 dehydrater setup：\n  " + "\n  ".join(missing))
    healthy = True
    for task in Task:
        try:
            asyncio.run(verify_task(settings, task))
            console.print(f"  [green]✓[/green] {task.label}")
        except Exception as error:  # 网络、鉴权等各种失败都只需要告诉用户
            healthy = False
            logger.exception("检查 %s 失败", task)
            console.print(f"  [red]✗[/red] {task.label}：{describe(error)}")
            names = "、".join(
                env_name(task, field) for field in (Field.URL, Field.MODEL, Field.KEY)
            )
            console.print(f"    [dim]相关设置：{names}[/dim]")
    if not healthy:
        console.print(f"\n详细日志：{global_log_path()}")
        raise typer.Exit(1)


def main() -> None:
    configure_logging()
    app()
