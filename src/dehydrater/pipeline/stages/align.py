from dehydrater.pipeline.artifacts import ALIGNMENT, CLEAN_TRANSCRIPT, DECK
from dehydrater.pipeline.stage import Stage, StageContext


class AlignStage(Stage):
    """把清洗后的讲解对齐到课件页。"""

    name = "align"
    inputs = (CLEAN_TRANSCRIPT, DECK)
    outputs = (ALIGNMENT,)

    async def run(self, ctx: StageContext) -> None:
        raise NotImplementedError("计划在 S5 实现")
