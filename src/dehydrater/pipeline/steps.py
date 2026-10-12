"""面向用户的"步骤"：一个步骤由若干内部阶段组成。进度显示和 --redo 都以步骤为单位。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Step:
    name: str
    """命令行中使用的名字，例如 --redo notes。"""
    label: str
    stages: tuple[str, ...]


STEPS = (
    Step("audio", "提取音频", ("extract_audio",)),
    Step("slides", "读取课件", ("ingest_slides",)),
    Step("transcribe", "语音转写", ("transcribe", "render_raw")),
    Step("dehydrate", "逐字稿脱水", ("dehydrate", "render_dehydrated")),
    Step("notes", "撰写笔记", ("outline", "write_notes", "render_notes")),
)

REDOABLE = ("transcribe", "dehydrate", "notes")


def step_of(stage: str) -> Step:
    return next(step for step in STEPS if stage in step.stages)


def first_stage(step_name: str) -> str:
    return next(step for step in STEPS if step.name == step_name).stages[0]
