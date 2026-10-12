"""把结构化产物渲染成用户可见的 Markdown，每份输出一个阶段，产出后立即可读。"""

from dehydrater.pipeline.artifacts import DEHYDRATED_TRANSCRIPT, LECTURE, NOTES, RAW_TRANSCRIPT
from dehydrater.pipeline.stage import Stage, StageContext
from dehydrater.pipeline.templating import TemplateSet


class _RenderStage(Stage):
    always_run = True
    outputs = ()

    def __init__(self, templates: TemplateSet) -> None:
        self._templates = templates

    def _write(self, ctx: StageContext, template: str, output: str, **variables: object) -> None:
        text = self._templates.render(template, lecture=ctx.read(LECTURE), **variables)
        (ctx.workspace.root / output).write_text(text, encoding="utf-8")


class RenderRawStage(_RenderStage):
    name = "render_raw"
    inputs = (LECTURE, RAW_TRANSCRIPT)

    async def run(self, ctx: StageContext) -> None:
        self._write(ctx, "raw.md.j2", "raw.md", transcript=ctx.read(RAW_TRANSCRIPT))


class RenderDehydratedStage(_RenderStage):
    name = "render_dehydrated"
    inputs = (LECTURE, DEHYDRATED_TRANSCRIPT)

    async def run(self, ctx: StageContext) -> None:
        transcript = ctx.read(DEHYDRATED_TRANSCRIPT)
        self._write(ctx, "dehydrated.md.j2", "dehydrated.md", transcript=transcript)


class RenderNotesStage(_RenderStage):
    name = "render_notes"
    inputs = (LECTURE, NOTES)

    async def run(self, ctx: StageContext) -> None:
        self._write(ctx, "notes.md.j2", "notes.md", notes=ctx.read(NOTES))
