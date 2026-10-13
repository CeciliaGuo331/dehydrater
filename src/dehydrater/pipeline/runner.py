"""按顺序执行阶段，命中缓存的跳过，并通过事件汇报进度。"""

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from dehydrater.domain.base import DomainModel
from dehydrater.pipeline.artifacts import ArtifactKey
from dehydrater.pipeline.cache import StageMeta, compute_cache_key, is_fresh, load_meta, save_meta
from dehydrater.pipeline.events import (
    PipelineEvent,
    StageFailed,
    StageFinished,
    StageProgress,
    StageSkipped,
    StageStarted,
    StageWarning,
)
from dehydrater.pipeline.stage import Stage, StageContext
from dehydrater.pipeline.workspace import ArtifactStore, Workspace

logger = logging.getLogger(__name__)


class PipelineDefinitionError(Exception):
    pass


class StageState(StrEnum):
    FRESH = "fresh"
    """缓存有效，下次运行会跳过。"""
    STALE = "stale"
    """运行过，但输入或参数已经变化。"""
    PENDING = "pending"
    """从未成功运行过，或上游还没有产物。"""


@dataclass(frozen=True)
class StageStatus:
    stage: str
    state: StageState
    meta: StageMeta | None


class Runner:
    def __init__(
        self,
        stages: Sequence[Stage],
        workspace: Workspace,
        *,
        sources: Sequence[ArtifactKey[DomainModel]],
        on_event: Callable[[PipelineEvent], None] = lambda _: None,
    ) -> None:
        """stages 必须按依赖顺序排列；sources 是运行前由调用方写好的产物。"""
        _check_order(stages, sources)
        self._stages = tuple(stages)
        self._workspace = workspace
        self._store = ArtifactStore(workspace)
        self._on_event = on_event

    @property
    def stage_names(self) -> list[str]:
        return [stage.name for stage in self._stages]

    async def run(self, *, force_from: str | None = None, until: str | None = None) -> None:
        """依次执行阶段。

        force_from：该阶段及其所有下游忽略缓存、强制重跑。
        until：执行完该阶段后停止。
        """
        forced = self._downstream_of(force_from) if force_from else set[str]()
        if until is not None:
            self._require_stage(until)
        for stage in self._stages:
            await self._run_stage(stage, force=stage.name in forced)
            if stage.name == until:
                return

    def status(self) -> list[StageStatus]:
        return [self._status_of(stage) for stage in self._stages]

    async def _run_stage(self, stage: Stage, *, force: bool) -> None:
        cache_key = compute_cache_key(stage, self._store)
        if cache_key is None:
            raise PipelineDefinitionError(f"{stage.name} 的输入产物不全，上游阶段可能没有写出产物")
        meta_path = self._workspace.stage_meta_path(stage.name)
        if not (force or stage.always_run) and is_fresh(
            load_meta(meta_path), cache_key, stage, self._store
        ):
            logger.info("阶段 %s：沿用上次结果（缓存键 %s）", stage.name, cache_key[:12])
            self._on_event(StageSkipped(stage.name))
            return

        logger.info(
            "阶段 %s：开始%s（缓存键 %s）",
            stage.name,
            "（强制重做）" if force else "",
            cache_key[:12],
        )
        self._on_event(StageStarted(stage.name))
        ctx = StageContext(
            stage,
            self._store,
            self._workspace,
            on_progress=lambda done, total: self._on_event(StageProgress(stage.name, done, total)),
            on_warning=lambda message: self._on_event(StageWarning(stage.name, message)),
        )
        started = time.monotonic()
        try:
            await stage.run(ctx)
        except Exception as error:
            logger.exception("阶段 %s：失败，耗时 %.1f 秒", stage.name, time.monotonic() - started)
            self._on_event(StageFailed(stage.name, error))
            raise
        elapsed = time.monotonic() - started
        save_meta(
            meta_path,
            cache_key=cache_key,
            stage=stage,
            store=self._store,
            elapsed_seconds=elapsed,
            usage=ctx.usage,
            audio_seconds=ctx.audio_seconds,
        )
        logger.info(
            "阶段 %s：完成，耗时 %.1f 秒，token %d/%d",
            stage.name,
            elapsed,
            ctx.usage.prompt_tokens,
            ctx.usage.completion_tokens,
        )
        self._on_event(StageFinished(stage.name, elapsed))

    def _status_of(self, stage: Stage) -> StageStatus:
        meta = load_meta(self._workspace.stage_meta_path(stage.name))
        cache_key = compute_cache_key(stage, self._store)
        if meta is None or cache_key is None:
            state = StageState.PENDING
        elif is_fresh(meta, cache_key, stage, self._store):
            state = StageState.FRESH
        else:
            state = StageState.STALE
        return StageStatus(stage.name, state, meta)

    def _require_stage(self, stage_name: str) -> None:
        if stage_name not in self.stage_names:
            raise PipelineDefinitionError(f"没有名为 {stage_name} 的阶段")

    def _downstream_of(self, stage_name: str) -> set[str]:
        self._require_stage(stage_name)
        affected = {stage_name}
        tainted: set[ArtifactKey[DomainModel]] = set()
        for stage in self._stages:
            if stage.name in affected or tainted.intersection(stage.inputs):
                affected.add(stage.name)
                tainted.update(stage.outputs)
        return affected


def _check_order(stages: Sequence[Stage], sources: Sequence[ArtifactKey[DomainModel]]) -> None:
    """每个输入都必须来自 sources 或排在前面的阶段；每个产物只能有一个生产者。"""
    available = set(sources)
    for stage in stages:
        missing = [key.name for key in stage.inputs if key not in available]
        if missing:
            raise PipelineDefinitionError(f"{stage.name} 的输入 {missing} 没有在它之前产生")
        duplicated = [key.name for key in stage.outputs if key in available]
        if duplicated:
            raise PipelineDefinitionError(f"{stage.name} 的输出 {duplicated} 已由其他来源产生")
        available.update(stage.outputs)
