import asyncio

from dehydrater.domain.slides import Deck, SlidePage
from dehydrater.pipeline.artifacts import DECK, LECTURE
from dehydrater.pipeline.stage import Stage, StageContext
from dehydrater.ports import Fingerprint, SlideReader


class IngestSlidesStage(Stage):
    """读取全部课件，按输入顺序给所有页统一编号。"""

    name = "ingest_slides"
    inputs = (LECTURE,)
    outputs = (DECK,)

    def __init__(self, reader: SlideReader) -> None:
        self._reader = reader

    def fingerprint(self) -> Fingerprint:
        return self._reader.fingerprint()

    async def run(self, ctx: StageContext) -> None:
        pages: list[SlidePage] = []
        for slides in ctx.read(LECTURE).slides:
            texts = await asyncio.to_thread(self._reader.read, ctx.workspace.resolve(slides.path))
            pages += [
                SlidePage(number=len(pages) + page, source=slides.path.name, page=page, text=text)
                for page, text in enumerate(texts, start=1)
            ]
        ctx.write(DECK, Deck(pages=pages))
