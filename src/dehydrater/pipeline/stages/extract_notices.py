from dehydrater.pipeline.artifacts import LECTURE, NOTICES, RAW_TRANSCRIPT
from dehydrater.pipeline.stage import Stage, StageContext
from dehydrater.ports import ChatModel, Fingerprint


class ExtractNoticesStage(Stage):
    """从原始逐字稿中提取课堂通知。必须读原始稿：clean 会把通知当废话删掉。"""

    name = "extract_notices"
    inputs = (RAW_TRANSCRIPT, LECTURE)
    outputs = (NOTICES,)

    def __init__(self, chat: ChatModel) -> None:
        self._chat = chat

    def fingerprint(self) -> Fingerprint:
        return self._chat.fingerprint()

    async def run(self, ctx: StageContext) -> None:
        raise NotImplementedError("计划在 S4 实现")
