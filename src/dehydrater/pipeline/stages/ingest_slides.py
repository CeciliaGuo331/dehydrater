import asyncio
import shutil

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

        image_dir = ctx.workspace.assets_dir / "slides"
        # 换了课件后旧页图不能残留，否则会混进讲义
        shutil.rmtree(image_dir, ignore_errors=True)
        pdf = ctx.workspace.resolve(lecture.slides.path)
        pages = await asyncio.to_thread(self._reader.read, pdf, image_dir)
        portable_pages = [
            page.model_copy(update={"image": ctx.workspace.portable_path(page.image)})
            for page in pages
        ]
        # TODO(S3): 从课件文本中抽取术语表
        ctx.write(DECK, Deck(pages=portable_pages, glossary=[]))
