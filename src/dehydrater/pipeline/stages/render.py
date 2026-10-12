"""把结构化产物渲染成用户可见的 Markdown。

三份输出各自一个阶段，这样 transcript.md 和 notices.md 不必等讲义生成完才出现。
"""

from dehydrater.pipeline.artifacts import CLEAN_TRANSCRIPT, DECK, LECTURE, NOTES, NOTICES
from dehydrater.pipeline.stage import Stage, StageContext


class RenderNoticesStage(Stage):
    name = "render_notices"
    inputs = (LECTURE, NOTICES)
    outputs = ()
    always_run = True

    async def run(self, ctx: StageContext) -> None:
        raise NotImplementedError("计划在 S4 实现")


class RenderTranscriptStage(Stage):
    name = "render_transcript"
    inputs = (LECTURE, CLEAN_TRANSCRIPT)
    outputs = ()
    always_run = True

    async def run(self, ctx: StageContext) -> None:
        raise NotImplementedError("计划在 S4 实现")


class RenderLectureStage(Stage):
    name = "render_lecture"
    inputs = (LECTURE, DECK, NOTES)
    outputs = ()
    always_run = True

    async def run(self, ctx: StageContext) -> None:
        raise NotImplementedError("计划在 S6 实现")
