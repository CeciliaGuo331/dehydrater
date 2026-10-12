"""命令行入口。只负责解析参数和展示结果，业务逻辑都在 pipeline 中。"""

import asyncio
from datetime import date
from pathlib import Path
from typing import Annotated, NoReturn

import typer
from rich.console import Console
from rich.table import Table

from dehydrater.bootstrap import build_pipeline, build_secret_store, missing_keys
from dehydrater.config import (
    AppConfig,
    ConfigError,
    default_config_path,
    example_config,
    load_config,
)
from dehydrater.credentials import KeychainUnavailableError, SecretStore, env_var_name
from dehydrater.domain.timecode import format_timecode
from dehydrater.pipeline.events import (
    PipelineEvent,
    StageFailed,
    StageFinished,
    StageProgress,
    StageSkipped,
    StageStarted,
    StageWarning,
)
from dehydrater.pipeline.workspace import Workspace, WorkspaceError

app = typer.Typer(help="把课堂录像和课件脱水成逐字稿、通知清单和讲义。", no_args_is_help=True)
config_app = typer.Typer(help="管理配置文件。", no_args_is_help=True)
app.add_typer(config_app, name="config")
key_app = typer.Typer(help="管理各渠道的 API 密钥。", no_args_is_help=True)
app.add_typer(key_app, name="key")

console = Console()

# Typer 不识别 PEP 695 的 type 别名，这里只能用普通赋值
WorkspaceArg = Annotated[Path, typer.Argument(help="工作区目录，一节课一个。")]
ConfigOption = Annotated[
    Path | None, typer.Option("--config", help="配置文件路径，默认使用用户配置目录。")
]


@app.command()
def init(
    workspace: WorkspaceArg,
    recording: Annotated[
        Path,
        typer.Option(
            "--recording",
            "-r",
            exists=True,
            dir_okay=False,
            help="课堂录像或录音，任何音视频格式。",
        ),
    ],
    slides: Annotated[
        Path | None,
        typer.Option("--slides", "-s", exists=True, dir_okay=False, help="PDF 课件，可选。"),
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
            recording=recording,
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
    secrets = build_secret_store()
    _require_keys(config, secrets)
    pipeline = build_pipeline(Workspace(workspace), config, secrets, on_event=_print_event)
    try:
        asyncio.run(pipeline.run(force_from=force_from, until=until))
    except WorkspaceError as error:
        _fail(str(error))
    except Exception:
        # 失败详情已由 StageFailed 事件打印
        raise typer.Exit(1) from None
    for output in ("raw.md", "dehydrated.md", "notes.md"):
        if (path := Path(workspace) / output).exists():
            console.print(f"输出：{path}")


@app.command()
def status(workspace: WorkspaceArg, config_path: ConfigOption = None) -> None:
    """查看各阶段的缓存状态、耗时和 token 用量。"""
    pipeline = build_pipeline(Workspace(workspace), _load_config(config_path), build_secret_store())
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
    """校验配置文件，并检查每个用到的渠道都能找到密钥。"""
    config = _load_config(config_path)
    _require_keys(config, build_secret_store())
    console.print("配置有效，密钥均已设置。")


@key_app.command("list")
def key_list(config_path: ConfigOption = None) -> None:
    """列出配置中各渠道的密钥来源（不显示密钥本身）。"""
    config = _load_config(config_path)
    secrets = build_secret_store()
    table = Table("渠道", "环境变量名", "来源")
    for name in config.providers:
        secret = secrets.get(name)
        source = f"{secret.source.value}（{secret.location}）" if secret else "[red]未设置[/red]"
        table.add_row(name, env_var_name(name), source)
    console.print(table)


@key_app.command("set")
def key_set(provider: Annotated[str, typer.Argument(help="渠道名，见 `key list`。")]) -> None:
    """把某个渠道的密钥保存到系统钥匙串。输入时不回显。"""
    value = typer.prompt(f"{provider} 的 API Key", hide_input=True)
    try:
        build_secret_store().save_to_keychain(provider, value)
    except KeychainUnavailableError as error:
        _fail(f"{error}\n可以改为设置环境变量或在 .env 中写入 {env_var_name(provider)}。")
    console.print(f"已保存到系统钥匙串：{provider}")


@key_app.command("unset")
def key_unset(provider: Annotated[str, typer.Argument(help="渠道名。")]) -> None:
    """从系统钥匙串中删除某个渠道的密钥。环境变量和 .env 需要自行修改。"""
    try:
        deleted = build_secret_store().delete_from_keychain(provider)
    except KeychainUnavailableError as error:
        _fail(str(error))
    console.print(f"已删除：{provider}" if deleted else f"钥匙串中没有 {provider}")


def _require_keys(config: AppConfig, secrets: SecretStore) -> None:
    if missing := missing_keys(config, secrets):
        names = "\n".join(f"  {name}（{env_var_name(name)}）" for name in missing)
        hint = "请设置环境变量、写入 .env，或运行 `dehydrater key set <渠道名>`。"
        _fail(f"以下渠道缺少密钥：\n{names}\n{hint}")


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
        case StageWarning(stage, message):
            console.print(f"[yellow]! {stage}：{message}[/yellow]")
        case StageFinished(stage, elapsed):
            console.print(f"[green]✓ {stage}[/green] {elapsed:.1f}s")
        case StageFailed(stage, error):
            console.print(f"[red]✗ {stage}[/red] {type(error).__name__}: {error}")


def _fail(message: str) -> NoReturn:
    console.print(f"[red]{message}[/red]")
    raise typer.Exit(1)
