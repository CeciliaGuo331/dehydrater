from dehydrater.domain.base import DomainModel, Seconds


class TranscriptSegment(DomainModel):
    start: Seconds
    end: Seconds
    text: str


class Transcript(DomainModel):
    segments: list[TranscriptSegment]
