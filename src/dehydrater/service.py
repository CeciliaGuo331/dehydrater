"""整理一节课的应用流程。交互式与脚本式命令行共用；将来的 UI 也复用这里，而不是 cli。"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from dehydrater.bootstrap import build_media_probe, build_pipeline, build_verifier
from dehydrater.config import Settings, Task
from dehydrater.domain.base import Seconds
from dehydrater.domain.dates import date_in_filename
from dehydrater.pipeline.cache import StageMeta
from dehydrater.pipeline.events import PipelineEvent
from dehydrater.pipeline.runner import StageState
from dehydrater.pipeline.steps import STEPS, Step, first_stage
from dehydrater.pipeline.workspace import Workspace
from dehydrater.ports import NotAMediaFileError

OUTPUT_FILES = (("笔记", "notes.md"), ("脱水稿", "dehydrated.md"), ("原始稿", "raw.md"))


class PlanError(ValueError):
    """用户提供的课堂信息有误，消息可以直接展示给用户。"""


@dataclass(frozen=True)
class Materials:
    recording: Path
    duration: Seconds
    recorded_on: date | None
    slides: list[Path]


@dataclass(frozen=True)
class LecturePlan:
    title: str
    lecture_date: date
    date_source: str
    recording: Path
    duration: Seconds
    slides: list[Path]
    output: Path
    resumes: bool
    """输出路径中已有这节课的整理进度，将从断点继续。"""
    crowded: bool
    """输出路径是一个已有内容、但不是整理目录的文件夹（可能选错了目录）。"""


def inspect_materials(paths: Sequence[Path]) -> Materials:
    """区分录音和课件：PDF 是课件，其余必须是带音轨的音视频文件，且恰好一个。"""
    probe = build_media_probe()
    recordings: list[tuple[Path, Seconds, date | None]] = []
    slides: list[Path] = []
    for path in paths:
        if not path.is_file():
            raise PlanError(f"找不到文件：{path}")
        if path.suffix.lower() == ".pdf":
            slides.append(path.resolve())
            continue
        try:
            info = probe.probe(path)
        except NotAMediaFileError as error:
            raise PlanError(f"{error}。课堂资料只支持音视频文件和 PDF 课件") from error
        recorded_on = info.recorded_at.date() if info.recorded_at else None
        recordings.append((path.resolve(), info.duration, recorded_on))
    if len(recordings) != 1:
        found = "、".join(path.name for path, _, _ in recordings) or "一个也没有"
        raise PlanError(f"课堂资料中需要恰好一个录音或录像，现在是：{found}")
    recording, duration, recorded_on = recordings[0]
    return Materials(recording, duration, recorded_on, slides)


def check_output(output: Path) -> None:
    if output.exists() and not output.is_dir():
        raise PlanError(f"输出路径 {output} 是一个文件，请提供目录")


def plan_lecture(
    title: str, materials: Materials, output: Path, *, lecture_date: date | None = None
) -> LecturePlan:
    title = title.strip()
    if not title:
        raise PlanError("课堂名称不能为空")
    check_output(output)
    resolved_date, date_source = _infer_date(materials, lecture_date)
    return LecturePlan(
        title=title,
        lecture_date=resolved_date,
        date_source=date_source,
        recording=materials.recording,
        duration=materials.duration,
        slides=materials.slides,
        output=output.resolve(),
        resumes=(output / "lecture.toml").exists(),
        crowded=output.is_dir()
        and not (output / "lecture.toml").exists()
        and any(output.iterdir()),
    )


async def run_lecture(
    plan: LecturePlan,
    settings: Settings,
    *,
    redo: str | None = None,
    on_event: Callable[[PipelineEvent], None] = lambda _: None,
) -> list[tuple[str, Path]]:
    """执行整理，返回生成的文件。redo 为步骤名（见 pipeline.steps.REDOABLE）。"""
    workspace = Workspace.prepare(
        plan.output,
        title=plan.title,
        lecture_date=plan.lecture_date,
        recording=plan.recording,
        slides=plan.slides,
    )
    pipeline = build_pipeline(workspace, settings, on_event)
    await pipeline.run(force_from=first_stage(redo) if redo else None)
    return [(label, workspace.root / name) for label, name in OUTPUT_FILES]


@dataclass(frozen=True)
class Usage:
    """一个步骤或整节课的耗时和用量。用量包括沿用缓存的部分，即产出结果的完整用量。"""

    elapsed_seconds: float = 0.0
    audio_seconds: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            elapsed_seconds=self.elapsed_seconds + other.elapsed_seconds,
            audio_seconds=self.audio_seconds + other.audio_seconds,
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
        )


@dataclass(frozen=True)
class StepReport:
    step: Step
    done: bool
    usage: Usage


@dataclass(frozen=True)
class LectureReport:
    steps: list[StepReport]

    @property
    def total(self) -> Usage:
        return sum((report.usage for report in self.steps), Usage())


def lecture_report(output: Path, settings: Settings) -> LectureReport:
    """按用户可见的步骤汇总一节课的耗时和 token 用量。"""
    statuses = {s.stage: s for s in build_pipeline(Workspace(output), settings).status()}
    return LectureReport(
        steps=[
            StepReport(
                step=step,
                done=all(statuses[stage].state == StageState.FRESH for stage in step.stages),
                usage=sum(
                    (_stage_usage(meta) for stage in step.stages if (meta := statuses[stage].meta)),
                    Usage(),
                ),
            )
            for step in STEPS
        ]
    )


def _stage_usage(meta: StageMeta) -> Usage:
    return Usage(
        elapsed_seconds=meta.elapsed_seconds,
        audio_seconds=meta.audio_seconds,
        prompt_tokens=meta.prompt_tokens,
        completion_tokens=meta.completion_tokens,
    )


async def verify_task(settings: Settings, task: Task) -> None:
    """检查某个任务的接入地址和 API Key 是否可用，不可用时抛出异常。"""
    await build_verifier(settings, task).verify()


def _infer_date(materials: Materials, given: date | None) -> tuple[date, str]:
    if given:
        return given, "手动指定"
    if from_name := date_in_filename(materials.recording.name):
        return from_name, "取自文件名"
    if materials.recorded_on:
        return materials.recorded_on, "取自录制时间"
    return date.fromtimestamp(materials.recording.stat().st_mtime), "取自文件修改时间"
