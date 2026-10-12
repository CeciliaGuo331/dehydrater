import asyncio

from dehydrater.domain.lecture import AudioFile
from dehydrater.pipeline.artifacts import AUDIO, LECTURE
from dehydrater.pipeline.stage import Stage, StageContext
from dehydrater.pipeline.workspace import sha256_of
from dehydrater.ports import AudioExtractor, Fingerprint


class ExtractAudioStage(Stage):
    name = "extract_audio"
    inputs = (LECTURE,)
    outputs = (AUDIO,)

    def __init__(self, extractor: AudioExtractor) -> None:
        self._extractor = extractor

    def fingerprint(self) -> Fingerprint:
        return self._extractor.fingerprint()

    async def run(self, ctx: StageContext) -> None:
        lecture = ctx.read(LECTURE)
        dest = ctx.files_dir / "audio.mp3"
        recording = ctx.workspace.resolve(lecture.recording.path)
        extracted = await asyncio.to_thread(self._extractor.extract, recording, dest)
        ctx.write(
            AUDIO,
            AudioFile(
                path=ctx.workspace.portable_path(dest),
                sha256=sha256_of(dest),
                duration=extracted.duration,
            ),
        )
