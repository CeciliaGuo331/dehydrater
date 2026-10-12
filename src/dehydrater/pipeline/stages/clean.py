from dehydrater.pipeline.artifacts import CLEAN_TRANSCRIPT, DECK, RAW_TRANSCRIPT
from dehydrater.pipeline.stage import Stage, StageContext
from dehydrater.ports import ChatModel, Fingerprint


class CleanStage(Stage):
    """去口癖、去重复、修正术语。只删不写，保留时间戳。"""

    name = "clean"
    inputs = (RAW_TRANSCRIPT, DECK)
    outputs = (CLEAN_TRANSCRIPT,)

    def __init__(self, chat: ChatModel) -> None:
        self._chat = chat

    def fingerprint(self) -> Fingerprint:
        return self._chat.fingerprint()

    async def run(self, ctx: StageContext) -> None:
        raise NotImplementedError("计划在 S4 实现")
