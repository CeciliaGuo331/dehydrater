"""把流水线事件渲染成按"步骤"显示的进度界面。"""

import time
from collections.abc import Collection
from enum import Enum, auto
from types import TracebackType

from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from dehydrater.pipeline.events import (
    PipelineEvent,
    StageFailed,
    StageFinished,
    StageProgress,
    StageSkipped,
    StageStarted,
    StageWarning,
)
from dehydrater.pipeline.steps import STEPS, Step, step_of


class _State(Enum):
    PENDING = auto()
    RUNNING = auto()
    DONE = auto()
    FAILED = auto()


class _StepProgress:
    def __init__(self, step: Step) -> None:
        self.step = step
        self.finished_stages: set[str] = set()
        self.reused = False
        """有阶段沿用了上次的结果。"""
        self.started_at: float | None = None
        self.elapsed = 0.0
        self.detail = ""
        self.failed = False

    @property
    def state(self) -> _State:
        if self.failed:
            return _State.FAILED
        if self.finished_stages == set(self.step.stages):
            return _State.DONE
        return _State.RUNNING if self.started_at is not None else _State.PENDING


class ProgressDisplay:
    """用作 with 语句：进入时开始实时刷新，退出时停在最终状态。"""

    def __init__(self, console: Console, *, hidden_steps: Collection[str] = ()) -> None:
        self._steps = [_StepProgress(step) for step in STEPS if step.name not in hidden_steps]
        self._messages: list[Text] = []
        self._live = Live(console=console, get_renderable=self._render, refresh_per_second=8)

    def __enter__(self) -> "ProgressDisplay":
        self._live.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._live.stop()

    def handle(self, event: PipelineEvent) -> None:
        progress = self._progress_of(event.stage)
        if progress is None:
            return
        match event:
            case StageStarted():
                if progress.started_at is None:
                    progress.started_at = time.monotonic()
            case StageSkipped(stage):
                progress.reused = True
                progress.finished_stages.add(stage)
            case StageProgress(_, done, total):
                progress.detail = f"{done}/{total}"
            case StageWarning(_, message):
                self._messages.append(Text(f"  ! {progress.step.label}：{message}", "yellow"))
            case StageFinished(stage, elapsed):
                progress.finished_stages.add(stage)
                progress.elapsed += elapsed
                progress.detail = ""
            case StageFailed(_, error):
                progress.failed = True
                self._messages.append(Text(f"  ✗ {progress.step.label}：{describe(error)}", "red"))

    def _progress_of(self, stage: str) -> _StepProgress | None:
        step = step_of(stage)
        return next((p for p in self._steps if p.step is step), None)

    def _render(self) -> RenderableType:
        table = Table.grid(padding=(0, 2))
        for progress in self._steps:
            table.add_row(*_row(progress))
        return Group(table, *self._messages)


def _row(progress: _StepProgress) -> tuple[RenderableType, str, str]:
    label = progress.step.label
    match progress.state:
        case _State.PENDING:
            return Text("  ·", "dim"), f"[dim]{label}[/dim]", ""
        case _State.RUNNING:
            assert progress.started_at is not None
            elapsed = format_duration(time.monotonic() - progress.started_at)
            return Spinner("dots", style="cyan"), label, f"{progress.detail}  {elapsed}".strip()
        case _State.DONE:
            # 渲染类阶段每次都会执行但几乎不耗时，不能据此判断"重新做过"
            if progress.reused and progress.elapsed < 1:
                return Text("  ✓", "green"), label, "[dim]沿用上次结果[/dim]"
            return Text("  ✓", "green"), label, format_duration(progress.elapsed)
        case _State.FAILED:
            return Text("  ✗", "red"), f"[red]{label}[/red]", ""


def format_duration(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes} 分 {secs:02d} 秒" if minutes else f"{secs} 秒"


def describe(error: BaseException) -> str:
    """面向用户的错误说明。有些异常（如网络超时）没有文字说明，只能显示类型。"""
    name = type(error).__name__
    if "Timeout" in name:
        return f"网络超时（{name}）：上传录音或等待服务器响应的时间过长，请检查网络后重试"
    if "Connect" in name:
        return f"无法连接服务器（{name}）：请检查网络和接入地址"
    if name in {"ReadError", "WriteError", "RemoteProtocolError"}:
        return f"网络连接中断（{name}）：请检查网络后重试"
    return str(error) or name
