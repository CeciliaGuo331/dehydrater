from dehydrater.pipeline.artifacts import ALIGNMENT, CLEAN_TRANSCRIPT, DECK, NOTES
from dehydrater.pipeline.stage import Stage, StageContext
from dehydrater.ports import ChatModel, Fingerprint


class WriteSectionsStage(Stage):
    """为每一节（若干连续课件页及其讲解）生成结构化笔记。"""

    name = "write_sections"
    inputs = (CLEAN_TRANSCRIPT, DECK, ALIGNMENT)
    outputs = (NOTES,)

    def __init__(self, chat: ChatModel) -> None:
        self._chat = chat

    def fingerprint(self) -> Fingerprint:
        return self._chat.fingerprint()

    async def run(self, ctx: StageContext) -> None:
        raise NotImplementedError("计划在 S6 实现")
