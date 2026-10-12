from dehydrater.pipeline.artifacts import AUDIO, DECK, RAW_TRANSCRIPT
from dehydrater.pipeline.stage import Stage, StageContext
from dehydrater.ports import Fingerprint, Transcriber, TranscriptionHints


class TranscribeStage(Stage):
    name = "transcribe"
    inputs = (AUDIO, DECK)
    outputs = (RAW_TRANSCRIPT,)

    def __init__(self, transcriber: Transcriber) -> None:
        self._transcriber = transcriber

    def fingerprint(self) -> Fingerprint:
        return self._transcriber.fingerprint()

    async def run(self, ctx: StageContext) -> None:
        audio = ctx.read(AUDIO)
        deck = ctx.read(DECK)
        transcript = await self._transcriber.transcribe(
            ctx.workspace.resolve(audio.path), TranscriptionHints(hotwords=deck.glossary)
        )
        ctx.write(RAW_TRANSCRIPT, transcript)
