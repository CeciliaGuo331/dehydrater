"""命令行入口。只负责解析参数和展示结果，业务逻辑都在 pipeline 中。"""

import asyncio
from datetime import date
from pathlib import Path
from typing import Annotated, NoReturn

import typer
from rich.console import Console
from rich.table import Table

from dehydrater.bootstrap import build_pipeline
from dehydrater.config import (
    AppConfig,
    ConfigError,
    default_config_path,
    example_config,
    load_config,
)
from dehydrater.domain.timecode import format_timecode
from dehydrater.pipeline.events import (
    PipelineEvent,
    StageFailed,
    StageFinished,
    StageProgress,
    StageSkipped,
    StageStarted,
)
from dehydrater.pipeline.workspace import Workspace, WorkspaceError

app = typer.Typer(help="把课堂录像和课件脱水成逐字稿、通知清单和讲义。", no_args_is_help=True)
config_app = typer.Typer(help="管理配置文件。", no_args_is_help=True)
app.add_typer(config_app, name="config")

console = Console()

# Typer 不识别 PEP 695 的 type 别名，这里只能用普通赋值
WorkspaceArg = Annotated[Path, typer.Argument(help="工作区目录，一节课一个。")]
ConfigOption = Annotated[
    Path | None, typer.Option("--config", help="配置文件路径，默认使用用户配置目录。")
]


@app.command()
def init(
    workspace: WorkspaceArg,
    video: Annotated[Path, typer.Option(exists=True, dir_okay=False, help="课堂录像。")],
    slides: Annotated[
        Path | None, typer.Option(exists=True, dir_okay=False, help="PDF 课件。")
    ] = None,
    lecture_date: Annotated[
        str | None, typer.Option("--date", help="上课日期，YYYY-MM-DD，默认今天。")
    ] = None,
    title: Annotated[str | None, typer.Option(help="课程标题，默认使用目录名。")] = None,
) -> None:
    """创建一节课的工作区。"""
    try:
        created = Workspace.create(
            workspace,
            title=title or workspace.resolve().name,
            lecture_date=date.fromisoformat(lecture_date) if lecture_date else date.today(),
            video=video,
            slides=slides,
        )
    except (WorkspaceError, ValueError) as error:
        _fail(str(error))
    console.print(f"已创建工作区 {created.root}，可以编辑 {created.manifest_path.name} 修改设置。")


@app.command()
def run(
    workspace: WorkspaceArg,
    force_from: Annotated[
        str | None, typer.Option("--from", help="从该阶段起忽略缓存、强制重跑。")
    ] = None,
    until: Annotated[str | None, typer.Option(help="执行完该阶段后停止。")] = None,
    config_path: ConfigOption = None,
) -> None:
    """执行流水线。命中缓存的阶段会被跳过。"""
    config = _load_config(config_path)
    if missing := config.missing_secrets():
        _fail(f"缺少以下环境变量：{', '.join(missing)}")
    pipeline = build_pipeline(Workspace(workspace), config, on_event=_print_event)
    try:
        asyncio.run(pipeline.run(force_from=force_from, until=until))
    except WorkspaceError as error:
        _fail(str(error))
    except Exception:
        # 失败详情已由 StageFailed 事件打印
        raise typer.Exit(1) from None


@app.command()
def status(workspace: WorkspaceArg, config_path: ConfigOption = None) -> None:
    """查看各阶段的缓存状态、耗时和 token 用量。"""
    pipeline = build_pipeline(Workspace(workspace), _load_config(config_path))
    try:
        statuses = pipeline.status()
    except WorkspaceError as error:
        _fail(str(error))

    table = Table("阶段", "状态", "耗时", "输入 token", "输出 token")
    for item in statuses:
        meta = item.meta
        table.add_row(
            item.stage,
            item.state.value,
            format_timecode(meta.elapsed_seconds) if meta else "",
            str(meta.prompt_tokens) if meta else "",
            str(meta.completion_tokens) if meta else "",
        )
    console.print(table)


@config_app.command("init")
def config_init(config_path: ConfigOption = None) -> None:
    """生成一份示例配置文件。"""
    path = config_path or default_config_path()
    if path.exists():
        _fail(f"{path} 已存在")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(example_config(), encoding="utf-8")
    console.print(f"已写入 {path}")


@config_app.command("check")
def config_check(config_path: ConfigOption = None) -> None:
    """校验配置文件，并检查所需的密钥环境变量是否已设置。"""
    config = _load_config(config_path)
    if missing := config.missing_secrets():
        _fail(f"配置有效，但缺少以下环境变量：{', '.join(missing)}")
    console.print("配置有效，密钥均已设置。")


def _load_config(path: Path | None) -> AppConfig:
    try:
        return load_config(path or default_config_path())
    except ConfigError as error:
        _fail(str(error))


def _print_event(event: PipelineEvent) -> None:
    match event:
        case StageStarted(stage):
            console.print(f"[bold]▶ {stage}[/bold]")
        case StageSkipped(stage):
            console.print(f"[dim]· {stage}（缓存）[/dim]")
        case StageProgress(stage, done, total):
            console.print(f"  {stage} {done}/{total}")
        case StageFinished(stage, elapsed):
            console.print(f"[green]✓ {stage}[/green] {elapsed:.1f}s")
        case StageFailed(stage, error):
            console.print(f"[red]✗ {stage}[/red] {type(error).__name__}: {error}")


def _fail(message: str) -> NoReturn:
    console.print(f"[red]{message}[/red]")
    raise typer.Exit(1)
