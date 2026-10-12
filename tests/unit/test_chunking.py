from dehydrater.domain.chunking import chunk_segments
from dehydrater.domain.transcript import TranscriptSegment


def _segments(*lengths: int) -> list[TranscriptSegment]:
    return [TranscriptSegment(start=i, end=i + 1, text="字" * n) for i, n in enumerate(lengths)]


def test_splits_at_segment_boundaries_within_budget() -> None:
    assert chunk_segments(_segments(4, 4, 4, 4, 4), max_chars=10) == [
        range(0, 2),
        range(2, 4),
        range(4, 5),
    ]


def test_oversized_segment_gets_its_own_chunk() -> None:
    assert chunk_segments(_segments(3, 20, 3), max_chars=10) == [
        range(0, 1),
        range(1, 2),
        range(2, 3),
    ]


def test_empty_transcript_has_no_chunks() -> None:
    assert chunk_segments([], max_chars=10) == []
