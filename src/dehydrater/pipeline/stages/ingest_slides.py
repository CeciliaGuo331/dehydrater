import asyncio

from dehydrater.domain.slides import Deck
from dehydrater.pipeline.artifacts import DECK, LECTURE
from dehydrater.pipeline.stage import Stage, StageContext
from dehydrater.ports import Fingerprint, SlideReader


class IngestSlidesStage(Stage):
    name = "ingest_slides"
    inputs = (LECTURE,)
    outputs = (DECK,)

    def __init__(self, reader: SlideReader) -> None:
        self._reader = reader

    def fingerprint(self) -> Fingerprint:
        return self._reader.fingerprint()

    async def run(self, ctx: StageContext) -> None:
        lecture = ctx.read(LECTURE)
        if lecture.slides is None:
            ctx.write(DECK, Deck.empty())
            return
        pdf = ctx.workspace.resolve(lecture.slides.path)
        ctx.write(DECK, Deck(pages=await asyncio.to_thread(self._reader.read, pdf)))
