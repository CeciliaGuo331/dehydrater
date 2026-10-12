"""测试用的最小阶段与产物，用来验证调度和缓存逻辑，不涉及真实业务。"""

from dehydrater.domain.base import DomainModel
from dehydrater.pipeline.artifacts import ArtifactKey
from dehydrater.pipeline.stage import Stage, StageContext
from dehydrater.ports import Fingerprint


class Number(DomainModel):
    value: int


SEED = ArtifactKey("seed", Number)
DOUBLED = ArtifactKey("doubled", Number)
PLUS_ONE = ArtifactKey("plus_one", Number)


class Double(Stage):
    name = "double"
    inputs = (SEED,)
    outputs = (DOUBLED,)

    def __init__(self, calls: list[str], factor: int = 2) -> None:
        self._calls = calls
        self._factor = factor

    def fingerprint(self) -> Fingerprint:
        return {"factor": self._factor}

    async def run(self, ctx: StageContext) -> None:
        self._calls.append(self.name)
        ctx.write(DOUBLED, Number(value=ctx.read(SEED).value * self._factor))


class PlusOne(Stage):
    name = "plus_one"
    inputs = (DOUBLED,)
    outputs = (PLUS_ONE,)

    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    async def run(self, ctx: StageContext) -> None:
        self._calls.append(self.name)
        ctx.write(PLUS_ONE, Number(value=ctx.read(DOUBLED).value + 1))


class ReadsUndeclared(Stage):
    name = "reads_undeclared"
    inputs = (SEED,)
    outputs = ()

    async def run(self, ctx: StageContext) -> None:
        ctx.read(DOUBLED)
