"""一节课的处理入口：把 lecture.toml 写成源产物，再交给 Runner。"""

from collections.abc import Callable, Sequence

from dehydrater.pipeline.artifacts import LECTURE
from dehydrater.pipeline.events import PipelineEvent
from dehydrater.pipeline.runner import Runner, StageStatus
from dehydrater.pipeline.stage import Stage
from dehydrater.pipeline.workspace import ArtifactStore, Workspace


class LecturePipeline:
    def __init__(
        self,
        workspace: Workspace,
        stages: Sequence[Stage],
        on_event: Callable[[PipelineEvent], None] = lambda _: None,
    ) -> None:
        self._workspace = workspace
        self.runner = Runner(stages, workspace, sources=[LECTURE], on_event=on_event)

    async def run(self, *, force_from: str | None = None, until: str | None = None) -> None:
        self._refresh_sources()
        await self.runner.run(force_from=force_from, until=until)

    def status(self) -> list[StageStatus]:
        self._refresh_sources()
        return self.runner.status()

    def _refresh_sources(self) -> None:
        # 每次都重新读取 lecture.toml：用户可能改了它，或者替换了视频文件
        ArtifactStore(self._workspace).write(LECTURE, self._workspace.load_lecture())
