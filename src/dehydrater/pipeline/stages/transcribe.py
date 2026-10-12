from dehydrater.pipeline.artifacts import AUDIO, RAW_TRANSCRIPT
from dehydrater.pipeline.stage import Stage, StageContext
from dehydrater.ports import Fingerprint, Transcriber, TranscriptionHints


class TranscribeStage(Stage):
    name = "transcribe"
    inputs = (AUDIO,)
    outputs = (RAW_TRANSCRIPT,)

    def __init__(self, transcriber: Transcriber) -> None:
        self._transcriber = transcriber

    def fingerprint(self) -> Fingerprint:
        return self._transcriber.fingerprint()

    async def run(self, ctx: StageContext) -> None:
        audio = ctx.read(AUDIO)
        transcript = await self._transcriber.transcribe(
            ctx.workspace.resolve(audio.path), TranscriptionHints()
        )
        ctx.write(RAW_TRANSCRIPT, transcript)
