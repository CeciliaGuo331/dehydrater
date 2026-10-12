"""阶段的定义，以及阶段运行时能访问的上下文。"""

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path
from typing import ClassVar

from dehydrater.domain.base import DomainModel
from dehydrater.pipeline.artifacts import ArtifactKey
from dehydrater.pipeline.workspace import ArtifactStore, Workspace
from dehydrater.ports import Fingerprint, TokenUsage


class Stage(ABC):
    """流水线中的一步：读取声明的输入产物，写出声明的输出产物。

    输入、输出、版本号和 fingerprint 共同决定缓存键。
    修改了阶段逻辑或输出格式时，要把 version 加一，让旧缓存失效。
    """

    name: ClassVar[str]
    version: ClassVar[int] = 1
    inputs: ClassVar[tuple[ArtifactKey[DomainModel], ...]]
    outputs: ClassVar[tuple[ArtifactKey[DomainModel], ...]]
    always_run: ClassVar[bool] = False
    """为 True 时忽略缓存。用于开销很小、且输出是用户可见文件的阶段。"""

    def fingerprint(self) -> Fingerprint:
        """除输入产物之外、影响输出的参数，例如所用的模型。"""
        return {}

    @abstractmethod
    async def run(self, ctx: "StageContext") -> None: ...


logger = logging.getLogger(__name__)


class UndeclaredArtifactError(Exception):
    pass


class StageContext:
    """阶段运行时唯一的对外通道。只允许读写阶段声明过的产物，保证缓存键完整。"""

    def __init__(
        self,
        stage: Stage,
        store: ArtifactStore,
        workspace: Workspace,
        on_progress: Callable[[int, int], None],
        on_warning: Callable[[str], None],
    ) -> None:
        self._stage = stage
        self._store = store
        self._on_progress = on_progress
        self._on_warning = on_warning
        self.workspace = workspace
        self.usage = TokenUsage(prompt_tokens=0, completion_tokens=0)

    @property
    def files_dir(self) -> Path:
        path = self.workspace.files_dir(self._stage.name)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def read[M: DomainModel](self, key: ArtifactKey[M]) -> M:
        if key not in self._stage.inputs:
            raise UndeclaredArtifactError(f"{self._stage.name} 读取了未声明的输入 {key.name}")
        return self._store.read(key)

    def write[M: DomainModel](self, key: ArtifactKey[M], value: M) -> None:
        if key not in self._stage.outputs:
            raise UndeclaredArtifactError(f"{self._stage.name} 写入了未声明的输出 {key.name}")
        self._store.write(key, value)

    def report_progress(self, done: int, total: int) -> None:
        self._on_progress(done, total)

    def warn(self, message: str) -> None:
        logger.warning("阶段 %s：%s", self._stage.name, message)
        self._on_warning(message)

    def record_usage(self, usage: TokenUsage) -> None:
        self.usage = TokenUsage(
            prompt_tokens=self.usage.prompt_tokens + usage.prompt_tokens,
            completion_tokens=self.usage.completion_tokens + usage.completion_tokens,
        )
